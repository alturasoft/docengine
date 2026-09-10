"""DocEngine — Infrastructure: PostgreSQL Hybrid Search Repository.

Read-only repository that combines pgvector cosine similarity with PostgreSQL
Full-Text Search (tsvector) using Reciprocal Rank Fusion (RRF) for improved
recall in the RAG query path.

This module is strictly read-only — it performs NO write operations and does
NOT import or interfere with PgRagRepository or any ingestion-side logic.

Search Strategy:
1. Vector search (pgvector <=> operator) over Child Chunks.
2. Full-Text Search (tsvector @@ tsquery) over Child Chunks.
3. RRF combination with k=60 constant for rank fusion.
4. Parent resolution: fetch complete Parent Chunks for LLM context.
"""

from __future__ import annotations

import re
from typing import Any

from app.domain.models.query_models import RetrievedChunk
from app.infrastructure.database.db_connection import DatabaseManager
from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Conversational words and generic fillers to omit when constructing the flexible tsquery
_CONVERSATIONAL_STOPWORDS = {
    "dame", "dar", "da", "dime", "decir", "cual", "cuál", "cuales", "cuáles",
    "que", "qué", "quien", "quién", "como", "cómo", "donde", "dónde", "cuando",
    "por", "favor", "existe", "existen", "hay", "tiene", "tienen", "lista",
    "figura", "figuran", "muestra", "muestrame", "muéstrame", "completa", "todos",
    "todas", "personas", "numero", "número", "nro", "poliza", "póliza", "archivo",
    "documento", "documentos", "adjunto", "adjuntos", "tabla", "tablas", "sobre"
}


def _build_flexible_tsquery(query_text: str) -> str:
    """Build a high-precision query for websearch_to_tsquery from semantic keywords.

    Filters conversational stopwords and standalone policy codes (handled by metadata/filters),
    and creates a targeted search: (keywords AND) or primary keyword.
    """
    tokens = re.findall(r"[a-zA-Z0-9áéíóúÁÉÍÓÚñÑ\-_]{3,}", query_text)
    keywords: list[str] = []
    for t in tokens:
        tl = t.lower()
        if tl in _CONVERSATIONAL_STOPWORDS:
            continue
        # Skip pure policy code tokens (e.g. SCE0651635, CAC-SCE0651635)
        # to prevent penalizing table rows that don't repeat the policy code in their text
        if re.match(r"^[A-Za-z]{2,5}-?[A-Za-z0-9]{4,15}$", t) and any(c.isdigit() for c in t):
            continue
        keywords.append(t)

    if not keywords:
        # Fallback: keep words >= 4 chars not in stopwords
        keywords = [t for t in tokens if len(t) >= 4 and t.lower() not in _CONVERSATIONAL_STOPWORDS]

    if not keywords:
        return query_text

    if len(keywords) > 1:
        # e.g. "(nómina asegurados) or nómina"
        and_part = " ".join(keywords[:4])
        return f"({and_part}) or {keywords[0]}"
    return keywords[0]


def _is_table_content(content: str, metadata: dict[str, Any] | None = None) -> bool:
    """Determine if a chunk content or its metadata indicates a Markdown table."""
    if metadata and metadata.get("is_table"):
        return True
    if "Tabla:" in content:
        return True
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    table_lines = [l for l in lines if l.startswith("|") and l.endswith("|")]
    return len(table_lines) >= 3


def _extract_table_signature(content: str) -> str | None:
    """Extract table header row signature to match related table fragments."""
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("|") and line.endswith("|") and not re.match(r"^\|\s*:?-+:?\s*\|", line):
            return line
    return None

# ---------------------------------------------------------------------------
# Hybrid RRF query template
# ---------------------------------------------------------------------------
# The query searches ONLY Child Chunks (chunk_type = 'child'), combines
# vector + FTS scores via RRF, and returns the top-K children with their
# parent_id for subsequent Parent resolution.
#
# Fallback: if no children exist (e.g. short documents where parents have
# no children), the query also considers parent chunks without children.

_HYBRID_RRF_QUERY = """
WITH vector_search AS (
    SELECT
        pc.id,
        pc.chunk_id,
        pc.chunk_content,
        pc.policy_id,
        pc.chunk_index,
        pc.metadata_json,
        pc.parent_id,
        pc.chunk_type,
        ROW_NUMBER() OVER (ORDER BY pc.embedding <=> %(query_vector)s::vector) AS vector_rank
    FROM policy_chunks pc
    {join_clause}
    WHERE pc.embedding IS NOT NULL
      {filter_clause}
    ORDER BY pc.embedding <=> %(query_vector)s::vector
    LIMIT %(rrf_pool)s
),
text_search AS (
    SELECT
        pc.id,
        pc.chunk_id,
        pc.chunk_content,
        pc.policy_id,
        pc.chunk_index,
        pc.metadata_json,
        pc.parent_id,
        pc.chunk_type,
        ROW_NUMBER() OVER (
            ORDER BY ts_rank_cd(
                pc.content_tsvector,
                websearch_to_tsquery('spanish', %(flexible_query)s)
            ) DESC
        ) AS text_rank
    FROM policy_chunks pc
    {join_clause}
    WHERE (
        pc.content_tsvector @@ plainto_tsquery('spanish', %(query_text)s)
        OR pc.content_tsvector @@ websearch_to_tsquery('spanish', %(flexible_query)s)
    )
      {filter_clause}
    ORDER BY ts_rank_cd(
        pc.content_tsvector,
        websearch_to_tsquery('spanish', %(flexible_query)s)
    ) DESC
    LIMIT %(rrf_pool)s
),
rrf_combined AS (
    SELECT
        COALESCE(v.id, t.id) AS id,
        COALESCE(v.chunk_id, t.chunk_id) AS chunk_id,
        COALESCE(v.chunk_content, t.chunk_content) AS chunk_content,
        COALESCE(v.policy_id, t.policy_id) AS policy_id,
        COALESCE(v.chunk_index, t.chunk_index) AS chunk_index,
        COALESCE(v.metadata_json, t.metadata_json) AS metadata_json,
        COALESCE(v.parent_id, t.parent_id) AS parent_id,
        COALESCE(v.chunk_type, t.chunk_type) AS chunk_type,
        COALESCE(1.0 / (60 + v.vector_rank), 0.0) +
        COALESCE(1.0 / (60 + t.text_rank), 0.0) AS rrf_score
    FROM vector_search v
    FULL OUTER JOIN text_search t ON v.id = t.id
)
SELECT id, chunk_id, chunk_content, policy_id::text, chunk_index,
       metadata_json, parent_id, chunk_type, rrf_score
FROM rrf_combined
ORDER BY rrf_score DESC
LIMIT %(top_k)s;
"""

# Query to fetch Parent Chunks by their chunk_id values
_PARENT_FETCH_QUERY = """
SELECT id, chunk_id, chunk_content, policy_id::text, chunk_index,
       metadata_json, chunk_type
FROM policy_chunks
WHERE chunk_id = ANY(%(parent_ids)s::uuid[])
  AND chunk_type = 'parent';
"""


class PgHybridSearchRepository:
    """Read-only repository for hybrid vector + FTS search with RRF fusion.

    Combines pgvector cosine similarity with PostgreSQL Full-Text Search
    using Reciprocal Rank Fusion (RRF) to improve recall over pure vector
    search. Searches Child Chunks for precision, then resolves and returns
    the corresponding Parent Chunks for complete LLM context.

    This class does NOT modify any data. All operations are SELECT-only.
    """

    def __init__(self, db_manager: DatabaseManager) -> None:
        self._db = db_manager

    def search_and_resolve(
        self,
        query_vector: list[float],
        query_text: str,
        top_k_children: int = 20,
        rrf_pool: int = 60,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        """Execute hybrid search, resolve Parents, and return deduplicated Parent Chunks.

        Strategy:
        1. Run hybrid RRF query to find the top-K most relevant Child Chunks.
        2. Collect unique parent_id values from the retrieved Children.
        3. Fetch the full Parent Chunks from the database.
        4. Return deduplicated Parent Chunks ordered by their best child's RRF score.

        For chunks that are Parent-only (no children exist, e.g. short text or tables),
        the search still captures them since the RRF query includes all chunks with
        embeddings.

        Args:
            query_vector: Dense 1024-dimensional query embedding (bge-m3).
            query_text: Original user question text for FTS matching.
            top_k_children: Maximum number of children to retrieve via RRF (default 20).
            rrf_pool: Size of the candidate pool for each search method before
                RRF fusion (default 60). Higher values improve recall at slight
                compute cost.
            filters: Optional pre-filter dict. Supported keys:
                - "policy_id" (str): Filter to a specific policy UUID.
                - "company_sigla" (str): Filter to a specific insurance company.

        Returns:
            List of RetrievedChunk instances containing Parent Chunk content,
            ordered by the best RRF score of their children. Deduplicated by
            parent_id.

        Raises:
            psycopg2.DatabaseError: On connection or query failure.
        """
        top_k_children = min(max(1, top_k_children), 100)

        # Step 1: Execute hybrid RRF search
        children = self._hybrid_search(
            query_vector=query_vector,
            query_text=query_text,
            top_k=top_k_children,
            rrf_pool=rrf_pool,
            filters=filters,
        )

        if not children:
            logger.info("Hybrid search returned no results")
            return []

        # Step 2: Collect unique parent_ids and track best RRF scores
        parent_id_scores: dict[str, float] = {}
        standalone_parents: list[RetrievedChunk] = []

        for child in children:
            if child.get("parent_id") is not None:
                pid = str(child["parent_id"])
                score = float(child["rrf_score"])
                if pid not in parent_id_scores or score > parent_id_scores[pid]:
                    parent_id_scores[pid] = score
            else:
                # This is a parent-only chunk (no children) that matched directly
                standalone_parents.append(
                    RetrievedChunk(
                        chunk_id=str(child["chunk_id"]) if child["chunk_id"] else str(child["id"]),
                        policy_id=str(child["policy_id"]),
                        chunk_index=child["chunk_index"],
                        chunk_content=child["chunk_content"],
                        metadata_json=child["metadata_json"] if isinstance(child["metadata_json"], dict) else {},
                        similarity_score=float(child["rrf_score"]),
                    )
                )

        # Step 3: Fetch Parent Chunks from database
        resolved_parents: list[RetrievedChunk] = []
        if parent_id_scores:
            resolved_parents = self._fetch_parents(
                parent_ids=list(parent_id_scores.keys()),
                parent_scores=parent_id_scores,
            )

        # Step 4: Combine resolved parents + standalone parents, deduplicate
        all_parents = resolved_parents + standalone_parents
        seen_ids: set[str] = set()
        deduplicated: list[RetrievedChunk] = []
        for parent in all_parents:
            key = parent.chunk_id or f"{parent.policy_id}_{parent.chunk_index}"
            if key not in seen_ids:
                seen_ids.add(key)
                deduplicated.append(parent)

        # Sort by score descending
        deduplicated.sort(key=lambda c: c.similarity_score, reverse=True)

        logger.info(
            "Hybrid search with parent resolution completed",
            children_found=len(children),
            unique_parents=len(deduplicated),
        )

        return deduplicated

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _hybrid_search(
        self,
        query_vector: list[float],
        query_text: str,
        top_k: int,
        rrf_pool: int,
        filters: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """Execute the hybrid RRF SQL query and return raw result dicts."""
        vector_str = _vector_to_pg_str(query_vector)

        # Build filter clauses
        filter_parts: list[str] = []
        needs_policy_join = False

        if filters:
            if filters.get("policy_id"):
                filter_parts.append("AND pc.policy_id = %(policy_id)s::uuid")
            if filters.get("company_sigla"):
                needs_policy_join = True
                filter_parts.append("AND p.company_sigla = UPPER(%(company_sigla)s)")

        filter_clause = " ".join(filter_parts)
        join_clause = "JOIN policies p ON pc.policy_id = p.id" if needs_policy_join else ""

        sql = _HYBRID_RRF_QUERY.format(
            filter_clause=filter_clause,
            join_clause=join_clause,
        )

        flexible_query = _build_flexible_tsquery(query_text)
        params: dict[str, Any] = {
            "query_vector": vector_str,
            "query_text": query_text,
            "flexible_query": flexible_query,
            "top_k": top_k,
            "rrf_pool": rrf_pool,
        }
        if filters:
            if filters.get("policy_id"):
                params["policy_id"] = filters["policy_id"]
            if filters.get("company_sigla"):
                params["company_sigla"] = filters["company_sigla"]

        logger.debug(
            "Executing hybrid RRF search",
            top_k=top_k,
            rrf_pool=rrf_pool,
            filters=filters,
        )

        results: list[dict[str, Any]] = []
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                columns = [desc[0] for desc in cur.description]
                for row in cur.fetchall():
                    results.append(dict(zip(columns, row)))

        return results

    def _fetch_parents(
        self,
        parent_ids: list[str],
        parent_scores: dict[str, float],
    ) -> list[RetrievedChunk]:
        """Fetch Parent Chunks by their chunk_id values."""
        if not parent_ids:
            return []

        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_PARENT_FETCH_QUERY, {"parent_ids": parent_ids})
                rows = cur.fetchall()

        parents: list[RetrievedChunk] = []
        for row in rows:
            db_id, chunk_id, chunk_content, policy_id, chunk_index, metadata_json, chunk_type = row
            cid = str(chunk_id) if chunk_id else str(db_id)
            parents.append(
                RetrievedChunk(
                    chunk_id=cid,
                    policy_id=str(policy_id),
                    chunk_index=chunk_index,
                    chunk_content=chunk_content,
                    metadata_json=metadata_json if isinstance(metadata_json, dict) else {},
                    similarity_score=parent_scores.get(cid, 0.0),
                )
            )

        return parents

    def expand_table_chunks(
        self, parent_chunks: list[RetrievedChunk]
    ) -> list[RetrievedChunk]:
        """Expand partial table sub-chunks into their complete contiguous table sequence.

        Strategy:
        1. If a chunk has metadata['table_group_id'], all chunks belonging to that table_group_id
           are retrieved from PostgreSQL in sequential order of table_part.
        2. Heuristic fallback for documents stored prior to table_group_id:
           Checks if chunk is a Markdown table and scans adjacent chunk indices (chunk_index +/- 5)
           on the same policy sharing the same table header or table title signature.
        3. Preserves ordering and deduplicates chunks.

        Args:
            parent_chunks: List of retrieved parent chunks.

        Returns:
            List of parent chunks with full contiguous table fragments assembled.
        """
        if not parent_chunks:
            return []

        expanded: list[RetrievedChunk] = []
        seen_ids: set[str] = set()

        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                for chunk in parent_chunks:
                    cid = chunk.chunk_id or f"{chunk.policy_id}_{chunk.chunk_index}"
                    if cid in seen_ids:
                        continue

                    # Check if chunk represents a Markdown table
                    if not _is_table_content(chunk.chunk_content, chunk.metadata_json):
                        seen_ids.add(cid)
                        expanded.append(chunk)
                        continue

                    table_group_id = chunk.metadata_json.get("table_group_id")
                    if table_group_id:
                        # Fetch all parts of this table group
                        cur.execute(
                            """
                            SELECT id, chunk_id, chunk_content, policy_id::text, chunk_index,
                                   metadata_json, chunk_type
                            FROM policy_chunks
                            WHERE policy_id = %(policy_id)s::uuid
                              AND metadata_json->>'table_group_id' = %(group_id)s
                              AND chunk_type = 'parent'
                            ORDER BY (metadata_json->>'table_part')::int ASC, chunk_index ASC;
                            """,
                            {"policy_id": chunk.policy_id, "group_id": str(table_group_id)},
                        )
                        rows = cur.fetchall()
                        for r in rows:
                            part_cid = str(r[1]) if r[1] else str(r[0])
                            if part_cid not in seen_ids:
                                seen_ids.add(part_cid)
                                expanded.append(
                                    RetrievedChunk(
                                        chunk_id=part_cid,
                                        policy_id=str(r[3]),
                                        chunk_index=r[4],
                                        chunk_content=r[2],
                                        metadata_json=r[5] if isinstance(r[5], dict) else {},
                                        similarity_score=chunk.similarity_score,
                                    )
                                )
                    else:
                        # Heuristic fallback: inspect adjacent parent chunks
                        header_sig = _extract_table_signature(chunk.chunk_content)
                        curr_idx = chunk.chunk_index
                        cur.execute(
                            """
                            SELECT id, chunk_id, chunk_content, policy_id::text, chunk_index,
                                   metadata_json, chunk_type
                            FROM policy_chunks
                            WHERE policy_id = %(policy_id)s::uuid
                              AND chunk_type = 'parent'
                              AND chunk_index BETWEEN %(min_idx)s AND %(max_idx)s
                            ORDER BY chunk_index ASC;
                            """,
                            {
                                "policy_id": chunk.policy_id,
                                "min_idx": max(0, curr_idx - 5),
                                "max_idx": curr_idx + 5,
                            },
                        )
                        neighbor_rows = cur.fetchall()
                        by_index = {r[4]: r for r in neighbor_rows}

                        collected_indices = [curr_idx]
                        # Scan backwards
                        scan_idx = curr_idx - 1
                        while scan_idx in by_index:
                            nb_content = by_index[scan_idx][2]
                            nb_sig = _extract_table_signature(nb_content)
                            if _is_table_content(nb_content, by_index[scan_idx][5]) and (
                                nb_sig == header_sig or ("Tabla:" in chunk.chunk_content and "Tabla:" in nb_content)
                            ):
                                collected_indices.insert(0, scan_idx)
                                scan_idx -= 1
                            else:
                                break

                        # Scan forwards
                        scan_idx = curr_idx + 1
                        while scan_idx in by_index:
                            nb_content = by_index[scan_idx][2]
                            nb_sig = _extract_table_signature(nb_content)
                            if _is_table_content(nb_content, by_index[scan_idx][5]) and (
                                nb_sig == header_sig or ("Tabla:" in chunk.chunk_content and "Tabla:" in nb_content)
                            ):
                                collected_indices.append(scan_idx)
                                scan_idx += 1
                            else:
                                break

                        for idx in collected_indices:
                            r = by_index[idx]
                            part_cid = str(r[1]) if r[1] else str(r[0])
                            if part_cid not in seen_ids:
                                seen_ids.add(part_cid)
                                expanded.append(
                                    RetrievedChunk(
                                        chunk_id=part_cid,
                                        policy_id=str(r[3]),
                                        chunk_index=r[4],
                                        chunk_content=r[2],
                                        metadata_json=r[5] if isinstance(r[5], dict) else {},
                                        similarity_score=chunk.similarity_score,
                                    )
                                )

        logger.info(
            "Table chunk expansion complete",
            original_chunks=len(parent_chunks),
            expanded_chunks=len(expanded),
        )
        return expanded


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _vector_to_pg_str(vector: list[float]) -> str:
    """Convert a Python float list to a pgvector-compatible string literal.

    PostgreSQL pgvector expects the format: '[0.1, 0.2, ..., 0.n]'

    Args:
        vector: List of floats representing the embedding.

    Returns:
        String in pgvector format: '[f1, f2, ..., fn]'.
    """
    return "[" + ",".join(str(v) for v in vector) + "]"
