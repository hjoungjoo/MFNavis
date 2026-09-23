#!/usr/bin/env python3
"""Record exact MFNavis image/source/package identities; reject development MFDS."""

import argparse
import json
from pathlib import Path
import subprocess
import tempfile

from install_mfds import digest, extract, verify_package


def record(repo, firmware_version, tag, image, source_archive, mfds_archive, output):
    repo = Path(repo).resolve()
    if subprocess.check_output(
        ["git", "-C", str(repo), "status", "--porcelain"], text=True
    ).strip():
        raise ValueError("Product release requires a clean PiFinder source tree")
    head = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    tagged = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", f"refs/tags/{tag}^{{commit}}"], text=True
    ).strip()
    if tagged != head:
        raise ValueError("PiFinder tag must identify the built checkout")
    for path in (image, source_archive, mfds_archive):
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"Missing/empty release artifact: {path}")
    with tempfile.TemporaryDirectory() as temporary:
        root = extract(mfds_archive, Path(temporary))
        manifest = json.loads((root / "PACKAGE.json").read_text())
        manifest_hash = digest(root / "PACKAGE.json")
        lock = {
            "schema": 1,
            "profile": "commercial-process-only",
            "version": manifest["version"],
            "source_commit": manifest["source_commit"],
            "assets": {manifest["platform"]: {"manifest_sha256": manifest_hash}},
        }
        verify_package(root, lock, manifest["platform"], execute=False)
    data = {
        "schema": 1,
        "product": "MFNavis",
        "distributor": "FNPD 한국",
        "creator": "MagicFly",
        "firmware_version": firmware_version,
        "pifinder": {"tag": tag, "commit": head, "source_dirty": False},
        "mfds": {
            k: manifest[k]
            for k in ("version", "source_commit", "platform", "profile", "source_dirty")
        },
        "mfds_manifest_sha256": manifest_hash,
        "artifacts": {
            name: {"filename": path.name, "sha256": digest(path)}
            for name, path in (
                ("image", image),
                ("corresponding_source", source_archive),
                ("mfds", mfds_archive),
            )
        },
        "source_delivery": "GPLv3-6(a) physical source medium; 6(d) for downloads",
    }
    # A source archive hash identifies the reviewed archive; it does not itself
    # prove completeness of corresponding source or installation information.
    with output.open("x") as stream:
        stream.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--firmware-version", required=True)
    parser.add_argument("--pifinder-tag", required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--mfds-archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    record(
        args.repo,
        args.firmware_version,
        args.pifinder_tag,
        args.image,
        args.source_archive,
        args.mfds_archive,
        args.output,
    )
