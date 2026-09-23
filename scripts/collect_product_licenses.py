#!/usr/bin/env python3
"""Collect installed license evidence; report missing texts instead of assuming compliance."""

import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
import re
import shutil
import subprocess


def collect(output):
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for dist in sorted(
        metadata.distributions(), key=lambda d: d.metadata.get("Name", "")
    ):
        name = dist.metadata.get("Name", "unknown")
        slug = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{name}-{dist.version}")
        folder = output / "python" / slug
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "METADATA").write_text(dist.read_text("METADATA") or "")
        copied = []
        for entry in dist.files or []:
            if any(
                token in str(entry).lower()
                for token in ("license", "licence", "copying", "notice", "authors")
            ):
                source = Path(dist.locate_file(entry))
                if not source.is_file():
                    continue
                data = source.read_bytes()
                target = f"{hashlib.sha256(str(entry).encode()).hexdigest()[:12]}-{source.name}"
                (folder / target).write_bytes(data)
                copied.append(
                    {
                        "source": str(entry),
                        "file": target,
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                )
        has_terms = any(
            any(t in item["source"].lower() for t in ("license", "licence", "copying"))
            for item in copied
        )
        records.append(
            {
                "name": name,
                "version": dist.version,
                "license_metadata": dist.metadata.get("License"),
                "files": copied,
                "needs_review": not has_terms,
            }
        )
    os_dir = output / "os"
    os_dir.mkdir()
    packages = subprocess.check_output(
        ["dpkg-query", "-W", "-f=${Package}\t${Version}\t${Architecture}\n"], text=True
    )
    (os_dir / "packages.tsv").write_text(packages)
    missing_os = []
    for line in packages.splitlines():
        name = line.split("\t")[0]
        copyright_file = Path("/usr/share/doc") / name / "copyright"
        if copyright_file.is_file():
            shutil.copyfile(copyright_file, os_dir / f"{name}.copyright")
        else:
            missing_os.append(name)
    shutil.copytree(
        "/usr/share/common-licenses", os_dir / "common-licenses", symlinks=False
    )
    report = {
        "python": records,
        "os_missing_copyright": missing_os,
        "scope": "Installed Python/OS evidence only; separately review bundled web assets, fonts, data and source delivery.",
    }
    (output / "inventory.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    missing = [r["name"] for r in records if r["needs_review"]]
    print(
        json.dumps(
            {
                "python_packages": len(records),
                "python_needs_review": missing,
                "os_missing_copyright": missing_os,
            },
            ensure_ascii=False,
        )
    )
    return bool(missing or missing_os)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(collect(args.output))
