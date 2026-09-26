#!/usr/bin/env python3
"""Prepare relocatable Python wheels and native dependencies for INDI v2."""

import argparse
import importlib.metadata as metadata
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from packaging.requirements import Requirement


ROOT_PACKAGES = (
    "pyindi-client",
    "indiweb",
    "fastapi",
    "starlette",
    "uvicorn",
    "anyio",
    "jinja2",
    "wsproto",
)


def installed_dependencies():
    pending = list(ROOT_PACKAGES)
    distributions = {}
    while pending:
        dist = metadata.distribution(pending.pop())
        name = re.sub(r"[-_.]+", "-", dist.metadata["Name"]).lower()
        if name in distributions:
            continue
        distributions[name] = dist
        for spec in dist.requires or ():
            requirement = Requirement(spec)
            if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
                continue
            dependency = metadata.distribution(requirement.name)
            if dependency.version not in requirement.specifier:
                raise ValueError(f"installed dependency does not satisfy {spec}")
            pending.append(requirement.name)
    return distributions


def pack_installed_wheel(distribution, wheelhouse):
    """Repack the two source-built distributions, retaining licenses and tags."""
    if not distribution.read_text("WHEEL"):
        raise ValueError(f"missing wheel metadata: {distribution.metadata['Name']}")
    with tempfile.TemporaryDirectory(dir=wheelhouse.parent) as directory:
        destination = Path(directory)
        for entry in distribution.files or ():
            # pip recreates console entry points from entry_points.txt. Installed
            # scripts contain the build host's interpreter and must not travel.
            if ".." in entry.parts or entry.is_absolute():
                continue
            if "__pycache__" in entry.parts or entry.suffix == ".pyc":
                continue
            if entry.name in {"RECORD", "INSTALLER", "REQUESTED"}:
                continue
            source = Path(distribution.locate_file(entry))
            if source.is_file():
                target = destination / entry
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        subprocess.run(
            [sys.executable, "-m", "wheel", "pack", directory, "-d", str(wheelhouse)],
            check=True,
        )


def native_runtime_packages(rootfs, extra_binaries=()):
    """Map resolved ELF dependencies outside the payload to Debian packages."""
    bundled = {
        (Path("/") / path.relative_to(rootfs)).resolve()
        for path in rootfs.rglob("*")
        if path.is_file()
    }
    libraries = set()
    for binary in [*rootfs.rglob("*"), *extra_binaries]:
        if not binary.is_file() or binary.is_symlink():
            continue
        with binary.open("rb") as source:
            if source.read(4) != b"\x7fELF":
                continue
        result = subprocess.run(
            ["ldd", str(binary)], capture_output=True, text=True, check=False
        )
        if "not found" in result.stdout:
            raise ValueError(
                f"unresolved native dependencies: {binary}\n{result.stdout}"
            )
        if result.returncode:
            # Static archives/executables have no dynamically loaded libraries.
            if "not a dynamic executable" in result.stderr + result.stdout:
                continue
            raise ValueError(f"ldd failed: {binary}: {result.stderr}")
        for line in result.stdout.splitlines():
            match = re.search(r"(?:=>\s+|^\s*)(/\S+)", line)
            if match:
                path = Path(match[1]).resolve()
                if path not in bundled:
                    libraries.add(path)
    packages = {}
    for library in sorted(libraries):
        result = subprocess.run(
            ["dpkg-query", "-S", str(library)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise ValueError(f"unpackaged runtime library: {library}")
        owner = result.stdout.splitlines()[0].rsplit(": ", 1)[0]
        package = owner.split(":", 1)[0]
        if not re.fullmatch(r"[a-z0-9][a-z0-9+.-]*", package):
            raise ValueError(f"invalid library package: {owner}")
        version = subprocess.check_output(
            ["dpkg-query", "-W", "-f=${Version}", owner], text=True
        ).strip()
        packages[package] = version
    return dict(sorted(packages.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("staging", type=Path)
    args = parser.parse_args()
    staging = args.staging
    wheelhouse = staging / "wheels"
    wheelhouse.mkdir()
    distributions = installed_dependencies()
    requirements = [
        f"{name}=={dist.version}" for name, dist in sorted(distributions.items())
    ]
    meta = staging / "metadata"
    (meta / "python-requirements.txt").write_text("\n".join(requirements) + "\n")
    custom = {"pyindi-client", "indiweb"}
    for name in sorted(custom):
        pack_installed_wheel(distributions[name], wheelhouse)
    pypi = [spec for spec in requirements if spec.split("==")[0] not in custom]
    (meta / "python-requirements-pypi.txt").write_text("\n".join(pypi) + "\n")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--wheel-dir",
            str(wheelhouse),
            "-r",
            str(meta / "python-requirements-pypi.txt"),
        ],
        check=True,
    )
    pyindi = distributions["pyindi-client"]
    extensions = [
        Path(pyindi.locate_file(entry))
        for entry in pyindi.files or ()
        if entry.name.startswith("_PyIndi") and entry.suffix == ".so"
    ]
    if len(extensions) != 1:
        raise ValueError("expected one installed PyIndi extension")
    packages = native_runtime_packages(staging / "rootfs", extensions)
    (meta / "runtime-packages.txt").write_text("\n".join(packages) + "\n")
    (meta / "runtime-package-versions.json").write_text(
        json.dumps(packages, indent=2) + "\n"
    )
    print(
        f"Prepared {len(distributions)} Python packages and {len(packages)} native dependencies."
    )


if __name__ == "__main__":
    main()
