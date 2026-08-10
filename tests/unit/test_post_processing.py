"""Unit tests for Markdown post-processing pipeline and rules ("skills")."""

from __future__ import annotations

import pytest

from app.application.post_processing import (
    BasePostProcessor,
    PostProcessingContext,
    PostProcessingPipeline,
    create_default_pipeline,
)
from app.application.post_processing.processors import (
    DeduplicateOverlappingParagraphsProcessor,
    InsuranceTableSplitterProcessor,
    PolicyKeyValueFormatterProcessor,
    SpacedTextFixerProcessor,
)


class DummyProcessor(BasePostProcessor):
    def __init__(self, suffix: str = " [modified]"):
        self._suffix = suffix

    @property
    def name(self) -> str:
        return "dummy_processor"

    def process(self, markdown: str, context: PostProcessingContext) -> str:
        return markdown.strip() + self._suffix


class FailingProcessor(BasePostProcessor):
    @property
    def name(self) -> str:
        return "failing_processor"

    def process(self, markdown: str, context: PostProcessingContext) -> str:
        raise ValueError("Simulated processor error")


class TestPostProcessingPipeline:
    """Tests for pipeline registration, execution, and error isolation."""

    def test_pipeline_executes_registered_processors(self) -> None:
        pipeline = PostProcessingPipeline()
        pipeline.register(DummyProcessor(suffix=" 1"))
        pipeline.register(DummyProcessor(suffix=" 2"))

        result_md, ctx = pipeline.run("Hello")
        assert result_md == "Hello 1 2"
        assert "dummy_processor" in ctx.transformations_applied

    def test_pipeline_isolates_failing_processor(self) -> None:
        pipeline = PostProcessingPipeline()
        pipeline.register(FailingProcessor())
        pipeline.register(DummyProcessor(suffix=" OK"))

        result_md, ctx = pipeline.run("Hello")
        assert result_md == "Hello OK"
        assert len(ctx.errors) == 1
        assert "Simulated processor error" in ctx.errors[0]

    def test_default_pipeline_has_all_processors(self) -> None:
        pipeline = create_default_pipeline()
        rules = pipeline.registered_rules
        assert "spaced_text_fixer" in rules
        assert "deduplicate_overlapping_paragraphs" in rules
        assert "policy_key_value_formatter" in rules
        assert "insurance_table_splitter" in rules
        assert "repeated_elements" in rules


class TestDeduplicateOverlappingParagraphsProcessor:
    """Tests for deduplicating overlapping ghost paragraphs."""

    def test_removes_ghost_subsumed_paragraph(self) -> None:
        processor = DeduplicateOverlappingParagraphsProcessor()
        ctx = PostProcessingContext()

        sample_text = (
            "EnVirtuddelasolicitudescritapresentadaporelinteresado\n"
            "En Virtud de la solicitud escrita presentada por el interesado la misma que constituye la base y forma parte de este contrato y en razón de haberse convenido la forma de pago de la prima correspondiente, Alianza Vida, compañía de Seguros y Reaseguros S.A.\n"
        )

        result = processor.process(sample_text, ctx)
        assert "EnVirtuddelasolicitudescritapresentadaporelinteresado" not in result
        assert "En Virtud de la solicitud escrita presentada por el interesado" in result
        assert ctx.metadata.get("deduplicated_paragraphs_count", 0) >= 1


class TestPolicyKeyValueFormatterProcessor:
    """Tests for formatting policy Key-Value form blocks."""

    def test_formats_scattered_kv_lines_into_table(self) -> None:
        processor = PolicyKeyValueFormatterProcessor()
        ctx = PostProcessingContext()

        sample_text = (
            "Producto:\n"
            "100 Accidentes Personales Empresas\n"
            "Tipo de Póliza:\n"
            "Colectiva\n"
            "Póliza:\n"
            "97015945\n"
        )

        result = processor.process(sample_text, ctx)
        assert "| Campo | Detalle / Valor |" not in result
        assert "| **Producto** | 100 Accidentes Personales Empresas |" in result
        assert "| **Tipo de Póliza** | Colectiva |" in result
        assert "| **Póliza** | 97015945 |" in result

    def test_strips_existing_generic_kv_table_headers(self) -> None:
        processor = PolicyKeyValueFormatterProcessor()
        ctx = PostProcessingContext()

        sample_text = (
            "| Campo | Detalle / Valor |\n"
            "| --- | --- |\n"
            "| **Vigencia** | Desde las 12:00 Hrs. del 31/07/2025 Hasta las 12:00 Hrs. del 31/07/2026 (365 días). |\n"
        )

        result = processor.process(sample_text, ctx)
        assert "| Campo | Detalle / Valor |" not in result
        assert "| --- | --- |" not in result
        assert "| **Vigencia** | Desde las 12:00 Hrs. del 31/07/2025 Hasta las 12:00 Hrs. del 31/07/2026 (365 días). |" in result

    def test_kv_formatter_prevents_narrative_swallow(self) -> None:
        processor = PolicyKeyValueFormatterProcessor()
        ctx = PostProcessingContext()

        sample_text = (
            "Póliza:\n"
            "97015945\n"
            "En Virtud de la solicitud escrita basada por el interesado...\n"
            "Producto: 100 Accidentes Personales Empresas\n"
            "Tipo de Póliza: Colectiva\n"
        )

        result = processor.process(sample_text, ctx)
        assert "En Virtud de la solicitud escrita basada por el interesado..." in result
        assert "| **Póliza** | En Virtud" not in result

    def test_kv_formatter_parses_inline_multi_keys(self) -> None:
        processor = PolicyKeyValueFormatterProcessor()
        ctx = PostProcessingContext()

        sample_text = (
            "Producto: 100 Accidentes Personales Empresas\n"
            "Tipo de Póliza: Colectiva Póliza: 97015945 Certificado: 6\n"
            "Frecuencia de Pago: Anual\n"
        )

        result = processor.process(sample_text, ctx)
        assert "| **Tipo de Póliza** | Colectiva |" in result
        assert "| **Póliza** | 97015945 |" in result
        assert "| **Certificado** | 6 |" in result


class TestInsuranceTableSplitterProcessor:
    """Tests for splitting merged tables, stripping footer noise, and pruning empty columns."""

    def test_splits_merged_table_on_sub_header(self) -> None:
        processor = InsuranceTableSplitterProcessor()
        ctx = PostProcessingContext()

        merged_table = (
            "| Código | Nombre | Figura |\n"
            "| --- | --- | --- |\n"
            "| N0000000485264 | ROCA MACHADO, ALEX | Asegurado |\n"
            "| Código | Descripción de Coberturas | Capital Moneda |\n"
            "| 1 | Muerte Accidental | 30.000,00 Dólares |\n"
            "| Página | 21 de | 32 |\n"
        )

        result = processor.process(merged_table, ctx)
        assert "Página" not in result
        assert "Muerte Accidental" in result

    def test_prunes_empty_columns(self) -> None:
        processor = InsuranceTableSplitterProcessor()
        ctx = PostProcessingContext()

        table_with_empty_cols = (
            "| Código | Nombre | | | | Figura | | |\n"
            "| --- | --- | --- | --- | --- | --- | --- | ---\n"
            "| N0000000668489 | PUCHO SANCHEZ, RUBEN | | | | Asegurado | | |\n"
        )

        result = processor.process(table_with_empty_cols, ctx)
        assert "| Código | Nombre | Figura |" in result
        assert "| N0000000668489 | PUCHO SANCHEZ, RUBEN | Asegurado |" in result

    def test_extracts_embedded_title_heading(self) -> None:
        processor = InsuranceTableSplitterProcessor()
        ctx = PostProcessingContext()

        table_with_title = (
            "| | | DESCRIPCIÓN DE COBERTURAS | | | | | |\n"
            "| --- | --- | --- | --- | --- | --- | --- | ---\n"
            "| Código | Descripción | Capital | Moneda | Aplica | Importe | Minimo | Maximo |\n"
            "| 1 | Muerte Accidental | 30.000,00 Dólares | | | | | |\n"
        )

        result = processor.process(table_with_title, ctx)
        assert "## DESCRIPCIÓN DE COBERTURAS" in result
        assert "| Código | Descripción | Capital | Moneda | Aplica | Importe | Minimo | Maximo |" in result


class TestEndToEndInsuranceProcessing:
    """End-to-end test with full default pipeline on insurance PDF sample."""

    def test_full_pipeline_cleans_user_sample(self) -> None:
        pipeline = create_default_pipeline()
        raw_markdown = (
            "## Condiciones Particulares PÓLIZA DE SEGURO DE ACCIDENTES PERSONALES\n\n"
            "Código:\n\n"
            "207 – 935021 – 2012 10 115\n\n"
            "Póliza: 97015945\n"
            "En Virtud de la solicitud escrita presentada por el interesado la misma que constituye la base y forma parte de este contrato y en razón de haberse convenido la forma de pago de la prima correspondiente, Alianza Vida, compañía de Seguros y Reaseguros S.A.\n\n"
            "Producto: 100 Accidentes Personales Empresas\n"
            "Tipo de Póliza: Colectiva Póliza: 97015945 Certificado: 6\n"
            "Frecuencia de Pago: Anual\n"
            "Vigencia: Desde el 05 de julio del 2024 12 M. Hasta el 05 de julio del 2025 12 M.\n"
            "Forma de Pago: Financiado.\n"
            "Agente: J0000000000081 SUDAMERICANA S.R.L. CORREDORES Y ASESORES DE SEGURO\n\n"
            "Se consideran aceptadas las estipulaciones de esta póliza...\n\n"
            "## CLIENTES / REGISTRO DE ASEGURADOS\n\n"
            "| Código | Nombre | | | | Figura | | |\n"
            "|---|---|---|---|---|---|---|---|\n"
            "| N0000000668489 | PUCHO SANCHEZ, RUBEN | | | | Asegurado | | |\n\n"
            "| | | DESCRIPCIÓN DE COBERTURAS | | | | | |\n"
            "|---|---|---|---|---|---|---|---|\n"
            "| Código | Descripción | Capital | Moneda | Aplica | Importe | Minimo | Maximo |\n"
            "| 1 | Muerte Accidental | 30.000,00 Dólares | | | | | |\n"
        )

        result, ctx = pipeline.run(raw_markdown)

        # 1. Check KV table is formed without swallowing paragraph
        assert "| **Producto** | 100 Accidentes Personales Empresas |" in result
        assert "En Virtud de la solicitud escrita" in result

        # 2. Check Table 2 pruned to 3 columns
        assert "| Código | Nombre | Figura |" in result
        assert "| N0000000668489 | PUCHO SANCHEZ, RUBEN | Asegurado |" in result

        # 3. Check Table 3 title extracted
        assert "## DESCRIPCIÓN DE COBERTURAS" in result
        assert "| Código | Descripción | Capital | Moneda | Aplica | Importe | Minimo | Maximo |" in result


class TestTableColumnAlignmentFixes:
    """Tests for table column alignment fixes when Docling omits zero-value cells."""

    def test_fixes_shifted_coberturas_table(self) -> None:
        from app.application.company_skill_loader import CompanySkill
        from app.application.post_processing.processors.company_kv_rules import (
            CompanyKVRulesProcessor,
        )

        skill = CompanySkill(
            sigla="GENERAL",
            empresa="(general)",
            estado="activo",
            table_column_alignment_fixes=[
                {
                    "id": "fix_franq_pct_zero_omission",
                    "header_pattern": ["COBERTURAS", "Alc.", "Franq.(Bs.)", "Franq.(%)", "Valor Asegurado (Bs.)"],
                    "expected_columns": 5,
                    "insert_at_index": 3,
                    "fill_value": "0.00",
                }
            ],
        )

        processor = CompanyKVRulesProcessor(skill)
        ctx = PostProcessingContext()

        sample_table = (
            "| COBERTURAS | Alc. | Franq.(Bs.) | Franq.(%) | Valor Asegurado (Bs.) |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| MUERTE ACCIDENTAL | 100% | 0.00 | 3,710,000.00 |\n"
            "| INCAPACIDAD TOTAL PERMANENTE | 100% | 0.00 | 3,710,000.00 |\n"
            "| GASTOS MEDICOS | 100% | 0.00 | 742,000.00 |\n"
            "| SEPELIO | 100% | 0.00 | 231,000.00 |\n"
            "Prima Total Emitida : Bs. ***5,686.00 .-\n"
        )

        result = processor.process(sample_table, ctx)

        assert "| MUERTE ACCIDENTAL | 100% | 0.00 | 0.00 | 3,710,000.00 |" in result
        assert "| INCAPACIDAD TOTAL PERMANENTE | 100% | 0.00 | 0.00 | 3,710,000.00 |" in result
        assert "| GASTOS MEDICOS | 100% | 0.00 | 0.00 | 742,000.00 |" in result
        assert "| SEPELIO | 100% | 0.00 | 0.00 | 231,000.00 |" in result
        assert "Prima Total Emitida : Bs. ***5,686.00 .-" in result

    def test_fixes_shifted_centro_convenio_table(self):
        from app.application.company_skill_loader import CompanySkill
        from app.application.post_processing.pipeline import PostProcessingContext
        from app.application.post_processing.processors.company_kv_rules import (
            CompanyKVRulesProcessor,
        )

        skill = CompanySkill(
            sigla="GENERAL",
            empresa="(general)",
            estado="activo",
            table_column_alignment_fixes=[
                {
                    "id": "fix_centro_convenio_table",
                    "header_pattern": ["CENTRO DE CONVENIO", "PERSONA DE CONTACTO"],
                    "expected_columns": 4,
                    "expected_header": ["CENTRO DE CONVENIO", "DIRECCION", "TELÉFONOS", "PERSONA DE CONTACTO"],
                    "rule_type": "reorder_split_provider_table",
                }
            ],
        )

        processor = CompanyKVRulesProcessor(skill)
        ctx = PostProcessingContext()

        sample_user_table = (
            "| CENTRO DE CONVENIO | DIRECCION  TELÉFONOS | PERSONA DE  CONTACTO |\n"
            "| --- | --- | --- |\n"
            "| Av. Mutualista esq. Andrés Muñoz, 2  cuadras antes de llegar al 4º anillo. | 3483929  - 69050134 | CLÍNICA FIGUEROA  Dra. Paola Vargas |\n"
            "| Av. Monseñor Rivero 265 | 3363400 77379932 | CLÍNICA KAMIYA  Claudio Bonada |\n"
            "| C/Sara 241 Z/Central | 3332828 3344433 | CLÍNICA TRAUMA  CLINIC  José Cuellar |\n"
            "| Av. Cañoto Esq. Rafael Peña | 3366969 | CLÍNICA NIÑO JESÚS I  Carla Villarroel |\n"
            "| Calle Ballivian # 747 | 3342883 | CLÍNICA NIÑO JESÚS II  Erika Arancibia |\n"
            "| HOSPITAL  Av. Noel Kempff Mercado 705  (tercer anillo interno) | 71353796 | UNIVERSITARIO  Steffany Choque |\n"
            "| CLÍNICA BUENA  SALUD Av. Virgen de Cotoca Z/Pampa de la  isla a 2 cuadras del Matadero  Municipal | 3467677 3488878 | José Edgar Torrez  Añez |\n"
            "| Av. Irala 468 | 3362211 3365577 | CLÍNICA FOIANINI  Claudia Gutiérrez |\n"
            "| Av. Melchor Pinto 103 | 3331920 3331921 | CLÍNICA MAURER  Katiuska Reyes  Orihuela |\n"
            "| Av. Grigota 2450 B/ Urbari | 3520982 3542689 | CLÍNICA MELENDRES  Sra. Fermina Gamos |\n"
            "| HOSPITAL HERNÁNDEZ  VERA Av. Principal entre calle 9 y 10 Villa  1º de mayo | 3463858 | Lidia |\n"
            "| CLÍNICA MAYO | Calle Bolivar esq. Heroes del chaco  Nº 185  -  WARNES | 9232707 709 61877 | Lourdes Suárez |\n"
            "| --- | --- | --- | --- |\n"
            "| CLÍNICA UNIMAX | C/Independencia 264  -  MONTERO | 9224600 9224700 | Lic. Hugo Maciel  78440239 |\n"
            "| CLÍNICA MEDICMEL | Doble vía a La Guardia Km 9  –  LA  GUARDIA | 3540090 | Daniela Tarqui |\n"
        )

        result = processor.process(sample_user_table, ctx)

        assert "| CENTRO DE CONVENIO | DIRECCION | TELÉFONOS | PERSONA DE CONTACTO |" in result
        assert "| CLÍNICA FIGUEROA | Av. Mutualista esq. Andrés Muñoz, 2 cuadras antes de llegar al 4º anillo. | 3483929 - 69050134 | Dra. Paola Vargas |" in result
        assert "| CLÍNICA KAMIYA | Av. Monseñor Rivero 265 | 3363400 77379932 | Claudio Bonada |" in result
        assert "| CLÍNICA TRAUMA CLINIC | C/Sara 241 Z/Central | 3332828 3344433 | José Cuellar |" in result
        assert "| CLÍNICA NIÑO JESÚS I | Av. Cañoto Esq. Rafael Peña | 3366969 | Carla Villarroel |" in result
        assert "| CLÍNICA NIÑO JESÚS II | Calle Ballivian # 747 | 3342883 | Erika Arancibia |" in result
        assert "| HOSPITAL UNIVERSITARIO | Av. Noel Kempff Mercado 705 (tercer anillo interno) | 71353796 | Steffany Choque |" in result
        assert "| CLÍNICA BUENA SALUD | Av. Virgen de Cotoca Z/Pampa de la isla a 2 cuadras del Matadero Municipal | 3467677 3488878 | José Edgar Torrez Añez |" in result
        assert "| CLÍNICA FOIANINI | Av. Irala 468 | 3362211 3365577 | Claudia Gutiérrez |" in result
        assert "| CLÍNICA MAURER | Av. Melchor Pinto 103 | 3331920 3331921 | Katiuska Reyes Orihuela |" in result
        assert "| CLÍNICA MELENDRES | Av. Grigota 2450 B/ Urbari | 3520982 3542689 | Sra. Fermina Gamos |" in result
        assert "| HOSPITAL HERNÁNDEZ VERA | Av. Principal entre calle 9 y 10 Villa 1º de mayo | 3463858 | Lidia |" in result
        assert "| CLÍNICA MAYO | Calle Bolivar esq. Heroes del chaco Nº 185 - WARNES | 9232707 709 61877 | Lourdes Suárez |" in result

    def test_fixes_nomina_asegurados_incap_omission(self):
        from app.application.company_skill_loader import CompanySkill
        from app.application.post_processing.pipeline import PostProcessingContext
        from app.application.post_processing.processors.company_kv_rules import (
            CompanyKVRulesProcessor,
        )

        skill = CompanySkill(
            sigla="GENERAL",
            empresa="(general)",
            estado="activo",
            table_column_alignment_fixes=[
                {
                    "id": "fix_nomina_asegurados_incap_omission",
                    "header_pattern": ["NOMINA DE ASEGURADOS", "DOC.", "M. ACC.", "INCAP.", "G. MED.", "SEP.", "PRIMA"],
                    "expected_columns": 7,
                    "insert_at_index": 3,
                    "fill_value": "copy_previous",
                    "condition": "row_cells == 6 and header_cells == 7",
                }
            ],
        )

        processor = CompanyKVRulesProcessor(skill)
        ctx = PostProcessingContext()

        sample_table = (
            "| --- | --- | --- | --- |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "| NOMINA DE ASEGURADOS | DOC. | M. ACC. | INCAP. | G. MED. | SEP. | PRIMA |\n"
            "| 1 .- , IVAN FERNANDO NATANAEL PICARDI | CI. 18207 NT | 70,000.00 | 14,000.00 | 7,000.00 | 99.00 |\n"
            "| 19 .- , IVANNA GERALDINE CARRASCO HURTADO | CI. 5332969 NT | 210,000.00 | 42,000.00 | 7,000.00 | 352.00 |\n"
            "| 21 .- , MARIA VICTORIA GUERRERO FIGUEROA | CI. 6294748 NT | 350,000.00 | 70,000.00 | 7,000.00 | 494.40 |\n"
            "| 33 .- , OMAR QUIROGA GARCIA | CI. 5873683 NT | 70,000.00 | 14,000.00 | 7,000.00 | 99.00 |\n"
            "<Fin de la Nomina>\n"
        )

        result = processor.process(sample_table, ctx)

        # Ensure orphan separator lines were dropped
        assert not any(line.strip() == "| --- | --- | --- | --- |" for line in result.splitlines())
        assert not any(line.strip() == "| --- | --- | --- | --- | --- | --- |" for line in result.splitlines())
        # Ensure header is followed by proper separator row
        assert "| NOMINA DE ASEGURADOS | DOC. | M. ACC. | INCAP. | G. MED. | SEP. | PRIMA |" in result
        assert "| --- | --- | --- | --- | --- | --- | --- |" in result

        # Ensure INCAP. value is copied from M. ACC. (70,000.00 | 70,000.00) and columns shifted back
        assert "| 1 .- , IVAN FERNANDO NATANAEL PICARDI | CI. 18207 NT | 70,000.00 | 70,000.00 | 14,000.00 | 7,000.00 | 99.00 |" in result
        assert "| 19 .- , IVANNA GERALDINE CARRASCO HURTADO | CI. 5332969 NT | 210,000.00 | 210,000.00 | 42,000.00 | 7,000.00 | 352.00 |" in result
        assert "| 21 .- , MARIA VICTORIA GUERRERO FIGUEROA | CI. 6294748 NT | 350,000.00 | 350,000.00 | 70,000.00 | 7,000.00 | 494.40 |" in result
        assert "| 33 .- , OMAR QUIROGA GARCIA | CI. 5873683 NT | 70,000.00 | 70,000.00 | 14,000.00 | 7,000.00 | 99.00 |" in result



