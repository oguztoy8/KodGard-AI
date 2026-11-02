import hashlib
from typing import Any
from unittest.mock import patch

from app import indexer


class FakeEmbedder:
    """Deterministic 384-dimensional embedder with zero network/model usage."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        vec: list[float] = []
        for i in range(384):
            b = digest[i % len(digest)]
            vec.append(round(((b + (i % 17)) % 256) / 255.0, 6))
        return vec


class _InMemoryStore:
    def __init__(self) -> None:
        self.chunks: list[dict[str, Any]] = []
        self.indexed_at_updated = 0
        self.findings: list[dict[str, Any]] = [
            {
                "id": 5,
                "commit_id": 1,
                "source": "semgrep",
                "rule_id": "kodgard-eval-usage-python",
                "severity": "high",
                "file": "app.py",
                "line": 10,
                "cwe": "CWE-95",
                "title": "Tehlikeli eval()",
                "explanation": "RCE riski",
                "fix": "ast.literal_eval kullan",
                "status": "open",
                "ignore_reason": None,
            }
        ]


class _FakeCursor:
    def __init__(self, store: _InMemoryStore) -> None:
        self.store = store
        self._rows: list[dict[str, Any]] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        norm = " ".join(sql.split())
        if "SELECT id, sha, repo_path FROM commits" in norm:
            self._rows = [{"id": 1, "sha": "abcdef1234567890", "repo_path": "/tmp/fake-repo"}]
        elif "SELECT kind, body_md FROM docs" in norm:
            self._rows = [
                {"kind": "summary", "body_md": "Kısa özet metni."},
                {"kind": "detail", "body_md": "Detaylı doküman metni."},
            ]
        elif "FROM findings WHERE commit_id =" in norm:
            self._rows = [dict(f) for f in self.store.findings]
        elif "SELECT DISTINCT f.file FROM findings" in norm:
            self._rows = []
        elif "DELETE FROM chunks WHERE commit_id = %s AND kind = 'finding'" in norm:
            cid = int(params[0])
            self.store.chunks = [
                c for c in self.store.chunks if not (c["commit_id"] == cid and c["kind"] == "finding")
            ]
            self._rows = []
        elif "DELETE FROM chunks WHERE commit_id = %s" in norm:
            cid = int(params[0])
            self.store.chunks = [c for c in self.store.chunks if c["commit_id"] != cid]
            self._rows = []
        elif "INSERT INTO chunks" in norm:
            cid, kind, ref, content, vec_str = params
            self.store.chunks.append(
                {
                    "commit_id": int(cid),
                    "kind": str(kind),
                    "source_ref": str(ref),
                    "content": str(content),
                    "embedding": str(vec_str),
                }
            )
            self._rows = []
        elif "UPDATE commits SET indexed_at = now()" in norm:
            self.store.indexed_at_updated += 1
            self._rows = []

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)


class _FakeConn:
    def __init__(self, store: _InMemoryStore) -> None:
        self.store = store

    def __enter__(self) -> "_FakeConn":
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.store)

    def commit(self) -> None:
        pass


class _FakePool:
    def __init__(self, store: _InMemoryStore) -> None:
        self.store = store

    def connection(self) -> _FakeConn:
        return _FakeConn(self.store)


def test_index_commit_is_idempotent_and_refresh_finding_chunks_updates_status() -> None:
    store = _InMemoryStore()
    fake_pool = _FakePool(store)
    embedder = FakeEmbedder()

    with (
        patch("app.indexer.db.get_pool", return_value=fake_pool),
        patch("app.indexer.filter_changed_files", return_value=["app.py"]),
        patch("app.indexer._git_file_diff", return_value="--- a/app.py\n+++ b/app.py\n+x = eval(y)\n"),
        patch("app.indexer._git_file_content", return_value="x = eval(y)\n"),
    ):
        counts1 = indexer.index_commit(1, embedder=embedder)
        chunk_total_1 = len(store.chunks)
        assert counts1["total"] == chunk_total_1
        assert chunk_total_1 == 5  # summary + detail + 1 finding + 1 diff + 1 file

        # Running index_commit a second time must NOT duplicate chunks
        counts2 = indexer.index_commit(1, embedder=embedder)
        assert counts2["total"] == chunk_total_1
        assert len(store.chunks) == chunk_total_1
        assert store.indexed_at_updated == 2

        # Update finding status to ignored and refresh finding chunks
        store.findings[0]["status"] = "ignored"
        store.findings[0]["ignore_reason"] = "Bilinen durum"
        refreshed = indexer.refresh_finding_chunks(1, embedder=embedder)
        assert refreshed == 1
        assert len(store.chunks) == chunk_total_1

        finding_chunk = next(c for c in store.chunks if c["kind"] == "finding")
        assert "Status: ignored" in finding_chunk["content"]
        assert "Ignore Reason: Bilinen durum" in finding_chunk["content"]
