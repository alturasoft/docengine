"""DocEngine — Post-Processor: Insurance Table Splitter & Cleaner.

Detects and splits Markdown tables merged by TableFormer, and cleans
footer noise (page numbers, user signatures) embedded inside table cells.
"""

from __future__ import annotations

import re

from app.application.post_processing.base import (
    BasePostProcessor,
    PostProcessingContext,
)

# Regex to detect footer/page noise inside table rows (e.g. | Página | 21 de | 32 |)
_FOOTER_ROW_PATTERN = re.compile(
    r"\|?\s*(?:Página|Page|Pág\.?)\b",
    re.IGNORECASE,
)


class InsuranceTableSplitterProcessor(BasePostProcessor):
    """Splits merged insurance tables and strips table footer noise.

    TableFormer frequently merges adjacent tables (e.g. REGISTRO DE ASEGURADOS
    and DESCRIPCIÓN DE COBERTURAS) into a single 8-column grid with duplicated
    columns and embedded page numbers.

    This rule:
    1. Splits tables at internal sub-headings or repeated header rows.
    2. Strips footer noise rows (page numbers, signatures) inside tables.
    3. Normalizes column alignment and removes redundant duplicate cells.
    """

    @property
    def name(self) -> str:
        return "insurance_table_splitter"

    def process(self, markdown: str, context: PostProcessingContext) -> str:
        """Process and clean all Markdown tables in the document."""
        if not markdown.strip():
            return markdown

        # Match a full Markdown table block: 2 or more contiguous lines starting with '|'
        table_block_regex = re.compile(
            r"((?:^[ \t]*\|[^\n]*\n?){2,})",
            re.MULTILINE,
        )

        def _clean_and_split(match: re.Match[str]) -> str:
            table_text = match.group(0)
            return self._process_single_table(table_text, context)

        return table_block_regex.sub(_clean_and_split, markdown)

    def _process_single_table(
        self, table_text: str, context: PostProcessingContext
    ) -> str:
        """Clean footer noise and split a single table block if merged."""
        rows = [r for r in table_text.strip().split("\n") if r.strip()]
        if len(rows) < 3:
            return table_text

        # Step 1: Filter out footer noise rows (e.g. | Página | 21 de | 32 | ... | karinahcv |)
        cleaned_rows: list[str] = []
        for r in rows:
            if _FOOTER_ROW_PATTERN.search(r):
                context.metadata["table_footer_rows_removed"] = (
                    context.metadata.get("table_footer_rows_removed", 0) + 1
                )
                continue
            cleaned_rows.append(r)

        if not cleaned_rows:
            return ""

        # Step 2: Check for internal split point (sub-header or repeated header)
        split_index = None
        for idx in range(2, len(cleaned_rows)):
            row_content = cleaned_rows[idx]
            # Check if this row looks like a sub-header or new header row
            if self._is_sub_header_row(row_content):
                split_index = idx
                break

        if split_index is None:
            return self._reformat_table_rows(cleaned_rows)

        # Split into two tables
        table_a_rows = cleaned_rows[:split_index]
        table_b_rows = cleaned_rows[split_index:]

        context.metadata["tables_split_count"] = (
            context.metadata.get("tables_split_count", 0) + 1
        )

        table_a_str = self._reformat_table_rows(table_a_rows)
        table_b_str = self._reformat_table_rows(table_b_rows)

        return f"{table_a_str}\n\n{table_b_str}"

    def _is_sub_header_row(self, row: str) -> bool:
        """Return True if row looks like an internal table split header."""
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        non_empty = [c for c in cells if c]
        if not non_empty:
            return False

        # Keywords indicating a new table section in insurance docs
        split_keywords = [
            "descripción de coberturas",
            "descripcion de coberturas",
            "coberturas",
            "código",
            "codigo",
            "detalles",
        ]
        row_lower = row.lower()

        for kw in split_keywords:
            if kw in row_lower and ("código" in row_lower or "descripción" in row_lower or "coberturas" in row_lower):
                return True

        return False

    def _reformat_table_rows(self, rows: list[str]) -> str:
        """Ensure valid header, separator, and data rows in Markdown table."""
        if not rows:
            return ""

        # Step 1: Parse rows into cell lists and extract embedded titles
        parsed_rows: list[list[str]] = []
        header_title_prefix = ""

        for r in rows:
            if "---" in r or "-|-" in r:
                continue
            cells = [c.strip() for c in r.strip().strip("|").split("|")]
            non_empty = [c for c in cells if c]

            # Check if this row is a single-cell section title row (e.g. | | | DESCRIPCIÓN DE COBERTURAS | | | | | |)
            if len(non_empty) == 1 and len(cells) > 2:
                title_text = non_empty[0].strip()
                if title_text and not title_text.isdigit():
                    header_title_prefix = f"## {title_text}\n\n"
                    continue

            parsed_rows.append(cells)

        if not parsed_rows:
            return header_title_prefix.strip()

        # Step 2: Prune completely empty columns across all rows
        pruned_rows = self._prune_empty_columns(parsed_rows)
        if not pruned_rows:
            return ""

        header_cells = pruned_rows[0]
        cols_count = max(1, len(header_cells))
        header_str = "| " + " | ".join(header_cells) + " |"
        sep_str = "| " + " | ".join(["---"] * cols_count) + " |"

        data_lines: list[str] = []
        for r_cells in pruned_rows[1:]:
            cleaned_row_cells: list[str] = []
            i = 0
            while i < len(r_cells):
                curr = r_cells[i]
                if i + 1 < len(r_cells) and curr and curr == r_cells[i + 1]:
                    cleaned_row_cells.append(curr)
                    i += 2
                else:
                    cleaned_row_cells.append(curr)
                    i += 1
            data_lines.append("| " + " | ".join(cleaned_row_cells) + " |")

        table_body = "\n".join([header_str, sep_str] + data_lines)
        return f"{header_title_prefix}{table_body}"

    def _prune_empty_columns(self, rows_cells: list[list[str]]) -> list[list[str]]:
        """Remove columns that are completely empty across all table rows."""
        if not rows_cells or not rows_cells[0]:
            return rows_cells

        num_cols = max(len(r) for r in rows_cells)
        active_cols: list[int] = []

        for col in range(num_cols):
            has_content = False
            for r in rows_cells:
                if col < len(r):
                    cell_val = r[col].strip()
                    if cell_val and not re.match(r"^:?-+:?$", cell_val):
                        has_content = True
                        break
            if has_content:
                active_cols.append(col)

        if not active_cols or len(active_cols) == num_cols:
            return rows_cells

        pruned_rows: list[list[str]] = []
        for r in rows_cells:
            pruned_r = [r[col].strip() if col < len(r) else "" for col in active_cols]
            pruned_rows.append(pruned_r)

        return pruned_rows

    def _deduplicate_cell_values(self, row: str) -> str:
        """Deduplicate identical adjacent cell content (e.g. Muerte Accidental | Muerte Accidental)."""
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        if len(cells) < 2:
            return row

        deduped: list[str] = []
        i = 0
        while i < len(cells):
            curr = cells[i]
            if i + 1 < len(cells) and curr and curr == cells[i + 1]:
                deduped.append(curr)
                i += 2
            else:
                deduped.append(curr)
                i += 1

        return "| " + " | ".join(deduped) + " |"
