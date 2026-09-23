"""Exercise import alias repair only in disposable repositories."""

from pathlib import Path
import subprocess

import pytest

pytestmark = pytest.mark.unit
SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ensure_tetra3_link.sh"
TARGET = "PiFinder/tetra3/tetra3"


@pytest.fixture
def repo(tmp_path):
    # Include whitespace so path handling is exercised as well.
    root = tmp_path / "MFNavis test"
    (root / "python" / TARGET).mkdir(parents=True)
    return root


def ensure_link(repo):
    return subprocess.run(
        ["bash", str(SCRIPT), str(repo)], capture_output=True, text=True, check=False
    )


def test_create_relative_alias_and_repeat_without_changes(repo):
    alias = repo / "python/tetra3"
    assert ensure_link(repo).returncode == 0
    assert str(alias.readlink()) == TARGET
    inode = alias.lstat().st_ino
    assert ensure_link(repo).returncode == 0
    assert alias.lstat().st_ino == inode
    assert list((repo / "python").glob("tetra3.backup.*")) == []


@pytest.mark.parametrize("kind", ("absolute", "dangling", "directory", "file"))
def test_nonstandard_path_is_preserved_not_deleted(repo, kind):
    alias = repo / "python/tetra3"
    if kind == "absolute":
        alias.symlink_to(repo / "python" / TARGET)
    elif kind == "dangling":
        alias.symlink_to("missing-user-path")
    elif kind == "directory":
        alias.mkdir()
        (alias / "user-data").write_text("keep this")
    else:
        alias.write_text("keep this")
    assert ensure_link(repo).returncode == 0
    assert str(alias.readlink()) == TARGET
    backups = [
        directory / "original"
        for directory in (repo / "python").glob("tetra3.backup.*")
    ]
    assert len(backups) == 1
    saved = backups[0]
    if kind in ("absolute", "dangling"):
        assert saved.is_symlink()
        expected = (
            str(repo / "python" / TARGET) if kind == "absolute" else "missing-user-path"
        )
        assert str(saved.readlink()) == expected
    else:
        assert (
            saved / "user-data" if kind == "directory" else saved
        ).read_text() == "keep this"


def test_missing_submodule_leaves_existing_alias_untouched(repo):
    alias = repo / "python/tetra3"
    alias.symlink_to("missing-user-path")
    (repo / "python" / TARGET).rmdir()
    result = ensure_link(repo)
    assert result.returncode != 0
    assert "not initialized" in result.stderr
    assert str(alias.readlink()) == "missing-user-path"
    assert list((repo / "python").glob("tetra3.backup.*")) == []
