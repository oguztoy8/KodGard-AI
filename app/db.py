import atexit
from pathlib import Path
import sys
from typing import Any, Mapping

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import settings

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
    """Fetch a single commit by full or prefix SHA, including scan status and findings=[]."""
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
            result["findings"] = []
            return result


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
