"""Tests [ADITIVOS] para FleetExtractorService, PgFleetRepository y LargePolicyContextStrategy fleet hooks."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.application.fleet_extractor_service import FleetExtractorService
from app.application.large_policy_context import LargePolicyConfig, LargePolicyContextStrategy
from app.infrastructure.database.pg_fleet_repository import PgFleetRepository


def test_parse_single_vehicle():
    raw_text = """
    ## ITEM 143
    TIPO VEHICULO: CAMIONETA
    MARCA: TOYOTA
    MODELO: HILUX 4X4 D/CAB
    AÑO: 2011
    PLACA: 2571EDF
    CHASIS: MR0FX22G701060798
    MOTOR: 2KD8493021
    COLOR: BLANCO
    USO: OPERATIVO
    PLAZA: POTOSI
    VALOR DEL VEHICULO: $us. 20,258.41
    Prima Individual Emitida: $us. ***1,418.09
    """

    v = FleetExtractorService._parse_single_vehicle(143, raw_text)
    assert v is not None
    assert v["item_number"] == 143
    assert v["tipo_vehiculo"] == "CAMIONETA"
    assert v["marca"] == "TOYOTA"
    assert "HILUX" in v["modelo"]
    assert v["anio"] == 2011
    assert v["placa"] == "2571EDF"
    assert v["chasis"] == "MR0FX22G701060798"
    assert v["motor"] == "2KD8493021"
    assert v["valor_asegurado_usd"] == 20258.41
    assert v["prima_usd"] == 1418.09


def test_parse_vehicles_from_chunks():
    chunks = [
        {
            "chunk_index": 1,
            "content": "ITEM 1\nTIPO VEHICULO: CAMION\nMARCA: VOLVO\nPLACA: 1234ABC\nVALOR DEL VEHICULO: $us. 50,000.00",
            "metadata": {"Header 2": "ITEM 1"},
        },
        {
            "chunk_index": 2,
            "content": "ITEM 2\nTIPO VEHICULO: BUS\nMARCA: MERCEDES\nPLACA: 5678DEF\nVALOR DEL VEHICULO: $us. 80,000.00",
            "metadata": {"Header 2": "ITEM 2"},
        },
    ]

    service = FleetExtractorService(MagicMock())
    vehicles = service._parse_vehicles_from_chunks(chunks)
    assert len(vehicles) == 2
    assert vehicles[0]["item_number"] == 1
    assert vehicles[0]["placa"] == "1234ABC"
    assert vehicles[1]["item_number"] == 2
    assert vehicles[1]["placa"] == "5678DEF"


def test_format_fleet_summary_chunk():
    mock_repo = MagicMock(spec=PgFleetRepository)
    mock_repo.get_fleet_summary.return_value = {
        "total_vehiculos": 224,
        "total_valor_asegurado_usd": 6984225.77,
        "total_prima_usd": 350000.0,
        "distribucion_tipo": {"CAMIONETA": 142, "VAGONETA": 32, "CAMION": 21},
        "distribucion_marca": {"TOYOTA": 150, "NISSAN": 40},
        "muestra": [
            {
                "item_number": 1,
                "tipo_vehiculo": "CAMIONETA",
                "marca": "TOYOTA",
                "modelo": "HILUX",
                "anio": 2015,
                "placa": "1273ATD",
                "chasis": "MR0123456789",
                "valor_asegurado_usd": 25000.0,
            }
        ],
    }

    service = FleetExtractorService(MagicMock(), fleet_repo=mock_repo)
    chunk = service.format_fleet_summary_chunk(policy_id="test-policy-uuid")

    assert chunk is not None
    assert "224 unidades" in chunk.chunk_content
    assert "$us. 6,984,225.77" in chunk.chunk_content
    assert "CAMIONETA: 142" in chunk.chunk_content
    assert "1273ATD" in chunk.chunk_content
    assert chunk.metadata_json["tipo_documento"] == "NOMINA_FLOTA"


def test_is_fleet_query_detection():
    strategy = LargePolicyContextStrategy(
        config=LargePolicyConfig(),
        priority_fn=lambda c: (1, 1.0, 1),
    )

    # Queries that should match fleet intent
    assert strategy.is_fleet_query("dame el listado de todos los vehículos asegurados en esta póliza")
    assert strategy.is_fleet_query("¿cuántos vehículos tiene la flota?")
    assert strategy.is_fleet_query("muéstrame la nómina de automotores")
    assert strategy.is_fleet_query("detalle de los camiones y unidades aseguradas")
    assert strategy.is_fleet_query("total de vehículos asegurados")
    assert strategy.is_fleet_query("relación de placas aseguradas")

    # Queries that should NOT match fleet intent
    assert not strategy.is_fleet_query("¿cuál es el deducible para la cobertura de terremoto?")
    assert not strategy.is_fleet_query("¿quién es el contratante y asegurado de la póliza?")
    assert not strategy.is_fleet_query("resumen de las condiciones generales")
