#!/usr/bin/env python3
"""Move the former public MFDS checkout without discarding local files."""

from pathlib import Path
import subprocess
import sys


def migrate(repo):
    repo = Path(repo).resolve()
    old, new = repo / "python/mf_detect_star", repo / "python/MFDS"
    if not old.exists():
        return
    if old.is_symlink() or new.is_symlink():
        raise RuntimeError("Refusing ambiguous detector symlink layout")
    if new.exists() and any(new.iterdir()):
        raise RuntimeError("Both detector directories contain files; inspect manually")
    if not (old / ".git").exists():
        raise RuntimeError("Former detector directory is not a Git checkout")
    origin = subprocess.check_output(
        ["git", "-C", str(old), "remote", "get-url", "origin"], text=True
    ).strip()
    if origin not in (
        "https://github.com/hjoungjoo/MFDS.git",
        "git@github.com:hjoungjoo/MFDS.git",
    ):
        raise RuntimeError("Former detector is not the public MFDS repository")
    if new.exists():
        new.rmdir()
    old.rename(new)
    # Gitfiles retain their relative depth, but the module's worktree setting
    # must follow the renamed directory. Standalone checkouts need no change.
    if (new / ".git").is_file():
        git_dir = (
            new / (new / ".git").read_text().strip().removeprefix("gitdir: ")
        ).resolve()
        subprocess.run(
            [
                "git",
                "config",
                "--file",
                str(git_dir / "config"),
                "core.worktree",
                str(new),
            ],
            check=True,
        )


if __name__ == "__main__":
    migrate(sys.argv[1])
