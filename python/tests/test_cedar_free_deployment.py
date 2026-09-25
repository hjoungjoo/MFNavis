import importlib.util
import hashlib
import io
import platform
import tarfile
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


def write_package(repo, directory, version="0.3.0", artifact="original build"):
    files = {
        "VERSION": (version + "\n").encode(),
        "build/mf_detect_star_server": f"#!/bin/sh\necho MFDS {version}\n".encode(),
        "build/artifact": artifact.encode(),
    }
    manifest = {
        "schema": 1,
        "version": version,
        "source_commit": "a" * 40,
        "platform": f"linux-{platform.machine()}",
        "abi": 1,
        "files": {n: hashlib.sha256(v).hexdigest() for n, v in files.items()},
    }
    files["PACKAGE.json"] = json.dumps(manifest).encode()
    archive = directory / f"package-{version}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo("MFDS/" + name)
            info.size = len(data)
            info.mode = 0o755 if name.startswith("build/") else 0o644
            tar.addfile(info, io.BytesIO(data))
    lock = {
        "schema": 1,
        "version": version,
        "source_commit": "a" * 40,
        "assets": {
            f"linux-{arch}": {
                "url": f"https://github.com/hjoungjoo/MFDS/releases/download/v{version}/MFDS-{version}-linux-{arch}.tar.gz",
                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "manifest_sha256": hashlib.sha256(files["PACKAGE.json"]).hexdigest(),
            }
            for arch in ("aarch64", "x86_64")
        },
    }
    (repo / "deployment/mfds.lock.json").write_text(json.dumps(lock))
    (repo / "scripts/prepare_code_update.sh").write_text(
        f'#!/bin/sh\nset -e\npython3 scripts/install_mfds.py --repo . --archive "{archive}"\n'
    )
    return archive


@pytest.fixture
def repository(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "test/binary-release")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    (repo / "seed").write_text("seed")
    (repo / ".gitignore").write_text("python/MFDS\npython/.mfds/\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "seed")
    (repo / "python").mkdir()
    (repo / "deployment").mkdir()
    (repo / "deployment/cedar_free.json").write_text(
        json.dumps({"schema": 1, "detector": "mf"})
    )
    (repo / "scripts").mkdir()
    for name in ("check_cedar_free.py", "transactional_update.py", "install_mfds.py"):
        shutil.copy(ROOT / "scripts" / name, repo / "scripts")
    shutil.copy(ROOT / "mfnavis_update.sh", repo)
    (repo / "scripts/ensure_tetra3_link.sh").write_text(":\n")
    (repo / "mfnavis_paths.sh").write_text(":\n")
    (repo / "mfnavis_post_update.sh").write_text(
        'printf "%s:%s" "$MFNAVIS_CODE_UPDATE" "$MFNAVIS_REPO_DIR" > post-called\n'
    )
    write_package(repo, tmp_path)
    git(repo, "add", ".")
    git(repo, "commit", "-m", "Binary release candidate")
    return repo


def commit(repo):
    git(repo, "add", ".")
    git(repo, "commit", "-m", "change")


def test_candidate_requires_marker_and_pinned_binary(repository):
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
    subprocess.run(["bash", "scripts/prepare_code_update.sh"], cwd=clone, check=True)
    return clone


def run_update(repo):
    return subprocess.run(
        ["bash", str(repo / "mfnavis_update.sh")],
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_ALLOW_PROTOCOL": "file"},
    )


def test_update_preserves_branch_and_fast_forwards(repository, update_clone):
    (repository / "new-version").write_text("reviewed")
    commit(repository)
    result = run_update(update_clone)
    assert result.returncode == 0, result.stderr
    assert git(update_clone, "branch", "--show-current") == "test/binary-release"
    assert (update_clone / "new-version").read_text() == "reviewed"
    assert (update_clone / "post-called").read_text() == f"1:{update_clone}"


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
    native_before = (update_clone / "python/MFDS").resolve()
    write_package(repository, repository.parent, "0.3.1", "candidate")
    (repository / "seed").write_text("candidate")
    hook = (
        "scripts/prepare_code_update.sh"
        if phase == "prepare"
        else "mfnavis_post_update.sh"
    )
    with (repository / hook).open("a") as stream:
        stream.write("exit 17\n")
    commit(repository)
    result = run_update(update_clone)
    assert result.returncode != 0
    assert git(update_clone, "rev-parse", "HEAD") == before
    assert (update_clone / "python/MFDS").resolve() == native_before
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
    (repository / "mfnavis_post_update.sh").write_text('kill -KILL "$PPID"\n')
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


def installer_module():
    spec = importlib.util.spec_from_file_location(
        "mfds_installer", ROOT / "scripts/install_mfds.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bad_archive_never_changes_active_package(repository):
    installer = installer_module()
    original = repository.parent / "package-0.3.0.tar.gz"
    installer.install(repository, original)
    before = (repository / "python/MFDS").resolve()
    candidate = write_package(repository, repository.parent, "0.3.1", "candidate")
    candidate.write_bytes(candidate.read_bytes() + b"corruption")
    with pytest.raises(ValueError, match="SHA-256"):
        installer.install(repository, candidate)
    assert (repository / "python/MFDS").resolve() == before
    assert (before / "build/artifact").read_text() == "original build"


def test_download_failure_never_changes_active_package(repository, monkeypatch):
    installer = installer_module()
    installer.install(repository, repository.parent / "package-0.3.0.tar.gz")
    before = (repository / "python/MFDS").resolve()
    write_package(repository, repository.parent, "0.3.1", "candidate")

    def fail(*args, **kwargs):
        raise OSError("network unavailable")

    monkeypatch.setattr(installer.urllib.request, "urlopen", fail)
    with pytest.raises(OSError, match="network unavailable"):
        installer.install(repository)
    assert (repository / "python/MFDS").resolve() == before


def test_cached_package_modification_is_detected(repository):
    installer = installer_module()
    installer.install(repository, repository.parent / "package-0.3.0.tar.gz")
    (repository / "python/MFDS/build/artifact").write_text("modified locally")
    with pytest.raises(ValueError, match="file mismatch"):
        installer.install(repository)


def test_wrong_architecture_rejected_before_execution(repository):
    installer = installer_module()
    target = installer.extract(
        repository.parent / "package-0.3.0.tar.gz", repository.parent / "unpacked"
    )
    lock = installer.load_lock(repository / "deployment/mfds.lock.json")
    platform_key = (
        "linux-x86_64" if platform.machine() == "aarch64" else "linux-aarch64"
    )
    with pytest.raises(ValueError, match="platform differs"):
        installer.verify_package(target, lock, platform_key)


@pytest.mark.parametrize("attack", ["traversal", "symlink", "duplicate"])
def test_unsafe_archive_is_rejected_without_writing(tmp_path, attack):
    installer = installer_module()
    archive = tmp_path / "unsafe.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo(
            "MFDS/../../escape" if attack == "traversal" else "MFDS/file"
        )
        if attack == "symlink":
            info.type = tarfile.SYMTYPE
            info.linkname = "/tmp/escape"
        tar.addfile(info)
        if attack == "duplicate":
            tar.addfile(info)
    with pytest.raises(ValueError, match="Unsafe/duplicate"):
        installer.extract(archive, tmp_path / "destination")
    assert not (tmp_path / "destination").exists()


def test_source_checkout_is_not_silently_overwritten(repository):
    detector = repository / "python/MFDS"
    detector.mkdir(parents=True)
    (detector / "local-edit").write_text("keep")
    with pytest.raises(RuntimeError, match="source checkout remains"):
        installer_module().install(
            repository, repository.parent / "package-0.3.0.tar.gz"
        )
    assert (detector / "local-edit").read_text() == "keep"
