"""Exercise the setup install-ref selector against disposable local Git repos."""

import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
SETUP = ROOT / "mfnavis_setup.sh"


def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def commit(repo, message):
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            message,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def remote(tmp_path):
    repo = tmp_path / "remote"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    (repo / "deployment").mkdir()
    (repo / "deployment/cedar_free.json").write_text("{}\n")
    commit(repo, "base")
    git(repo, "branch", "release")
    git(repo, "tag", "v1")
    (repo / "version.txt").write_text("v2\n")
    commit(repo, "main update")
    git(repo, "tag", "v2")
    return repo


def checkout(remote, tmp_path, ref):
    installed = tmp_path / "installed"
    subprocess.run(
        ["git", "clone", "--branch", ref, str(remote), str(installed)],
        check=True,
        capture_output=True,
    )
    return installed


def select(installed, ref=None):
    source = SETUP.read_text()
    selector = source.split("mfnavis_update_checkout() {\n", 1)[1].split(
        "\n}\n\nif [[ -d MFNavis/ ]]", 1
    )[0]
    script = (
        "set -e\nmfnavis_update_checkout() {\n"
        + selector
        + "\n}\nmfnavis_update_checkout\n"
    )
    env = {**os.environ, "GIT_ALLOW_PROTOCOL": "file"}
    env.pop("MFNAVIS_INSTALL_BRANCH", None)
    if ref is not None:
        env["MFNAVIS_INSTALL_BRANCH"] = ref
    return subprocess.run(
        ["bash", "-c", script], cwd=installed, env=env, capture_output=True, text=True
    )


def test_tagged_release_switches_to_latest_main(remote, tmp_path):
    installed = checkout(remote, tmp_path, "v1")
    result = select(installed, "main")
    assert result.returncode == 0, result.stderr
    assert git(installed, "symbolic-ref", "--short", "HEAD") == "main"
    assert git(installed, "rev-parse", "HEAD") == git(remote, "rev-parse", "main")


def test_tagged_release_switches_to_release_branch(remote, tmp_path):
    installed = checkout(remote, tmp_path, "v1")
    result = select(installed, "release")
    assert result.returncode == 0, result.stderr
    assert git(installed, "symbolic-ref", "--short", "HEAD") == "release"
    assert git(installed, "rev-parse", "HEAD") == git(remote, "rev-parse", "release")


def test_tagged_release_switches_to_newer_release_tag(remote, tmp_path):
    installed = checkout(remote, tmp_path, "v1")
    result = select(installed, "v2")
    assert result.returncode == 0, result.stderr
    assert git(installed, "rev-parse", "HEAD") == git(remote, "rev-parse", "v2")
    assert (
        subprocess.run(
            ["git", "symbolic-ref", "--quiet", "HEAD"],
            cwd=installed,
            capture_output=True,
        ).returncode
        != 0
    )


def test_current_branch_fast_forwards_without_explicit_ref(remote, tmp_path):
    installed = checkout(remote, tmp_path, "release")
    git(remote, "switch", "release")
    (remote / "release.txt").write_text("new release\n")
    commit(remote, "release update")
    result = select(installed)
    assert result.returncode == 0, result.stderr
    assert git(installed, "rev-parse", "HEAD") == git(remote, "rev-parse", "release")


def test_refuses_tracked_edits_and_backward_release(remote, tmp_path):
    installed = checkout(remote, tmp_path, "main")
    before = git(installed, "rev-parse", "HEAD")
    (installed / "version.txt").write_text("local change\n")
    result = select(installed, "v1")
    assert "Tracked files have local changes" in result.stderr
    (installed / "version.txt").write_text("v2\n")
    result = select(installed, "v1")
    assert "not a fast-forward" in result.stderr
    assert git(installed, "rev-parse", "HEAD") == before


def test_refuses_divergent_local_target_branch(remote, tmp_path):
    installed = checkout(remote, tmp_path, "v1")
    git(installed, "switch", "main")
    (installed / "local.txt").write_text("local\n")
    commit(installed, "local main")
    git(installed, "switch", "--detach", "v1")
    result = select(installed, "main")
    assert "Local main has commits" in result.stderr
    assert git(installed, "rev-parse", "HEAD") == git(remote, "rev-parse", "v1")
