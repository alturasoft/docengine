"""DocEngine — Automated Batch Policy Q&A Testing and Reliability Benchmark.

This script parses a questions file (e.g., tests/PreguntasValidacion.txt),
executes every question against the indexed RAG pipeline filtered to a specific
policy, logs the answers and sources, and generates a comprehensive .TXT report
with full statistical analysis and reliability metrics.

Usage:
    python scripts/run_policy_qa_test.py
    python scripts/run_policy_qa_test.py --file tests/PreguntasValidacion.txt --policy-number AUT-SCR0667473
    python scripts/run_policy_qa_test.py --output outputs/reporte_test_AUT-SCR0667473.txt
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Ensure stdout and stderr use UTF-8 on Windows
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


from app.cli.rag_query_factory import create_rag_query_service
from app.config.settings import get_settings
from app.infrastructure.database.db_connection import DatabaseManager


@dataclass
class QuestionItem:
    """Represents a single parsed question with its category."""
    index: int
    category: str
    question_text: str


@dataclass
class QuestionResult:
    """Stores the evaluation result of a single question."""
    item: QuestionItem
    answer: str
    is_answered: bool
    status_label: str  # CONTESTADA, SIN INFORMACIÓN, ERROR
    reliability_score: float  # 0.0 to 100.0
    latency_seconds: float
    sources_count: int
    top_similarity_score: float
    sources_summary: list[dict[str, Any]] = field(default_factory=list)
    error_msg: str | None = None


# Phrases indicating that the RAG model could not find sufficient information in the context
_UNANSWERED_PATTERNS = [
    r"no dispongo de",
    r"no se dispone de",
    r"no cuento con",
    r"no se encontr[oó]",
    r"no se menciona",
    r"no figura",
    r"no se especifica",
    r"no contiene informaci[oó]n",
    r"no est[aá] disponible",
    r"no es posible determinar",
    r"no se detalla",
    r"no existe informaci[oó]n",
    r"no hay informaci[oó]n",
    r"no se incluye",
    r"no se proporciona",
    r"no se indica",
    r"no se se[ñn]ala",
    r"no precisa",
    r"documentos proporcionados no",
    r"no indican",
]
_UNANSWERED_REGEX = re.compile("|".join(_UNANSWERED_PATTERNS), re.IGNORECASE)



def parse_questions_file(filepath: Path) -> list[QuestionItem]:
    """Parse a validation text file into structured QuestionItem objects.

    Recognizes numbered section headers (e.g. '1. Datos Generales...')
    and individual question lines.
    """
    if not filepath.exists():
        raise FileNotFoundError(f"Questions file not found: {filepath}")

    content = filepath.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines()

    current_category = "General"
    questions: list[QuestionItem] = []
    q_index = 1

    category_pattern = re.compile(r"^\s*(\d+[\.\)]\s*[^¿\?\n]+)$")

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        # Check if line is a category header
        cat_match = category_pattern.match(line)
        if cat_match and not ("¿" in line or "?" in line):
            current_category = cat_match.group(1).strip()
            continue

        # Check if line is a question
        if "¿" in line or line.endswith("?"):
            questions.append(
                QuestionItem(
                    index=q_index,
                    category=current_category,
                    question_text=line,
                )
            )
            q_index += 1

    return questions


def find_target_policy(policy_identifier: str | None) -> dict[str, Any]:
    """Look up the target policy in PostgreSQL by ID, filename, or partial match."""
    settings = get_settings()
    db = DatabaseManager(settings.database)

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            if policy_identifier:
                cur.execute(
                    """
                    SELECT id, file_name, company_sigla, total_pages
                    FROM policies
                    WHERE id::text = %s OR file_name ILIKE %s
                    LIMIT 1
                    """,
                    (policy_identifier, f"%{policy_identifier}%"),
                )
            else:
                cur.execute(
                    """
                    SELECT id, file_name, company_sigla, total_pages
                    FROM policies
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                )
            row = cur.fetchone()
            if not row:
                raise ValueError(
                    f"No policy found matching identifier: '{policy_identifier}'. "
                    "Make sure documents are processed into PostgreSQL."
                )
            return {
                "id": str(row[0]),
                "file_name": str(row[1]),
                "company_sigla": str(row[2]) if row[2] else "N/A",
                "total_pages": int(row[3]) if row[3] else 0,
            }


def calculate_reliability(
    answer: str,
    sources: list[Any],
    top_score: float,
    is_answered: bool,
) -> float:
    """Calculate a reliability index percentage (0.0 to 100.0) based on retrieval & generation metrics."""
    if not is_answered or not sources:
        return 0.0

    # Base score from top similarity/rerank score (scale 0.0 - 1.0)
    # Typical good cosine similarity in bge-m3 / cross-encoder: 0.60 - 0.95
    normalized_score = min(max((top_score - 0.3) / 0.6, 0.0), 1.0) * 50.0

    # Source grounding score: having 2+ supporting chunks provides higher consensus
    chunks_score = min(len(sources) / 3.0, 1.0) * 30.0

    # Answer completeness heuristic: adequate length and absence of uncertainty
    ans_length = len(answer.strip())
    length_score = 20.0 if ans_length > 40 else (ans_length / 40.0 * 20.0)

    # Deduction for placeholders or generic queries
    if "[" in answer and "]" in answer:
        length_score *= 0.5

    total = normalized_score + chunks_score + length_score
    return round(min(max(total, 10.0), 100.0), 1)


def run_benchmark(
    questions_path: Path,
    output_path: Path,
    policy_query: str = "AUT-SCR0667473",
    top_k: int = 5,
) -> Path:
    """Execute the full batch test and generate the formatted .txt report."""
    print("=" * 80)
    print("🚀 DOCENGINE — PROCESO DE TESTEO AUTOMATIZADO DE PREGUNTAS Y FIABILIDAD")
    print("=" * 80)

    # 1. Resolve target policy
    policy_info = find_target_policy(policy_query)
    print(f"📄 Póliza Objetivo : {policy_info['file_name']}")
    print(f"🔑 Policy UUID     : {policy_info['id']}")
    print(f"🏢 Aseguradora     : {policy_info['company_sigla']}")
    print(f"📑 Páginas         : {policy_info['total_pages']}")
    print("-" * 80)

    # 2. Parse questions
    questions = parse_questions_file(questions_path)
    print(f"📋 Total preguntas cargadas: {len(questions)} desde {questions_path.name}\n")

    # 3. Initialize RAG Query Service
    print("⚙️  Inicializando RAG Query Service (Modelos + Base de Datos)...")
    rag_service = create_rag_query_service()
    settings = get_settings()
    print("✅ RAG Query Service listo.\n")

    results: list[QuestionResult] = []
    total_start = time.perf_counter()

    # 4. Iterate over questions
    for q_item in questions:
        print(f"[{q_item.index:02d}/{len(questions):02d}] {q_item.question_text[:70]}...", end=" ", flush=True)

        filters = {
            "policy_id": policy_info["id"],
        }
        if policy_info["company_sigla"] and policy_info["company_sigla"] != "N/A":
            filters["company_sigla"] = policy_info["company_sigla"]

        q_start = time.perf_counter()
        try:
            response = rag_service.query(
                question=q_item.question_text,
                top_k=top_k,
                filters=filters,
            )
            elapsed = time.perf_counter() - q_start

            answer = response.answer.strip()
            sources = response.sources or []
            top_score = max([s.similarity_score for s in sources], default=0.0)

            # Determine if answered
            has_unanswered_text = bool(_UNANSWERED_REGEX.search(answer))
            is_answered = (len(sources) > 0) and not (has_unanswered_text and len(answer) < 300)

            status_label = "CONTESTADA" if is_answered else "SIN INFORMACIÓN"
            rel_score = calculate_reliability(answer, sources, top_score, is_answered)

            sources_summary = []
            for s in sources:
                sources_summary.append({
                    "label": getattr(s, "document_label", "Doc"),
                    "score": getattr(s, "similarity_score", 0.0),
                    "chunk_id": str(getattr(s, "chunk_id", "")),
                    "preview": getattr(s, "chunk_content", "")[:250].replace("\n", " "),
                })

            res = QuestionResult(
                item=q_item,
                answer=answer,
                is_answered=is_answered,
                status_label=status_label,
                reliability_score=rel_score,
                latency_seconds=elapsed,
                sources_count=len(sources),
                top_similarity_score=top_score,
                sources_summary=sources_summary,
            )
            results.append(res)
            icon = "✅" if is_answered else "⚠️"
            print(f"{icon} {status_label} ({rel_score}% fiabilidad | {elapsed:.2f}s)")

        except Exception as exc:
            elapsed = time.perf_counter() - q_start
            res = QuestionResult(
                item=q_item,
                answer=f"ERROR en ejecución: {exc}",
                is_answered=False,
                status_label="ERROR",
                reliability_score=0.0,
                latency_seconds=elapsed,
                sources_count=0,
                top_similarity_score=0.0,
                error_msg=str(exc),
            )
            results.append(res)
            print(f"❌ ERROR: {exc}")

    total_duration = time.perf_counter() - total_start

    # 5. Compute Statistics
    total_q = len(results)
    answered_q = [r for r in results if r.is_answered]
    unanswered_q = [r for r in results if not r.is_answered and r.status_label != "ERROR"]
    errors_q = [r for r in results if r.status_label == "ERROR"]

    answered_count = len(answered_q)
    unanswered_count = len(unanswered_q)
    errors_count = len(errors_q)

    pct_answered = (answered_count / total_q * 100.0) if total_q > 0 else 0.0
    pct_unanswered = (unanswered_count / total_q * 100.0) if total_q > 0 else 0.0
    pct_errors = (errors_count / total_q * 100.0) if total_q > 0 else 0.0

    avg_latency = sum(r.latency_seconds for r in results) / total_q if total_q > 0 else 0.0
    answered_scores = [r.reliability_score for r in answered_q]
    avg_reliability = (sum(answered_scores) / len(answered_scores)) if answered_scores else 0.0

    # Category breakdown
    categories: dict[str, list[QuestionResult]] = {}
    for r in results:
        cat = r.item.category
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(r)

    # 6. Generate .TXT Report
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        f.write("=" * 85 + "\n")
        f.write("                     DOCENGINE — REPORTE DE EVALUACIÓN Y TEST Q&A\n")
        f.write("=" * 85 + "\n\n")

        f.write("1. METADATOS DE LA EJECUCIÓN\n")
        f.write("-" * 85 + "\n")
        f.write(f"• Fecha y Hora          : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"• Archivo de Preguntas  : {questions_path.name}\n")
        f.write(f"• Póliza Evaluada       : {policy_info['file_name']}\n")
        f.write(f"• ID Póliza (UUID)      : {policy_info['id']}\n")
        f.write(f"• Aseguradora           : {policy_info['company_sigla']}\n")
        f.write(f"• Total Páginas Póliza  : {policy_info['total_pages']}\n")
        f.write(f"• Top-K Chunks RAG      : {top_k}\n")
        f.write(f"• Modelo LLM Utilizado  : {settings.rag_query.llm_model}\n")
        f.write(f"• Tiempo Total de Test  : {total_duration:.2f} segundos\n")
        f.write("-" * 85 + "\n\n")


        f.write("2. DETALLE DE PREGUNTAS Y RESPUESTAS OBTENIDAS\n")
        f.write("=" * 85 + "\n")

        for cat_name, cat_results in categories.items():
            f.write(f"\n>>> SECCIÓN: {cat_name.upper()}\n")
            f.write("-" * 85 + "\n")

            for r in cat_results:
                f.write(f"\n[PREGUNTA #{r.item.index:02d}]\n")
                f.write(f"Pregunta   : {r.item.question_text}\n")
                f.write(f"Estado     : {r.status_label}\n")
                f.write(f"Fiabilidad : {r.reliability_score:.1f}% | Latencia: {r.latency_seconds:.2f}s | Chunks Usados: {r.sources_count}\n")
                f.write(f"Respuesta  :\n{r.answer}\n\n")

                if r.sources_summary:
                    f.write("Fuentes Utilizadas:\n")
                    for s_idx, src in enumerate(r.sources_summary, start=1):
                        f.write(f"  [{s_idx}] Score: {src['score']:.4f} | {src['label']}\n")
                        f.write(f"      Fragmento: {src['preview']}...\n")
                f.write("." * 85 + "\n")

        f.write("\n" + "=" * 85 + "\n")
        f.write("3. RESUMEN ESTADÍSTICO Y MÉTRICAS DE FIABILIDAD\n")
        f.write("=" * 85 + "\n\n")

        f.write(f"• Total de Preguntas Realizadas        : {total_q}\n")
        f.write(f"• Preguntas Contestadas con Éxito       : {answered_count} ({pct_answered:.1f}%)\n")
        f.write(f"• Preguntas No Contestadas / Sin Datos  : {unanswered_count} ({pct_unanswered:.1f}%)\n")
        f.write(f"• Errores Técnicos de Ejecución        : {errors_count} ({pct_errors:.1f}%)\n\n")

        f.write(f"• Nivel de Fiabilidad Promedio         : {avg_reliability:.1f}%\n")
        f.write(f"• Tiempo Promedio por Pregunta         : {avg_latency:.2f} segundos\n\n")

        f.write("DESGLOSE POR CATEGORÍAS:\n")
        f.write("-" * 85 + "\n")
        f.write(f"{'Categoría':<45} | {'Total':<6} | {'Contestadas':<12} | {'Fiabilidad':<10}\n")
        f.write("-" * 85 + "\n")
        for cat_name, cat_results in categories.items():
            cat_total = len(cat_results)
            cat_ans = sum(1 for x in cat_results if x.is_answered)
            cat_scores = [x.reliability_score for x in cat_results if x.is_answered]
            cat_rel = (sum(cat_scores) / len(cat_scores)) if cat_scores else 0.0
            f.write(f"{cat_name[:44]:<45} | {cat_total:<6} | {cat_ans:<12} | {cat_rel:.1f}%\n")
        f.write("-" * 85 + "\n\n")

        if unanswered_q:
            f.write("DETALLE DE PREGUNTAS NO CONTESTADAS O SIN INFORMACIÓN EN EL DOCUMENTO:\n")
            f.write("-" * 85 + "\n")
            for u in unanswered_q:
                f.write(f"• [#{u.item.index:02d}] {u.item.question_text}\n")
                # Add observation if question contains placeholders
                if "[" in u.item.question_text and "]" in u.item.question_text:
                    f.write("  Nota: La pregunta contiene comodines genéricos como [Nombre de Cobertura].\n")
            f.write("-" * 85 + "\n\n")

        f.write("=" * 85 + "\n")
        f.write("                            FIN DEL REPORTE\n")
        f.write("=" * 85 + "\n")

    # Clean up scratch files if any
    scratch_check = _PROJECT_ROOT / "scripts" / "check_db_policies.py"
    if scratch_check.exists():
        try:
            scratch_check.unlink()
        except OSError:
            pass

    print("\n" + "=" * 80)
    print("📊 RESUMEN FINAL DEL TEST")
    print("=" * 80)
    print(f"• Total Preguntas        : {total_q}")
    print(f"• Contestadas con Éxito   : {answered_count} ({pct_answered:.1f}%)")
    print(f"• Sin Información / N/A  : {unanswered_count} ({pct_unanswered:.1f}%)")
    print(f"• Errores                : {errors_count} ({pct_errors:.1f}%)")
    print(f"• Fiabilidad Promedio    : {avg_reliability:.1f}%")
    print(f"• Tiempo Total           : {total_duration:.2f}s (Promedio: {avg_latency:.2f}s/pregunta)")
    print(f"\n💾 Reporte completo guardado en: {output_path.resolve()}")
    print("=" * 80)

    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="DocEngine Automated Policy Q&A Testing Benchmark.")
    parser.add_argument(
        "--file",
        "-f",
        type=str,
        default="tests/PreguntasValidacion.txt",
        help="Path to questions text file (default: tests/PreguntasValidacion.txt)",
    )
    parser.add_argument(
        "--policy-number",
        "-p",
        type=str,
        default="AUT-SCR0667473",
        help="Policy number or filename pattern to target (default: AUT-SCR0667473)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="outputs/reporte_test_AUT-SCR0667473.txt",
        help="Output .TXT report path (default: outputs/reporte_test_AUT-SCR0667473.txt)",
    )
    parser.add_argument(
        "--top-k",
        "-k",
        type=int,
        default=5,
        help="Number of retrieved Parent chunks per query (default: 5)",
    )

    args = parser.parse_args()

    questions_path = Path(args.file)
    output_path = Path(args.output)

    run_benchmark(
        questions_path=questions_path,
        output_path=output_path,
        policy_query=args.policy_number,
        top_k=args.top_k,
    )


if __name__ == "__main__":
    main()
