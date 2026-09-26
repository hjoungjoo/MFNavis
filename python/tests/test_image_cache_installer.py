"""Cache warm-up must leave complete images and report failed downloads."""

from io import BytesIO
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from PIL import Image
import pytest

from PiFinder import audit_images, gen_images, get_images


REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def cache_warmup():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "warm_mfnavis_caches", REPO / "scripts/warm_mfnavis_caches.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cache_warmup_refuses_root_owned_output(cache_warmup, monkeypatch, capsys):
    module = cache_warmup
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(sys, "argv", ["warm_mfnavis_caches", "--images", "none"])
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2
    assert "without sudo" in capsys.readouterr().err


def test_cache_warmup_selects_installed_venv(cache_warmup, tmp_path, monkeypatch):
    runtime = tmp_path / ".venv-trixie" / "bin" / "python"
    runtime.parent.mkdir(parents=True)
    runtime.symlink_to(sys.executable)
    monkeypatch.setattr(cache_warmup, "REPO_ROOT", tmp_path)
    monkeypatch.delenv("MFNAVIS_PYTHON", raising=False)
    monkeypatch.setattr(sys, "prefix", sys.base_prefix)
    args = ["warm_mfnavis_caches.py", "--images", "poss", "--workers", "4"]
    monkeypatch.setattr(sys, "argv", args)
    launches = []
    monkeypatch.setattr(cache_warmup.os, "execv", lambda *args: launches.append(args))
    cache_warmup._ensure_runtime_python()
    assert launches == [
        (str(runtime), [str(runtime), cache_warmup.__file__, *args[1:]])
    ]


def test_cache_warmup_honors_explicit_python(cache_warmup, monkeypatch):
    # An explicit runtime also takes precedence over an active virtualenv.
    monkeypatch.setenv("MFNAVIS_PYTHON", sys.executable)
    launches = []
    monkeypatch.setattr(cache_warmup.os, "execv", lambda *args: launches.append(args))
    monkeypatch.setattr(sys, "executable", "/different/venv/bin/python")
    monkeypatch.setattr(sys, "argv", ["warm_pifinder_caches.py", "--images", "none"])
    cache_warmup._ensure_runtime_python()
    assert launches[0][1][1:] == [cache_warmup.__file__, "--images", "none"]


@pytest.mark.parametrize("installed", [True, False])
def test_cache_warmup_does_not_reexec_active_venv(
    cache_warmup, tmp_path, monkeypatch, installed
):
    monkeypatch.setattr(cache_warmup, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sys, "prefix", str(tmp_path / ".venv-trixie"))
    monkeypatch.setattr(sys, "base_prefix", "/usr")
    monkeypatch.delenv("MFNAVIS_PYTHON", raising=False)
    if installed:
        runtime = tmp_path / ".venv-trixie" / "bin" / "python"
        runtime.parent.mkdir(parents=True)
        runtime.symlink_to(sys.executable)
    monkeypatch.setattr(
        cache_warmup.os, "execv", lambda *_: pytest.fail("unexpected re-exec")
    )
    cache_warmup._ensure_runtime_python()


def test_cache_warmup_falls_back_on_bookworm(cache_warmup, tmp_path, monkeypatch):
    monkeypatch.setattr(cache_warmup, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sys, "prefix", sys.base_prefix)
    monkeypatch.delenv("MFNAVIS_PYTHON", raising=False)
    monkeypatch.setattr(
        cache_warmup.os, "execv", lambda *_: pytest.fail("unexpected re-exec")
    )
    cache_warmup._ensure_runtime_python()


def test_cache_warmup_rejects_invalid_python(cache_warmup, tmp_path, monkeypatch):
    monkeypatch.setenv("MFNAVIS_PYTHON", str(tmp_path / "missing-python"))
    with pytest.raises(RuntimeError, match="MFNAVIS_PYTHON is not executable"):
        cache_warmup._ensure_runtime_python()


def test_image_save_is_atomic_and_cleans_failed_temporary_file(tmp_path, monkeypatch):
    path = tmp_path / "catalog_images" / "1" / "NGC1_POSS.jpg"
    image = Image.new("L", (8, 8), 128)
    gen_images.save_image_atomically(image, str(path))
    original = path.read_bytes()
    with Image.open(path) as saved:
        assert saved.format == "JPEG"

    def fail_after_partial_write(self, filename, **_kwargs):
        Path(filename).write_bytes(b"partial")
        raise OSError("disk full")

    monkeypatch.setattr(Image.Image, "save", fail_after_partial_write)
    with pytest.raises(OSError, match="disk full"):
        gen_images.save_image_atomically(image, str(path))
    assert path.read_bytes() == original
    assert not list(path.parent.glob(".mfnavis-image-*"))


def test_zero_byte_image_is_refetched(tmp_path, monkeypatch):
    monkeypatch.setattr(gen_images, "BASE_IMAGE_PATH", str(tmp_path))
    path = Path(gen_images.resolve_image_path("NGC1", "POSS"))
    path.parent.mkdir()
    path.write_bytes(b"")
    calls = []
    monkeypatch.setattr(
        gen_images,
        "fetch_poss",
        lambda *args: calls.append(args) or (True, ""),
    )
    _name, results = gen_images.fetch_object(None, 1.0, 2.0, "NGC1", True, False, False)
    assert calls
    assert results["POSS"] == (True, "")


def test_failed_download_returns_nonzero(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gen_images, "BASE_IMAGE_PATH", str(tmp_path))
    monkeypatch.setattr(
        gen_images, "get_objects_to_fetch", lambda: [(1.0, 2.0, "NGC1")]
    )
    monkeypatch.setattr(
        gen_images,
        "fetch_object",
        lambda *_args: ("NGC1", {"POSS": (False, "HTTP 503")}),
    )
    monkeypatch.setattr(sys, "argv", ["gen_images", "--poss", "--workers", "1"])
    assert gen_images.main() == 1
    assert "NGC1_POSS" in capsys.readouterr().out


def test_sdss_outside_survey_is_not_a_transient_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gen_images, "BASE_IMAGE_PATH", str(tmp_path))
    monkeypatch.setattr(
        gen_images, "get_objects_to_fetch", lambda: [(1.0, 2.0, "NGC1")]
    )
    monkeypatch.setattr(
        gen_images,
        "fetch_object",
        lambda *_args: ("NGC1", {"SDSS": (False, "out of range")}),
    )
    monkeypatch.setattr(sys, "argv", ["gen_images", "--sdss", "--workers", "1"])
    assert gen_images.main() == 0
    assert "1 unavailable, 0 failed" in capsys.readouterr().out


def test_legacy_downloader_rejects_non_jpeg(tmp_path):
    class Session:
        def get(self, *_args, **_kwargs):
            return type("Response", (), {"status_code": 200, "content": b"not jpeg"})()

    path = tmp_path / "NGC1_POSS.jpg"
    success, error = get_images.download_image_from_url(Session(), "url", str(path))
    assert not success
    assert error
    assert not path.exists()


def test_legacy_downloader_preserves_existing_image_on_replace_failure(
    tmp_path, monkeypatch
):
    image_bytes = BytesIO()
    Image.new("L", (8, 8), 128).save(image_bytes, format="JPEG")

    class Session:
        def get(self, *_args, **_kwargs):
            return type(
                "Response", (), {"status_code": 200, "content": image_bytes.getvalue()}
            )()

    path = tmp_path / "NGC1_POSS.jpg"
    path.write_bytes(b"existing")

    def fail_replace(*_args):
        raise OSError("replace failed")

    monkeypatch.setattr(get_images.os, "replace", fail_replace)
    success, error = get_images.download_image_from_url(Session(), "url", str(path))
    assert not success and "replace failed" in error
    assert path.read_bytes() == b"existing"
    assert not list(tmp_path.glob(".mfnavis-image-*"))


def test_legacy_downloader_fetches_only_missing_source(tmp_path, monkeypatch):
    monkeypatch.setattr(get_images.cat_images, "BASE_IMAGE_PATH", str(tmp_path))
    poss_path = tmp_path / "1" / "NGC1_POSS.jpg"
    poss_path.parent.mkdir()
    poss_path.write_bytes(b"existing")
    calls = []
    monkeypatch.setattr(
        get_images,
        "download_image_from_url",
        lambda _session, url, _path: calls.append(url) or (True, ""),
    )
    _name, success, errors = get_images.fetch_images_for_object(None, "NGC1")
    assert success and not errors
    assert len(calls) == 1 and "SDSS.jpg" in calls[0]


def test_image_audit_reads_current_database_schema(tmp_path, monkeypatch):
    database = tmp_path / "catalog.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE object_images (image_name TEXT)")
        connection.executemany(
            "INSERT INTO object_images VALUES (?)", [("NGC1",), ("NGC1",), ("M31",)]
        )
    monkeypatch.setattr(audit_images.utils, "pifinder_db", database)
    assert audit_images.get_image_names() == ["NGC1", "M31"]


def test_indi_source_installer_rejects_bad_jobs_before_apt(tmp_path):
    result = subprocess.run(
        ["bash", str(REPO / "scripts/install_indi_mount_OnstepX.sh")],
        env={"PATH": "/usr/bin:/bin", "JOBS": "0", "BUILD_ROOT": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "JOBS must be a positive integer" in result.stderr


def test_indi_source_installer_rejects_dirty_upstream_checkout(tmp_path):
    checkout = tmp_path / "indi"
    checkout.mkdir()
    subprocess.run(["git", "init", "-q", str(checkout)], check=True)
    (checkout / "file.txt").write_text("original\n")
    subprocess.run(["git", "-C", str(checkout), "add", "file.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "base",
        ],
        check=True,
    )
    subprocess.run(["git", "-C", str(checkout), "tag", "v2.2.3.1"], check=True)
    (checkout / "file.txt").write_text("patched\n")
    result = subprocess.run(
        ["bash", str(REPO / "scripts/install_indi_mount_OnstepX.sh")],
        env={
            "PATH": "/usr/bin:/bin",
            "BUILD_ROOT": str(tmp_path),
            "INDI_PATCH_DIR": "none",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "unmodified INDI checkout" in result.stderr


def test_indi_source_installer_accepts_clean_git_worktree(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    (source / "file.txt").write_text("original\n")
    subprocess.run(["git", "-C", str(source), "add", "file.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "base",
        ],
        check=True,
    )
    subprocess.run(["git", "-C", str(source), "tag", "v2.2.3.1"], check=True)
    build_root = tmp_path / "build"
    build_root.mkdir()
    checkout = build_root / "indi"
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "worktree",
            "add",
            "--quiet",
            "--detach",
            str(checkout),
            "v2.2.3.1",
        ],
        check=True,
    )
    assert (checkout / ".git").is_file()

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_sudo = fake_bin / "sudo"
    fake_sudo.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$MF_INSTALL_MARKER"\nexit 42\n'
    )
    fake_sudo.chmod(0o755)
    marker = tmp_path / "sudo_calls"
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "BUILD_ROOT": str(build_root),
            "INDI_PATCH_DIR": "none",
            "MF_INSTALL_MARKER": str(marker),
        }
    )
    result = subprocess.run(
        ["bash", str(REPO / "scripts/install_indi_mount_OnstepX.sh")],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 42
    assert marker.read_text().splitlines() == ["apt update"]
