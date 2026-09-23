"""Commercial package gates must reject ordinary and contaminated artifacts."""

import importlib.util
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[2] / "scripts/install_mfds.py"
spec = importlib.util.spec_from_file_location("commercial_installer", path)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
pytestmark = pytest.mark.unit


def test_existing_development_lock_rejected_for_sales():
    with pytest.raises(ValueError, match="commercial-process-only"):
        installer.load_lock(path.parent.parent / "deployment/mfds.lock.json", True)


@pytest.mark.parametrize(
    "manifest",
    [
        {"profile": "development", "source_dirty": False},
        {"profile": "commercial-process-only", "source_dirty": True},
        {"profile": "commercial-process-only"},
    ],
)
def test_profile_and_clean_source_required(tmp_path, manifest):
    with pytest.raises(ValueError):
        installer.verify_commercial(tmp_path, manifest)


def test_extra_payload_rejected(tmp_path):
    (tmp_path / "evil.so").write_bytes(b"native")
    with pytest.raises(ValueError, match="Native library"):
        installer.verify_commercial(
            tmp_path,
            {
                "profile": "commercial-process-only",
                "source_dirty": False,
                "files": {},
            },
        )


def test_sales_marker_forces_commercial_lock(monkeypatch, tmp_path):
    marker = tmp_path / "mfnavis-commercial"
    marker.touch()
    monkeypatch.setattr(installer, "COMMERCIAL_MARKER", marker)
    calls = []

    def check_lock(path, require_commercial=False):
        calls.append((path, require_commercial))
        raise ValueError("stop before install")

    monkeypatch.setattr(installer, "load_lock", check_lock)
    with pytest.raises(ValueError, match="stop before install"):
        installer.install(tmp_path)
    assert calls == [(tmp_path / "deployment/mfds-commercial.lock.json", True)]
