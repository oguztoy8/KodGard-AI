import threading
from unittest.mock import patch

import pytest

from app import worker
from app.reviewer import ReviewResult


def test_worker_loop_exits_cleanly_on_stop_event(capsys: pytest.CaptureFixture[str]) -> None:
    stop_event = threading.Event()
    call_count = 0

    def fake_process_one() -> dict | None:
        nonlocal call_count
        call_count += 1
        stop_event.set()
        return {"scan_id": 1, "commit_id": 1, "sha": "1af4070e", "status": "done"}

    with patch("app.worker.process_one_scan", side_effect=fake_process_one):
        rc = worker.run_worker(loop=True, interval=0.1, stop_event=stop_event)

    assert rc == 0
    assert call_count == 1
    captured = capsys.readouterr()
    assert "Worker stopped" in captured.out


def test_indexing_error_does_not_fail_scan() -> None:
    job = {
        "scan_id": 15,
        "commit_id": 15,
        "sha": "1af4070e2cfa054959f084a642142b3ebd3d4692",
        "repo_path": "/tmp/kg-test",
        "subject": "test commit",
    }

    with (
        patch("app.worker.db.claim_next_pending_scan", return_value=job),
        patch("app.worker.filter_changed_files", return_value=["vuln.py"]),
        patch("app.worker.scanner.prepare_diff", return_value=("diff", [])),
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
        patch("app.worker.db.upsert_doc", return_value=1),
        patch("app.worker.db.save_commit_findings", return_value=[]),
        patch("app.worker.db.complete_scan") as mock_complete,
        patch("app.worker.db.fail_scan") as mock_fail,
        patch("app.worker.indexer.index_commit", side_effect=RuntimeError("embedding failure")),
    ):
        res = worker.process_one_scan()

    assert res is not None
    assert res["status"] == "done"
    mock_complete.assert_called_once_with(15)
    mock_fail.assert_not_called()
