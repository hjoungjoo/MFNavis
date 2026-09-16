import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "cedar_deployment", ROOT / "scripts/check_cedar_free.py"
)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def git(path, *args):
    return (
        subprocess.check_output(["git", "-C", str(path), *args], stderr=subprocess.PIPE)
        .decode()
        .strip()
    )


@pytest.fixture
def repository(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "test/cedar-free")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    (repo / "seed").write_text("seed")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "seed")
    (repo / "deployment").mkdir()
    (repo / "deployment/cedar_free.json").write_text(
        json.dumps({"schema": 1, "detector": "mf"})
    )
    (repo / "scripts").mkdir()
    shutil.copy(ROOT / "scripts/check_cedar_free.py", repo / "scripts")
    shutil.copy(ROOT / "pifinder_update.sh", repo)
    shutil.copy(ROOT / "scripts/transactional_update.py", repo / "scripts")
    (repo / "scripts/prepare_code_update.sh").write_text(
        "set -e\ngit submodule update --init\nmkdir -p python/MFDS/build\n"
        "cp seed python/MFDS/build/artifact\n"
    )
    (repo / "scripts/ensure_tetra3_link.sh").write_text(":\n")
    (repo / "pifinder_paths.sh").write_text(":\n")
    (repo / "pifinder_post_update.sh").write_text("echo called > post-called\n")
    native = tmp_path / "native"
    native.mkdir()
    git(native, "init", "-b", "main")
    git(native, "config", "user.email", "test@example.invalid")
    git(native, "config", "user.name", "Test")
    (native / "source").write_text("native")
    (native / ".gitignore").write_text("build/\n")
    git(native, "add", ".")
    git(native, "commit", "-m", "native source")
    git(
        repo,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        str(native),
        "python/MFDS",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "Cedar-free candidate")
    return repo


def commit(repo):
    git(repo, "add", ".")
    git(repo, "commit", "-m", "change")


def test_candidate_requires_marker_and_pinned_detector(repository):
    assert checker.check_repo(repository) == []
    (repository / "deployment/cedar_free.json").unlink()
    commit(repository)
    assert checker.check_repo(repository)
    assert checker.check_repo(repository, "HEAD~1") == []


@pytest.mark.parametrize(
    "artifact",
    [
        "bin/cedar-detect-server-arm64",
        "python/cedar_detect_pb2.py",
        "pi_config_files/cedar_detect.service",
    ],
)
def test_reintroduced_artifact_rejected(repository, artifact):
    path = repository / artifact
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("old Cedar")
    commit(repository)
    assert artifact in checker.check_repo(repository)


def test_image_finds_units_symlinks_and_histories_without_following(tmp_path):
    image = tmp_path / "image"
    (image / "etc/systemd/system").mkdir(parents=True)
    (image / "usr").mkdir()
    assert checker.check_image(image) == []
    (image / "etc/systemd/system/custom.service").write_text(
        "ExecStart=/opt/cedar-detect-server\n"
    )
    (image / "etc/systemd/system/old.service").symlink_to(
        "/lib/systemd/system/cedar_detect.service"
    )
    (image / ".git").mkdir()
    (image / "host").symlink_to(tmp_path, target_is_directory=True)
    assert set(checker.check_image(image)) == {
        ".git",
        "etc/systemd/system/custom.service",
        "etc/systemd/system/old.service",
    }
    with pytest.raises(ValueError):
        checker.check_image(Path("/"))
    with pytest.raises(ValueError):
        checker.check_image(tmp_path / "missing")


@pytest.fixture
def update_clone(repository, tmp_path):
    clone = tmp_path / "installed"
    subprocess.run(
        ["git", "clone", str(repository), str(clone)], check=True, capture_output=True
    )
    git(clone, "-c", "protocol.file.allow=always", "submodule", "update", "--init")
    (clone / "python/MFDS/build").mkdir()
    (clone / "python/MFDS/build/artifact").write_text("original build")
    return clone


def run_update(repo):
    return subprocess.run(
        ["bash", str(repo / "pifinder_update.sh")],
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_ALLOW_PROTOCOL": "file"},
    )


def test_update_preserves_branch_and_fast_forwards(repository, update_clone):
    (repository / "new-version").write_text("reviewed")
    commit(repository)
    result = run_update(update_clone)
    assert result.returncode == 0, result.stderr
    assert git(update_clone, "branch", "--show-current") == "test/cedar-free"
    assert (update_clone / "new-version").read_text() == "reviewed"
    assert (update_clone / "post-called").exists()


def test_update_rejects_cedar_before_checkout_or_post_update(repository, update_clone):
    before = git(update_clone, "rev-parse", "HEAD")
    (repository / "cedar_detect_client.py").write_text("old code")
    commit(repository)
    assert run_update(update_clone).returncode != 0
    assert git(update_clone, "rev-parse", "HEAD") == before
    assert not (update_clone / "post-called").exists()


@pytest.mark.parametrize("state", ["dirty", "detached"])
def test_update_rejects_unsafe_checkout(update_clone, state):
    if state == "dirty":
        (update_clone / "seed").write_text("local changes")
    else:
        git(update_clone, "checkout", "--detach")
    assert run_update(update_clone).returncode != 0
    assert not (update_clone / "post-called").exists()


@pytest.mark.parametrize("phase", ["prepare", "activate"])
def test_failed_update_restores_source_and_native_build(
    repository, update_clone, phase
):
    before = git(update_clone, "rev-parse", "HEAD")
    native_before = git(update_clone / "python/MFDS", "rev-parse", "HEAD")
    native = repository / "python/MFDS"
    origin = Path(git(native, "remote", "get-url", "origin"))
    (origin / "source").write_text("next native source")
    commit(origin)
    git(native, "fetch", "origin")
    git(native, "checkout", "--detach", git(origin, "rev-parse", "HEAD"))
    (repository / "seed").write_text("candidate")
    hook = (
        "scripts/prepare_code_update.sh"
        if phase == "prepare"
        else "pifinder_post_update.sh"
    )
    with (repository / hook).open("a") as stream:
        stream.write("exit 17\n")
    commit(repository)
    result = run_update(update_clone)
    assert result.returncode != 0
    assert git(update_clone, "rev-parse", "HEAD") == before
    assert git(update_clone / "python/MFDS", "rev-parse", "HEAD") == native_before
    assert (update_clone / "python/MFDS/build/artifact").read_text() == "original build"
    assert not (update_clone / ".git/update-transaction").exists()


def test_dependency_change_is_rejected_before_mutation(repository, update_clone):
    before = git(update_clone, "rev-parse", "HEAD")
    (repository / "python/requirements.txt").write_text("new-dependency==1\n")
    commit(repository)
    result = run_update(update_clone)
    assert result.returncode != 0
    assert "separate staged installation" in result.stderr
    assert git(update_clone, "rev-parse", "HEAD") == before
    assert not (update_clone / "post-called").exists()


def test_interrupted_activation_keeps_journal_and_can_be_recovered(
    repository, update_clone
):
    before = git(update_clone, "rev-parse", "HEAD")
    (repository / "seed").write_text("candidate")
    (repository / "pifinder_post_update.sh").write_text('kill -KILL "$PPID"\n')
    commit(repository)
    assert run_update(update_clone).returncode != 0
    assert (update_clone / ".git/update-transaction/journal.json").exists()
    assert git(update_clone, "rev-parse", "HEAD") != before
    assert run_update(update_clone).returncode != 0
    result = subprocess.run(
        [
            "python3",
            str(update_clone / "scripts/transactional_update.py"),
            str(update_clone),
            "--recover",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert git(update_clone, "rev-parse", "HEAD") == before
    assert (update_clone / "python/MFDS/build/artifact").read_text() == "original build"
    assert not (update_clone / ".git/update-transaction").exists()


def test_mfds_path_migration_preserves_submodule_and_build(repository):
    spec = importlib.util.spec_from_file_location(
        "mfds_path", ROOT / "scripts/migrate_mfds_path.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    detector = repository / "python/MFDS"
    before = git(detector, "rev-parse", "HEAD")
    git(
        detector, "remote", "set-url", "origin", "https://github.com/hjoungjoo/MFDS.git"
    )
    (detector / "build").mkdir()
    (detector / "build/artifact").write_text("preserved")
    git(repository, "mv", "python/MFDS", "python/mf_detect_star")
    module.migrate(repository)
    module.migrate(repository)
    assert not (repository / "python/mf_detect_star").exists()
    assert git(detector, "rev-parse", "HEAD") == before
    assert (detector / "build/artifact").read_text() == "preserved"


def test_mfds_path_migration_rejects_conflicting_directories(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "mfds_path", ROOT / "scripts/migrate_mfds_path.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ("MFDS", "mf_detect_star"):
        path = tmp_path / "python" / name
        path.mkdir(parents=True)
        (path / "keep").write_text(name)
    with pytest.raises(RuntimeError, match="Both detector directories"):
        module.migrate(tmp_path)
    for name in ("MFDS", "mf_detect_star"):
        assert (tmp_path / "python" / name / "keep").read_text() == name
