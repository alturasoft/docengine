"""DocEngine — Post-Processor: Policy Key-Value Formatter.

Detects scattered key-value metadata lines in insurance policies and reformats
them into clean Markdown Key-Value tables.
"""

from __future__ import annotations

import re

from app.application.post_processing.base import (
    BasePostProcessor,
    PostProcessingContext,
)

# Known key patterns in insurance policy header forms
_POLICY_KEYS = [
    r"Producto(?:\:)?",
    r"Tipo\s+de\s+Póliza(?:\:)?",
    r"Tipo\s+Póliza(?:\:)?",
    r"Póliza(?:\:)?",
    r"Poliza(?:\:)?",
    r"Certificado(?:\:)?",
    r"Frecuencia\s+de\s+Pago(?:\:)?",
    r"Frecuencia\s+Pago(?:\:)?",
    r"Vigencia(?:\:)?",
    r"Forma\s+de\s+Pago(?:\:)?",
    r"Forma\s+Pago(?:\:)?",
    r"Agente(?:\:)?",
    r"Corredor(?:\:)?",
    r"Ejecutivo(?:\:)?",
]

_INLINE_KEY_REGEX = re.compile(
    r"(?P<key>" + "|".join(_POLICY_KEYS) + r")",
    re.IGNORECASE,
)

_NARRATIVE_PREFIXES = (
    "en virtud",
    "aprobada por",
    "se consideran",
    "conste por",
    "por la presente",
    "el presente",
    "de acuerdo con",
    "la presente póliza",
)


def _is_narrative_line(line: str) -> bool:
    """Return True if line is a narrative sentence or legal clause, not a KV value."""
    s = line.strip().lower()
    if not s:
        return False
    if any(s.startswith(prefix) for prefix in _NARRATIVE_PREFIXES):
        return True
    words = s.split()
    if len(words) > 12:
        return True
    return False


def _parse_inline_kv_pairs(line: str) -> list[tuple[str, str]]:
    """Extract multiple inline key-value pairs from a single line."""
    matches = list(_INLINE_KEY_REGEX.finditer(line))
    if not matches:
        return []

    pairs: list[tuple[str, str]] = []
    for idx, match in enumerate(matches):
        key_raw = match.group("key").rstrip(":")
        val_start = match.end()
        val_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(line)
        val_text = line[val_start:val_end].strip()
        pairs.append((key_raw, val_text))

    return pairs


class PolicyKeyValueFormatterProcessor(BasePostProcessor):
    """Reconstructs scattered insurance policy Key-Value metadata blocks.

    Docling parses layout form boxes (Producto, Póliza, Vigencia, Agente) as
    loose text lines in reading order. This rule aggregates related keys and
    values and renders them as a clean 2-column Markdown table.
    """

    @property
    def name(self) -> str:
        return "policy_key_value_formatter"

    def process(self, markdown: str, context: PostProcessingContext) -> str:
        """Format scattered policy K/V blocks into structured Markdown tables."""
        if not markdown.strip():
            return markdown

        lines = markdown.splitlines()
        result_lines: list[str] = []
        i = 0

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # Strip existing generic K/V table headers if encountered
            if re.match(r"^\s*\|\s*Campo\s*\|\s*Detalle\s*(?:/\s*Valor)?\s*\|\s*$", stripped, re.IGNORECASE):
                i += 1
                if i < len(lines) and re.match(r"^\s*\|\s*:?-+:?\s*\|\s*:?-+:?\s*\|\s*$", lines[i].strip()):
                    i += 1
                continue

            # Check if this line starts a policy K/V sequence
            matches = _parse_inline_kv_pairs(stripped)
            if matches and not stripped.startswith("|"):
                # Collect contiguous K/V block
                kv_pairs: list[tuple[str, str]] = []
                j = i

                while j < len(lines):
                    curr = lines[j].strip()
                    if not curr:
                        j += 1
                        continue

                    # Stop if we hit a table, heading, or narrative clause
                    if curr.startswith(("#", "|", "```", "<!--")) or _is_narrative_line(curr):
                        break

                    inline_pairs = _parse_inline_kv_pairs(curr)
                    if inline_pairs:
                        # Check if the last extracted pair has an empty value and needs lookahead
                        all_has_val = True
                        for idx, (k_name, v_val) in enumerate(inline_pairs):
                            if idx == len(inline_pairs) - 1 and not v_val:
                                all_has_val = False
                            else:
                                kv_pairs.append((k_name, v_val))

                        if all_has_val:
                            j += 1
                        else:
                            last_k_name = inline_pairs[-1][0]
                            # Look ahead for value on next line(s)
                            val_acc: list[str] = []
                            k = j + 1
                            while k < len(lines):
                                next_l = lines[k].strip()
                                if not next_l:
                                    k += 1
                                    continue
                                if (
                                    _parse_inline_kv_pairs(next_l)
                                    or next_l.startswith(("#", "|", "```", "<!--"))
                                    or _is_narrative_line(next_l)
                                ):
                                    break
                                val_acc.append(next_l)
                                k += 1

                            val_str = " ".join(val_acc).strip()
                            kv_pairs.append((last_k_name, val_str))
                            j = k if val_acc else j + 1
                    else:
                        break

                if len(kv_pairs) >= 2:
                    # Format as clean 2-column Markdown table without generic header
                    table_md = self._render_kv_table(kv_pairs)
                    result_lines.extend(table_md)
                    context.metadata["policy_kv_tables_formatted"] = (
                        context.metadata.get("policy_kv_tables_formatted", 0) + 1
                    )
                    i = j
                    continue

            result_lines.append(line)
            i += 1

        return "\n".join(result_lines)

    def _render_kv_table(self, kv_pairs: list[tuple[str, str]]) -> list[str]:
        """Render list of (key, value) pairs as Markdown table lines without generic header."""
        table_lines = [
            "",
        ]
        for k, v in kv_pairs:
            clean_k = k.strip()
            clean_v = v.strip() if v else "-"
            table_lines.append(f"| **{clean_k}** | {clean_v} |")
        table_lines.append("")
        return table_lines
