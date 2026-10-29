import logging
import subprocess
from pathlib import Path

import pytest

from app import git_reader


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    return repo


def test_list_commits_diff_and_patch_id(sample_repo: Path) -> None:
    file_a = sample_repo / "a.py"
    file_a.write_text("print(1)\n", encoding="utf-8")
    _git(sample_repo, "add", "a.py")
    _git(sample_repo, "commit", "-m", "ilk")
    sha1 = _git(sample_repo, "rev-parse", "HEAD")

    pid1 = git_reader.patch_id(sample_repo, sha1)
    assert len(pid1) == 40

    diff = git_reader.commit_diff(sample_repo, sha1)
    assert "+print(1)" in diff

    commits = git_reader.list_commits(sample_repo, limit=10)
    assert len(commits) == 1
    assert commits[0]["sha"] == sha1
    assert commits[0]["patch_id"] == pid1
    assert commits[0]["subject"] == "ilk"

    # Amend commit message only: SHA changes, patch_id stays identical
    _git(sample_repo, "commit", "--amend", "-m", "ilk düzeltildi")
    sha2 = _git(sample_repo, "rev-parse", "HEAD")
    assert sha2 != sha1
    pid2 = git_reader.patch_id(sample_repo, sha2)
    assert pid2 == pid1


def test_skips_and_logs_merge_commits(sample_repo: Path, caplog: pytest.LogCaptureFixture) -> None:
    (sample_repo / "main.py").write_text("x = 1\n", encoding="utf-8")
    _git(sample_repo, "add", "main.py")
    _git(sample_repo, "commit", "-m", "root commit")

    _git(sample_repo, "checkout", "-b", "feature")
    (sample_repo / "feat.py").write_text("y = 2\n", encoding="utf-8")
    _git(sample_repo, "add", "feat.py")
    _git(sample_repo, "commit", "-m", "feature commit")

    _git(sample_repo, "checkout", "main")
    (sample_repo / "other.py").write_text("z = 3\n", encoding="utf-8")
    _git(sample_repo, "add", "other.py")
    _git(sample_repo, "commit", "-m", "main commit")

    _git(sample_repo, "merge", "--no-ff", "feature", "-m", "Merge branch 'feature'")
    merge_sha = _git(sample_repo, "rev-parse", "HEAD")

    with caplog.at_level(logging.INFO):
        commits = git_reader.list_commits(sample_repo, limit=10)

    returned_shas = [c["sha"] for c in commits]
    assert merge_sha not in returned_shas
    assert len(commits) == 3
    assert any(merge_sha in rec.message for rec in caplog.records)
