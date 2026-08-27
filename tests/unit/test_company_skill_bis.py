"""DocEngine — Unit Tests: BIS Company Skill & Post-Processing Rules.

Tests for BISA Seguros y Reaseguros S.A. skill loading, rule merging,
form metadata extraction, table column alignment, and OCR cleanup.
"""

from __future__ import annotations

import pytest

from app.application.company_skill_loader import (
    CompanySkill,
    load_company_skill_merged,
    load_company_skill,
)
from app.application.post_processing.base import PostProcessingContext
from app.application.post_processing.processors.company_kv_rules import (
    CompanyKVRulesProcessor,
)


class TestBisSkillLoading:
    """Validate skill-bis.md parses correctly and merges with general skill."""

    def test_load_bis_skill(self) -> None:
        skill = load_company_skill("BIS")
        assert skill is not None
        assert skill.sigla == "BIS"
        assert skill.version >= 2
        assert skill.estado == "activo"
        assert "Póliza" in skill.kv_keys
        assert "Prima Total Anual" in skill.kv_keys
        assert "Forma de Pago" in skill.kv_keys
        assert "Moneda" in skill.kv_keys
        assert len(skill.header_metadata_patterns) > 0
        assert len(skill.table_cell_cleanup_rules) > 0
        assert len(skill.table_column_alignment_fixes) > 0

    def test_load_bis_skill_merged_with_general(self) -> None:
        merged = load_company_skill_merged("BIS")
        assert merged.sigla == "BIS"
        # Includes general keys
        assert "Producto" in merged.kv_keys
        assert "Vigencia" in merged.kv_keys
        # Includes company keys
        assert "Prima Total Anual" in merged.kv_keys
        assert "Moneda" in merged.kv_keys
        # Includes metadata extraction patterns and cleanup rules
        assert len(merged.header_metadata_patterns) > 0
        assert len(merged.table_cell_cleanup_rules) > 0


class TestBisMetadataAndFormExtraction:
    """Validate extraction of form metadata (Policy number, Vigencia, Tomador, Asegurado)."""

    def test_extracts_policy_and_metadata_from_header(self) -> None:
        skill = load_company_skill_merged("BIS")
        processor = CompanyKVRulesProcessor(skill)

        sample_markdown = """# CARÁTULA DE PÓLIZA

NÚMERO DE PÓLIZA: P1010000046
ASEGURADO: EMPRESA CONTRATISTA S.A.
TOMADOR: INVERSIONES BOLIVIA S.R.L.

## COBERTURAS
| Cobertura | Límite |
| --- | --- |
| Gastos Médicos | 100% |
"""
        context = PostProcessingContext()
        processed = processor.process(sample_markdown, context)

        assert context.metadata.get("extracted_policy_number") == "P1010000046"
        assert context.metadata.get("extracted_insured_name") == "EMPRESA CONTRATISTA S.A."
        assert context.metadata.get("extracted_policyholder_name") == "INVERSIONES BOLIVIA S.R.L."
        assert "| **Póliza** | P1010000046 |" in processed
        assert "| **Asegurado** | EMPRESA CONTRATISTA S.A. |" in processed
        assert "| **Tomador** | INVERSIONES BOLIVIA S.R.L. |" in processed


class TestBisTableCleanupAndAlignment:
    """Validate table cell OCR corrections and alignment fixes for BIS."""

    def test_clean_broker_ocr_truncation(self) -> None:
        skill = load_company_skill_merged("BIS")
        processor = CompanyKVRulesProcessor(skill)

        sample_markdown = """| CAMPO | DETALLE |
| --- | --- |
| Intermediario | Sudamericana S.R.L. es |
"""
        context = PostProcessingContext()
        processed = processor.process(sample_markdown, context)

        assert "Sudamericana S.R.L. Corredores Y Asesores De Seguros" in processed
        assert "Sudamericana S.R.L. es" not in processed

    def test_reconstruct_bis_fragmented_deducibles_table(self) -> None:
        skill = load_company_skill_merged("BIS")
        processor = CompanyKVRulesProcessor(skill)

        sample_markdown = """Opciones de deducible anual obligatorio:

<!-- image -->


| **Plan** | 1 |


Dentro del país de residencia:

Doscientos cincuenta dólares (US$250)

## Fuera del país de residencia


| **Plan** | 2 Dos mil dólares (US$2,000) Dos mil dólares (US$2,000) |


| **Plan** | 3 Cinco mil dólares (US$5,000) Cinco mil dólares (US$5,000) |


| **Plan** | 4 Diez mil dólares (US$10,000) Diez mil dólares (US$10,000) |
"""
        context = PostProcessingContext()
        processed = processor.process(sample_markdown, context)

        expected_rows = [
            "| Plan | Dentro del país de residencia | Fuera del país de residencia |",
            "| --- | --- | --- |",
            "| Plan 1 | Doscientos cincuenta dólares (US$250) | Cinco mil dólares (US$5,000) |",
            "| Plan 2 | Dos mil dólares (US$2,000) | Dos mil dólares (US$2,000) |",
            "| Plan 3 | Cinco mil dólares (US$5,000) | Cinco mil dólares (US$5,000) |",
            "| Plan 4 | Diez mil dólares (US$10,000) | Diez mil dólares (US$10,000) |",
        ]

        for row in expected_rows:
            assert row in processed

        assert "## Fuera del país de residencia" not in processed

