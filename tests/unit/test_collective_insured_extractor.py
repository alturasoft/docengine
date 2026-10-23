"""Tests [ADITIVOS] para CollectiveInsuredExtractorService, PgInsuredPersonsRepository y RAG hooks."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.application.collective_insured_extractor_service import CollectiveInsuredExtractorService
from app.application.large_policy_context import LargePolicyConfig, LargePolicyContextStrategy
from app.domain.models.insured_person import InsuredPerson
from app.infrastructure.database.pg_insured_persons_repository import PgInsuredPersonsRepository


def test_insured_person_model():
    person = InsuredPerson(
        nombre_completo="JUAN PEREZ ROJAS",
        item_number=1,
        policy_id="pol-123",
        documento_identidad="4829102-LP",
        edad=35,
        parentesco_categoria="TITULAR",
        cargo_ocupacion="INGENIERO",
        suma_asegurada_usd=50000.0,
    )
    d = person.to_dict()
    assert d["nombre_completo"] == "JUAN PEREZ ROJAS"
    assert d["documento_identidad"] == "4829102-LP"
    assert d["edad"] == 35
    assert d["parentesco_categoria"] == "TITULAR"
    assert d["suma_asegurada_usd"] == 50000.0


def test_parse_tables_from_markdown():
    service = CollectiveInsuredExtractorService(MagicMock())
    markdown_table = """
    ## NÓMINA OFICIAL DE ASEGURADOS
    
    | Item | Nombre y Apellidos | C.I. | Parentesco | Edad | Suma Asegurada |
    |------|--------------------|------|------------|------|----------------|
    | 1 | Carlos Alberto Mendoza | 4920192 SC | TITULAR | 42 | 100,000.00 |
    | 2 | Maria Elena Gutierrez | 3829104 SC | CONYUGE | 39 | 50,000.00 |
    | 3 | Rodrigo Mendoza Gutierrez | 8920194 SC | HIJO | 14 | 25,000.00 |
    """

    persons = service._parse_tables_from_markdown(markdown_table)
    assert len(persons) == 3
    assert persons[0]["item_number"] == 1
    assert persons[0]["nombre_completo"] == "Carlos Alberto Mendoza"
    assert persons[0]["documento_identidad"] == "4920192 SC"
    assert persons[0]["parentesco_categoria"] == "TITULAR"
    assert persons[0]["edad"] == 42
    assert persons[0]["suma_asegurada_usd"] == 100000.0

    assert persons[1]["item_number"] == 2
    assert persons[1]["nombre_completo"] == "Maria Elena Gutierrez"
    assert persons[1]["parentesco_categoria"] == "CONYUGE"
    assert persons[1]["suma_asegurada_usd"] == 50000.0


def test_parse_blocks_from_chunks():
    service = CollectiveInsuredExtractorService(MagicMock())
    chunks = [
        {
            "index": 1,
            "content": "ANEXO 1 - CERTIFICADO INDIVIDUAL\nASEGURADO: Juan Carlos Perez\nCARNET: 4920182\nCATEGORIA: EMPLEADO\nSUMA ASEGURADA: $us. 20,000.00",
            "metadata": {},
        },
        {
            "index": 2,
            "content": "ANEXO 2 - CERTIFICADO INDIVIDUAL\nASEGURADO: Sandra Lopez Fernandez\nCARNET: 6819201\nCATEGORIA: EMPLEADA\nSUMA ASEGURADA: $us. 20,000.00",
            "metadata": {},
        },
    ]

    persons = service._parse_blocks_from_chunks(chunks)
    assert len(persons) == 2
    assert persons[0]["nombre_completo"] == "Juan Carlos Perez"
    assert persons[0]["documento_identidad"] == "4920182"
    assert persons[0]["suma_asegurada_usd"] == 20000.0
    assert persons[1]["nombre_completo"] == "Sandra Lopez Fernandez"
    assert persons[1]["documento_identidad"] == "6819201"


def test_parse_global_collective_declaration():
    service = CollectiveInsuredExtractorService(MagicMock())
    raw_md = """
    CONDICIONES PARTICULARES
    CONTRATANTE: EMPRESA CONSTRUCTORA S.A.
    MATERIA DEL SEGURO: 709 Personas según planilla adjunta dependientes del tomador
    COBERTURAS: Muerte Accidental e Invalidez
    """

    res = service._parse_global_collective_declaration(raw_md)
    assert res is not None
    assert "709" in res["nombre_completo"]
    assert res["parentesco_categoria"] == "COLECTIVO / PLANILLA"
    assert res["raw_metadata"]["total_declarado"] == 709


def test_format_insured_summary_chunk():
    mock_repo = MagicMock(spec=PgInsuredPersonsRepository)
    mock_repo.get_insured_summary.return_value = {
        "total_asegurados": 150,
        "total_suma_asegurada_usd": 3000000.0,
        "total_prima_usd": 45000.0,
        "edad_promedio": 36.5,
        "distribucion_categoria": {"TITULAR": 90, "DEPENDIENTE": 60},
        "distribucion_genero": {"MASCULINO": 85, "FEMENINO": 65},
        "muestra": [
            {
                "item_number": 1,
                "nombre_completo": "MARCELO SILVA",
                "documento_identidad": "4729102",
                "parentesco_categoria": "TITULAR",
                "edad": 38,
                "cargo_ocupacion": "OPERADOR",
                "suma_asegurada_usd": 20000.0,
            }
        ],
    }

    service = CollectiveInsuredExtractorService(MagicMock(), insured_repo=mock_repo)
    chunk = service.format_insured_summary_chunk(policy_id="test-policy-uuid")

    assert chunk is not None
    assert "150 personas" in chunk.chunk_content
    assert "$us. 3,000,000.00" in chunk.chunk_content
    assert "TITULAR: 90" in chunk.chunk_content
    assert "MARCELO SILVA" in chunk.chunk_content
    assert chunk.metadata_json["tipo_documento"] == "NOMINA_ASEGURADOS"


def test_is_insured_query_detection():
    strategy = LargePolicyContextStrategy(
        config=LargePolicyConfig(),
        priority_fn=lambda c: (1, 1.0, 1),
    )

    # Consultas que deben activar la intención de nómina de personas
    assert strategy.is_insured_query("¿quiénes están asegurados en esta póliza colectiva?")
    assert strategy.is_insured_query("dame la nómina de todos los asegurados")
    assert strategy.is_insured_query("listado de personas aseguradas")
    assert strategy.is_insured_query("¿cuántos asegurados tiene la póliza?")
    assert strategy.is_insured_query("cuántas personas están aseguradas")
    assert strategy.is_insured_query("relación de los afiliados y dependientes")
    assert strategy.is_insured_query("total de vidas aseguradas")

    # Consultas que NO deben activar nómina de personas
    assert not strategy.is_insured_query("¿cuál es la prima total de la póliza?")
    assert not strategy.is_insured_query("¿cuál es el deducible por accidente?")
    assert not strategy.is_insured_query("listado de vehículos de la flota")
