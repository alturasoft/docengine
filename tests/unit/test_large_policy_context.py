"""Tests [ADITIVOS] para la estrategia de contexto de pólizas GRANDES."""

from __future__ import annotations

from app.application.large_policy_context import (
    LargePolicyContextStrategy,
    is_request_too_large,
)
from app.application.rag_query_service import RAGQueryService
from app.config.settings import LargePolicyConfig
from app.domain.models.query_models import RetrievedChunk


def _chunk(i: int, chars: int = 3500, tipo: str = "CONDICIONADO_GENERAL", pid: str = "p1") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"c{i}",
        policy_id=pid,
        chunk_index=i,
        chunk_content="x" * chars,
        metadata_json={"tipo_documento": tipo},
        similarity_score=1.0,
    )


def _strategy(**kw) -> LargePolicyContextStrategy:
    cfg = LargePolicyConfig(**{"token_threshold": 10_000, "context_budget_tokens": 8_000, **kw})
    return LargePolicyContextStrategy(cfg, RAGQueryService._chunk_hierarchy_priority)


class _TooLarge(Exception):
    pass


def test_small_policy_is_not_large():
    s = _strategy()
    assert s.is_large([_chunk(i) for i in range(5)]) is False  # ~5K tokens


def test_large_policy_is_detected():
    s = _strategy()
    assert s.is_large([_chunk(i) for i in range(20)]) is True  # ~20K tokens


def test_disabled_never_large():
    s = _strategy(enabled=False)
    assert s.is_large([_chunk(i) for i in range(50)]) is False


def test_build_respects_budget_and_prioritises_retrieved():
    s = _strategy()
    all_chunks = [_chunk(i) for i in range(100)]
    all_chunks[50] = _chunk(50, tipo="ANEXO")
    retrieved = [all_chunks[70], all_chunks[10]]

    calls = {}

    def fake_retrieve(**kwargs):
        calls.update(kwargs)
        return retrieved

    out = s.build("q", [0.0], all_chunks, [], {"envelope_id": "env1"}, fake_retrieve)
    ids = [c.chunk_id for c in out]
    assert calls["filters"] == {"envelope_id": "env1"}
    assert ids[:2] == ["c70", "c10"]
    assert "c69" in ids and "c71" in ids  # vecinos
    assert "c50" in ids  # anexo (prioridad 1)
    assert s.estimate_tokens(out) <= 8_000


def test_build_falls_back_when_retrieval_fails():
    s = _strategy()
    all_chunks = [_chunk(i) for i in range(100)]

    def boom(**kwargs):
        raise RuntimeError("db down")

    out = s.build("q", [0.0], all_chunks, [], {}, boom)
    assert out and s.estimate_tokens(out) <= 8_000


def test_is_request_too_large_classification():
    assert is_request_too_large(_TooLarge("Request too large for gpt-4.1-mini ... must be reduced"))
    assert is_request_too_large(_TooLarge("This model's maximum context length is 1047576 tokens"))
    assert not is_request_too_large(
        _TooLarge("Rate limit reached for gpt-4.1-mini on tokens per min. Please try again in 9s.")
    )
