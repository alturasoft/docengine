"""Unit tests for app.application.company_skill_loader."""

from __future__ import annotations

from pathlib import Path
from app.application.company_skill_loader import (
    CompanySkill,
    load_company_skill,
    load_general_skill,
    load_company_skill_merged,
    merge_skills,
)


def test_load_general_skill():
    general = load_general_skill()
    assert general is not None
    assert general.sigla == "GENERAL"
    assert "Producto" in general.kv_keys
    assert len(general.header_patterns) > 0


def test_merge_skills_lists_union():
    base = CompanySkill(
        sigla="GENERAL",
        empresa="(general)",
        kv_keys=["Producto", "Vigencia"],
        header_patterns=["Syncfusion"],
    )
    override = CompanySkill(
        sigla="CRI",
        empresa="Credinform",
        kv_keys=["Póliza", "Vigencia"],  # Vigencia is duplicate
        header_patterns=["Footer CRI"],
    )

    merged = merge_skills(base, override)

    assert merged.sigla == "CRI"
    assert merged.empresa == "Credinform"
    assert merged.kv_keys == ["Producto", "Vigencia", "Póliza"]
    assert merged.header_patterns == ["Syncfusion", "Footer CRI"]


def test_load_company_skill_merged_fallback():
    # Non-existent company sigla should use general skill base
    merged = load_company_skill_merged("XYZ")
    assert merged.sigla == "XYZ"
    assert "Producto" in merged.kv_keys


def test_cri_skill_removes_footer_fragments():
    from app.application.post_processing.processors.company_kv_rules import (
        CompanyKVRulesProcessor,
    )
    from app.application.post_processing.base import PostProcessingContext

    cri_skill = load_company_skill_merged("CRI")
    processor = CompanyKVRulesProcessor(cri_skill)
    context = PostProcessingContext()

    fragments = [
        # Fragment 1
        "OFICINA PRINCIPAL\nPOTOSI\nTelf: (02)6223189\nORURO\nTelf: (02)5277544\nTARIJA\nTelf: (04)6642736\nCalle Capitan Ravelo Nro. 2328",
        # Fragment 2
        "SUCURSAL 1\nCalle Capitan Ravelo Nro. 2328\nTelf: (02)2315566\nSANTA CRUZ\nTelf: (03)3341335\nCOCHABAMBA\nTelf: (04)4250095\nSUCRE\nTelf: (04)6453312\nPOTOSI\nTelf: (02)6223189\nORURO\nTelf: (02)5277544\nTARIJA\nTelf: (04)6642736\nCAMIRI\nTelf: (03)9522176\nYACUIBA\nTelf: (04)6823799\nTRINIDAD",
        # Fragment 6 with real heading
        "SUCURSAL 1\nCalle Capitan Ravelo Nro. 2328\nTelf: (02)2315566\n## A/B/R\nTRINIDAD\nTelf: (03)4628717",
    ]

    for frag in fragments[:2]:
        cleaned = processor.process(frag, context)
        assert cleaned.strip() == ""

    cleaned_frag6 = processor.process(fragments[2], context)
    assert cleaned_frag6.strip() == "## A/B/R"

