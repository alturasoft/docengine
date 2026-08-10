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
        """Apply all three passes to the Markdown text.

        Args:
            markdown: Current Markdown content.
            context: Shared post-processing context.

        Returns:
            Transformed Markdown.
        """
        if not markdown.strip() or self._skill.is_empty:
            return markdown

        md = self._remove_header_patterns(markdown, context)
        md = self._apply_kv_rules(md, context)
        md = self._apply_table_split_hints(md, context)
        md = self._apply_table_column_alignment_fixes(md, context)
        return md

    # ------------------------------------------------------------------
    # Private passes
    # ------------------------------------------------------------------

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


