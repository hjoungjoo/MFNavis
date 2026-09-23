#!/usr/bin/env python3
"""Prepare and activate code-only updates, preserving source/package rollback data.

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
    previous = journal.get("detector_before_link")
    if not previous:
        raise RuntimeError(
            "Legacy source update journal: use the saved pre-migration updater"
        )
    if detector.exists() and not detector.is_symlink():
        raise RuntimeError("MFDS runtime link was replaced by a directory")
    replacement = detector.with_name(".mfds-restore")
    replacement.unlink(missing_ok=True)
    replacement.symlink_to(previous)
    os.replace(replacement, detector)


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
        origin = git(repo, "remote", "get-url", "origin")
        if origin in {
            "https://github.com/hjoungjoo/MF_PiFinder",
            "https://github.com/hjoungjoo/MF_PiFinder.git",
            "git@github.com:hjoungjoo/MF_PiFinder.git",
        }:
            run(
                repo,
                "git",
                "remote",
                "set-url",
                "origin",
                "https://github.com/hjoungjoo/MFNavis.git",
            )
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
        if not detector.is_symlink() or not (detector / "PACKAGE.json").is_file():
            raise RuntimeError(
                "Install the pinned MFDS binary package before code updates"
            )
        detector_before_link = os.readlink(detector)
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
            # Preserve the existing package link before changing application source or runtime artifacts.
            journal = {
                "before": before,
                "target": target,
                "branch": branch,
                "detector_before_link": detector_before_link,
            }
            (state / "journal.json").write_text(json.dumps(journal, indent=2))
            if git(repo, "rev-parse", "HEAD") != before or git(
                repo, "status", "--porcelain", "--untracked-files=no"
            ):
                raise RuntimeError("Checkout changed while preparing the update")
            if (
                not detector.is_symlink()
                or os.readlink(detector) != detector_before_link
            ):
                raise RuntimeError("MFDS runtime changed while preparing update")
            activated = True
            run(repo, "git", "merge", "--ff-only", target)
            staged_package = (candidate / "python/MFDS").resolve()
            if not (staged_package / "PACKAGE.json").is_file():
                raise RuntimeError("Prepared MFDS package is missing")
            installed = repo / "python/.mfds" / staged_package.name
            if not installed.exists():
                shutil.copytree(staged_package, installed)
            run(repo, sys.executable, "scripts/install_mfds.py", "--repo", str(repo))
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
