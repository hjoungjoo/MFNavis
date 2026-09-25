"""INDI archives must be checked before their contents can overlay /usr."""

import hashlib
import io
from pathlib import Path
import subprocess
import sys
import tarfile


VERIFY = Path(__file__).resolve().parents[2] / "scripts/verify_indi_archive.py"


def run_verifier(tmp_path, extra=(), checksum_valid=True):
    archive = tmp_path / "indi.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        for name, kind, content in (
            ("rootfs", "dir", ""),
            ("rootfs/usr", "dir", ""),
            ("metadata", "dir", ""),
            ("metadata/build_info.txt", "file", "test"),
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
