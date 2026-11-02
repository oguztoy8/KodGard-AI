import atexit
import logging
from pathlib import Path
import sys
from typing import Any, Mapping

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import settings

logger = logging.getLogger(__name__)

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=settings.DATABASE_URL,
            min_size=1,
            max_size=10,
            kwargs={"row_factory": dict_row},
            open=True,
        )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


atexit.register(close_pool)


def check_db() -> bool:
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS ok")
            row = cur.fetchone()
            return bool(row and row.get("ok") == 1)


def migrate() -> list[str]:
    """Run all SQL files in migrations/*.sql in sorted order, tracking applied files in schema_migrations."""
    migrations_dir = Path(settings.KODGARD_HOME) / "migrations"
    sql_files = sorted(migrations_dir.glob("*.sql"))
    applied: list[str] = []
    with ConnectionPool(
        conninfo=settings.DATABASE_URL,
        min_size=1,
        max_size=2,
        kwargs={"row_factory": dict_row},
        open=True,
    ) as pool:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        filename TEXT PRIMARY KEY,
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
                for sql_file in sql_files:
                    cur.execute(
                        "SELECT filename FROM schema_migrations WHERE filename = %s",
                        (sql_file.name,),
                    )
                    if cur.fetchone():
                        continue
                    sql_text = sql_file.read_text(encoding="utf-8")
                    cur.execute(sql_text)
                    cur.execute(
                        "INSERT INTO schema_migrations (filename) VALUES (%s)",
                        (sql_file.name,),
                    )
                    applied.append(sql_file.name)
            conn.commit()
    return applied


def _extract_field(commit: Mapping[str, Any] | Any, key: str, default: Any = None) -> Any:
    if isinstance(commit, Mapping):
        return commit.get(key, default)
    return getattr(commit, key, default)


def upsert_commit(commit: Mapping[str, Any] | Any, repo_path: str | Path | None = None) -> int:
    """
    Upsert commit into `commits` table:
    1. If `sha` matches an existing row, update it.
    2. Else if `patch_id` matches an existing row (for the same repo_path if provided), update its `sha` and metadata without creating a new row.
    3. Else insert a new row.
    """
    sha = _extract_field(commit, "sha")
    patch_id_val = _extract_field(commit, "patch_id")
    author = _extract_field(commit, "author")
    committed_at = _extract_field(commit, "committed_at")
    subject = _extract_field(commit, "subject")
    resolved_repo = str(
        Path(repo_path or _extract_field(commit, "repo_path", "")).resolve()
    )

    if not sha or not patch_id_val:
        raise ValueError("commit must contain both 'sha' and 'patch_id'")

    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            # 1. Check by SHA
            cur.execute("SELECT id FROM commits WHERE sha = %s", (sha,))
            existing_sha = cur.fetchone()
            if existing_sha:
                commit_id = int(existing_sha["id"])
                cur.execute(
                    """
                    UPDATE commits
                    SET patch_id = %s,
                        author = %s,
                        committed_at = %s,
                        subject = %s,
                        repo_path = %s
                    WHERE id = %s
                    """,
                    (patch_id_val, author, committed_at, subject, resolved_repo, commit_id),
                )
                conn.commit()
                return commit_id

            # 2. Check by patch_id (preferring same repo_path, fallback to any matching patch_id)
            cur.execute(
                """
                SELECT id FROM commits
                WHERE patch_id = %s AND repo_path = %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (patch_id_val, resolved_repo),
            )
            existing_patch = cur.fetchone()
            if not existing_patch:
                cur.execute(
                    """
                    SELECT id FROM commits
                    WHERE patch_id = %s
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (patch_id_val,),
                )
                existing_patch = cur.fetchone()

            if existing_patch:
                commit_id = int(existing_patch["id"])
                cur.execute(
                    """
                    UPDATE commits
                    SET sha = %s,
                        author = %s,
                        committed_at = %s,
                        subject = %s,
                        repo_path = %s
                    WHERE id = %s
                    """,
                    (sha, author, committed_at, subject, resolved_repo, commit_id),
                )
                conn.commit()
                return commit_id

            # 3. Insert new commit
            cur.execute(
                """
                INSERT INTO commits (sha, patch_id, author, committed_at, subject, repo_path)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (sha, patch_id_val, author, committed_at, subject, resolved_repo),
            )
            inserted = cur.fetchone()
            conn.commit()
            return int(inserted["id"])


def enqueue_scan(commit_id: int) -> int:
    """Create or reset a pending scan record for `commit_id`."""
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM scans
                WHERE commit_id = %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (commit_id,),
            )
            existing = cur.fetchone()
            if existing:
                scan_id = int(existing["id"])
                cur.execute(
                    """
                    UPDATE scans
                    SET status = 'pending',
                        error = NULL,
                        started_at = NULL,
                        finished_at = NULL
                    WHERE id = %s
                    """,
                    (scan_id,),
                )
                conn.commit()
                return scan_id

            cur.execute(
                """
                INSERT INTO scans (commit_id, status)
                VALUES (%s, 'pending')
                RETURNING id
                """,
                (commit_id,),
            )
            row = cur.fetchone()
            conn.commit()
            return int(row["id"])


def list_commits_with_status(
    repo_path: str | Path | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    """List commits joined with their latest scan status."""
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            if repo_path:
                resolved_repo = str(Path(repo_path).resolve())
                cur.execute(
                    """
                    SELECT
                        c.id,
                        c.sha,
                        c.patch_id,
                        c.author,
                        c.committed_at,
                        c.subject,
                        c.repo_path,
                        c.created_at,
                        s.id AS scan_id,
                        COALESCE(s.status, 'pending') AS status,
                        s.error,
                        s.started_at,
                        s.finished_at
                    FROM commits c
                    LEFT JOIN LATERAL (
                        SELECT id, status, error, started_at, finished_at
                        FROM scans
                        WHERE scans.commit_id = c.id
                        ORDER BY id DESC
                        LIMIT 1
                    ) s ON true
                    WHERE c.repo_path = %s
                    ORDER BY c.committed_at DESC NULLS LAST, c.id DESC
                    LIMIT %s
                    """,
                    (resolved_repo, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT
                        c.id,
                        c.sha,
                        c.patch_id,
                        c.author,
                        c.committed_at,
                        c.subject,
                        c.repo_path,
                        c.created_at,
                        s.id AS scan_id,
                        COALESCE(s.status, 'pending') AS status,
                        s.error,
                        s.started_at,
                        s.finished_at
                    FROM commits c
                    LEFT JOIN LATERAL (
                        SELECT id, status, error, started_at, finished_at
                        FROM scans
                        WHERE scans.commit_id = c.id
                        ORDER BY id DESC
                        LIMIT 1
                    ) s ON true
                    ORDER BY c.committed_at DESC NULLS LAST, c.id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
            return list(cur.fetchall())


def get_commit_by_sha(sha: str) -> dict[str, Any] | None:
    """Fetch a single commit by full or prefix SHA, including scan status and findings."""
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    c.id,
                    c.sha,
                    c.patch_id,
                    c.author,
                    c.committed_at,
                    c.subject,
                    c.repo_path,
                    c.created_at,
                    s.id AS scan_id,
                    COALESCE(s.status, 'pending') AS status,
                    s.error,
                    s.started_at,
                    s.finished_at
                FROM commits c
                LEFT JOIN LATERAL (
                    SELECT id, status, error, started_at, finished_at
                    FROM scans
                    WHERE scans.commit_id = c.id
                    ORDER BY id DESC
                    LIMIT 1
                ) s ON true
                WHERE c.sha = %s OR c.sha LIKE %s
                ORDER BY c.id DESC
                LIMIT 1
                """,
                (sha, f"{sha}%"),
            )
            row = cur.fetchone()
            if not row:
                return None
            result = dict(row)
            commit_id = int(result["id"])
            cur.execute(
                """
                SELECT
                    id,
                    commit_id,
                    source,
                    rule_id,
                    severity,
                    file,
                    line,
                    cwe,
                    title,
                    explanation,
                    fix,
                    status,
                    ignore_reason,
                    fingerprint,
                    created_at
                FROM findings
                WHERE commit_id = %s
                ORDER BY
                    CASE severity
                        WHEN 'critical' THEN 1
                        WHEN 'high' THEN 2
                        WHEN 'medium' THEN 3
                        WHEN 'low' THEN 4
                        ELSE 5
                    END,
                    id ASC
                """,
                (commit_id,),
            )
            result["findings"] = [dict(r) for r in cur.fetchall()]
            return result


def claim_next_pending_scan() -> dict[str, Any] | None:
    """
    Claim a single pending scan row using `SELECT ... FOR UPDATE SKIP LOCKED`
    and immediately transition its status to 'running'.
    """
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    s.id AS scan_id,
                    s.commit_id,
                    c.sha,
                    c.patch_id,
                    c.author,
                    c.committed_at,
                    c.subject,
                    c.repo_path
                FROM scans s
                JOIN commits c ON c.id = s.commit_id
                WHERE s.status = 'pending'
                ORDER BY s.id ASC
                FOR UPDATE OF s SKIP LOCKED
                LIMIT 1
                """
            )
            row = cur.fetchone()
            if not row:
                conn.commit()
                return None
            scan_id = int(row["scan_id"])
            cur.execute(
                """
                UPDATE scans
                SET status = 'running',
                    error = NULL,
                    started_at = now(),
                    finished_at = NULL
                WHERE id = %s
                """,
                (scan_id,),
            )
            conn.commit()
            return dict(row)


def complete_scan(scan_id: int) -> None:
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE scans
                SET status = 'done',
                    error = NULL,
                    finished_at = now()
                WHERE id = %s
                """,
                (scan_id,),
            )
        conn.commit()


def fail_scan(scan_id: int, error_class_name: str) -> None:
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE scans
                SET status = 'failed',
                    error = %s,
                    finished_at = now()
                WHERE id = %s
                """,
                (error_class_name, scan_id),
            )
        conn.commit()


def upsert_doc(commit_id: int, kind: str, body_md: str, model: str) -> int:
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO docs (commit_id, kind, body_md, model)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (commit_id, kind) DO UPDATE
                SET body_md = EXCLUDED.body_md,
                    model = EXCLUDED.model,
                    created_at = now()
                RETURNING id
                """,
                (commit_id, kind, body_md, model),
            )
            row = cur.fetchone()
        conn.commit()
        return int(row["id"])


def get_docs_by_sha(sha: str) -> dict[str, Any] | None:
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, sha
                FROM commits
                WHERE sha = %s OR sha LIKE %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (sha, f"{sha}%"),
            )
            commit_row = cur.fetchone()
            if not commit_row:
                return None
            commit_id = int(commit_row["id"])
            full_sha = str(commit_row["sha"])
            cur.execute(
                """
                SELECT kind, body_md, model, created_at
                FROM docs
                WHERE commit_id = %s
                """,
                (commit_id,),
            )
            docs_rows = cur.fetchall()
            out: dict[str, Any] = {
                "sha": full_sha,
                "summary": "",
                "detail": "",
            }
            for r in docs_rows:
                kind = r["kind"]
                if kind in ("summary", "detail"):
                    out[kind] = r["body_md"]
            return out


def save_commit_findings(
    commit_id: int,
    repo_path: str,
    changed_files: list[str],
    new_findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Save findings for `commit_id` while:
    1. Preserving 'ignored' status & ignore_reason if the same fingerprint was ever marked ignored in this repo.
    2. Marking earlier 'open' findings on `changed_files` in the same repo as 'fixed' if their fingerprint did not recur.
    """
    from app.findings import apply_ignored_preservation, determine_fixed_finding_ids

    resolved_repo = str(Path(repo_path).resolve())
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    f.id,
                    f.commit_id,
                    f.file,
                    f.status,
                    f.ignore_reason,
                    f.fingerprint
                FROM findings f
                JOIN commits c ON c.id = f.commit_id
                WHERE c.repo_path = %s
                ORDER BY f.id ASC
                """,
                (resolved_repo,),
            )
            existing_repo_findings = [dict(r) for r in cur.fetchall()]

            prepared = apply_ignored_preservation(new_findings, existing_repo_findings)

            # Upsert unique by fingerprint (deduplicate in-memory first if needed)
            dedup_by_fp: dict[str, dict[str, Any]] = {}
            for item in prepared:
                dedup_by_fp[item["fingerprint"]] = item

            saved: list[dict[str, Any]] = []
            for item in dedup_by_fp.values():
                cur.execute(
                    """
                    INSERT INTO findings (
                        commit_id, source, rule_id, severity, file, line,
                        cwe, title, explanation, fix, status, ignore_reason, fingerprint
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (commit_id, fingerprint) DO UPDATE
                    SET source = EXCLUDED.source,
                        rule_id = EXCLUDED.rule_id,
                        severity = EXCLUDED.severity,
                        file = EXCLUDED.file,
                        line = EXCLUDED.line,
                        cwe = EXCLUDED.cwe,
                        title = EXCLUDED.title,
                        explanation = EXCLUDED.explanation,
                        fix = EXCLUDED.fix,
                        status = CASE
                            WHEN findings.status = 'ignored' THEN 'ignored'
                            ELSE EXCLUDED.status
                        END,
                        ignore_reason = CASE
                            WHEN findings.status = 'ignored' THEN findings.ignore_reason
                            ELSE EXCLUDED.ignore_reason
                        END
                    RETURNING *
                    """,
                    (
                        commit_id,
                        item.get("source"),
                        item.get("rule_id"),
                        item.get("severity"),
                        item.get("file"),
                        item.get("line"),
                        item.get("cwe"),
                        item.get("title"),
                        item.get("explanation"),
                        item.get("fix"),
                        item.get("status", "open"),
                        item.get("ignore_reason"),
                        item["fingerprint"],
                    ),
                )
                row = cur.fetchone()
                if row:
                    saved.append(dict(row))

            earlier_open = [
                ef
                for ef in existing_repo_findings
                if int(ef["commit_id"]) != int(commit_id) and ef.get("status") == "open"
            ]
            fixed_ids = determine_fixed_finding_ids(
                earlier_open, list(dedup_by_fp.values()), changed_files
            )
            affected_fixed_commits: set[int] = set()
            if fixed_ids:
                fixed_id_set = set(fixed_ids)
                for ef in earlier_open:
                    if ef.get("id") in fixed_id_set and ef.get("commit_id") is not None:
                        affected_fixed_commits.add(int(ef["commit_id"]))
                cur.execute(
                    """
                    UPDATE findings
                    SET status = 'fixed'
                    WHERE id = ANY(%s)
                    """,
                    (fixed_ids,),
                )
        conn.commit()

    if affected_fixed_commits:
        from app import indexer

        for fixed_cid in sorted(affected_fixed_commits):
            try:
                indexer.refresh_finding_chunks(fixed_cid)
            except Exception as exc:
                logger.warning(
                    "refresh_finding_chunks failed for commit_id=%d with %s",
                    fixed_cid,
                    type(exc).__name__,
                )
    return saved


def update_finding_status(
    finding_id: int,
    status: str,
    ignore_reason: str | None = None,
) -> dict[str, Any] | None:
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE findings
                SET status = %s,
                    ignore_reason = %s
                WHERE id = %s
                RETURNING
                    id,
                    commit_id,
                    source,
                    rule_id,
                    severity,
                    file,
                    line,
                    cwe,
                    title,
                    explanation,
                    fix,
                    status,
                    ignore_reason,
                    fingerprint,
                    created_at
                """,
                (status, ignore_reason if status == "ignored" else None, finding_id),
            )
            row = cur.fetchone()
        conn.commit()

    if not row:
        return None

    result = dict(row)
    try:
        from app import indexer

        indexer.refresh_finding_chunks(int(result["commit_id"]))
    except Exception as exc:
        logger.warning(
            "refresh_finding_chunks failed for commit_id=%s with %s",
            result.get("commit_id"),
            type(exc).__name__,
        )
    return result


def enqueue_scan_if_missing(commit_id: int) -> tuple[int, bool]:
    """
    Create a pending scan record for `commit_id` only if no scan record exists yet.
    Returns (scan_id, created_new).
    """
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM scans
                WHERE commit_id = %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (commit_id,),
            )
            existing = cur.fetchone()
            if existing:
                conn.commit()
                return int(existing["id"]), False

            cur.execute(
                """
                INSERT INTO scans (commit_id, status)
                VALUES (%s, 'pending')
                RETURNING id
                """,
                (commit_id,),
            )
            row = cur.fetchone()
            conn.commit()
            return int(row["id"]), True


def list_done_commits(sha: str | None = None) -> list[dict[str, Any]]:
    """
    List commits for reindexing:
    - If `sha` is provided, return matching commit(s) by full or prefix SHA.
    - If `sha` is None, return all commits whose latest scan status is 'done'.
    """
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            if sha:
                cur.execute(
                    """
                    SELECT c.id, c.sha, c.repo_path, c.subject
                    FROM commits c
                    WHERE c.sha = %s OR c.sha LIKE %s
                    ORDER BY c.id ASC
                    """,
                    (sha, f"{sha}%"),
                )
            else:
                cur.execute(
                    """
                    SELECT c.id, c.sha, c.repo_path, c.subject
                    FROM commits c
                    JOIN LATERAL (
                        SELECT status
                        FROM scans
                        WHERE scans.commit_id = c.id
                        ORDER BY id DESC
                        LIMIT 1
                    ) s ON true
                    WHERE s.status = 'done'
                    ORDER BY c.id ASC
                    """
                )
            return [dict(r) for r in cur.fetchall()]


def search_chunks_by_vector(
    query_vector: list[float],
    commit_sha: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Retrieve top-K chunks ordered by cosine distance (`embedding <=> query_vector`)."""
    vec_literal = "[" + ",".join(f"{float(x):.8f}" for x in query_vector) + "]"
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            if commit_sha and commit_sha.strip():
                sha_val = commit_sha.strip()
                cur.execute(
                    """
                    SELECT
                        ch.id,
                        ch.commit_id,
                        c.sha,
                        ch.kind,
                        ch.source_ref,
                        ch.content,
                        (ch.embedding <=> %s::vector) AS distance
                    FROM chunks ch
                    JOIN commits c ON c.id = ch.commit_id
                    WHERE c.sha = %s OR c.sha LIKE %s
                    ORDER BY ch.embedding <=> %s::vector ASC, ch.id ASC
                    LIMIT %s
                    """,
                    (vec_literal, sha_val, f"{sha_val}%", vec_literal, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT
                        ch.id,
                        ch.commit_id,
                        c.sha,
                        ch.kind,
                        ch.source_ref,
                        ch.content,
                        (ch.embedding <=> %s::vector) AS distance
                    FROM chunks ch
                    JOIN commits c ON c.id = ch.commit_id
                    ORDER BY ch.embedding <=> %s::vector ASC, ch.id ASC
                    LIMIT %s
                    """,
                    (vec_literal, vec_literal, limit),
                )
            return [dict(r) for r in cur.fetchall()]


def get_assistant_status() -> dict[str, int]:
    """Return counts of indexed commits, total commits, and total chunks."""
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM commits WHERE indexed_at IS NOT NULL) AS indexed_commits,
                    (SELECT COUNT(*) FROM commits) AS total_commits,
                    (SELECT COUNT(*) FROM chunks) AS chunks
                """
            )
            row = cur.fetchone() or {}
            return {
                "indexed_commits": int(row.get("indexed_commits") or 0),
                "total_commits": int(row.get("total_commits") or 0),
                "chunks": int(row.get("chunks") or 0),
            }


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    try:
        if not args or args[0] == "migrate":
            applied = migrate()
            if applied:
                print(f"Applied migrations: {', '.join(applied)}")
            else:
                print("already applied")
            return 0
        print(f"Unknown command: {' '.join(args)}", file=sys.stderr)
        return 1
    finally:
        close_pool()


if __name__ == "__main__":
    raise SystemExit(main())
