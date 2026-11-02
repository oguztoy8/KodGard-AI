import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

from app.config import settings
from app.findings import VALID_SEVERITIES, compute_fingerprint
from app.ignore import filter_changed_files

MAX_DIFF_CHARS = 60000

SEMGREP_SEVERITY_MAP = {
    "ERROR": "high",
    "WARNING": "medium",
    "INFO": "low",
    "CRITICAL": "critical",
    "HIGH": "high",
    "MEDIUM": "medium",
    "LOW": "low",
}


def _clean_subprocess_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    if extra:
        env.update(extra)
    return env


def prepare_diff(
    repo: str | Path,
    sha: str,
    changed_files: list[str] | None = None,
    max_chars: int = MAX_DIFF_CHARS,
) -> tuple[str, list[str]]:
    """
    Build unified diff for filtered .py and .js files of a commit.
    Truncates per file if total characters exceed `max_chars` (default 60000).
    Returns (diff_text, truncated_files).
    """
    repo_str = str(Path(repo).resolve())
    files = changed_files if changed_files is not None else filter_changed_files(repo_str, sha)
    if not files:
        return "", []

    file_diffs: list[tuple[str, str]] = []
    for rel_file in files:
        proc = subprocess.run(
            ["git", "-C", repo_str, "show", "--format=", "--patch", sha, "--", rel_file],
            check=True,
            capture_output=True,
            text=True,
            env=_clean_subprocess_env(),
        )
        if proc.stdout:
            file_diffs.append((rel_file, proc.stdout))

    total_len = sum(len(d) for _, d in file_diffs)
    if total_len <= max_chars:
        return "\n".join(d for _, d in file_diffs), []

    truncated_files: list[str] = []
    per_file_budget = max(500, max_chars // max(len(file_diffs), 1))
    assembled: list[str] = []
    remaining = max_chars

    for rel_file, diff_chunk in file_diffs:
        if remaining <= 0:
            truncated_files.append(rel_file)
            continue
        marker = f"\n... [{rel_file} dosyası 60000 karakter sınırı nedeniyle kısaltıldı] ...\n"
        limit = min( max(per_file_budget, remaining), remaining )
        if len(diff_chunk) > limit:
            keep = max(0, limit - len(marker))
            assembled.append(diff_chunk[:keep] + marker)
            truncated_files.append(rel_file)
            remaining -= len(assembled[-1])
        else:
            assembled.append(diff_chunk)
            remaining -= len(diff_chunk)

    final_diff = "".join(assembled)
    if len(final_diff) > max_chars:
        final_diff = final_diff[:max_chars]
    return final_diff, truncated_files


def parse_semgrep_output(
    raw_data: str | dict[str, Any],
    base_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Parse Semgrep JSON output into normalized finding dicts."""
    if not raw_data:
        return []
    data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
    results = data.get("results", []) if isinstance(data, dict) else []

    base_path = Path(base_dir).resolve() if base_dir else None
    findings: list[dict[str, Any]] = []

    for item in results:
        check_id = str(item.get("check_id") or "semgrep-rule")
        rule_id = check_id.split(".")[-1] if "." in check_id else check_id

        raw_path = str(item.get("path") or "")
        rel_file = raw_path
        if base_path and raw_path:
            try:
                rel_file = str(Path(raw_path).resolve().relative_to(base_path))
            except ValueError:
                rel_file = raw_path

        start_info = item.get("start") or {}
        line = int(start_info.get("line") or 1)

        extra = item.get("extra") or {}
        metadata = extra.get("metadata") or {}

        raw_sev = str(metadata.get("severity") or extra.get("severity") or "WARNING").upper()
        severity = SEMGREP_SEVERITY_MAP.get(raw_sev, "medium")
        if severity not in VALID_SEVERITIES:
            severity = "medium"

        raw_cwe = metadata.get("cwe") or ""
        if isinstance(raw_cwe, list):
            cwe = str(raw_cwe[0]) if raw_cwe else ""
        else:
            cwe = str(raw_cwe)

        title = str(metadata.get("title") or rule_id)
        explanation = str(extra.get("message") or title)
        fix = str(metadata.get("fix") or "Güvenli kodlama pratiklerine uygun olarak ilgili satırı düzeltin.")

        fp = compute_fingerprint("semgrep", rule_id, rel_file, line, title)
        findings.append(
            {
                "source": "semgrep",
                "rule_id": rule_id,
                "severity": severity,
                "file": rel_file,
                "line": line,
                "cwe": cwe,
                "title": title,
                "explanation": explanation,
                "fix": fix,
                "status": "open",
                "ignore_reason": None,
                "fingerprint": fp,
            }
        )

    return findings


def run_semgrep(
    repo: str | Path,
    sha: str,
    changed_files: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Extract commit tree via `git archive <sha>` into `/tmp` and run Semgrep
    with local rules (`rules/python-js.yml`) and `--metrics=off` on changed .py/.js files.
    """
    repo_str = str(Path(repo).resolve())
    files = changed_files if changed_files is not None else filter_changed_files(repo_str, sha)
    if not files:
        return []

    rules_path = Path(settings.KODGARD_HOME) / "rules" / "python-js.yml"
    semgrep_bin = shutil.which("semgrep") or str(Path.home() / ".local" / "bin" / "semgrep")

    with tempfile.TemporaryDirectory(dir="/tmp", prefix=f"kodgard_semgrep_{sha[:8]}_") as tmpdir:
        tmp_path = Path(tmpdir)
        archive_proc = subprocess.Popen(
            ["git", "-C", repo_str, "archive", "--format=tar", sha, "--", *files],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_clean_subprocess_env(),
        )
        tar_proc = subprocess.run(
            ["tar", "-x", "-C", str(tmp_path)],
            stdin=archive_proc.stdout,
            capture_output=True,
            check=False,
            env=_clean_subprocess_env(),
        )
        if archive_proc.stdout:
            archive_proc.stdout.close()
        archive_rc = archive_proc.wait()
        if archive_rc != 0 or tar_proc.returncode != 0:
            return []

        target_files = [str(tmp_path / f) for f in files if (tmp_path / f).is_file()]
        if not target_files:
            return []

        proc = subprocess.run(
            [
                semgrep_bin,
                "--metrics=off",
                "--disable-version-check",
                "--no-git-ignore",
                "--config",
                str(rules_path),
                "--json",
                *target_files,
            ],
            capture_output=True,
            text=True,
            check=False,
            env=_clean_subprocess_env({"HOME": "/tmp"}),
        )
        if not proc.stdout.strip():
            return []
        return parse_semgrep_output(proc.stdout, base_dir=tmp_path)


def parse_gitleaks_output(
    raw_data: str | list[dict[str, Any]],
    allowed_files: set[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Parse Gitleaks JSON output into normalized finding dicts.
    Never exposes or repeats the secret value; only records file, line, and rule_id,
    sets severity='high', and warns to revoke and rotate the key.
    """
    if not raw_data:
        return []
    items = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
    if not isinstance(items, list):
        return []

    findings: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        rule_id = str(item.get("RuleID") or "gitleaks-secret")
        rel_file = str(item.get("File") or "")
        if allowed_files is not None and rel_file not in allowed_files:
            continue
        line = int(item.get("StartLine") or item.get("Line") or 1)

        title = f"Gizli anahtar tespiti ({rule_id})"
        explanation = (
            f"{rel_file}:{line} konumunda '{rule_id}' kuralı ile eşleşen bir sır tespit edildi. "
            "Sızan anahtarı iptal et ve döndür (revoke and rotate)."
        )
        fix = (
            "Sırrı kaynak koddan ve geçmişten kaldırın, anahtarı iptal et ve döndür, "
            "ardından ortam değişkenlerinden (os.environ) okuyun."
        )
        fp = compute_fingerprint("gitleaks", rule_id, rel_file, line, rule_id)
        findings.append(
            {
                "source": "gitleaks",
                "rule_id": rule_id,
                "severity": "high",
                "file": rel_file,
                "line": line,
                "cwe": "CWE-798",
                "title": title,
                "explanation": explanation,
                "fix": fix,
                "status": "open",
                "ignore_reason": None,
                "fingerprint": fp,
            }
        )

    return findings


def _has_parent_commit(repo_str: str, sha: str) -> bool:
    proc = subprocess.run(
        ["git", "-C", repo_str, "rev-parse", "--verify", "--quiet", f"{sha}^"],
        capture_output=True,
        text=True,
        check=False,
        env=_clean_subprocess_env(),
    )
    return proc.returncode == 0


def run_gitleaks(repo: str | Path, sha: str) -> list[dict[str, Any]]:
    """
    Run Gitleaks CLI on commit `<sha>^..<sha>` (or `<sha>` for root commits)
    writing JSON report to `/tmp` with `--exit-code 0 --no-banner`.
    """
    repo_str = str(Path(repo).resolve())
    gitleaks_bin = shutil.which("gitleaks") or str(Path.home() / ".local" / "bin" / "gitleaks")
    log_opts = f"{sha}^..{sha}" if _has_parent_commit(repo_str, sha) else sha

    with tempfile.TemporaryDirectory(dir="/tmp", prefix=f"kodgard_gitleaks_{sha[:8]}_") as tmpdir:
        report_path = Path(tmpdir) / "gitleaks.json"
        subprocess.run(
            [
                gitleaks_bin,
                "git",
                f"--log-opts={log_opts}",
                "--report-format",
                "json",
                "--report-path",
                str(report_path),
                "--exit-code",
                "0",
                "--no-banner",
                repo_str,
            ],
            capture_output=True,
            text=True,
            check=False,
            env=_clean_subprocess_env(),
        )
        if not report_path.is_file():
            return []
        raw_text = report_path.read_text(encoding="utf-8").strip()
        if not raw_text:
            return []
        return parse_gitleaks_output(raw_text)
