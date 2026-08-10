"""DocEngine — Application: Company Skill Loader.

Reads and parses per-company skill files (``skills/skill-<sigla>.md``) that
accumulate extraction rules for each insurer, plus a general skill file
(``skills/skill-general.md``) that provides common baseline rules for all
companies.

Merge strategy
--------------
When ``load_company_skill_merged()`` is called:

1. The *general* skill (``skill-general.md``) is loaded as the base.
2. The *company* skill (``skill-<sigla>.md``) is loaded as the override.
3. ``merge_skills()`` produces a combined ``CompanySkill`` where:
   - List fields (``kv_keys``, ``header_patterns``, ``table_split_hints``,
     ``currency_fields``) are **unioned** (no duplicates).
   - Scalar fields (``normalize_dates``) are **overridden** by the company
     skill when the company skill is non-draft (``estado != 'borrador'``).
   - Identity fields (``sigla``, ``empresa``, ``version``, ``estado``,
     ``skill_path``) are taken from the company skill.

The loader is intentionally tolerant: missing or malformed sections produce
an empty ``CompanySkill`` rather than raising exceptions, so the pipeline
degrades gracefully when a skill is still in draft state.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Default skills directory (relative to project root)
# ---------------------------------------------------------------------------

_DEFAULT_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"

# Sigla reserved for the general (cross-company) skill file
GENERAL_SKILL_SIGLA = "GENERAL"

# ---------------------------------------------------------------------------
# Domain object
# ---------------------------------------------------------------------------

# Known company registry: maps SIGLA → full name
COMPANY_REGISTRY: dict[str, str] = {
    "ALI": "ALIANZA CIA DE SEGUROS Y REASEGUROS SA",
    "ALV": "ALIANZA VIDA SEGUROS Y REASEGUROS S.A",
    "BIS": "BISA SEGUROS Y REASEGUROS",
    "FOV": "COMPAÑIA DE SEGUROS DE VIDA FORTALEZA S.A",
    "CRI": "CREDINFORM INTERNATIONAL S.A",
    "CRG": "CREDISEGURO S.A. SEGUROS GENERALES",
    "CRP": "CREDISEGURO S.A. SEGUROS PERSONALES",
    "FOR": "FORTALEZA COMPAÑIA DE SEGUROS Y REASEGUROS",
    "LBC": "LA BOLIVIANA CIACRUZ DE SEGUROS Y REASEGUROS",
    "LBP": "LA BOLIVIANA CIACRUZ SEGUROS PERSONALES",
    "VIT": "LA VITALICIA DE SEGUROS Y REASEGUROS",
    "MSC": "MERCANTIL SANTA CRUZ SEGUROS Y REASEGUROS GENERALES S.A",
    "NPF": "NACIONAL SEGUROS PATRIMONIALES Y FIANZAS S.A",
    "NVS": "NACIONAL SEGUROS VIDA Y SALUD S.A",
    "UNI": "SEGUROS Y REASEGUROS PERSONALES UNIVIDA S.A",
    "UBI": "UNIBIENES SEGUROS Y REASEGUROS",
}


@dataclass
class CompanySkill:
    """Parsed company-specific extraction rules from a skill file.

    Attributes:
        sigla: 3-letter company code (e.g. "CRI").
        empresa: Full company name.
        version: Skill file version number.
        estado: Skill maturity state: 'borrador' | 'activo' | 'validado'.
        kv_keys: Extra key-value field names specific to this company.
            These are added to the generic KV detection pipeline.
        header_patterns: Regex patterns that match recurring page headers
            to be removed from the extracted Markdown.
        table_split_hints: Section keywords that signal table boundary points
            for the table-splitter post-processor.
        normalize_dates: Whether to normalise date strings to ISO format.
        currency_fields: Field names whose values should be parsed as currency.
        skill_path: Absolute path of the skill file that was loaded.
        is_empty: True if the skill has no active rules yet (draft state).
    """

    sigla: str
    empresa: str
    version: int = 1
    estado: str = "borrador"
    kv_keys: list[str] = field(default_factory=list)
    header_patterns: list[str] = field(default_factory=list)
    table_split_hints: list[str] = field(default_factory=list)
    normalize_dates: bool = False
    currency_fields: list[str] = field(default_factory=list)
    table_column_alignment_fixes: list[dict] = field(default_factory=list)
    skill_path: Path | None = None

    @property
    def is_empty(self) -> bool:
        """Return True if the skill has no active rules defined yet."""
        return (
            not self.kv_keys
            and not self.header_patterns
            and not self.table_split_hints
            and not self.currency_fields
            and not self.table_column_alignment_fixes
        )

    @property
    def is_active(self) -> bool:
        """Return True if the skill has been promoted past draft state."""
        return self.estado in ("activo", "validado")


# ---------------------------------------------------------------------------
# Internal YAML parsing helpers (no external dependency on PyYAML)
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_RULES_BLOCK_RE = re.compile(
    r"##\s+Reglas\s+de\s+Post-Procesado.*?```yaml\s*\n(.*?)```",
    re.DOTALL | re.IGNORECASE,
)


def _parse_simple_yaml(text: str) -> dict:
    """Parse a minimal subset of YAML (key: value, key: [list]).

    Supports:
    - Scalar values:   ``key: value``
    - Quoted strings:  ``key: "value"``
    - Inline lists:    ``key: [a, b, c]``
    - Block lists:     ``- item`` (after a list key)
    - Boolean values:  ``true`` / ``false``

    Args:
        text: Raw YAML text to parse.

    Returns:
        Dictionary of parsed key/value pairs.
    """
    try:
        import yaml
        parsed = yaml.safe_load(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    result: dict = {}
    current_key: str | None = None
    current_list: list[str] | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        # Block list item (- value)
        if line.startswith("- ") and current_key and current_list is not None:
            item = line[2:].strip().strip("\"'")
            if item:
                current_list.append(item)
            continue

        # Empty list item close — reset list tracking
        if ":" in line:
            # Flush previous block list
            if current_key and current_list is not None:
                result[current_key] = current_list
                current_list = None

            key, _, raw_val = line.partition(":")
            key = key.strip()
            val = raw_val.strip().strip("\"'")

            if val.startswith("[") and val.endswith("]"):
                # Inline list: [a, b, c]
                inner = val[1:-1].strip()
                if inner:
                    result[key] = [v.strip().strip("\"'") for v in inner.split(",") if v.strip()]
                else:
                    result[key] = []
                current_key = None
            elif val == "" or val == "[]":
                # Empty or block list to follow
                result[key] = []
                current_key = key
                current_list = result[key]
            elif val.lower() == "true":
                result[key] = True
                current_key = None
            elif val.lower() == "false":
                result[key] = False
                current_key = None
            else:
                try:
                    result[key] = int(val)
                except ValueError:
                    result[key] = val
                current_key = None

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_company_skill(
    sigla: str,
    skills_dir: Path | None = None,
) -> CompanySkill | None:
    """Load and parse the skill file for the given company sigla.

    Reads ``skills/skill-<sigla_lower>.md`` and extracts:
    - Front-matter metadata (sigla, empresa, version, estado)
    - Active rules from the ``yaml`` block in the "Reglas de Post-Procesado" section

    Args:
        sigla: 3-letter company code, case-insensitive (e.g. "CRI", "ali").
        skills_dir: Directory containing skill files. Defaults to the
            project-level ``skills/`` directory.

    Returns:
        Parsed ``CompanySkill`` instance, or ``None`` if no skill file exists.
    """
    sigla_upper = sigla.strip().upper()
    sigla_lower = sigla_upper.lower()
    skills_root = skills_dir or _DEFAULT_SKILLS_DIR
    skill_path = skills_root / f"skill-{sigla_lower}.md"

    if not skill_path.exists():
        logger.warning(
            "Company skill file not found",
            sigla=sigla_upper,
            path=str(skill_path),
        )
        return None

    try:
        content = skill_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.error("Failed to read skill file", sigla=sigla_upper, error=str(exc))
        return None

    # --- Parse front-matter ---
    fm_match = _FRONTMATTER_RE.match(content)
    fm: dict = {}
    if fm_match:
        fm = _parse_simple_yaml(fm_match.group(1))

    # --- Parse rules block ---
    rules_match = _RULES_BLOCK_RE.search(content)
    rules: dict = {}
    if rules_match:
        rules = _parse_simple_yaml(rules_match.group(1))

    empresa = fm.get("empresa", COMPANY_REGISTRY.get(sigla_upper, sigla_upper))

    skill = CompanySkill(
        sigla=sigla_upper,
        empresa=str(empresa),
        version=int(fm.get("version", 1)),
        estado=str(fm.get("estado", "borrador")),
        kv_keys=list(rules.get("kv_keys", [])),
        header_patterns=list(rules.get("header_patterns", [])),
        table_split_hints=list(rules.get("table_split_hints", [])),
        normalize_dates=bool(rules.get("normalize_dates", False)),
        currency_fields=list(rules.get("currency_fields", [])),
        table_column_alignment_fixes=list(rules.get("table_column_alignment_fixes", [])),
        skill_path=skill_path,
    )

    logger.info(
        "Company skill loaded",
        sigla=sigla_upper,
        empresa=empresa,
        estado=skill.estado,
        kv_keys_count=len(skill.kv_keys),
        is_empty=skill.is_empty,
    )

    return skill


# ---------------------------------------------------------------------------
# General skill + merge helpers
# ---------------------------------------------------------------------------


def load_general_skill(skills_dir: Path | None = None) -> CompanySkill:
    """Load the general (cross-company) skill file.

    Reads ``skills/skill-general.md`` using the same parsing logic as
    ``load_company_skill()``.  Returns an **empty** ``CompanySkill`` with
    ``sigla=GENERAL`` if the file does not exist, so the pipeline degrades
    gracefully.

    Args:
        skills_dir: Directory containing skill files. Defaults to the
            project-level ``skills/`` directory.

    Returns:
        Parsed ``CompanySkill`` for the general skill, or an empty one.
    """
    general = load_company_skill(GENERAL_SKILL_SIGLA, skills_dir=skills_dir)
    if general is None:
        logger.warning(
            "General skill file not found — using empty base",
            sigla=GENERAL_SKILL_SIGLA,
        )
        return CompanySkill(
            sigla=GENERAL_SKILL_SIGLA,
            empresa="(general)",
            estado="borrador",
        )
    return general


def merge_skills(base: CompanySkill, override: CompanySkill) -> CompanySkill:
    """Merge a base (general) skill with a company-specific override.

    Merge rules:
    - **List fields**: union of base + override (preserving order, no duplicates).
    - **normalize_dates**: override value takes precedence when the override
      skill is not in 'borrador' state; otherwise the base value is kept.
    - **Identity fields** (sigla, empresa, version, estado, skill_path):
      taken from ``override``.

    Args:
        base: General (baseline) skill — provides default rules.
        override: Company-specific skill — extends and overrides base.

    Returns:
        New ``CompanySkill`` with merged rules.
    """

    def _union(a: list, b: list) -> list:
        """Return a + b with duplicates removed, preserving order."""
        seen: set = set()
        result: list = []
        for item in (*a, *b):
            key = item
            if isinstance(item, dict):
                key = item.get("id") or str(sorted(item.items()))
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result

    # Scalar override: company wins only when it has been explicitly activated
    if override.estado != "borrador":
        normalize_dates = override.normalize_dates
    else:
        normalize_dates = base.normalize_dates or override.normalize_dates

    merged = CompanySkill(
        sigla=override.sigla,
        empresa=override.empresa,
        version=override.version,
        estado=override.estado,
        kv_keys=_union(base.kv_keys, override.kv_keys),
        header_patterns=_union(base.header_patterns, override.header_patterns),
        table_split_hints=_union(base.table_split_hints, override.table_split_hints),
        normalize_dates=normalize_dates,
        currency_fields=_union(base.currency_fields, override.currency_fields),
        table_column_alignment_fixes=_union(base.table_column_alignment_fixes, override.table_column_alignment_fixes),
        skill_path=override.skill_path,
    )

    logger.info(
        "Skills merged",
        sigla=override.sigla,
        kv_keys_total=len(merged.kv_keys),
        kv_keys_from_general=len([k for k in base.kv_keys if k in merged.kv_keys]),
        kv_keys_from_company=len(override.kv_keys),
        header_patterns_total=len(merged.header_patterns),
        is_empty=merged.is_empty,
    )

    return merged


def load_company_skill_merged(
    sigla: str,
    skills_dir: Path | None = None,
) -> CompanySkill:
    """Load a merged skill: General skill base + company-specific override.

    This is the **recommended entry point** for the extraction pipeline.
    It always returns a valid ``CompanySkill`` (never None), degrading
    gracefully when either skill file is missing or empty.

    Args:
        sigla: 3-letter company code, case-insensitive (e.g. "CRI", "ali").
        skills_dir: Directory containing skill files. Defaults to the
            project-level ``skills/`` directory.

    Returns:
        Merged ``CompanySkill`` combining general + company rules.
    """
    general = load_general_skill(skills_dir=skills_dir)
    company = load_company_skill(sigla, skills_dir=skills_dir)

    if company is None:
        # No company skill → return general skill relabelled with company identity
        sigla_upper = sigla.strip().upper()
        empresa = COMPANY_REGISTRY.get(sigla_upper, sigla_upper)
        logger.warning(
            "No company skill found — using general skill only",
            sigla=sigla_upper,
        )
        return CompanySkill(
            sigla=sigla_upper,
            empresa=empresa,
            version=general.version,
            estado=general.estado,
            kv_keys=list(general.kv_keys),
            header_patterns=list(general.header_patterns),
            table_split_hints=list(general.table_split_hints),
            normalize_dates=general.normalize_dates,
            currency_fields=list(general.currency_fields),
            table_column_alignment_fixes=list(general.table_column_alignment_fixes),
            skill_path=general.skill_path,
        )

    return merge_skills(general, company)


def detect_company_from_path(folder: Path) -> str | None:
    """Infer the company sigla from a folder path under ``empresas/``.

    Checks if any component of ``folder`` is a known company sigla
    (case-insensitive). The folder structure is expected to be::

        empresas/<SIGLA>/...

    but the function works regardless of depth or path prefix.

    Args:
        folder: Path to inspect (can be absolute or relative).

    Returns:
        Uppercase sigla string (e.g. "CRI"), or None if not detectable.

    Examples:
        >>> detect_company_from_path(Path("empresas/CRI"))
        'CRI'
        >>> detect_company_from_path(Path("c:/docengine/empresas/ali"))
        'ALI'
    """
    parts = [p.upper() for p in folder.parts]
    for part in parts:
        if part in COMPANY_REGISTRY:
            return part
    return None
