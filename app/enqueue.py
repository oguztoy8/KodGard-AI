import os
from pathlib import Path
import re
import subprocess
from typing import Any

from app import db, git_reader
from app.config import settings

SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")


class EnqueueError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class RepoNotAllowedError(EnqueueError):
    def __init__(self) -> None:
        super().__init__("repo_not_allowed")


class InvalidShaError(EnqueueError):
    def __init__(self, code: str = "invalid_sha") -> None:
        super().__init__(code)


def _clean_git_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    return env


def resolve_and_validate_repo(repo: str) -> str:
    """
    Translate host repository path to container path when REPOS_HOST_DIR / REPOS_CONTAINER_DIR
    are configured, resolve with realpath, verify containment under the allowed REPOS root
    (preventing '../' traversal and symlink escapes), and check that '.git' exists inside.
    Raises RepoNotAllowedError on any violation without leaking filesystem details.
    """
    if not repo or not repo.strip():
        raise RepoNotAllowedError()

    raw_parts = Path(repo).parts
    if ".." in raw_parts:
        raise RepoNotAllowedError()

    repos_host_dir = (os.environ.get("REPOS_HOST_DIR") or settings.REPOS_HOST_DIR or "").strip()
    repos_container_env = (os.environ.get("REPOS_CONTAINER_DIR") or "").strip()

    real_root: Path | None = None

    if repos_host_dir:
        host_root = Path(os.path.normpath(repos_host_dir))
        norm_repo = Path(os.path.normpath(repo))
        try:
            rel = norm_repo.relative_to(host_root)
        except ValueError as exc:
            raise RepoNotAllowedError() from exc

        if rel == Path(".") or ".." in rel.parts:
            raise RepoNotAllowedError()

        if repos_container_env:
            container_root_str = repos_container_env
        elif Path(settings.REPOS_CONTAINER_DIR).exists():
            container_root_str = settings.REPOS_CONTAINER_DIR
        else:
            container_root_str = repos_host_dir

        real_root = Path(os.path.realpath(container_root_str))
        if not real_root.is_dir():
            raise RepoNotAllowedError()

        candidate = real_root / rel
        real_repo = Path(os.path.realpath(candidate))
        if real_repo == real_root or not real_repo.is_relative_to(real_root):
            raise RepoNotAllowedError()
    elif repos_container_env:
        real_root = Path(os.path.realpath(repos_container_env))
        if not real_root.is_dir():
            raise RepoNotAllowedError()
        real_repo = Path(os.path.realpath(repo))
        if real_repo == real_root or not real_repo.is_relative_to(real_root):
            raise RepoNotAllowedError()
    else:
        real_repo = Path(os.path.realpath(repo))

    if not real_repo.is_dir():
        raise RepoNotAllowedError()

    git_entry = real_repo / ".git"
    if not git_entry.exists():
        raise RepoNotAllowedError()

    if real_root is not None:
        real_git = Path(os.path.realpath(git_entry))
        if not real_git.is_relative_to(real_root):
            raise RepoNotAllowedError()

    return str(real_repo)


def resolve_commit_sha(repo_path: str, sha: str) -> str:
    """Validate SHA format and resolve to full 40-character commit SHA via git rev-parse."""
    cleaned = (sha or "").strip()
    if not SHA_RE.match(cleaned):
        raise InvalidShaError("invalid_sha")

    proc = subprocess.run(
        ["git", "-C", repo_path, "rev-parse", "--verify", "--quiet", f"{cleaned}^{{commit}}"],
        capture_output=True,
        text=True,
        check=False,
        env=_clean_git_env(),
    )
    full_sha = proc.stdout.strip()
    if proc.returncode != 0 or not SHA_RE.match(full_sha):
        raise InvalidShaError("invalid_sha")
    return full_sha


def enqueue_commit(repo: str, sha: str) -> dict[str, Any]:
    """
    Shared enqueue implementation used by both CLI (`python -m app.cli enqueue`)
    and HTTP (`POST /enqueue`).
    - Validates SHA format and repo path containment / .git presence.
    - Resolves SHA to full 40-char SHA.
    - Skips merge commits (`status='skipped_merge'`).
    - Upserts commit and idempotently enqueues a scan (`enqueue_scan_if_missing`)
      so repeated calls for the same commit do not open a new scan.
    """
    cleaned_sha = (sha or "").strip()
    if not SHA_RE.match(cleaned_sha):
        raise InvalidShaError("invalid_sha")

    resolved_repo = resolve_and_validate_repo(repo)
    full_sha = resolve_commit_sha(resolved_repo, cleaned_sha)

    try:
        commit = git_reader.get_commit(resolved_repo, full_sha)
    except Exception as exc:
        raise InvalidShaError("invalid_sha") from exc

    if commit is None:
        return {
            "status": "skipped_merge",
            "sha": full_sha,
            "repo_path": resolved_repo,
        }

    commit_id = db.upsert_commit(commit, resolved_repo)
    scan_id, created = db.enqueue_scan_if_missing(commit_id)
    return {
        "status": "enqueued",
        "commit_id": commit_id,
        "scan_id": scan_id,
        "sha": str(commit["sha"]),
        "created": created,
        "repo_path": resolved_repo,
    }
