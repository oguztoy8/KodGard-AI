import hashlib
from typing import Any

VALID_STATUSES = {"open", "ignored", "fixed"}
VALID_SEVERITIES = {"low", "medium", "high", "critical"}
VALID_SOURCES = {"semgrep", "gitleaks", "llm"}


def compute_fingerprint(
    source: str,
    rule_id: str | None,
    file: str | None,
    line: int | None,
    summary: str | None = "",
) -> str:
    """Compute deterministic sha256(source + rule_id + file + line + short content summary)."""
    src = (source or "").strip().lower()
    rid = (rule_id or "").strip()
    fpath = (file or "").strip()
    lnum = str(line if line is not None else 0)
    short_summary = " ".join((summary or "").strip().split())[:120]
    payload = f"{src}|{rid}|{fpath}|{lnum}|{short_summary}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def apply_ignored_preservation(
    new_findings: list[dict[str, Any]],
    existing_findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Preserve status='ignored' and ignore_reason if a finding with the same fingerprint
    was previously marked as ignored. New findings default to status='open'.
    """
    ignored_by_fp: dict[str, str | None] = {}
    for ef in existing_findings:
        if ef.get("status") == "ignored" and ef.get("fingerprint"):
            ignored_by_fp[ef["fingerprint"]] = ef.get("ignore_reason")

    result: list[dict[str, Any]] = []
    for item in new_findings:
        f_copy = dict(item)
        fp = f_copy.get("fingerprint") or compute_fingerprint(
            f_copy.get("source", ""),
            f_copy.get("rule_id"),
            f_copy.get("file"),
            f_copy.get("line"),
            f_copy.get("title") or f_copy.get("explanation") or "",
        )
        f_copy["fingerprint"] = fp
        if fp in ignored_by_fp:
            f_copy["status"] = "ignored"
            f_copy["ignore_reason"] = ignored_by_fp[fp]
        else:
            f_copy["status"] = "open"
            f_copy["ignore_reason"] = None
        result.append(f_copy)
    return result


def determine_fixed_finding_ids(
    existing_open_findings: list[dict[str, Any]],
    current_findings: list[dict[str, Any]],
    changed_files: list[str] | set[str],
) -> list[int]:
    """
    For a subsequent commit in the same repo: if a file was changed in this commit
    and a previous 'open' finding on that file (by fingerprint) is no longer present
    in current_findings, mark that previous finding as 'fixed'.
    """
    changed_set = set(changed_files)
    if not changed_set:
        return []

    current_fps = {
        f.get("fingerprint")
        for f in current_findings
        if f.get("fingerprint")
    }

    fixed_ids: list[int] = []
    for ef in existing_open_findings:
        if ef.get("status") != "open":
            continue
        if ef.get("file") not in changed_set:
            continue
        if ef.get("fingerprint") not in current_fps:
            ef["status"] = "fixed"
            if ef.get("id") is not None:
                fixed_ids.append(int(ef["id"]))
    return fixed_ids
