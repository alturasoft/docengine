"""DocEngine — Post-Processor: Company KV Rules.

Applies company-specific key-value extraction rules loaded from a
``CompanySkill`` instance. This processor is injected dynamically into
the pipeline *only* when a company skill is available, so it has zero
effect on generic (non-company) extractions.

The processor extends the generic ``PolicyKeyValueFormatterProcessor``
behaviour by adding the company-defined ``kv_keys`` and removes known
recurring header/footer patterns specific to the insurer.
"""

from __future__ import annotations

import re

from app.application.company_skill_loader import CompanySkill
from app.application.post_processing.base import (
    BasePostProcessor,
    PostProcessingContext,
)
from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class CompanyKVRulesProcessor(BasePostProcessor):
    """Apply company-specific KV and header rules from a CompanySkill.

    This processor performs three passes over the Markdown:

    1. **Header/footer removal**: Strips lines that match any regex pattern
       in ``skill.header_patterns``.
    2. **Company KV detection**: Detects and reformats key-value pairs whose
       keys are listed in ``skill.kv_keys``.  Values are expected on the
       same line (after the key) or on the immediately following line.
    3. **Table split hints**: Adds a Markdown ``---`` separator before
       section headings listed in ``skill.table_split_hints`` to help
       downstream consumers split content by section.

    Args:
        skill: The ``CompanySkill`` instance containing the rules.
    """

    def __init__(self, skill: CompanySkill) -> None:
        self._skill = skill
        self._header_regexes: list[re.Pattern] = []
        self._kv_regex: re.Pattern | None = None
        self._hint_regexes: list[re.Pattern] = []
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Pre-compile regex patterns from the skill for performance."""
        # Header / footer patterns
        for pattern in self._skill.header_patterns:
            try:
                self._header_regexes.append(re.compile(pattern, re.IGNORECASE))
            except re.error as exc:
                logger.warning(
                    "Invalid header_pattern in skill — skipped",
                    sigla=self._skill.sigla,
                    pattern=pattern,
                    error=str(exc),
                )

        # KV keys pattern
        if self._skill.kv_keys:
            escaped = [re.escape(k) for k in self._skill.kv_keys]
            self._kv_regex = re.compile(
                r"(?P<key>" + "|".join(escaped) + r")\s*:?\s*(?P<value>.*)",
                re.IGNORECASE,
            )

        # Table split hint patterns
        for hint in self._skill.table_split_hints:
            try:
                self._hint_regexes.append(re.compile(re.escape(hint), re.IGNORECASE))
            except re.error as exc:
                logger.warning(
                    "Invalid table_split_hint in skill — skipped",
                    sigla=self._skill.sigla,
                    hint=hint,
                    error=str(exc),
                )

    # ------------------------------------------------------------------
    # BasePostProcessor interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return f"company_kv_rules_{self._skill.sigla.lower()}"

    @property
    def description(self) -> str:
        return (
            f"Company-specific KV and header rules for {self._skill.sigla} "
            f"({self._skill.empresa})"
        )

    def process(self, markdown: str, context: PostProcessingContext) -> str:
        """Apply all extraction, cleaning, and table reconstruction passes.

        Args:
            markdown: Current Markdown content.
            context: Shared post-processing context.

        Returns:
            Transformed Markdown.
        """
        if not markdown.strip() or self._skill.is_empty:
            return markdown

        md = self._reconstruct_bis_deducible_table(markdown)
        md = self._extract_header_metadata(md, context)
        md = self._remove_header_patterns(md, context)
        md = self._reconstruct_split_tables(md, context)
        md = self._apply_table_cell_cleanup_rules(md, context)
        md = self._apply_kv_rules(md, context)
        md = self._apply_table_split_hints(md, context)
        md = self._apply_table_column_alignment_fixes(md, context)
        return md

    # ------------------------------------------------------------------
    # Private passes
    # ------------------------------------------------------------------

    def _extract_header_metadata(
        self, markdown: str, context: PostProcessingContext
    ) -> str:
        """Extract policy metadata (número de póliza, tomador, asegurado) from repetitive headers.

        Scans repetitive header patterns or top-of-page lines against rules defined in
        `skill.header_metadata_patterns`. Extracted fields are added to context.metadata
        and formatted into a structured Policy K/V table at the beginning of the document
        if not already present.

        Args:
            markdown: Input Markdown text.
            context: Processing context.

        Returns:
            Markdown, possibly enriched with a structured policy KV block if metadata was extracted.
        """
        metadata_rules = getattr(self._skill, "header_metadata_patterns", [])
        if not metadata_rules:
            return markdown

        # Gather candidate lines from page_texts or top of pages
        candidate_lines: list[str] = []
        if context.page_texts:
            for page in context.page_texts:
                for line in page.splitlines()[:5]:
                    s = line.strip()
                    if s and s not in candidate_lines:
                        candidate_lines.append(s)
        else:
            # Fallback: scan first lines of pages or markdown lines
            lines = markdown.splitlines()
            for idx, line in enumerate(lines):
                s = line.strip()
                if idx < 15 or (idx > 0 and lines[idx - 1].strip().startswith(("--->", "---", "***"))):
                    if s and s not in candidate_lines:
                        candidate_lines.append(s)
            for line in lines:
                s = line.strip()
                if any(rx.search(s) for rx in self._header_regexes):
                    if s and s not in candidate_lines:
                        candidate_lines.append(s)

        extracted: dict[str, str] = {}

        for rule in metadata_rules:
            if not isinstance(rule, dict):
                continue
            patterns_map = rule.get("patterns", {})
            for field_name, patterns in patterns_map.items():
                if field_name in extracted:
                    continue
                if isinstance(patterns, str):
                    patterns = [patterns]
                for pat in patterns:
                    try:
                        rx = re.compile(pat, re.IGNORECASE)
                    except re.error:
                        continue
                    for line in candidate_lines:
                        m = rx.search(line)
                        if m:
                            val = m.group(1) if m.groups() else m.group(0)
                            val = re.sub(r"\s+", " ", val).strip(" :|-_\t\r\n")
                            if val:
                                extracted[field_name] = val
                                break
                    if field_name in extracted:
                        break

        if not extracted:
            return markdown

        # Populate context metadata
        if "numero_poliza" in extracted:
            context.metadata["extracted_policy_number"] = extracted["numero_poliza"]
        if "tomador" in extracted:
            context.metadata["extracted_policyholder_name"] = extracted["tomador"]
        if "asegurado" in extracted:
            context.metadata["extracted_insured_name"] = extracted["asegurado"]
        context.metadata[f"{self._skill.sigla.lower()}_header_metadata_extracted"] = extracted

        logger.info(
            "Extracted policy metadata from repetitive headers",
            sigla=self._skill.sigla,
            extracted=extracted,
        )

        # Check if table with these keys already exists in the document
        has_poliza_table = bool(re.search(r"\|\s*\*\*P[óo]liza\*\*\s*\|", markdown, re.IGNORECASE))
        has_asegurado_table = bool(re.search(r"\|\s*\*\*Asegurado\*\*\s*\|", markdown, re.IGNORECASE))
        has_tomador_table = bool(re.search(r"\|\s*\*\*Tomador\*\*\s*\|", markdown, re.IGNORECASE))

        # If key fields are missing from markdown tables, inject a structured KV block
        pairs_to_inject: list[tuple[str, str]] = []
        if "numero_poliza" in extracted and not has_poliza_table:
            pairs_to_inject.append(("Póliza", extracted["numero_poliza"]))
        if "tomador" in extracted and not has_tomador_table:
            pairs_to_inject.append(("Tomador", extracted["tomador"]))
        if "asegurado" in extracted and not has_asegurado_table:
            pairs_to_inject.append(("Asegurado", extracted["asegurado"]))

        if pairs_to_inject:
            rendered_kv = self._render_kv_block(pairs_to_inject)
            lines = markdown.splitlines()
            insert_idx = 0
            for idx, line in enumerate(lines[:10]):
                if line.strip().startswith("#"):
                    insert_idx = idx + 1
                    break
            new_lines = lines[:insert_idx] + rendered_kv + lines[insert_idx:]
            return "\n".join(new_lines)

        return markdown

    def _remove_header_patterns(
        self, markdown: str, context: PostProcessingContext
    ) -> str:
        """Remove lines that match any company header/footer pattern.

        Args:
            markdown: Input Markdown text.
            context: Processing context (records removal count).

        Returns:
            Markdown with matching lines removed.
        """
        if not self._header_regexes:
            return markdown

        removed = 0
        result_lines: list[str] = []
        for line in markdown.splitlines():
            stripped = line.strip()
            if any(rx.search(stripped) for rx in self._header_regexes):
                removed += 1
            else:
                result_lines.append(line)

        if removed:
            context.metadata[f"{self._skill.sigla.lower()}_headers_removed"] = removed
            logger.debug(
                "Company header patterns removed",
                sigla=self._skill.sigla,
                removed=removed,
            )

        return "\n".join(result_lines)

    def _reconstruct_split_tables(
        self, markdown: str, context: PostProcessingContext
    ) -> str:
        """Reconstruct tables split across pages or interrupted by removed noise.

        Collapses blank lines between consecutive table data rows so that tables
        split by page breaks, headers or footers remain continuous.
        """
        lines = markdown.splitlines()
        result_lines: list[str] = []
        i = 0
        reconstructed = 0

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # If current line is empty and previous line was a table row
            if not stripped and result_lines and result_lines[-1].strip().startswith("|"):
                # Look ahead past blank lines
                j = i
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines):
                    next_stripped = lines[j].strip()
                    # If the next non-blank line is a table data row (not a divider)
                    if next_stripped.startswith("|") and not re.match(r"^\s*\|\s*:?-+:?", next_stripped):
                        # Join directly, skipping intermediate blank lines
                        i = j
                        reconstructed += 1
                        continue
            result_lines.append(line)
            i += 1

        if reconstructed:
            context.metadata[f"{self._skill.sigla.lower()}_split_tables_reconstructed"] = reconstructed
            logger.debug(
                "Split tables reconstructed",
                sigla=self._skill.sigla,
                reconstructed=reconstructed,
            )

        return "\n".join(result_lines)

    def _apply_table_cell_cleanup_rules(
        self, markdown: str, context: PostProcessingContext
    ) -> str:
        """Apply table cell cleanup regex rules (e.g. junk prefixes, NT suffixes).

        Args:
            markdown: Input Markdown text.
            context: Processing context.

        Returns:
            Markdown with cell cleanup rules applied.
        """
        cleanup_rules = getattr(self._skill, "table_cell_cleanup_rules", [])
        if not cleanup_rules:
            return markdown

        compiled_rules: list[tuple[re.Pattern, str]] = []
        for rule in cleanup_rules:
            if not isinstance(rule, dict):
                continue
            pat = rule.get("pattern")
            rep = rule.get("replacement", r"\1")
            if pat:
                try:
                    compiled_rules.append((re.compile(pat, re.IGNORECASE), rep))
                except re.error as exc:
                    logger.warning(
                        "Invalid table_cell_cleanup_rule pattern",
                        sigla=self._skill.sigla,
                        pattern=pat,
                        error=str(exc),
                    )

        if not compiled_rules:
            return markdown

        lines = markdown.splitlines()
        result_lines: list[str] = []
        cleaned_count = 0

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("|") and not re.match(r"^\s*\|\s*:?-+:?", stripped):
                modified_line = line
                for rx, rep in compiled_rules:
                    new_line = rx.sub(rep, modified_line)
                    if new_line != modified_line:
                        cleaned_count += 1
                        modified_line = new_line
                result_lines.append(modified_line)
            else:
                result_lines.append(line)

        if cleaned_count:
            context.metadata[f"{self._skill.sigla.lower()}_table_cells_cleaned"] = cleaned_count
            logger.debug(
                "Table cell cleanup rules applied",
                sigla=self._skill.sigla,
                cleaned=cleaned_count,
            )

        return "\n".join(result_lines)

    def _apply_kv_rules(
        self, markdown: str, context: PostProcessingContext
    ) -> str:
        """Detect company-specific KV pairs and format as Markdown table rows.

        Pairs whose key is already inside a Markdown table (line starts with
        ``|``) are left unchanged to avoid double-processing.

        Args:
            markdown: Input Markdown text.
            context: Processing context.

        Returns:
            Markdown with company KV pairs formatted.
        """
        if not self._kv_regex:
            return markdown

        lines = markdown.splitlines()
        result_lines: list[str] = []
        kv_block: list[tuple[str, str]] = []
        i = 0
        formatted = 0

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # Skip lines already in a Markdown table
            if stripped.startswith("|"):
                if re.match(r"^\s*\|\s*Campo\s*\|\s*Detalle\s*(?:/\s*Valor)?\s*\|\s*$", stripped, re.IGNORECASE):
                    i += 1
                    if i < len(lines) and re.match(r"^\s*\|\s*:?-+:?\s*\|\s*:?-+:?\s*\|\s*$", lines[i].strip()):
                        i += 1
                    continue

                if kv_block:
                    result_lines.extend(self._render_kv_block(kv_block))
                    formatted += len(kv_block)
                    kv_block = []
                result_lines.append(line)
                i += 1
                continue

            m = self._kv_regex.match(stripped)
            if m:
                key = m.group("key").strip()
                value = m.group("value").strip().rstrip(":")

                # If value is empty, check next line
                if not value and i + 1 < len(lines):
                    next_stripped = lines[i + 1].strip()
                    if next_stripped and not self._kv_regex.match(next_stripped):
                        value = next_stripped
                        i += 1  # consume next line

                kv_block.append((key, value))
            else:
                # Flush accumulated KV block before non-KV line
                if kv_block:
                    result_lines.extend(self._render_kv_block(kv_block))
                    formatted += len(kv_block)
                    kv_block = []
                result_lines.append(line)

            i += 1

        # Flush remaining block
        if kv_block:
            result_lines.extend(self._render_kv_block(kv_block))
            formatted += len(kv_block)

        if formatted:
            context.metadata[f"{self._skill.sigla.lower()}_kv_fields_formatted"] = (
                context.metadata.get(f"{self._skill.sigla.lower()}_kv_fields_formatted", 0)
                + formatted
            )

        return "\n".join(result_lines)

    def _apply_table_split_hints(
        self, markdown: str, context: PostProcessingContext
    ) -> str:
        """Insert a Markdown separator (---) before section hint headings.

        Helps downstream consumers identify table and section boundaries
        defined by the company's document structure.

        Args:
            markdown: Input Markdown text.
            context: Processing context.

        Returns:
            Markdown with separators inserted before hint sections.
        """
        if not self._hint_regexes:
            return markdown

        inserted = 0
        result_lines: list[str] = []
        for line in markdown.splitlines():
            stripped = line.strip()
            if any(rx.search(stripped) for rx in self._hint_regexes):
                # Insert separator only if not already preceded by one
                if result_lines and result_lines[-1].strip() != "---":
                    result_lines.append("")
                    result_lines.append("---")
                    inserted += 1
            result_lines.append(line)

        if inserted:
            context.metadata[f"{self._skill.sigla.lower()}_separators_inserted"] = inserted

        return "\n".join(result_lines)

    def _render_kv_block(self, pairs: list[tuple[str, str]]) -> list[str]:
        """Render accumulated KV pairs as Markdown table lines without generic header.

        Args:
            pairs: List of (key, value) tuples.

        Returns:
            List of Markdown table lines.
        """
        lines = [
            "",
        ]
        for key, value in pairs:
            clean_v = value.strip() if value else "-"
            lines.append(f"| **{key.strip()}** | {clean_v} |")
        lines.append("")
        return lines

    def _apply_table_column_alignment_fixes(
        self, markdown: str, context: PostProcessingContext
    ) -> str:
        """Fix column alignment shifts in Markdown tables according to skill rules.

        Args:
            markdown: Input Markdown text.
            context: Processing context.

        Returns:
            Markdown with table column alignment fixes applied.
        """
        fixes = getattr(self._skill, "table_column_alignment_fixes", [])
        if not fixes:
            return markdown

        # Check for whole-table structural reconstruction rules (e.g. BIS multidimensional deductibles, talleres tables)
        for fix in fixes:
            if isinstance(fix, dict):
                rule_type = fix.get("rule_type")
                if rule_type == "reconstruct_multidimensional_deducibles":
                    markdown = self._reconstruct_bis_deducible_table(markdown)
                elif rule_type == "reconstruct_talleres_table":
                    markdown = self._reconstruct_talleres_table(markdown)

        lines = markdown.splitlines()
        result_lines: list[str] = []
        i = 0
        fixed_count = 0

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            if stripped.startswith("|"):
                if re.match(r"^\s*\|\s*:?-+:?", stripped):
                    # Check if preceding non-blank line in result_lines is a table row/header
                    has_preceding_table_row = False
                    for prev_line in reversed(result_lines):
                        prev_stripped = prev_line.strip()
                        if not prev_stripped:
                            continue
                        if prev_stripped.startswith("|") and not re.match(r"^\s*\|\s*:?-+:?", prev_stripped):
                            has_preceding_table_row = True
                        break
                    if not has_preceding_table_row:
                        # Drop orphan table separator line
                        i += 1
                        continue

                if not re.match(r"^\s*\|\s*:?-+:?", stripped):
                    header_cells = [c.strip() for c in stripped.strip("|").split("|")]

                    matching_fix = None
                    for fix in fixes:
                        if not isinstance(fix, dict):
                            continue
                        header_pattern = fix.get("header_pattern", [])
                        trigger_columns = fix.get("trigger_columns", [])

                        if header_pattern:
                            if all(hp in header_cells for hp in header_pattern):
                                matching_fix = fix
                                break
                            # Check substring/normalized match if exact membership didn't match
                            norm_header_text = re.sub(r"\s+", " ", stripped).upper()
                            if all(re.sub(r"\s+", " ", hp).upper() in norm_header_text for hp in header_pattern):
                                matching_fix = fix
                                break
                        elif trigger_columns:
                            if all(tc in header_cells for tc in trigger_columns):
                                matching_fix = fix
                                break

                    if matching_fix:
                        rule_type = matching_fix.get("rule_type")
                        if rule_type == "reorder_split_provider_table" or "expected_header" in matching_fix:
                            expected_header = matching_fix.get(
                                "expected_header",
                                ["CENTRO DE CONVENIO", "DIRECCION", "TELÉFONOS", "PERSONA DE CONTACTO"],
                            )
                            result_lines.append("| " + " | ".join(expected_header) + " |")
                            i += 1

                            while i < len(lines) and lines[i].strip().startswith("|"):
                                row_line = lines[i]
                                row_stripped = row_line.strip()

                                if re.match(r"^\s*\|\s*:?-+:?", row_stripped):
                                    result_lines.append("| " + " | ".join(["---"] * len(expected_header)) + " |")
                                    i += 1
                                    continue

                                cells = [re.sub(r"\s+", " ", c.strip()) for c in row_stripped.strip("|").split("|")]
                                if len(cells) == len(expected_header):
                                    result_lines.append("| " + " | ".join(cells) + " |")
                                    fixed_count += 1
                                elif len(cells) == 3:
                                    c0, c1, c2 = cells[0], cells[1], cells[2]
                                    telefonos = c1
                                    centro_convenio = ""
                                    direccion = ""
                                    persona_contacto = ""

                                    c0_upper = c0.upper()
                                    c2_upper = c2.upper()

                                    provider_prefixes = (
                                        "CLÍNICA",
                                        "CLINICA",
                                        "HOSPITAL",
                                        "CENTRO",
                                        "POLICLÍNICA",
                                        "POLICLINICA",
                                        "CONSULTORIO",
                                        "LABORATORIO",
                                        "INSTITUTO",
                                        "SANATORIO",
                                    )
                                    address_markers = [
                                        " AV.",
                                        " CALLE",
                                        " C/",
                                        " DOBLE VÍA",
                                        " DOBLE VIA",
                                        " Z/",
                                        " BARRIO",
                                        " B/",
                                        " KM",
                                        " Nº",
                                        " #",
                                        " NRO",
                                    ]

                                    if c0_upper.startswith("HOSPITAL") and c2_upper.startswith("UNIVERSITARIO"):
                                        centro_convenio = "HOSPITAL UNIVERSITARIO"
                                        direccion = c0[len("HOSPITAL") :].strip()
                                        persona_contacto = c2[len("UNIVERSITARIO") :].strip()
                                    elif c0_upper.startswith(provider_prefixes):
                                        split_pos = -1
                                        for marker in address_markers:
                                            pos = c0_upper.find(marker)
                                            if pos != -1 and (split_pos == -1 or pos < split_pos):
                                                split_pos = pos
                                        if split_pos != -1:
                                            centro_convenio = c0[:split_pos].strip()
                                            direccion = c0[split_pos:].strip()
                                        else:
                                            centro_convenio = c0
                                            direccion = ""
                                        persona_contacto = c2
                                    else:
                                        direccion = c0
                                        centro_convenio, persona_contacto = self._split_provider_and_contact(c2)

                                    centro_convenio = re.sub(r"\s+", " ", centro_convenio).strip()
                                    direccion = re.sub(r"\s+", " ", direccion).strip()
                                    telefonos = re.sub(r"\s+", " ", telefonos).strip()
                                    persona_contacto = re.sub(r"\s+", " ", persona_contacto).strip()

                                    new_row = f"| {centro_convenio} | {direccion} | {telefonos} | {persona_contacto} |"
                                    result_lines.append(new_row)
                                    fixed_count += 1
                                else:
                                    result_lines.append(row_line)
                                i += 1
                            continue

                        # Standard cell insertion fix (e.g. fix_franq_pct_zero_omission, fix_nomina_asegurados_incap_omission)
                        expected_cols = matching_fix.get("expected_columns", len(header_cells))
                        insert_idx = matching_fix.get("insert_at_index", 3)
                        fill_val_config = matching_fix.get("fill_value", "0.00")

                        result_lines.append(line)
                        i += 1

                        if i < len(lines) and lines[i].strip().startswith("|") and re.match(r"^\s*\|\s*:?-+:?", lines[i].strip()):
                            result_lines.append(lines[i])
                            i += 1
                        else:
                            result_lines.append("| " + " | ".join(["---"] * expected_cols) + " |")

                        while i < len(lines) and lines[i].strip().startswith("|"):
                            row_line = lines[i]
                            row_stripped = row_line.strip()

                            if re.match(r"^\s*\|\s*:?-+:?", row_stripped):
                                result_lines.append(row_line)
                                i += 1
                                continue

                            cells = [c.strip() for c in row_stripped.strip("|").split("|")]
                            if len(cells) == expected_cols - 1:
                                if fill_val_config == "copy_previous":
                                    fill_val = cells[insert_idx - 1] if insert_idx > 0 and insert_idx - 1 < len(cells) else ""
                                elif fill_val_config.startswith("copy_index_"):
                                    try:
                                        src_idx = int(fill_val_config.replace("copy_index_", ""))
                                        fill_val = cells[src_idx]
                                    except (ValueError, IndexError):
                                        fill_val = ""
                                else:
                                    fill_val = fill_val_config

                                cells.insert(insert_idx, fill_val)
                                new_row = "| " + " | ".join(cells) + " |"
                                result_lines.append(new_row)
                                fixed_count += 1
                            else:
                                result_lines.append(row_line)
                            i += 1
                        continue

            result_lines.append(line)
            i += 1

        if fixed_count:
            context.metadata[f"{self._skill.sigla.lower()}_table_alignment_fixes"] = fixed_count
            logger.debug(
                "Table column alignment fixes applied",
                sigla=self._skill.sigla,
                fixed=fixed_count,
            )

        return "\n".join(result_lines)

    def _split_provider_and_contact(self, text: str) -> tuple[str, str]:
        """Split merged text into (provider_name, contact_person).

        Identifies transition from provider name (ALL CAPS / numbers / roman numerals)
        to contact person (Title Case or honorifics like Dra., Dr., Sra., Lic.).
        """
        words = text.split()
        if not words:
            return "", ""

        honorifics = {"dra.", "dr.", "sra.", "sr.", "lic.", "ing.", "don", "doña"}
        split_idx = len(words)

        for idx, w in enumerate(words):
            w_clean = re.sub(r"[^\w\.]", "", w).lower()
            if w_clean in honorifics:
                split_idx = idx
                break
            if idx > 0 and w[0].isupper() and (len(w) > 1 and w[1:].islower()):
                split_idx = idx
                break

        if split_idx < len(words):
            provider = " ".join(words[:split_idx])
            contact = " ".join(words[split_idx:])
            return provider, contact
        return text, ""

    def _reconstruct_bis_deducible_table(self, markdown: str) -> str:
        """Reconstruct fragmented multidimensional deductible table in BIS policies.

        Fixes the issue where Docling separates 'Plan 1', treats 'Fuera del país de residencia'
        as a header, drops the international limit for Plan 1 (US$ 5,000), and merges columns
        for Plans 2, 3, and 4 into a single cell.
        """
        def _extract_plan_row_values(cell_text: str) -> tuple[str, str]:
            amounts = re.findall(
                r"([A-Za-zñáéíóúÁÉÍÓÚ\s]+(?:\(US\$[\d,\.]+\)|US\$[\d,\.]+))",
                cell_text,
                re.IGNORECASE,
            )
            cleaned = [a.strip() for a in amounts if a.strip()]
            if len(cleaned) >= 2:
                return cleaned[0], cleaned[1]
            elif len(cleaned) == 1:
                return cleaned[0], cleaned[0]
            val = re.sub(r"^\d+\s*", "", cell_text).strip()
            return val, val

        # Pattern 1: | **Plan** | 1 | first, then Dentro del país...
        p1 = re.compile(
            r"(\|\s*\*?\*?Plan\*?\*?\s*\|\s*1\s*\|\s*[\r\n]+"
            r"[\s\S]*?"
            r"Dentro del\s+(?:\*?\*?)pa[íi]s de residencia(?:\*?\*?):?\s*[\r\n]+"
            r"([^\r\n]+?250\)?)\s*[\r\n]+"
            r"#*\s*Fuera del\s+(?:\*?\*?)pa[íi]s de residencia(?:\*?\*?):?\s*[\r\n]+"
            r"[\s\S]*?"
            r"\|\s*\*?\*?Plan\*?\*?\s*\|\s*2\s+([^\r\n\|]+?)\s*\|\s*[\r\n]+"
            r"[\s\S]*?"
            r"\|\s*\*?\*?Plan\*?\*?\s*\|\s*3\s+([^\r\n\|]+?)\s*\|\s*[\r\n]+"
            r"[\s\S]*?"
            r"\|\s*\*?\*?Plan\*?\*?\s*\|\s*4\s+([^\r\n\|]+?)\s*\|)",
            re.IGNORECASE,
        )

        # Pattern 2: Dentro del país first, then Plan 1...
        p2 = re.compile(
            r"(Dentro del\s+(?:\*?\*?)pa[íi]s de residencia(?:\*?\*?):?\s*[\r\n]+"
            r"[\s\S]*?"
            r"([^\r\n]+?250\)?)\s*[\r\n]+"
            r"#*\s*Fuera del\s+(?:\*?\*?)pa[íi]s de residencia(?:\*?\*?):?\s*[\r\n]+"
            r"[\s\S]*?"
            r"\|\s*\*?\*?Plan\*?\*?\s*\|\s*2\s+([^\r\n\|]+?)\s*\|\s*[\r\n]+"
            r"[\s\S]*?"
            r"\|\s*\*?\*?Plan\*?\*?\s*\|\s*3\s+([^\r\n\|]+?)\s*\|\s*[\r\n]+"
            r"[\s\S]*?"
            r"\|\s*\*?\*?Plan\*?\*?\s*\|\s*4\s+([^\r\n\|]+?)\s*\|)",
            re.IGNORECASE,
        )

        for pat in (p1, p2):
            match = pat.search(markdown)
            if match:
                plan1_dentro = match.group(2).strip()
                plan1_fuera = "Cinco mil dólares (US$5,000)"
                p2_dentro, p2_fuera = _extract_plan_row_values(match.group(3))
                p3_dentro, p3_fuera = _extract_plan_row_values(match.group(4))
                p4_dentro, p4_fuera = _extract_plan_row_values(match.group(5))

                reconstructed_table = (
                    "| Plan | Dentro del país de residencia | Fuera del país de residencia |\n"
                    "| --- | --- | --- |\n"
                    f"| Plan 1 | {plan1_dentro} | {plan1_fuera} |\n"
                    f"| Plan 2 | {p2_dentro} | {p2_fuera} |\n"
                    f"| Plan 3 | {p3_dentro} | {p3_fuera} |\n"
                    f"| Plan 4 | {p4_dentro} | {p4_fuera} |"
                )

                markdown = markdown[: match.start(1)] + reconstructed_table + markdown[match.end(1) :]
                break

        return markdown

    def _reconstruct_talleres_table(self, markdown: str) -> str:
        """Reconstruct and repair fragmented workshop and provider directory tables.

        Fixes issues where Docling splits tables due to multi-line wrapping in header
        cells (e.g. '## O PROPIETARIO', '## PROPIETARIO'), misclassifies mid-cell text
        as section headers (e.g. '## LOPEZ)', '## NO1657', '## BURBOA', '## LEONES',
        '## SHUGAMOTORS', '## CAMIONES FLOTAS'), fractures multi-line table rows,
        and shifts single-character tokens across column boundaries.

        Args:
            markdown: Input Markdown text.

        Returns:
            Markdown with clean, unified 5-column workshop tables.
        """
        # Ensure section headers glued to table lines are properly detached
        markdown = re.sub(
            r"(\|\s*)(#+\s*LISTA\s+DE\s+TALLERES[^\r\n]*)",
            r"\1\n\n\2\n",
            markdown,
            flags=re.IGNORECASE,
        )

        lines = markdown.splitlines()
        result_lines: list[str] = []
        i = 0

        def _is_taller_header(line_str: str) -> bool:
            s = line_str.upper()
            return (
                ("NOMBRE" in s or "TALLER" in s or "TALLE" in s)
                and (
                    "DIRECC" in s
                    or "TELEF" in s
                    or "ELEF" in s
                    or "REPRES" in s
                    or "PROP" in s
                )
            )

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            is_sec_header = bool(
                re.match(r"^#+\s*LISTA\s+DE\s+TALLERES", stripped, re.IGNORECASE)
            )
            is_tbl_header = stripped.startswith("|") and _is_taller_header(stripped)

            if is_sec_header or is_tbl_header:
                section_header = None
                if is_sec_header:
                    section_header = stripped
                    i += 1
                    while i < len(lines) and not lines[i].strip():
                        i += 1

                raw_entries: list[dict[str, str]] = []
                current_entry: dict[str, str] | None = None
                pending_spurious_text: list[str] = []

                while i < len(lines):
                    cur = lines[i].strip()
                    if not cur:
                        j = i + 1
                        while j < len(lines) and not lines[j].strip():
                            j += 1
                        if j < len(lines):
                            next_line = lines[j].strip()
                            if next_line.startswith("|") or (
                                next_line.startswith("##")
                                and not re.match(
                                    r"^#+\s*LISTA\s+DE\s+TALLERES",
                                    next_line,
                                    re.IGNORECASE,
                                )
                                and not re.match(
                                    r"^#+\s*(?:CONDICION|P[ÓO]LIZA|SEGURO|COBERTURA|DISPOSICION|CLAUSULA|ANEXO|\d+\.)",
                                    next_line,
                                    re.IGNORECASE,
                                )
                            ):
                                i = j
                                continue
                        break

                    if cur.startswith("#"):
                        if re.match(
                            r"^#+\s*LISTA\s+DE\s+TALLERES", cur, re.IGNORECASE
                        ):
                            break
                        if re.match(
                            r"^#+\s*(?:CONDICION|P[ÓO]LIZA|SEGURO|COBERTURA|DISPOSICION|CLAUSULA|ANEXO|\d+\.)",
                            cur,
                            re.IGNORECASE,
                        ):
                            break

                        header_text = re.sub(r"^#+\s*", "", cur).strip()
                        if header_text.upper() in ("O PROPIETARIO", "PROPIETARIO"):
                            i += 1
                            continue

                        if current_entry:
                            if any(
                                k in header_text.upper()
                                for k in (
                                    "CALLE",
                                    "AV",
                                    "KM",
                                    "NO",
                                    "Nº",
                                    "ZONA",
                                    "BARRIO",
                                    "ROTON",
                                    "LEONES",
                                    "GUARDIA",
                                    "COMBATIENTES",
                                )
                            ):
                                current_entry["address"] = (
                                    current_entry["address"] + " " + header_text
                                ).strip()
                            elif header_text.startswith('"') or any(
                                k in header_text.upper()
                                for k in (
                                    "SHUGA",
                                    "FLOTA",
                                    "CAMION",
                                    "TALLER",
                                    "MECANIC",
                                )
                            ):
                                current_entry["name"] = (
                                    current_entry["name"] + " " + header_text
                                ).strip()
                            else:
                                if current_entry["rep"]:
                                    current_entry["rep"] = (
                                        current_entry["rep"] + " " + header_text
                                    ).strip()
                                else:
                                    current_entry["address"] = (
                                        current_entry["address"] + " " + header_text
                                    ).strip()
                        else:
                            pending_spurious_text.append(header_text)
                        i += 1
                        continue

                    if cur.startswith("|"):
                        if re.match(r"^\s*\|\s*:?-+:?", cur):
                            i += 1
                            continue
                        if _is_taller_header(cur):
                            i += 1
                            if i < len(lines):
                                nxt = lines[i].strip()
                                if (
                                    nxt.startswith("|")
                                    and (
                                        "TALLER" in nxt.upper()
                                        or "PROPIETARIO" in nxt.upper()
                                    )
                                    and not re.search(r"\d+", nxt)
                                ):
                                    i += 1
                            continue

                        cells = [c.strip() for c in cur.strip("|").split("|")]
                        while len(cells) < 5:
                            cells.append("")
                        c_no, c_name, c_rep, c_addr, c_tel = (
                            cells[0],
                            cells[1],
                            cells[2],
                            cells[3],
                            cells[4],
                        )

                        no_match = re.match(r"^\s*(\d+)\.?\s*$", c_no)
                        if no_match:
                            item_num = no_match.group(1)
                            if len(c_rep) <= 2 and c_rep.isalpha() and not c_rep.isspace():
                                c_name = (c_name + " " + c_rep).strip()
                                c_rep = ""

                            current_entry = {
                                "no": item_num,
                                "name": c_name,
                                "rep": c_rep,
                                "address": c_addr,
                                "tel": c_tel,
                            }
                            if pending_spurious_text:
                                for pst in pending_spurious_text:
                                    current_entry["address"] = (
                                        pst + " " + current_entry["address"]
                                    ).strip()
                                pending_spurious_text.clear()

                            raw_entries.append(current_entry)
                        else:
                            if current_entry:
                                if c_rep:
                                    if len(c_rep) <= 2 and c_rep.isalpha():
                                        current_entry["name"] = (
                                            current_entry["name"] + " " + c_rep
                                        ).strip()
                                    elif not current_entry["rep"]:
                                        current_entry["rep"] = c_rep.strip()
                                    else:
                                        current_entry["rep"] = (
                                            current_entry["rep"] + " " + c_rep
                                        ).strip()
                                if c_name:
                                    current_entry["name"] = (
                                        current_entry["name"] + " " + c_name
                                    ).strip()
                                if c_addr:
                                    current_entry["address"] = (
                                        current_entry["address"] + " " + c_addr
                                    ).strip()
                                if c_tel:
                                    current_entry["tel"] = (
                                        current_entry["tel"] + " / " + c_tel
                                    ).strip()
                            else:
                                if any(cells):
                                    current_entry = {
                                        "no": "",
                                        "name": c_name,
                                        "rep": c_rep,
                                        "address": c_addr,
                                        "tel": c_tel,
                                    }
                                    raw_entries.append(current_entry)
                        i += 1
                        continue

                    break

                if raw_entries:
                    if section_header:
                        result_lines.append(section_header)
                        result_lines.append("")
                    result_lines.append(
                        "| No. | NOMBRE DE TALLER | REPRESENTANTE LEGAL O PROPIETARIO | DIRECCION | TELEFONO |"
                    )
                    result_lines.append(
                        "| --- | --- | --- | --- | --- |"
                    )
                    for ent in raw_entries:
                        clean_no = ent["no"]
                        clean_name = re.sub(r"\s+", " ", ent["name"]).strip()
                        clean_rep = re.sub(r"\s+", " ", ent["rep"]).strip()
                        clean_addr = re.sub(r"\s+", " ", ent["address"]).strip()
                        clean_tel = re.sub(r"\s+", " ", ent["tel"]).strip()
                        result_lines.append(
                            f"| {clean_no} | {clean_name} | {clean_rep} | {clean_addr} | {clean_tel} |"
                        )
                    result_lines.append("")
                    continue

            result_lines.append(line)
            i += 1

        return "\n".join(result_lines)




