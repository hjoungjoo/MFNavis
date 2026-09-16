#!/usr/bin/env python3
"""Prepare and activate code-only updates, preserving source/build rollback data.

System package / OS migrations are intentionally a separate installer operation.
A failed or interrupted transaction is kept under .git/update-transaction.
"""

import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def run(repo, *args, **kwargs):
    return subprocess.run(args, cwd=repo, check=True, **kwargs)


def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def restore(repo, state, journal):
    run(repo, "git", "reset", "--hard", journal["before"])
    detector = repo / "python/MFDS"
    if journal["detector_before"]:
        run(detector, "git", "checkout", "--detach", journal["detector_before"])
    build = detector / "build"
    if build.exists():
        shutil.rmtree(build)
    if journal["had_build"]:
        shutil.copytree(state / "previous-build", build)
    replacement = detector / "build.update"
    if replacement.exists():
        shutil.rmtree(replacement)


def recover(repo):
    """Explicit recovery after process termination; never invoked at boot."""
    git_dir = Path(git(repo, "rev-parse", "--absolute-git-dir"))
    with (git_dir / "update.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = git_dir / "update-transaction"
        journal = json.loads((state / "journal.json").read_text())
        if git(repo, "rev-parse", "HEAD") not in (journal["before"], journal["target"]):
            raise RuntimeError("Checkout advanced after interruption; inspect manually")
        if git(repo, "symbolic-ref", "--short", "HEAD") != journal["branch"]:
            raise RuntimeError("Branch changed after interruption; inspect manually")
        if git(repo, "diff", "--name-only") or git(
            repo, "diff", "--cached", "--name-only"
        ):
            # A changed submodule HEAD alone is part of an interrupted activation.
            changed = git(repo, "diff", "--name-only")
            if changed != "python/MFDS" or git(
                repo, "diff", "--cached", "--name-only"
            ):
                raise RuntimeError("Tracked edits after interruption; inspect manually")
        restore(repo, state, journal)
        shutil.rmtree(state)


def update(repo):
    git_dir = Path(git(repo, "rev-parse", "--absolute-git-dir"))
    # Serialize update attempts; normal running services are not restarted here.
    with (git_dir / "update.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = git_dir / "update-transaction"
        if state.exists():
            raise RuntimeError(f"Previous update needs inspection/recovery: {state}")
        branch = git(repo, "symbolic-ref", "--quiet", "--short", "HEAD")
        if git(repo, "status", "--porcelain", "--untracked-files=no"):
            raise RuntimeError("Tracked files have local changes; refusing update")
        before = git(repo, "rev-parse", "HEAD")
        run(repo, "git", "fetch", "--no-tags", "origin", f"refs/heads/{branch}")
        target = git(repo, "rev-parse", "FETCH_HEAD")
        run(repo, "git", "merge-base", "--is-ancestor", before, target)
        run(
            repo,
            sys.executable,
            "scripts/check_cedar_free.py",
            "--repo",
            str(repo),
            "--ref",
            target,
        )
        sensitive = git(
            repo,
            "diff",
            "--name-only",
            before,
            target,
            "--",
            "python/requirements.txt",
            "migration_source",
            "pi_config_files",
            ".gitmodules",
        )
        if sensitive:
            raise RuntimeError(
                "Dependency/OS/submodule layout changes require a separate staged installation: "
                + sensitive
            )
        detector = repo / "python/MFDS"
        detector_before = (
            git(detector, "rev-parse", "HEAD") if (detector / ".git").exists() else None
        )
        if detector_before is None:
            raise RuntimeError("Initialize the pinned MF submodule before code updates")
        build = detector / "build"
        state.mkdir()
        activated = False
        try:
            candidate = state / "candidate"
            run(
                repo,
                "git",
                "clone",
                "--shared",
                "--no-checkout",
                str(repo),
                str(candidate),
            )
            run(candidate, "git", "checkout", "--detach", target)
            run(candidate, "bash", "scripts/prepare_code_update.sh")
            # Preserve the existing build before changing either the source or native artifacts.
            journal = {
                "before": before,
                "target": target,
                "branch": branch,
                "detector_before": detector_before,
                "had_build": build.exists(),
            }
            if build.exists():
                shutil.copytree(build, state / "previous-build")
            (state / "journal.json").write_text(json.dumps(journal, indent=2))
            if git(repo, "rev-parse", "HEAD") != before or git(
                repo, "status", "--porcelain", "--untracked-files=no"
            ):
                raise RuntimeError("Checkout changed while preparing the update")
            activated = True
            run(repo, "git", "merge", "--ff-only", target)
            run(repo, "git", "submodule", "update", "--init", "--recursive")
            staged_build = candidate / "python/MFDS/build"
            if not staged_build.is_dir():
                raise RuntimeError("Prepared MF build is missing")
            replacement = detector / "build.update"
            if replacement.exists():
                raise RuntimeError("Unfinished MF build replacement")
            shutil.copytree(staged_build, replacement)
            if build.exists():
                shutil.rmtree(build)
            replacement.rename(build)
            run(repo, "bash", "scripts/ensure_tetra3_link.sh", str(repo))
            run(
                repo,
                "bash",
                "-e",
                "pifinder_post_update.sh",
                env={
                    **os.environ,
                    "PIFINDER_CODE_UPDATE": "1",
                    "PIFINDER_REPO_DIR": str(repo),
                },
            )
        except BaseException:
            if activated:
                restore(repo, state, journal)
            # Preparation failures cannot have touched the installed checkout.
            shutil.rmtree(state)
            raise
        shutil.rmtree(state)


if __name__ == "__main__":
    try:
        repo = Path(sys.argv[1]).resolve()
        if len(sys.argv) == 3 and sys.argv[2] == "--recover":
            recover(repo)
        else:
            update(repo)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Update failed: {exc}", file=sys.stderr)
        sys.exit(1)
