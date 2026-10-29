from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
import subprocess

from app.config import settings

ALLOWED_EXTENSIONS = {".py", ".js"}


def _load_kodgardignore_patterns(repo: Path) -> list[str]:
    patterns: list[str] = []
    candidate_files = [
        Path(settings.KODGARD_HOME) / ".kodgardignore",
        repo / ".kodgardignore",
    ]
    seen_files: set[Path] = set()
    for path in candidate_files:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved in seen_files or not resolved.is_file():
            continue
        seen_files.add(resolved)
        for raw_line in resolved.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line not in patterns:
                patterns.append(line)
    return patterns


def _matches_kodgardignore(rel_path: str, patterns: list[str]) -> bool:
    posix_path = PurePosixPath(rel_path)
    filename = posix_path.name
    parts = posix_path.parts

    for pat in patterns:
        if pat.endswith("/"):
            dir_pat = pat.rstrip("/")
            if fnmatchcase(rel_path, f"{dir_pat}/*") or fnmatchcase(rel_path, f"*/{dir_pat}/*"):
                return True
            if any(fnmatchcase(part, dir_pat) for part in parts[:-1]):
                return True
        else:
            if fnmatchcase(rel_path, pat) or fnmatchcase(filename, pat):
                return True
    return False


def _git_ignored_files(repo: Path, files: list[str]) -> set[str]:
    if not files:
        return set()
    proc = subprocess.run(
        ["git", "-C", str(repo), "check-ignore", "--no-index", "--stdin"],
        input="\n".join(files),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode not in (0, 1):
        raise subprocess.CalledProcessError(
            proc.returncode, proc.args, output=proc.stdout, stderr=proc.stderr
        )
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


def filter_changed_files(repo: str | Path, sha: str) -> list[str]:
    """Return changed .py and .js files for `sha` in `repo`, excluding .gitignore and .kodgardignore matches."""
    repo_path = Path(repo).resolve()
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(repo_path),
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--name-only",
            "-r",
            "--diff-filter=ACMR",
            sha,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    changed = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if not changed:
        return []

    patterns = _load_kodgardignore_patterns(repo_path)
    git_ignored = _git_ignored_files(repo_path, changed)

    filtered: list[str] = []
    for rel_path in changed:
        if rel_path in git_ignored:
            continue
        if _matches_kodgardignore(rel_path, patterns):
            continue
        suffix = PurePosixPath(rel_path).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            continue
        filtered.append(rel_path)

    return filtered
