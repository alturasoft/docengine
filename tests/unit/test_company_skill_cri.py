"""DocEngine — Unit Tests: CRI Company Skill & Header Metadata Extraction.

Tests for Credinform International S.A. skill loading, rule merging,
and extraction of tomador/asegurado and policy number from repetitive headers.
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


class TestCriskillLoading:
    """Validate skill-cri.md parses correctly."""

    def test_load_cri_skill(self) -> None:
        skill = load_company_skill("CRI")
        assert skill is not None
        assert skill.sigla == "CRI"
        assert skill.version >= 4
        assert skill.estado == "activo"
        assert "Asegurado" in skill.kv_keys
        assert "Tomador" in skill.kv_keys
        assert "Póliza" in skill.kv_keys
        assert len(skill.header_metadata_patterns) > 0

    def test_load_cri_skill_merged_with_general(self) -> None:
        merged = load_company_skill_merged("CRI")
        assert merged.sigla == "CRI"
        # Includes general keys
        assert "Producto" in merged.kv_keys
        assert "Vigencia" in merged.kv_keys
        # Includes company keys
        assert "Asegurado" in merged.kv_keys
        assert "Tomador" in merged.kv_keys
        # Includes metadata extraction patterns
        assert len(merged.header_metadata_patterns) > 0


class TestCriHeaderMetadataExtraction:
    """Validate repetitive header extraction of tomador, asegurado and policy number."""

    def test_extracts_policy_and_insured_from_repeating_header(self) -> None:
        skill = load_company_skill_merged("CRI")
        processor = CompanyKVRulesProcessor(skill)

        sample_markdown = """# CONDICIONADO PARTICULAR

PÓLIZA NRO. CAC-SCE0651635 | ASEGURADO: SERVICIOS PETROLEROS PONEX S.R.L

## COBERTURAS
| COBERTURAS | Suma |
| --- | --- |
| Muerte Accidental | 70,000 |

----> página 2
PÓLIZA NRO. CAC-SCE0651635 | ASEGURADO: SERVICIOS PETROLEROS PONEX S.R.L

Texto adicional de la póliza...
"""
        context = PostProcessingContext()
        processed = processor.process(sample_markdown, context)

        # Verify context metadata was populated
        assert context.metadata.get("extracted_policy_number") == "CAC-SCE0651635"
        assert context.metadata.get("extracted_insured_name") == "SERVICIOS PETROLEROS PONEX S.R.L"
        assert "cri_header_metadata_extracted" in context.metadata

        # Verify structured table was injected in markdown
        assert "| **Póliza** | CAC-SCE0651635 |" in processed
        assert "| **Asegurado** | SERVICIOS PETROLEROS PONEX S.R.L |" in processed

    def test_extracts_tomador_and_policy_from_page_texts(self) -> None:
        skill = load_company_skill_merged("CRI")
        processor = CompanyKVRulesProcessor(skill)

        page_texts = [
            "CREDINFORM INTERNATIONAL S.A.\nPOLIZA: 102-911210-2002\nTOMADOR: EMPRESA INDUSTRIAL BOLIVIANA S.A.\nCONDICIONES PARTICULARES",
            "CREDINFORM INTERNATIONAL S.A.\nPOLIZA: 102-911210-2002\nTOMADOR: EMPRESA INDUSTRIAL BOLIVIANA S.A.\nDetalle de coberturas...",
        ]

        sample_markdown = "# CONDICIONES PARTICULARES\n\nContenido de la póliza..."
        context = PostProcessingContext(page_texts=page_texts)
        processed = processor.process(sample_markdown, context)

        assert context.metadata.get("extracted_policy_number") == "102-911210-2002"
        assert context.metadata.get("extracted_policyholder_name") == "EMPRESA INDUSTRIAL BOLIVIANA S.A."
        assert "| **Póliza** | 102-911210-2002 |" in processed
        assert "| **Tomador** | EMPRESA INDUSTRIAL BOLIVIANA S.A. |" in processed


class TestCriTableCleanupAndNoiseRemoval:
    """Validate table cell junk cleaning, NT suffix removal, and noise elimination."""

    def test_clean_table_junk_prefixes_and_nt_suffixes(self) -> None:
        skill = load_company_skill_merged("CRI")
        processor = CompanyKVRulesProcessor(skill)

        sample_markdown = """| NRO | ASEGURADO | C.I. |
| --- | --- | --- |
| 1 | 1 .- , IVAN FERNANDO NATANAEL PICARDI | CI. 18207 NT |
| 2 | 3 .- , REGINA MARIA ABAROA BLEYER | 6232690 NT |
"""
        context = PostProcessingContext()
        processed = processor.process(sample_markdown, context)

        # Sub-task A: clean junk prefixes
        assert "| 1 | IVAN FERNANDO NATANAEL PICARDI |" in processed
        assert "| 2 | REGINA MARIA ABAROA BLEYER |" in processed
        # Sub-task B: clean CI prefixes and NT suffix
        assert "| 18207 |" in processed
        assert "| 6232690 |" in processed

    def test_noise_removal_and_table_reconstruction(self) -> None:
        skill = load_company_skill_merged("CRI")
        processor = CompanyKVRulesProcessor(skill)

        sample_markdown = """| NRO | ASEGURADO | C.I. |
| --- | --- | --- |
| 18 | MARIO AUGUSTO CAMACHO CABOCOTA | 4574645 |
SERVICIOS PETROLEROS PONEX S.R.L CAC-SCE0651635
Página 3 de 10
| 19 | IVANNA GERALDINE CARRASCO HURTADO | 5332969 |
"""
        context = PostProcessingContext()
        processed = processor.process(sample_markdown, context)

        expected = """| NRO | ASEGURADO | C.I. |
| --- | --- | --- |
| 18 | MARIO AUGUSTO CAMACHO CABOCOTA | 4574645 |
| 19 | IVANNA GERALDINE CARRASCO HURTADO | 5332969 |"""

        assert "SERVICIOS PETROLEROS PONEX S.R.L CAC-SCE0651635" not in processed
        assert "Página 3 de 10" not in processed
        assert expected in processed

    def test_ocr_truncation_cleanup_rules(self) -> None:
        skill = load_company_skill_merged("CRI")
        processor = CompanyKVRulesProcessor(skill)

        sample_markdown = """| No. | NOMBRE DE TALLER | PROPIETARIO | DIRECCION | TELEFONO |
| --- | --- | --- | --- | --- |
| 1 | SERVICICO MECANIC | ANDRÉS CABALLE | Av. Principal | 70012345 |
| 2 | Punto Axz | JUAN PEREZ | Calle 2 | 70054321 |
"""
        context = PostProcessingContext()
        processed = processor.process(sample_markdown, context)

        assert "| Servicios Mecánicos |" in processed
        assert "| Andrés Caballero |" in processed
        assert "| Punto Axzo |" in processed

    def test_email_celular_split_cleanup(self) -> None:
        skill = load_company_skill_merged("CRI")
        processor = CompanyKVRulesProcessor(skill)

        sample_markdown = """| Contacto |
| --- |
| jsteer@ag.com.bo 70059881 |
"""
        context = PostProcessingContext()
        processed = processor.process(sample_markdown, context)

        assert "| jsteer@ag.com.bo | 70059881 |" in processed


