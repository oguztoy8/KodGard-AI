import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from app import cli, git_reader


def test_backfill_requires_yes_when_limit_above_20(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.cmd_backfill(repo="/tmp/kg-backfill", limit=25, yes=False)
    assert rc != 0
    captured = capsys.readouterr()
    assert "her commit bir Claude çağrısı demektir" in (captured.out + captured.err)


def test_backfill_is_idempotent_and_counts_skipped_merges(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_commits = [
        git_reader.CommitRecord(
            sha="ccc3333333333333333333333333333333333333",
            patch_id="p3",
            author="A",
            committed_at="2026-11-02T10:00:00Z",
            subject="c3",
            repo_path=str(tmp_path),
        ),
        git_reader.CommitRecord(
            sha="bbb2222222222222222222222222222222222222",
            patch_id="p2",
            author="A",
            committed_at="2026-11-02T09:00:00Z",
            subject="c2",
            repo_path=str(tmp_path),
        ),
        git_reader.CommitRecord(
            sha="aaa1111111111111111111111111111111111111",
            patch_id="p1",
            author="A",
            committed_at="2026-11-02T08:00:00Z",
            subject="c1",
            repo_path=str(tmp_path),
        ),
    ]

    seen_commits: set[int] = set()
    sha_to_id = {
        "aaa1111111111111111111111111111111111111": 1,
        "bbb2222222222222222222222222222222222222": 2,
        "ccc3333333333333333333333333333333333333": 3,
    }

    def fake_list_commits(repo_str: str, limit: int = 20):
        logging.getLogger(git_reader.__name__).info(
            "Skipping merge commit deadbeef in %s", repo_str
        )
        return fake_commits[:limit]

    def fake_upsert(commit_obj, _repo_path):
        return sha_to_id[commit_obj["sha"]]

    def fake_enqueue_if_missing(cid: int) -> tuple[int, bool]:
        if cid in seen_commits:
            return cid * 10, False
        seen_commits.add(cid)
        return cid * 10, True

    with (
        patch("app.cli.git_reader.list_commits", side_effect=fake_list_commits),
        patch("app.cli.db.upsert_commit", side_effect=fake_upsert),
        patch("app.cli.db.enqueue_scan_if_missing", side_effect=fake_enqueue_if_missing),
    ):
        rc1 = cli.cmd_backfill(repo=str(tmp_path), limit=3, yes=False)
        out1 = capsys.readouterr().out
        assert rc1 == 0
        assert "eklenen=3 atlanan=0 merge=1" in out1

        # Second run is idempotent: 0 added, 3 skipped
        rc2 = cli.cmd_backfill(repo=str(tmp_path), limit=3, yes=False)
        out2 = capsys.readouterr().out
        assert rc2 == 0
        assert "eklenen=0 atlanan=3 merge=1" in out2
