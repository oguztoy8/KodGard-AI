from app.findings import (
    apply_ignored_preservation,
    compute_fingerprint,
    determine_fixed_finding_ids,
)


def test_compute_fingerprint_is_deterministic_and_unique() -> None:
    fp1 = compute_fingerprint("semgrep", "kodgard-eval-usage-python", "app.py", 10, "Tehlikeli eval")
    fp2 = compute_fingerprint("semgrep", "kodgard-eval-usage-python", "app.py", 10, "Tehlikeli eval")
    fp_diff_line = compute_fingerprint("semgrep", "kodgard-eval-usage-python", "app.py", 11, "Tehlikeli eval")
    fp_diff_src = compute_fingerprint("llm", "kodgard-eval-usage-python", "app.py", 10, "Tehlikeli eval")

    assert len(fp1) == 64
    assert fp1 == fp2
    assert fp1 != fp_diff_line
    assert fp1 != fp_diff_src


def test_ignored_preservation_keeps_status_and_reason() -> None:
    fp_ignored = compute_fingerprint("semgrep", "rule-1", "vuln.py", 5, "Eval usage")
    fp_open = compute_fingerprint("gitleaks", "aws-access-token", "vuln.py", 2, "aws-access-token")

    existing_findings = [
        {
            "id": 1,
            "commit_id": 10,
            "file": "vuln.py",
            "status": "ignored",
            "ignore_reason": "Test ortamı için bilinçli kullanım",
            "fingerprint": fp_ignored,
        },
        {
            "id": 2,
            "commit_id": 10,
            "file": "vuln.py",
            "status": "open",
            "ignore_reason": None,
            "fingerprint": fp_open,
        },
    ]

    new_findings = [
        {
            "source": "semgrep",
            "rule_id": "rule-1",
            "file": "vuln.py",
            "line": 5,
            "title": "Eval usage",
            "fingerprint": fp_ignored,
        },
        {
            "source": "gitleaks",
            "rule_id": "aws-access-token",
            "file": "vuln.py",
            "line": 2,
            "title": "aws-access-token",
            "fingerprint": fp_open,
        },
    ]

    reconciled = apply_ignored_preservation(new_findings, existing_findings)
    assert len(reconciled) == 2

    by_fp = {item["fingerprint"]: item for item in reconciled}
    assert by_fp[fp_ignored]["status"] == "ignored"
    assert by_fp[fp_ignored]["ignore_reason"] == "Test ortamı için bilinçli kullanım"
    assert by_fp[fp_open]["status"] == "open"
    assert by_fp[fp_open]["ignore_reason"] is None


def test_fixed_transition_only_for_changed_files_when_finding_disappears() -> None:
    fp_fixed = compute_fingerprint("semgrep", "rule-eval", "vuln.py", 10, "Eval")
    fp_still_present = compute_fingerprint("semgrep", "rule-shell", "vuln.py", 20, "Shell")
    fp_untouched_file = compute_fingerprint("semgrep", "rule-xss", "other.js", 8, "XSS")

    existing_open = [
        {"id": 101, "commit_id": 1, "file": "vuln.py", "status": "open", "fingerprint": fp_fixed},
        {"id": 102, "commit_id": 1, "file": "vuln.py", "status": "open", "fingerprint": fp_still_present},
        {"id": 103, "commit_id": 1, "file": "other.js", "status": "open", "fingerprint": fp_untouched_file},
    ]

    # Commit 2 only changed vuln.py, and only fp_still_present remains
    current_commit_findings = [
        {"file": "vuln.py", "fingerprint": fp_still_present},
    ]
    changed_files = ["vuln.py"]

    fixed_ids = determine_fixed_finding_ids(existing_open, current_commit_findings, changed_files)
    assert fixed_ids == [101]
    assert existing_open[0]["status"] == "fixed"
    assert existing_open[1]["status"] == "open"
    assert existing_open[2]["status"] == "open"
