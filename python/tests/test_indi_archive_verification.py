"""INDI archives must be checked before their contents can overlay /usr."""

import hashlib
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tarfile


VERIFY = Path(__file__).resolve().parents[2] / "scripts/verify_indi_archive.py"


def run_verifier(tmp_path, extra=(), checksum_valid=True, build_info="test"):
    archive = tmp_path / "indi.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        for name, kind, content in (
            ("rootfs", "dir", ""),
            ("rootfs/usr", "dir", ""),
            ("metadata", "dir", ""),
            ("metadata/build_info.txt", "file", build_info),
            *extra,
        ):
            member = tarfile.TarInfo(name)
            if kind == "dir":
                member.type = tarfile.DIRTYPE
                output.addfile(member)
            elif kind == "symlink":
                member.type = tarfile.SYMTYPE
                member.linkname = content
                output.addfile(member)
            else:
                data = content.encode()
                member.size = len(data)
                output.addfile(member, io.BytesIO(data))
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    if not checksum_valid:
        checksum = "0" * 64
    sidecar = tmp_path / "indi.tar.gz.sha256"
    sidecar.write_text(f"{checksum}  indi.tar.gz\n")
    return subprocess.run(
        [sys.executable, str(VERIFY), str(archive), str(sidecar)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_valid_indi_archive(tmp_path):
    result = run_verifier(tmp_path, (("rootfs/usr/bin/indiserver", "file", "data"),))
    assert result.returncode == 0, result.stderr


def test_checksum_mismatch_is_rejected(tmp_path):
    result = run_verifier(tmp_path, checksum_valid=False)
    assert result.returncode != 0
    assert "checksum mismatch" in result.stderr


def test_path_outside_usr_is_rejected(tmp_path):
    result = run_verifier(tmp_path, (("rootfs/etc/passwd", "file", "data"),))
    assert result.returncode != 0
    assert "unexpected archive path" in result.stderr


def test_symlink_escape_is_rejected(tmp_path):
    result = run_verifier(tmp_path, (("rootfs/usr/lib/test", "symlink", "../../etc"),))
    assert result.returncode != 0
    assert "unsafe archive symlink" in result.stderr


def test_member_below_symlink_is_rejected(tmp_path):
    result = run_verifier(
        tmp_path,
        (
            ("rootfs/usr/lib", "symlink", "bin"),
            ("rootfs/usr/lib/test", "file", "data"),
        ),
    )
    assert result.returncode != 0
    assert "nested below a symlink" in result.stderr


def test_missing_symlink_target_is_rejected(tmp_path):
    result = run_verifier(tmp_path, (("rootfs/usr/bin/driver", "symlink", "missing"),))
    assert result.returncode != 0
    assert "symlink target is missing" in result.stderr


V2_INFO = {
    "archive_format": "mfnavis-indi-binary-v2",
    "os_codename": "trixie",
    "machine": "aarch64",
    "python_version": "3.13",
    "python_soabi": "cpython-313-aarch64-linux-gnu",
    "python_payload": "wheels",
}
V2_TEXT = "\n".join(f"{key}={value}" for key, value in V2_INFO.items())
V2_PAYLOAD = (
    ("wheels", "dir", ""),
    ("wheels/pyindi_client-2.1.2-cp313-cp313-linux_aarch64.whl", "file", "wheel"),
    ("wheels/indiweb-1.0.0-py3-none-any.whl", "file", "wheel"),
    ("metadata/runtime-packages.txt", "file", "libev4t64\n"),
    (
        "metadata/python-requirements.txt",
        "file",
        "pyindi-client==2.1.2\nindiweb==1.0.0\n",
    ),
)


def test_valid_v2_archive(tmp_path):
    result = run_verifier(tmp_path, V2_PAYLOAD, build_info=V2_TEXT)
    assert result.returncode == 0, result.stderr


def test_v2_archive_missing_wheel_is_rejected(tmp_path):
    result = run_verifier(tmp_path, V2_PAYLOAD[:2] + V2_PAYLOAD[3:], build_info=V2_TEXT)
    assert result.returncode != 0
    assert "missing INDI Web Manager wheel" in result.stderr


def test_v2_wheel_symlink_is_rejected(tmp_path):
    payload = (
        *V2_PAYLOAD,
        ("wheels/other.whl", "symlink", V2_PAYLOAD[1][0].split("/")[1]),
    )
    result = run_verifier(tmp_path, payload, build_info=V2_TEXT)
    assert result.returncode != 0
    assert "invalid wheel member" in result.stderr


def test_v2_dependency_options_are_rejected(tmp_path):
    payload = V2_PAYLOAD[:-1] + (
        ("metadata/python-requirements.txt", "file", "--index-url https://invalid\n"),
    )
    result = run_verifier(tmp_path, payload, build_info=V2_TEXT)
    assert result.returncode != 0
    assert "invalid dependency list" in result.stderr


def verification_module():
    spec = importlib.util.spec_from_file_location("verify_indi_archive", VERIFY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v2_host_abi_matches():
    verification_module().verify_platform(
        V2_INFO, "trixie", "aarch64", "3.13", "cpython-313-aarch64-linux-gnu"
    )


def test_v2_host_abi_mismatch_is_rejected():
    import pytest

    with pytest.raises(ValueError, match="platform mismatch"):
        verification_module().verify_platform(
            V2_INFO, "trixie", "aarch64", "3.13", "cpython-313t-aarch64-linux-gnu"
        )


def test_renaming_bookworm_archive_cannot_bypass_host_check():
    import pytest

    info = {"archive_format": "mf-pifinder-indi-binary-v1", "machine": "aarch64"}
    with pytest.raises(ValueError, match="Bookworm archive requires"):
        verification_module().verify_platform(
            info, "trixie", "aarch64", "3.13", "cpython-313-aarch64-linux-gnu"
        )
