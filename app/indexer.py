import logging
import os
from pathlib import Path, PurePosixPath
import subprocess
from typing import Any, Mapping

from langchain_text_splitters import Language, RecursiveCharacterTextSplitter

from app import db
from app.config import CHUNK_OVERLAP, CHUNK_SIZE, MAX_FILE_BYTES, settings
from app.ignore import filter_changed_files

logger = logging.getLogger(__name__)

_embedder: Any | None = None


def get_embedder() -> Any:
    """Return process-wide lazy singleton HuggingFaceEmbeddings instance."""
    global _embedder
    if _embedder is None:
        if settings.HF_HOME and "HF_HOME" not in os.environ:
            os.environ["HF_HOME"] = settings.HF_HOME
        from langchain_huggingface import HuggingFaceEmbeddings

        _embedder = HuggingFaceEmbeddings(
            model_name=settings.EMBEDDING_MODEL_NAME,
            encode_kwargs={"normalize_embeddings": True},
        )
    return _embedder


def set_embedder(embedder: Any | None) -> None:
    """Override or reset the singleton embedder (used in tests)."""
    global _embedder
    _embedder = embedder


def vector_to_sql(vec: list[float]) -> str:
    """Format a float vector as a pgvector literal '[0.1,0.2,...]'."""
    return "[" + ",".join(f"{float(x):.8f}" for x in vec) + "]"


def split_markdown(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    if not text or not text.strip():
        return []
    splitter = RecursiveCharacterTextSplitter.from_language(
        language=Language.MARKDOWN,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    return [c for c in splitter.split_text(text) if c.strip()]


def split_diff(
    diff_text: str,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    if not diff_text or not diff_text.strip():
        return []
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    return [c for c in splitter.split_text(diff_text) if c.strip()]


def split_source_file(
    content: str,
    file_path: str,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
    max_bytes: int = MAX_FILE_BYTES,
) -> list[str]:
    if not content or not content.strip():
        return []
    encoded_len = len(content.encode("utf-8", errors="replace"))
    if encoded_len > max_bytes:
        logger.info("Skipping file >200KB (%d bytes): %s", encoded_len, file_path)
        return []

    suffix = PurePosixPath(file_path).suffix.lower()
    if suffix == ".py":
        splitter = RecursiveCharacterTextSplitter.from_language(
            language=Language.PYTHON,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
    elif suffix == ".js":
        splitter = RecursiveCharacterTextSplitter.from_language(
            language=Language.JS,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
    else:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
    return [c for c in splitter.split_text(content) if c.strip()]


def format_finding_chunk(finding: Mapping[str, Any]) -> str:
    """Format a single finding into one un-split text chunk."""
    f_id = finding.get("id")
    file_val = finding.get("file") or ""
    line_val = finding.get("line")
    loc = f"{file_val}:{line_val}" if line_val is not None else str(file_val)
    parts = [
        f"Finding ID: {f_id}",
        f"Severity: {finding.get('severity') or ''}",
        f"Source: {finding.get('source') or ''}",
        f"Rule: {finding.get('rule_id') or ''}",
        f"Location: {loc}",
        f"CWE: {finding.get('cwe') or ''}",
        f"Title: {finding.get('title') or ''}",
        f"Explanation: {finding.get('explanation') or ''}",
        f"Fix: {finding.get('fix') or ''}",
        f"Status: {finding.get('status') or 'open'}",
        f"Ignore Reason: {finding.get('ignore_reason') or '-'}",
    ]
    return "\n".join(parts)


def filter_secret_safe_files(
    changed_files: list[str],
    repo_gitleaks_files: set[str] | list[str],
) -> tuple[list[str], list[str]]:
    """
    Exclude any file that has ever had a source='gitleaks' finding in the repository
    from diff and file chunking.
    Returns (safe_files, skipped_files).
    """
    tainted = {str(p).strip() for p in repo_gitleaks_files if str(p).strip()}
    safe: list[str] = []
    skipped: list[str] = []
    for path in changed_files:
        if path in tainted:
            skipped.append(path)
        else:
            safe.append(path)
    if skipped:
        logger.info(
            "Skipped %d secret-tainted file(s) from diff/file chunks: %s",
            len(skipped),
            ", ".join(skipped),
        )
    return safe, skipped


def _git_file_diff(repo_path: str, sha: str, rel_path: str) -> str:
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    proc = subprocess.run(
        ["git", "-C", repo_path, "show", "--format=", "--patch", sha, "--", rel_path],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout


def _git_file_content(repo_path: str, sha: str, rel_path: str) -> str:
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    proc = subprocess.run(
        ["git", "-C", repo_path, "show", f"{sha}:{rel_path}"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout


def build_commit_chunks(
    docs: Mapping[str, str],
    findings: list[Mapping[str, Any]],
    changed_files: list[str],
    repo_gitleaks_files: set[str] | list[str],
    file_diffs: Mapping[str, str],
    file_contents: Mapping[str, str],
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> list[dict[str, str]]:
    """
    Assemble raw chunks (without embeddings) for a commit:
    1. doc_summary (source_ref='summary')
    2. doc_detail (source_ref='detail')
    3. finding (1 chunk per finding, source_ref='finding:<id>')
    4. diff (per safe file, source_ref='diff:<path>')
    5. file (per safe file <= 200KB, source_ref='file:<path>')
    """
    chunks: list[dict[str, str]] = []

    summary_md = docs.get("summary") or ""
    for part in split_markdown(summary_md, chunk_size=chunk_size, chunk_overlap=chunk_overlap):
        chunks.append(
            {
                "kind": "doc_summary",
                "source_ref": "summary",
                "content": part,
            }
        )

    detail_md = docs.get("detail") or ""
    for part in split_markdown(detail_md, chunk_size=chunk_size, chunk_overlap=chunk_overlap):
        chunks.append(
            {
                "kind": "doc_detail",
                "source_ref": "detail",
                "content": part,
            }
        )

    for finding in findings:
        f_id = finding.get("id")
        chunks.append(
            {
                "kind": "finding",
                "source_ref": f"finding:{f_id}",
                "content": format_finding_chunk(finding),
            }
        )

    safe_files, _ = filter_secret_safe_files(changed_files, repo_gitleaks_files)

    for rel_path in safe_files:
        d_text = file_diffs.get(rel_path) or ""
        for part in split_diff(d_text, chunk_size=chunk_size, chunk_overlap=chunk_overlap):
            chunks.append(
                {
                    "kind": "diff",
                    "source_ref": f"diff:{rel_path}",
                    "content": part,
                }
            )

        f_text = file_contents.get(rel_path) or ""
        for part in split_source_file(
            f_text,
            rel_path,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        ):
            chunks.append(
                {
                    "kind": "file",
                    "source_ref": f"file:{rel_path}",
                    "content": part,
                }
            )

    return chunks


def index_commit(commit_id: int, embedder: Any | None = None) -> dict[str, int]:
    """
    Index all chunks for `commit_id` in a single transaction:
    delete old chunks -> insert new chunks -> update commits.indexed_at = now().
    Returns chunk counts by kind.
    """
    pool = db.get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, sha, repo_path FROM commits WHERE id = %s",
                (commit_id,),
            )
            commit_row = cur.fetchone()
            if not commit_row:
                raise ValueError(f"Commit id={commit_id} not found")

            sha = str(commit_row["sha"])
            repo_path = str(Path(commit_row["repo_path"]).resolve())

            cur.execute(
                "SELECT kind, body_md FROM docs WHERE commit_id = %s",
                (commit_id,),
            )
            docs_map: dict[str, str] = {"summary": "", "detail": ""}
            for r in cur.fetchall():
                if r["kind"] in ("summary", "detail"):
                    docs_map[r["kind"]] = r["body_md"] or ""

            cur.execute(
                """
                SELECT
                    id, commit_id, source, rule_id, severity, file, line,
                    cwe, title, explanation, fix, status, ignore_reason
                FROM findings
                WHERE commit_id = %s
                ORDER BY id ASC
                """,
                (commit_id,),
            )
            findings_rows = [dict(r) for r in cur.fetchall()]

            cur.execute(
                """
                SELECT DISTINCT f.file
                FROM findings f
                JOIN commits c ON c.id = f.commit_id
                WHERE c.repo_path = %s
                  AND f.source = 'gitleaks'
                  AND f.file IS NOT NULL
                """,
                (repo_path,),
            )
            gitleaks_files = {str(r["file"]) for r in cur.fetchall() if r.get("file")}

    try:
        changed_files = filter_changed_files(repo_path, sha)
    except Exception:
        changed_files = []

    safe_files, _ = filter_secret_safe_files(changed_files, gitleaks_files)
    file_diffs: dict[str, str] = {}
    file_contents: dict[str, str] = {}
    for rel_path in safe_files:
        file_diffs[rel_path] = _git_file_diff(repo_path, sha, rel_path)
        file_contents[rel_path] = _git_file_content(repo_path, sha, rel_path)

    raw_chunks = build_commit_chunks(
        docs=docs_map,
        findings=findings_rows,
        changed_files=changed_files,
        repo_gitleaks_files=gitleaks_files,
        file_diffs=file_diffs,
        file_contents=file_contents,
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
    )

    emb_model = embedder or get_embedder()
    vectors: list[list[float]] = []
    if raw_chunks:
        vectors = emb_model.embed_documents([c["content"] for c in raw_chunks])

    counts: dict[str, int] = {
        "doc_summary": 0,
        "doc_detail": 0,
        "finding": 0,
        "diff": 0,
        "file": 0,
        "total": 0,
    }

    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM chunks WHERE commit_id = %s", (commit_id,))
            for chunk_item, vec in zip(raw_chunks, vectors):
                cur.execute(
                    """
                    INSERT INTO chunks (commit_id, kind, source_ref, content, embedding)
                    VALUES (%s, %s, %s, %s, %s::vector)
                    """,
                    (
                        commit_id,
                        chunk_item["kind"],
                        chunk_item["source_ref"],
                        chunk_item["content"],
                        vector_to_sql(vec),
                    ),
                )
                counts[chunk_item["kind"]] = counts.get(chunk_item["kind"], 0) + 1
                counts["total"] += 1

            cur.execute(
                "UPDATE commits SET indexed_at = now() WHERE id = %s",
                (commit_id,),
            )
        conn.commit()

    return counts


def refresh_finding_chunks(commit_id: int, embedder: Any | None = None) -> int:
    """
    Re-generate only the `kind='finding'` chunks for `commit_id` in a single transaction.
    Used when finding status changes (e.g. PATCH /findings/{id} or fixed transition).
    """
    pool = db.get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id, commit_id, source, rule_id, severity, file, line,
                    cwe, title, explanation, fix, status, ignore_reason
                FROM findings
                WHERE commit_id = %s
                ORDER BY id ASC
                """,
                (commit_id,),
            )
            findings_rows = [dict(r) for r in cur.fetchall()]

    finding_chunks = [
        {
            "kind": "finding",
            "source_ref": f"finding:{f['id']}",
            "content": format_finding_chunk(f),
        }
        for f in findings_rows
    ]

    emb_model = embedder or get_embedder()
    vectors: list[list[float]] = []
    if finding_chunks:
        vectors = emb_model.embed_documents([c["content"] for c in finding_chunks])

    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM chunks WHERE commit_id = %s AND kind = 'finding'",
                (commit_id,),
            )
            for chunk_item, vec in zip(finding_chunks, vectors):
                cur.execute(
                    """
                    INSERT INTO chunks (commit_id, kind, source_ref, content, embedding)
                    VALUES (%s, %s, %s, %s, %s::vector)
                    """,
                    (
                        commit_id,
                        "finding",
                        chunk_item["source_ref"],
                        chunk_item["content"],
                        vector_to_sql(vec),
                    ),
                )
        conn.commit()

    return len(finding_chunks)
