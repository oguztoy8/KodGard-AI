from typing import Any
from unittest.mock import patch

from app import assistant
from app.config import TOP_K_CHUNKS
from tests.test_indexer import FakeEmbedder


def test_sha_auto_detection_digit_requirement_and_resolution() -> None:
    # 1. Ordinary hex-letter words without digits (e.g. 'defaced', 'feedback') must be ignored
    assert assistant.extract_sha_candidates("The page was defaced with bad feedback") == []

    # 2. 7+ hex chars with at least one digit are extracted
    assert assistant.extract_sha_candidates("1af4070e commitinde ne degisti?") == ["1af4070e"]

    # 3. Single unique match in DB applies commit filter
    with patch(
        "app.assistant.db.resolve_unique_commit_sha",
        return_value="1af4070e2cfa054959f084a642142b3ebd3d4692",
    ) as mock_resolve:
        resolved = assistant.resolve_effective_commit_sha("1af4070e commitinde ne degisti?", None)
        assert resolved == "1af4070e2cfa054959f084a642142b3ebd3d4692"
        mock_resolve.assert_called_once_with("1af4070e")

    # 4. Zero match or ambiguous match returns None (no filter)
    with patch("app.assistant.db.resolve_unique_commit_sha", return_value=None):
        assert assistant.resolve_effective_commit_sha("deadbee1 commitinde ne var?", None) is None

    # Multiple distinct resolved SHAs in the same question -> ambiguous -> no filter
    with patch(
        "app.assistant.db.resolve_unique_commit_sha",
        side_effect=["1af4070e2cfa054959f084a642142b3ebd3d4692", "c796cb2811112222333344445555666677778888"],
    ):
        assert (
            assistant.resolve_effective_commit_sha("1af4070e ile c796cb28 farki nedir?", None)
            is None
        )

    # 5. Explicit commit_sha takes priority without calling auto-detection
    with patch("app.assistant.db.resolve_unique_commit_sha") as mock_resolve2:
        explicit = assistant.resolve_effective_commit_sha(
            "1af4070e commitinde ne degisti?", "c796cb28"
        )
        assert explicit == "c796cb28"
        mock_resolve2.assert_not_called()


def test_security_intent_detection_tr_and_en_and_single_search_when_absent() -> None:
    # Turkish and English security keywords
    assert assistant.has_security_intent("Hangi commitlerde güvenlik açığı bulundu?") is True
    assert assistant.has_security_intent("Hangi commitlerde guvenlik acigi bulundu?") is True
    assert assistant.has_security_intent("Bu kodda zafiyet veya sır sızıntısı var mı?") is True
    assert assistant.has_security_intent("Are there any CWE-89 SQL injection vulnerabilities or secret leaks?") is True
    assert assistant.has_security_intent("Kritik bulgu veya risk var mı?") is True

    # Non-security questions
    assert assistant.has_security_intent("demo reposunda hangi dosyalar var?") is False
    assert assistant.has_security_intent("1af4070e commitinde ne degisti?") is False

    embedder = FakeEmbedder()
    calls: list[dict[str, Any]] = []

    def fake_search(
        query_vector: list[float],
        commit_sha: str | None = None,
        limit: int = 8,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        calls.append({"commit_sha": commit_sha, "limit": limit, "kind": kind})
        return []

    # Without security intent -> single search call (kind=None)
    with patch("app.assistant.db.search_chunks_by_vector", side_effect=fake_search):
        assistant._embed_and_retrieve_sync(
            "demo reposunda hangi dosyalar var?",
            commit_sha=None,
            top_k=8,
            embedder=embedder,
        )
    assert len(calls) == 1
    assert calls[0] == {"commit_sha": None, "limit": 8, "kind": None}

    # With security intent -> two search calls (first kind='finding' limit=4, second general limit=8)
    calls.clear()
    with patch("app.assistant.db.search_chunks_by_vector", side_effect=fake_search):
        assistant._embed_and_retrieve_sync(
            "Hangi commitlerde guvenlik acigi bulundu?",
            commit_sha="1af4070e",
            top_k=8,
            embedder=embedder,
        )
    assert len(calls) == 2
    assert calls[0] == {"commit_sha": "1af4070e", "limit": 4, "kind": "finding"}
    assert calls[1] == {"commit_sha": "1af4070e", "limit": 8, "kind": None}


def test_hybrid_merge_finding_priority_deduplication_and_top_k_cap() -> None:
    assert TOP_K_CHUNKS == 8

    finding_chunks = [
        {"id": 10, "sha": "1af4070e", "kind": "finding", "source_ref": "finding:1", "content": "F1"},
        {"id": 11, "sha": "1af4070e", "kind": "finding", "source_ref": "finding:2", "content": "F2"},
        {"id": 12, "sha": "1af4070e", "kind": "finding", "source_ref": "finding:3", "content": "F3"},
    ]
    general_chunks = [
        {"id": 1, "sha": "b5fb9af8", "kind": "doc_summary", "source_ref": "summary", "content": "S1"},
        # Duplicate of id=10
        {"id": 10, "sha": "1af4070e", "kind": "finding", "source_ref": "finding:1", "content": "F1"},
        {"id": 2, "sha": "b5fb9af8", "kind": "doc_detail", "source_ref": "detail", "content": "D1"},
        {"id": 3, "sha": "c796cb28", "kind": "doc_summary", "source_ref": "summary", "content": "S2"},
        {"id": 4, "sha": "c796cb28", "kind": "doc_detail", "source_ref": "detail", "content": "D2"},
        {"id": 5, "sha": "14345ebd", "kind": "file", "source_ref": "file:helper.py", "content": "H1"},
        {"id": 6, "sha": "14345ebd", "kind": "diff", "source_ref": "diff:helper.py", "content": "DF1"},
    ]

    merged = assistant.merge_hybrid_chunks(finding_chunks, general_chunks, top_k=8)
    assert len(merged) == 8
    # First 3 must be the finding chunks
    assert [c["id"] for c in merged[:3]] == [10, 11, 12]
    # No duplicate id=10, and capped at 8 total
    assert [c["id"] for c in merged] == [10, 11, 12, 1, 2, 3, 4, 5]


def test_context_block_truncates_chunk_content_to_1500_chars() -> None:
    long_text = "A" * 1500 + "B" * 600
    chunks = [
        {
            "id": 99,
            "sha": "1af4070e2cfa054959f084a642142b3ebd3d4692",
            "kind": "doc_detail",
            "source_ref": "detail",
            "content": long_text,
        }
    ]
    ctx = assistant.build_context_block(chunks)
    assert "A" * 1500 in ctx
    assert "B" not in ctx
    assert "Status: fixed" in assistant.ASSISTANT_SYSTEM_PROMPT
    assert "ignored" in assistant.ASSISTANT_SYSTEM_PROMPT
