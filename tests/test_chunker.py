from app.indexer import (
    build_commit_chunks,
    split_markdown,
    split_source_file,
)


def test_markdown_python_js_chunk_sizes() -> None:
    md_text = "\n\n".join(
        [f"## Bölüm {i}\n" + ("Açıklama metni ve detaylar. " * 20) for i in range(10)]
    )
    md_chunks = split_markdown(md_text, chunk_size=800, chunk_overlap=100)
    assert len(md_chunks) > 1
    assert all(len(c) <= 800 for c in md_chunks)

    py_code = "\n\n".join(
        [f"def func_{i}(x):\n    return x + {i} * " + ("1 + " * 40) + "0" for i in range(15)]
    )
    py_chunks = split_source_file(py_code, "service.py", chunk_size=800, chunk_overlap=100)
    assert len(py_chunks) > 1
    assert all(len(c) <= 800 for c in py_chunks)

    js_code = "\n\n".join(
        [f"function handler_{i}(req) {{\n  return " + ("req.val + " * 35) + "0;\n}" for i in range(15)]
    )
    js_chunks = split_source_file(js_code, "app.js", chunk_size=800, chunk_overlap=100)
    assert len(js_chunks) > 1
    assert all(len(c) <= 800 for c in js_chunks)


def test_single_chunk_per_finding_and_gitleaks_file_exclusion_across_commits() -> None:
    docs = {
        "summary": "Özet bilgi.",
        "detail": "Detaylı inceleme.",
    }
    findings = [
        {
            "id": 10,
            "severity": "high",
            "source": "gitleaks",
            "rule_id": "aws-access-token",
            "file": "vuln.py",
            "line": 4,
            "cwe": "CWE-798",
            "title": "Gizli anahtar tespiti",
            "explanation": "Anahtarı iptal et ve döndür " * 40,
            "fix": "Ortam değişkeni kullan.",
            "status": "fixed",
            "ignore_reason": None,
        },
        {
            "id": 11,
            "severity": "medium",
            "source": "semgrep",
            "rule_id": "kodgard-innerhtml-assignment",
            "file": "clean.js",
            "line": 3,
            "cwe": "CWE-79",
            "title": "Güvensiz innerHTML",
            "explanation": "XSS riski.",
            "fix": "textContent kullan.",
            "status": "ignored",
            "ignore_reason": "Kabul edilen test",
        },
    ]

    # Even in a later commit where vuln.py was fixed, repo_gitleaks_files includes 'vuln.py' from an earlier commit
    changed_files = ["vuln.py", "clean.js"]
    repo_gitleaks_files = {"vuln.py"}
    file_diffs = {
        "vuln.py": "-AWS_KEY = 'SECRET_SHOULD_NOT_BE_INDEXED'\n+AWS_KEY = os.environ.get('KEY')",
        "clean.js": "+el.innerHTML = val;",
    }
    file_contents = {
        "vuln.py": "import os\nAWS_KEY = os.environ.get('KEY')\n",
        "clean.js": "const el = document.getElementById('a');\nel.innerHTML = val;\n",
    }

    chunks = build_commit_chunks(
        docs=docs,
        findings=findings,
        changed_files=changed_files,
        repo_gitleaks_files=repo_gitleaks_files,
        file_diffs=file_diffs,
        file_contents=file_contents,
    )

    finding_chunks = [c for c in chunks if c["kind"] == "finding"]
    assert len(finding_chunks) == 2
    assert finding_chunks[0]["source_ref"] == "finding:10"
    assert finding_chunks[1]["source_ref"] == "finding:11"
    assert "ignored" in finding_chunks[1]["content"]
    assert "Kabul edilen test" in finding_chunks[1]["content"]

    diff_refs = [c["source_ref"] for c in chunks if c["kind"] == "diff"]
    file_refs = [c["source_ref"] for c in chunks if c["kind"] == "file"]

    assert "diff:vuln.py" not in diff_refs
    assert "file:vuln.py" not in file_refs
    assert "diff:clean.js" in diff_refs
    assert "file:clean.js" in file_refs
    assert all("SECRET_SHOULD_NOT_BE_INDEXED" not in c["content"] for c in chunks)
