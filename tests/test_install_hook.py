from pathlib import Path
import subprocess

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SCRIPT = PROJECT_ROOT / "scripts" / "install-hook.sh"


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "main"], check=True, capture_output=True)


def test_install_hook_fresh_repo_and_uninstall(tmp_path: Path) -> None:
    repo = tmp_path / "fresh_repo"
    _init_repo(repo)

    res = subprocess.run(
        [str(INSTALL_SCRIPT), str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0

    hook_file = repo / ".git" / "hooks" / "post-commit"
    assert hook_file.is_file()
    content = hook_file.read_text(encoding="utf-8")
    assert "# kodgard-standalone-wrapper" in content
    assert "# >>> kodgard >>>" in content
    assert "KODGARD_API_URL" in content
    assert str(PROJECT_ROOT / "hooks" / "post-commit") in content

    # Verify core.hooksPath was not set
    hooks_path_cfg = subprocess.run(
        ["git", "-C", str(repo), "config", "--local", "--get", "core.hooksPath"],
        capture_output=True,
        text=True,
    )
    assert hooks_path_cfg.returncode != 0

    # Uninstall removes standalone wrapper completely
    subprocess.run(
        [str(INSTALL_SCRIPT), "--uninstall", str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert not hook_file.exists()


def test_install_hook_existing_hook_append_idempotent_and_uninstall(tmp_path: Path) -> None:
    repo = tmp_path / "existing_hook_repo"
    _init_repo(repo)

    hook_file = repo / ".git" / "hooks" / "post-commit"
    hook_file.parent.mkdir(parents=True, exist_ok=True)
    original_content = "#!/usr/bin/env bash\necho 'custom user hook'\n"
    hook_file.write_text(original_content, encoding="utf-8")
    hook_file.chmod(0o755)

    # First install appends block and creates .kodgard.bak
    subprocess.run([str(INSTALL_SCRIPT), str(repo)], check=True, capture_output=True, text=True)
    bak_file = repo / ".git" / "hooks" / "post-commit.kodgard.bak"
    assert bak_file.is_file()
    assert bak_file.read_text(encoding="utf-8") == original_content

    after_first = hook_file.read_text(encoding="utf-8")
    assert "echo 'custom user hook'" in after_first
    assert after_first.count("# >>> kodgard >>>") == 1
    assert after_first.count("# <<< kodgard <<<") == 1

    # Second install is idempotent (does not duplicate block)
    subprocess.run([str(INSTALL_SCRIPT), str(repo)], check=True, capture_output=True, text=True)
    after_second = hook_file.read_text(encoding="utf-8")
    assert after_second == after_first
    assert after_second.count("# >>> kodgard >>>") == 1

    # Uninstall removes only the marked block and preserves original hook
    subprocess.run(
        [str(INSTALL_SCRIPT), "--uninstall", str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert hook_file.is_file()
    after_uninstall = hook_file.read_text(encoding="utf-8")
    assert "echo 'custom user hook'" in after_uninstall
    assert "# >>> kodgard >>>" not in after_uninstall
    assert "# <<< kodgard <<<" not in after_uninstall


def test_install_hook_respects_without_modifying_core_hooks_path(tmp_path: Path) -> None:
    repo = tmp_path / "custom_hooks_repo"
    _init_repo(repo)
    custom_hooks = tmp_path / "my_custom_hooks"
    custom_hooks.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        ["git", "-C", str(repo), "config", "core.hooksPath", str(custom_hooks)],
        check=True,
    )

    subprocess.run([str(INSTALL_SCRIPT), str(repo)], check=True, capture_output=True, text=True)

    # Installed into custom_hooks without changing core.hooksPath
    assert (custom_hooks / "post-commit").is_file()
    cfg = subprocess.run(
        ["git", "-C", str(repo), "config", "--get", "core.hooksPath"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert cfg.stdout.strip() == str(custom_hooks)
