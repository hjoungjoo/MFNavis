import hashlib
from PiFinder.runtime_provenance import file_identity, detector_provenance
import pytest

pytestmark = pytest.mark.unit


def test_file_identity_tracks_actual_bytes_and_missing_files(tmp_path):
    binary = tmp_path / "server"
    binary.write_bytes(b"build one")
    assert file_identity(binary)["sha256"] == hashlib.sha256(b"build one").hexdigest()
    binary.write_bytes(b"build two")
    assert file_identity(binary)["sha256"] == hashlib.sha256(b"build two").hexdigest()
    binary.unlink()
    assert file_identity(binary)["error"] == "FileNotFoundError"


def test_capture_identity_includes_native_revision_and_dependencies():
    provenance = detector_provenance()
    assert len(provenance["mf_git_head"]) == 40
    assert len(provenance["configured_server"]["sha256"]) == 64
    assert provenance["dependency_versions"]["numpy"]
    assert provenance["dependency_versions"]["scipy"]
