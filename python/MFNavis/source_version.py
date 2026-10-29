"""Source identity recorded in settings, independent of the FRAM format version."""

from functools import lru_cache
from pathlib import Path
import subprocess


@lru_cache(maxsize=1)
def _read_source_version(root):
    try:
        version = (root / "version.txt").read_text(encoding="utf-8").strip()
    except OSError:
        version = "unknown"
    identity = {"version": version or "unknown", "git_commit": None, "git_dirty": None}
    # Archives can lack Git metadata; do not accidentally identify a parent repo.
    if (root / ".git").exists():
        try:

            def git(*args):
                return subprocess.run(
                    ["git", "--no-optional-locks", "-C", str(root), *args],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=3,
                ).stdout.strip()

            identity["git_commit"] = git("rev-parse", "HEAD")
            identity["git_dirty"] = bool(
                git("status", "--porcelain", "--untracked-files=normal")
            )
        except (OSError, subprocess.SubprocessError):
            pass
    return identity


def get_source_version():
    """Return a copy of this process's source identity; never probe Git per save."""
    return dict(_read_source_version(Path(__file__).resolve().parents[2]))
