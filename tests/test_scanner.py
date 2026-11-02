import json
from pathlib import Path

from app.scanner import (
     parse_gitleaks_output,
     parse_semgrep_output,
)


def test_parse_semgrep_output_with_fake_json(tmp_path: Path) -> None:
    fake_semgrep = {
        "results": [
            {
                "check_id": "rules.kodgard-eval-usage-python",
                "path": str(tmp_path / "src" / "app.py"),
                "start": {"line": 14, "col": 5},
                "end": {"line": 14, "col": 20},
                "extra": {
                    "severity": "ERROR",
                    "message": "Dinamik kod çalıştırma (eval) kullanımı tespit edildi.",
                    "metadata": {
                        "cwe": "CWE-95",
                        "title": "Tehlikeli eval() kullanımı",
                        "fix": "ast.literal_eval kullanın.",
                    },
                },
            },
            {
                "check_id": "rules.kodgard-innerhtml-assignment",
                "path": str(tmp_path / "web" / "ui.js"),
                "start": {"line": 42, "col": 1},
                "end": {"line": 42, "col": 35},
                "extra": {
                    "severity": "WARNING",
                    "message": "innerHTML ataması XSS riski taşır.",
                    "metadata": {
                        "cwe": ["CWE-79"],
                        "title": "Güvensiz innerHTML kullanımı",
                        "fix": "textContent kullanın.",
                    },
                },
            },
        ],
        "errors": [],
    }

    findings = parse_semgrep_output(json.dumps(fake_semgrep), base_dir=tmp_path)
    assert len(findings) == 2

    f1 = findings[0]
    assert f1["source"] == "semgrep"
    assert f1["rule_id"] == "kodgard-eval-usage-python"
    assert f1["severity"] == "high"
    assert f1["file"] == "src/app.py"
    assert f1["line"] == 14
    assert f1["cwe"] == "CWE-95"
    assert f1["title"] == "Tehlikeli eval() kullanımı"
    assert f1["status"] == "open"
    assert len(f1["fingerprint"]) == 64

    f2 = findings[1]
    assert f2["source"] == "semgrep"
    assert f2["rule_id"] == "kodgard-innerhtml-assignment"
    assert f2["severity"] == "medium"
    assert f2["file"] == "web/ui.js"
    assert f2["line"] == 42
    assert f2["cwe"] == "CWE-79"


def test_parse_gitleaks_output_never_includes_secret_value() -> None:
    fake_secret_value = "FAKE_SECRET_VALUE_999999"
    fake_gitleaks = [
        {
            "Description": "AWS Access Token",
            "StartLine": 8,
            "EndLine": 8,
            "StartColumn": 11,
            "EndColumn": 30,
            "Match": f"AWS_KEY = '{fake_secret_value}'",
            "Secret": fake_secret_value,
            "File": "config/settings.py",
            "RuleID": "aws-access-token",
            "Commit": "deadbeef12345678",
        }
    ]

    findings = parse_gitleaks_output(json.dumps(fake_gitleaks))
    assert len(findings) == 1

    f = findings[0]
    assert f["source"] == "gitleaks"
    assert f["rule_id"] == "aws-access-token"
    assert f["severity"] == "high"
    assert f["file"] == "config/settings.py"
    assert f["line"] == 8
    assert f["cwe"] == "CWE-798"
    assert "anahtarı iptal et ve döndür" in f["explanation"].lower()

    serialized = json.dumps(f, ensure_ascii=False)
    assert fake_secret_value not in serialized
