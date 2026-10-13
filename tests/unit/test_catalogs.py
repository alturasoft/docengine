"""Unit tests for app.application.catalog_service and API endpoints."""

from __future__ import annotations

import pytest
from app.application.catalog_service import catalog_service


def test_catalog_service_loads_companies():
    companies = catalog_service.get_all_companies()
    assert len(companies) == 18

    # Check Fortaleza Generales (FORT) and Fortaleza Vida (FORT-P)
    fort = catalog_service.get_company_by_sigla("FORT")
    assert fort is not None
    assert fort.id == 8
    assert "FORTALEZA" in fort.nombre

    fort_p = catalog_service.get_company_by_sigla("FORT-P")
    assert fort_p is not None
    assert fort_p.id == 18
    assert "VIDA FORTALEZA" in fort_p.nombre

    # Check new companies
    illi = catalog_service.get_company_by_sigla("ILLI")
    assert illi is not None
    assert illi.id == 3

    dhi = catalog_service.get_company_by_sigla("DHI")
    assert dhi is not None
    assert dhi.id == 10


def test_catalog_service_resolves_historical_aliases():
    assert catalog_service.resolve_sigla("CRI") == "CRE"
    assert catalog_service.resolve_sigla("cre") == "CRE"
    assert catalog_service.resolve_sigla("BIS") == "BISA"
    assert catalog_service.resolve_sigla("bisa") == "BISA"
    assert catalog_service.resolve_sigla("ALI") == "ALI-SEG"
    assert catalog_service.resolve_sigla("FOV") == "FORT-P"
    assert catalog_service.resolve_sigla("FORTV") == "FORT-P"
    assert catalog_service.resolve_sigla("FOR") == "FORT"


def test_catalog_service_loads_document_types():
    doc_types = catalog_service.get_all_document_types()
    assert len(doc_types) == 6
    cg = next(d for d in doc_types if d.id == 1)
    assert cg.documento == "Condicionado General"
    assert cg.codigo_normalizado == "CONDICIONADO_GENERAL"


def test_catalog_service_loads_ramos():
    ramos = catalog_service.get_all_ramos()
    assert len(ramos) == 39
    grouped = catalog_service.get_ramos_by_tipo()
    assert "SEGUROS GENERALES" in grouped
    assert "SEGURO DE FIANZAS" in grouped
    assert "SEGUROS PERSONAS" in grouped
    assert "SEGUROS OBLIGATORIOS" in grouped


def test_catalog_api_endpoints(test_client):
    res_comp = test_client.get("/api/v1/catalogs/companies")
    assert res_comp.status_code == 200
    comp_data = res_comp.json()
    assert len(comp_data) == 18
    assert any(c["sigla"] == "FORT" for c in comp_data)
    assert any(c["sigla"] == "FORT-P" for c in comp_data)

    res_docs = test_client.get("/api/v1/catalogs/document-types")
    assert res_docs.status_code == 200
    assert len(res_docs.json()) == 6

    res_ramos = test_client.get("/api/v1/catalogs/ramos")
    assert res_ramos.status_code == 200
    assert len(res_ramos.json()) == 39

    res_grouped = test_client.get("/api/v1/catalogs/ramos/grouped")
    assert res_grouped.status_code == 200
    assert "SEGUROS GENERALES" in res_grouped.json()
