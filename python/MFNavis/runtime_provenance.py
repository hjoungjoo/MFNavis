"""Bounded, read-only identities for reproducible capture manifests."""

import hashlib
import importlib.metadata
import os
import json
from pathlib import Path
import subprocess


def file_identity(path):
    path = Path(path)
    result = {"path": str(path)}
    try:
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            if before.st_size > 128 * 1024**2:
                return {**result, "error": "file exceeds identity size limit"}
            digest = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
            after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            return {**result, "error": "file changed during hashing"}
        result.update(sha256=digest.hexdigest(), bytes=before.st_size)
    except OSError as exc:
        result["error"] = type(exc).__name__
    return result


def detector_provenance():
    from PiFinder import mf_detect_process, star_detect

    root = Path(star_detect.__file__).resolve().parents[3]
    package = {}
    try:
        package = json.loads((root / "PACKAGE.json").read_text())
        revision = package["source_commit"]
    except (OSError, ValueError, KeyError):
        # Development in the canonical MFDS checkout remains supported.
        try:
            revision = subprocess.check_output(
                ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=3,
            ).strip()
            revision = (
                subprocess.check_output(
                    ["git", "-C", str(root), "rev-parse", "HEAD"],
                    text=True,
                    stderr=subprocess.DEVNULL,
                    timeout=3,
                ).strip()
                if Path(revision).resolve() == root
                else None
            )
        except (OSError, subprocess.SubprocessError):
            revision = None
    try:
        source_version = (root / "VERSION").read_text().strip()
    except OSError:
        source_version = None
    versions = {}
    for name in ("numpy", "scipy", "sep", "Pillow", "tetra3"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    # Called once in the capture writer, never per solver frame. Hash /proc/exe
    # to identify a running binary even if its pathname was replaced on disk.
    workers = []
    try:
        active = list(mf_detect_process._workers)
    except RuntimeError:
        active = []
    for worker in active:
        process = worker.process
        if (
            worker.owner_pid == os.getpid()
            and process is not None
            and process.poll() is None
        ):
            workers.append(
                {"pid": process.pid, **file_identity(f"/proc/{process.pid}/exe")}
            )
    library = getattr(star_detect, "_library", None)
    return {
        "mf_git_head": revision,
        "mf_distribution": "binary_release" if package else "source_checkout",
        "mf_package_manifest": file_identity(root / "PACKAGE.json"),
        "mf_package_platform": package.get("platform"),
        "mf_source_version": source_version,
        "mf_version_file": file_identity(root / "VERSION"),
        "mf_source_root": str(root),
        "configured_server": file_identity(mf_detect_process.native_server_path()),
        "configured_library": file_identity(star_detect.native_library_path()),
        "running_workers": workers,
        "loaded_library_path": str(library._name) if library is not None else None,
        "dependency_versions": versions,
        "note": "Configured paths describe disk files; running_workers hashes open process executables. ctypes path does not attest loaded memory. Vendored Tetra3 is identified by source hash.",
    }
