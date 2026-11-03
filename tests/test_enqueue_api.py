from pathlib import Path
import subprocess
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


def _run_git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def _init_git_repo(repo: Path) -> str:
    repo.mkdir(parents=True, exist_ok=True)
    _run_git(repo, "init", "-b", "main")
    _run_git(repo, "config", "user.name", "Test User")
    _run_git(repo, "config", "user.email", "test@example.com")
    (repo / "hello.py").write_text("print('merhaba')\n", encoding="utf-8")
    _run_git(repo, "add", "hello.py")
    _run_git(repo, "commit", "-m", "feat: initial commit")
    return _run_git(repo, "rev-parse", "HEAD")


def test_enqueue_valid_repo_and_idempotent_repeat(tmp_path: Path, monkeypatch) -> None:
    repos_root = tmp_path / "repos"
    repo_dir = repos_root / "demo"
    sha = _init_git_repo(repo_dir)

    monkeypatch.setenv("REPOS_HOST_DIR", str(repos_root))
    monkeypatch.setenv("REPOS_CONTAINER_DIR", str(repos_root))

    scans_db: dict[int, int] = {}
    upsert_calls: list[tuple[str, str]] = []
    enqueue_calls: list[int] = []

    def fake_upsert(commit: dict[str, Any], repo_path: str) -> int:
        upsert_calls.append((commit["sha"], repo_path))
        return 42

    def fake_enqueue_if_missing(commit_id: int) -> tuple[int, bool]:
        enqueue_calls.append(commit_id)
        if commit_id in scans_db:
            return scans_db[commit_id], False
        scans_db[commit_id] = 101
        return 101, True

    client = TestClient(app)
    with (
        patch("app.enqueue.db.upsert_commit", side_effect=fake_upsert),
        patch("app.enqueue.db.enqueue_scan_if_missing", side_effect=fake_enqueue_if_missing),
    ):
        res1 = client.post("/enqueue", params={"repo": str(repo_dir), "sha": sha[:8]})
        assert res1.status_code == 202
        assert res1.json() == {"scan_id": 101}

        # Second call with same commit does not open a new scan
        res2 = client.post("/enqueue", params={"repo": str(repo_dir), "sha": sha})
        assert res2.status_code == 202
        assert res2.json() == {"scan_id": 101}
        assert len(scans_db) == 1
        assert len(enqueue_calls) == 2


def test_enqueue_invalid_sha(tmp_path: Path, monkeypatch) -> None:
    repos_root = tmp_path / "repos"
    repo_dir = repos_root / "demo"
    _init_git_repo(repo_dir)

    monkeypatch.setenv("REPOS_HOST_DIR", str(repos_root))
    monkeypatch.setenv("REPOS_CONTAINER_DIR", str(repos_root))

    client = TestClient(app)
    # Bad characters / length
    res_fmt = client.post("/enqueue", params={"repo": str(repo_dir), "sha": "not-a-hex-sha!!"})
    assert res_fmt.status_code == 400
    assert res_fmt.json() == {"error": "invalid_sha"}

    # Non-existent commit SHA in repo
    res_missing = client.post(
        "/enqueue",
        params={"repo": str(repo_dir), "sha": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"},
    )
    assert res_missing.status_code == 400
    assert res_missing.json() == {"error": "invalid_sha"}


def test_enqueue_rejects_outside_repos_and_traversal_and_symlink(tmp_path: Path, monkeypatch) -> None:
    repos_root = tmp_path / "repos"
    inside_repo = repos_root / "demo"
    outside_repo = tmp_path / "outside"
    _init_git_repo(inside_repo)
    outside_sha = _init_git_repo(outside_repo)

    # Create a symlink inside repos_root pointing to outside_repo
    symlink_repo = repos_root / "escaped_link"
    symlink_repo.symlink_to(outside_repo)

    monkeypatch.setenv("REPOS_HOST_DIR", str(repos_root))
    monkeypatch.setenv("REPOS_CONTAINER_DIR", str(repos_root))

    client = TestClient(app)

    # 1. Outside REPOS root
    res_out = client.post("/enqueue", params={"repo": str(outside_repo), "sha": outside_sha})
    assert res_out.status_code == 400
    assert res_out.json() == {"error": "repo_not_allowed"}

    # 2. ../ path traversal
    traversal_path = f"{repos_root}/demo/../../outside"
    res_trav = client.post("/enqueue", params={"repo": traversal_path, "sha": outside_sha})
    assert res_trav.status_code == 400
    assert res_trav.json() == {"error": "repo_not_allowed"}

    # 3. Symlink escape
    res_sym = client.post("/enqueue", params={"repo": str(symlink_repo), "sha": outside_sha})
    assert res_sym.status_code == 400
    assert res_sym.json() == {"error": "repo_not_allowed"}


def test_enqueue_path_translation_host_to_container(tmp_path: Path, monkeypatch) -> None:
    container_repos = tmp_path / "container_mount"
    repo_in_container = container_repos / "team" / "service-a"
    sha = _init_git_repo(repo_in_container)

    # Host path does not even need to exist when mapped to container_repos
    virtual_host_root = "/virtual/host/repos"
    host_repo_arg = f"{virtual_host_root}/team/service-a"

    monkeypatch.setenv("REPOS_HOST_DIR", virtual_host_root)
    monkeypatch.setenv("REPOS_CONTAINER_DIR", str(container_repos))

    recorded_repos: list[str] = []

    def fake_upsert(commit: dict[str, Any], repo_path: str) -> int:
        recorded_repos.append(repo_path)
        return 7

    client = TestClient(app)
    with (
        patch("app.enqueue.db.upsert_commit", side_effect=fake_upsert),
        patch("app.enqueue.db.enqueue_scan_if_missing", return_value=(55, True)),
    ):
        res = client.post("/enqueue", params={"repo": host_repo_arg, "sha": sha})
        assert res.status_code == 202
        assert res.json() == {"scan_id": 55}
        assert recorded_repos == [str(repo_in_container.resolve())]


def test_enqueue_skips_merge_commit(tmp_path: Path, monkeypatch) -> None:
    repos_root = tmp_path / "repos"
    repo_dir = repos_root / "merge_demo"
    _init_git_repo(repo_dir)

    _run_git(repo_dir, "checkout", "-b", "feature")
    (repo_dir / "feature.py").write_text("x = 1\n", encoding="utf-8")
    _run_git(repo_dir, "add", "feature.py")
    _run_git(repo_dir, "commit", "-m", "feat: branch change")

    _run_git(repo_dir, "checkout", "main")
    (repo_dir / "main_change.py").write_text("y = 2\n", encoding="utf-8")
    _run_git(repo_dir, "add", "main_change.py")
    _run_git(repo_dir, "commit", "-m", "feat: main change")

    _run_git(repo_dir, "merge", "--no-ff", "feature", "-m", "Merge branch 'feature'")
    merge_sha = _run_git(repo_dir, "rev-parse", "HEAD")

    monkeypatch.setenv("REPOS_HOST_DIR", str(repos_root))
    monkeypatch.setenv("REPOS_CONTAINER_DIR", str(repos_root))

    client = TestClient(app)
    with patch("app.enqueue.db.upsert_commit") as mock_upsert:
        res = client.post("/enqueue", params={"repo": str(repo_dir), "sha": merge_sha})
        assert res.status_code == 200
        assert res.json() == {"status": "skipped_merge"}
        mock_upsert.assert_not_called()
