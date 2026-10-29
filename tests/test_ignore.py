import subprocess
from pathlib import Path

import pytest

from app.ignore import filter_changed_files


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


@pytest.fixture
def ignore_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    return repo


def test_filter_changed_files_respects_gitignore_and_kodgardignore(ignore_repo: Path) -> None:
    (ignore_repo / ".gitignore").write_text("ignored_dir/\nsecret.py\n", encoding="utf-8")
    (ignore_repo / ".kodgardignore").write_text(
        "*.lock\ndist/\nbuild/\n*.min.js\n", encoding="utf-8"
    )

    # Allowed files
    (ignore_repo / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (ignore_repo / "index.js").write_text("console.log('ok');\n", encoding="utf-8")

    # Disallowed by extension
    (ignore_repo / "README.md").write_text("# Doc\n", encoding="utf-8")
    (ignore_repo / "uv.lock").write_text("lock\n", encoding="utf-8")

    # Disallowed by .kodgardignore
    (ignore_repo / "bundle.min.js").write_text("console.log(1);\n", encoding="utf-8")
    (ignore_repo / "dist").mkdir()
    (ignore_repo / "dist" / "x.js").write_text("console.log('dist');\n", encoding="utf-8")
    (ignore_repo / "build").mkdir()
    (ignore_repo / "build" / "out.py").write_text("x = 1\n", encoding="utf-8")

    # Disallowed by .gitignore (even if force-added into commit)
    (ignore_repo / "secret.py").write_text("TOKEN='123'\n", encoding="utf-8")
    (ignore_repo / "ignored_dir").mkdir()
    (ignore_repo / "ignored_dir" / "inside.js").write_text("console.log(2);\n", encoding="utf-8")

    _git(ignore_repo, "add", "-f", ".")
    _git(ignore_repo, "commit", "-m", "test files")
    sha = _git(ignore_repo, "rev-parse", "HEAD")

    changed = filter_changed_files(ignore_repo, sha)
    assert sorted(changed) == ["app.py", "index.js"]
