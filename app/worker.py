import logging
from typing import Any

from app import db, reviewer, scanner
from app.ignore import filter_changed_files

logger = logging.getLogger(__name__)


def process_one_scan() -> dict[str, Any] | None:
    """
    Claim and process a single pending scan using SELECT ... FOR UPDATE SKIP LOCKED.
    Returns scan summary dict if a scan was processed, or None if no pending scan exists.
    """
    job = db.claim_next_pending_scan()
    if job is None:
        return None

    scan_id = int(job["scan_id"])
    commit_id = int(job["commit_id"])
    sha = str(job["sha"])
    repo_path = str(job["repo_path"])
    subject = job.get("subject")

    logger.info("Processing scan_id=%d commit_id=%d sha=%s", scan_id, commit_id, sha[:8])
    try:
        changed_files = filter_changed_files(repo_path, sha)
        diff_text, truncated_files = scanner.prepare_diff(
            repo_path, sha, changed_files=changed_files
        )
        semgrep_findings = scanner.run_semgrep(
            repo_path, sha, changed_files=changed_files
        )
        gitleaks_findings = scanner.run_gitleaks(repo_path, sha)
        pre_findings = semgrep_findings + gitleaks_findings

        effective_diff = (
            diff_text
            if diff_text.strip()
            else "(Bu commit'te filtrelenen .py veya .js dosyası değişikliği bulunmuyor.)"
        )
        review_res = reviewer.review_commit(
            diff_text=effective_diff,
            pre_findings=pre_findings,
            truncated_files=truncated_files,
            commit_subject=subject,
        )

        all_findings = pre_findings + review_res.findings
        db.upsert_doc(commit_id, "summary", review_res.summary_md, review_res.model)
        db.upsert_doc(commit_id, "detail", review_res.detail_md, review_res.model)
        saved_findings = db.save_commit_findings(
            commit_id=commit_id,
            repo_path=repo_path,
            changed_files=changed_files,
            new_findings=all_findings,
        )
        db.complete_scan(scan_id)
        logger.info(
            "Completed scan_id=%d sha=%s findings=%d",
            scan_id,
            sha[:8],
            len(saved_findings),
        )
        return {
            "scan_id": scan_id,
            "commit_id": commit_id,
            "sha": sha,
            "status": "done",
            "findings_count": len(saved_findings),
        }
    except Exception as exc:
        err_class = type(exc).__name__
        db.fail_scan(scan_id, err_class)
        logger.error("Failed scan_id=%d sha=%s error=%s", scan_id, sha[:8], err_class)
        return {
            "scan_id": scan_id,
            "commit_id": commit_id,
            "sha": sha,
            "status": "failed",
            "error": err_class,
        }


def run_worker() -> int:
    """Process all currently pending scans sequentially."""
    processed = 0
    while True:
        res = process_one_scan()
        if res is None:
            break
        processed += 1
    logger.info("Worker finished (processed %d scan(s))", processed)
    return 0
