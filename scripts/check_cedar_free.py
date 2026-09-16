"""Check known Cedar artifacts in a Git candidate or an offline product image.

Read-only: never stops services or removes files. A pass is not license clearance.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess


def forbidden(name):
    name = name.lower()
    return (
        name.startswith(("cedar-detect-server", "cedar_detect_server"))
        or name
        in {"cedar_detect.service", "cedar-detect.service", "cedar_detect.proto"}
        or name.startswith(("cedar_detect_client.", "cedar_detect_pb2"))
    )


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def check_repo(repo, ref="HEAD"):
    # Resolve first: a ref beginning with '-' must never become a git option.
    commit = git(repo, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}")
    commit = commit.decode().strip()
    entries = (
        git(repo, "ls-tree", "-r", "--name-only", "-z", commit).decode().split("\0")
    )
    problems = [p for p in entries if p and forbidden(Path(p).name)]
    try:
        marker = json.loads(git(repo, "show", commit + ":deployment/cedar_free.json"))
        if marker.get("schema") != 1 or marker.get("detector") != "mf":
            problems.append("invalid Cedar-free deployment marker")
    except (subprocess.CalledProcessError, ValueError, AttributeError):
        problems.append("missing/invalid Cedar-free deployment marker")
    entry = git(repo, "ls-tree", commit, "--", "python/MFDS").decode()
    if not entry.startswith("160000 commit "):
        problems.append("MF detector is not pinned as a submodule")
    return problems


def check_image(root):
    root = root.resolve()
    if root == Path("/") or not all((root / p).is_dir() for p in ("etc", "usr")):
        raise ValueError("Choose a mounted offline image directory, not the live root")
    problems = []
    # Do not traverse symlinks into the host. Also catch disabled unit symlinks
    # and git histories: shipping a copied development tree is not a clean image.
    for directory, folders, files in os.walk(root, followlinks=False):
        for name in folders + files:
            path = Path(directory) / name
            rel = str(path.relative_to(root))
            if forbidden(name) or name == ".git":
                problems.append(rel)
            elif path.is_symlink() and any(
                token in os.readlink(path).lower()
                for token in ("cedar-detect", "cedar_detect")
            ):
                problems.append(rel)
            elif name.endswith((".service", ".conf")) and not path.is_symlink():
                if "systemd" in path.parts and path.is_file():
                    data = path.read_text(errors="replace").lower()
                    if "cedar-detect" in data or "cedar_detect" in data:
                        problems.append(rel)
        folders[:] = [n for n in folders if n != ".git"]
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--image-root", type=Path)
    args = parser.parse_args()
    try:
        problems = check_repo(args.repo, args.ref)
        if args.image_root is not None:
            problems += check_image(args.image_root)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Cannot validate Cedar-free contents: {exc}\n")
    if problems:
        parser.exit(1, "Cedar-free check failed:\n" + "\n".join(problems) + "\n")
    print("Known Cedar artifacts absent; MF source pinned. Not license clearance.")


if __name__ == "__main__":
    main()
