import hashlib
import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CommitRecord(dict):
    """Dict-like commit object that also supports attribute access."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


def patch_id(repo: str | Path, sha: str) -> str:
    """Compute stable git patch-id (`git show <sha> | git patch-id --stable`, first column)."""
    repo_str = str(repo)
    show_proc = subprocess.run(
        ["git", "-C", repo_str, "show", sha],
        check=True,
        capture_output=True,
        text=True,
    )
    patch_proc = subprocess.run(
        ["git", "-C", repo_str, "patch-id", "--stable"],
        input=show_proc.stdout,
        check=True,
        capture_output=True,
        text=True,
    )
    output = patch_proc.stdout.strip()
    if output:
        return output.split()[0]
    # Fallback for empty commits where git patch-id produces no output
    diff_only = subprocess.run(
        ["git", "-C", repo_str, "show", "--format=", "--patch", sha],
        check=True,
        capture_output=True,
        text=True,
    )
    return hashlib.sha1(diff_only.stdout.encode("utf-8")).hexdigest()


def commit_diff(repo: str | Path, sha: str) -> str:
    """Return the unified diff for a given commit SHA."""
    repo_str = str(repo)
    proc = subprocess.run(
        ["git", "-C", repo_str, "show", "--format=", "--patch", sha],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout


def get_commit(repo: str | Path, sha: str) -> CommitRecord | None:
    """Read a single commit from repo. Returns None if it is a merge commit."""
    repo_str = str(Path(repo).resolve())
    fmt = "%H%x1f%P%x1f%an <%ae>%x1f%aI%x1f%s"
    proc = subprocess.run(
        ["git", "-C", repo_str, "show", "-s", f"--format={fmt}", sha],
        check=True,
        capture_output=True,
        text=True,
    )
    line = proc.stdout.strip()
    if not line:
        return None
    parts = line.split("\x1f")
    if len(parts) < 5:
        return None
    commit_sha, parents_str, author, committed_at, subject = parts[:5]
    parents = parents_str.split()
    if len(parents) > 1:
        logger.info("Skipping merge commit %s in %s", commit_sha, repo_str)
        return None

    return CommitRecord(
        sha=commit_sha,
        patch_id=patch_id(repo_str, commit_sha),
        author=author,
        committed_at=committed_at,
        subject=subject,
        repo_path=repo_str,
    )


def list_commits(repo: str | Path, limit: int = 20) -> list[CommitRecord]:
    """List up to `limit` non-merge commits from `repo`, skipping and logging merge commits."""
    repo_str = str(Path(repo).resolve())
    fmt = "%H%x1f%P%x1f%an <%ae>%x1f%aI%x1f%s"
    fetch_count = max(limit * 3, 50)
    proc = subprocess.run(
        ["git", "-C", repo_str, "log", f"-n{fetch_count}", f"--format={fmt}"],
        check=True,
        capture_output=True,
        text=True,
    )
    results: list[CommitRecord] = []
    for raw_line in proc.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("\x1f")
        if len(parts) < 5:
            continue
        commit_sha, parents_str, author, committed_at, subject = parts[:5]
        parents = parents_str.split()
        if len(parents) > 1:
            logger.info("Skipping merge commit %s in %s", commit_sha, repo_str)
            continue
        results.append(
            CommitRecord(
                sha=commit_sha,
                patch_id=patch_id(repo_str, commit_sha),
                author=author,
                committed_at=committed_at,
                subject=subject,
                repo_path=repo_str,
            )
        )
        if len(results) >= limit:
            break
    return results
