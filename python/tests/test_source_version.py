"""Settings provenance, including installations without a Git checkout."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from PiFinder import config, source_version

pytestmark = pytest.mark.unit


def test_archive_and_missing_version(tmp_path):
    assert source_version._read_source_version(tmp_path) == {
        "version": "unknown",
        "git_commit": None,
        "git_dirty": None,
    }
    (tmp_path / "version.txt").write_text("m3.0.2\n")
    source_version._read_source_version.cache_clear()
    assert source_version._read_source_version(tmp_path) == {
        "version": "m3.0.2",
        "git_commit": None,
        "git_dirty": None,
    }


@pytest.mark.parametrize("dirty", [False, True])
def test_git_identity_is_cached(tmp_path, monkeypatch, dirty):
    (tmp_path / ".git").mkdir()
    (tmp_path / "version.txt").write_text("m3.0.2\n")
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        assert kwargs["timeout"] == 3
        return SimpleNamespace(
            stdout=(
                "a" * 40 if "rev-parse" in args else " M config.py\n" if dirty else ""
            )
        )

    monkeypatch.setattr(source_version.subprocess, "run", run)
    first = source_version._read_source_version(tmp_path)
    assert first == {"version": "m3.0.2", "git_commit": "a" * 40, "git_dirty": dirty}
    assert source_version._read_source_version(tmp_path) == first
    assert len(calls) == 2


def test_git_failure_keeps_release_version(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    (tmp_path / "version.txt").write_text("m3.0.2")

    def unavailable(*args, **kwargs):
        raise subprocess.TimeoutExpired("git", 3)

    monkeypatch.setattr(source_version.subprocess, "run", unavailable)
    assert source_version._read_source_version(tmp_path) == {
        "version": "m3.0.2",
        "git_commit": None,
        "git_dirty": None,
    }


def test_startup_migrates_version_once_and_preserves_concurrent_settings(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(config.utils, "data_dir", tmp_path)
    monkeypatch.setattr(config.utils, "runtime_dir", tmp_path / "runtime")
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"camera_exp": 1234, "source_version": {"version": "old"}})
    )
    cfg = config.Config()
    current = {"version": "m3.0.2", "git_commit": "a" * 40, "git_dirty": False}
    monkeypatch.setattr(config, "get_source_version", lambda: dict(current))
    path.write_text(json.dumps({"camera_exp": 4321, "language": "ko"}))
    cfg.ensure_source_version()
    assert json.loads(path.read_text()) == {
        "camera_exp": 4321,
        "language": "ko",
        "source_version": current,
    }
    stamp = path.stat().st_mtime_ns
    cfg.ensure_source_version()
    assert path.stat().st_mtime_ns == stamp
    cfg.set_option("source_version", {"version": "wrong"})
    assert json.loads(path.read_text())["source_version"] == current
