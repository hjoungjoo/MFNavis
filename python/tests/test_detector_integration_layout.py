"""The application must consume the pinned detector instead of source copies."""

import json
from pathlib import Path

import pytest

from PiFinder import star_detect

pytestmark = pytest.mark.unit


def test_all_integration_paths_resolve_to_the_submodule():
    root = Path(__file__).resolve().parents[2]
    submodule = root / "python/mf_detect_star"
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
        == root / "mf_detect_star/build/libmf_detect_star.so"
    )
    monkeypatch.setenv("MF_DETECT_LIBRARY", "/tmp/explicit-mfds.so")
    assert star_detect.native_library_path() == Path("/tmp/explicit-mfds.so")


def test_submodule_uses_a_portable_remote():
    import configparser

    root = Path(__file__).resolve().parents[2]
    config = configparser.ConfigParser()
    config.read(root / ".gitmodules")
    assert config['submodule "mf_detect_star"']["url"] == (
        "https://github.com/hjoungjoo/MFDS.git"
    )
    assert config['submodule "mf_detect_star"']["path"] == "python/mf_detect_star"
