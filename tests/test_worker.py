import subprocess
from unittest.mock import patch

import pytest

from app import worker
from app.reviewer import ReviewResult


def test_worker_marks_commit_not_found_and_continues_to_next_scan(
    capsys: pytest.CaptureFixture[str],
) -> None:
    jobs = [
        {
            "scan_id": 4,
            "commit_id": 4,
            "sha": "99237ba0b80abd87f5cbe6ba54eb88f518907629",
            "repo_path": "/tmp/kg-test",
            "subject": "missing commit",
        },
        {
            "scan_id": 9,
            "commit_id": 9,
            "sha": "1af4070e2cfa054959f084a642142b3ebd3d4692",
            "repo_path": "/tmp/kg-test",
            "subject": "valid commit",
        },
        None,
    ]

    def fake_filter_changed_files(repo_path: str, sha: str) -> list[str]:
        if sha.startswith("99237ba0"):
            raise subprocess.CalledProcessError(
                128,
                ["git", "-C", repo_path, "diff-tree", sha],
                stderr="fatal: bad object",
            )
        return ["vuln.py"]

    with (
        patch("app.worker.db.claim_next_pending_scan", side_effect=jobs) as mock_claim,
        patch("app.worker.filter_changed_files", side_effect=fake_filter_changed_files),
        patch("app.worker.scanner.prepare_diff", return_value=("diff --git a/vuln.py b/vuln.py", [])),
        patch("app.worker.scanner.run_semgrep", return_value=[]),
        patch("app.worker.scanner.run_gitleaks", return_value=[]),
        patch(
            "app.worker.reviewer.review_commit",
            return_value=ReviewResult(
                summary_md="Özet",
                detail_md="Detay",
                findings=[],
                risk_level="low",
            ),
        ),
        patch("app.worker.db.upsert_doc", return_value=1) as mock_upsert_doc,
        patch("app.worker.db.save_commit_findings", return_value=[]) as mock_save_findings,
        patch("app.worker.db.complete_scan") as mock_complete,
        patch("app.worker.db.fail_scan") as mock_fail,
        patch("app.worker.indexer.index_commit", return_value={"total": 0}),
    ):
        rc = worker.run_worker()

    assert rc == 0
    assert mock_claim.call_count == 3

    # First scan failed with 'commit_not_found' (no stderr/path/cmd leaked)
    mock_fail.assert_called_once_with(4, "commit_not_found")

    # Second scan was processed and completed normally
    mock_complete.assert_called_once_with(9)
    assert mock_upsert_doc.call_count == 2
    mock_save_findings.assert_called_once()

    captured = capsys.readouterr()
    assert "scan_id=4 sha=99237ba0 skipped: commit_not_found" in captured.out
    assert "scan_id=9 sha=1af4070e done" in captured.out
