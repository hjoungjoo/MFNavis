"""The application must consume the pinned detector instead of source copies."""

import json
from pathlib import Path

import pytest

from PiFinder import star_detect

pytestmark = pytest.mark.unit


def test_all_integration_paths_resolve_to_the_release_package():
    root = Path(__file__).resolve().parents[2]
    submodule = root / "python/MFDS"
    manifest = json.loads((submodule / "integrations/pifinder/SOURCE.json").read_text())
    for entry in manifest["files"]:
        source = root / entry["from"]
        assert source.is_symlink()
        assert source.samefile(submodule / entry["to"])
    assert (root / "docs/test_cedar_free_20260915").samefile(
        submodule / "docs/test_cedar_free_20260915"
    )


def test_native_default_is_from_the_same_source_tree(monkeypatch):
    monkeypatch.delenv("MF_DETECT_LIBRARY", raising=False)
    root = Path(__file__).resolve().parents[1]
    assert (
        star_detect.native_library_path()
        == (root / "MFDS/build/libmf_detect_star.so").resolve()
    )
    monkeypatch.setenv("MF_DETECT_LIBRARY", "/tmp/explicit-mfds.so")
    assert star_detect.native_library_path() == Path("/tmp/explicit-mfds.so")


def test_distribution_is_pinned_without_a_source_checkout():
    root = Path(__file__).resolve().parents[2]
    lock = json.loads((root / "deployment/mfds.lock.json").read_text())
    manifest = json.loads((root / "python/MFDS/PACKAGE.json").read_text())
    assert manifest["version"] == lock["version"]
    assert manifest["source_commit"] == lock["source_commit"]
    assert not (root / "python/MFDS/.git").exists()
    assert not (root / "python/MFDS/src").exists()
    assert not (root / "python/MFDS/Makefile").exists()
