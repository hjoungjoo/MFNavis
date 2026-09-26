#!/usr/bin/env python3
"""Populate MFNavis's rebuildable on-disk caches.

This utility deliberately does not change settings, observations, or other user
data.  It can be stopped with Ctrl-C and run again: catalog survey images that
already exist are skipped by ``MFNavis.gen_images``.

Examples:

    python3 scripts/warm_mfnavis_caches.py
    python3 scripts/warm_mfnavis_caches.py --images poss
    python3 scripts/warm_mfnavis_caches.py --images none

The default creates the runtime caches and downloads both POSS and SDSS catalog
images.  POSS is the image used by MFNavis and web catalog views; SDSS is
included by default to make the complete survey-image cache available offline.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"


def _add_project_to_path() -> None:
    """Allow direct execution without requiring a PYTHONPATH setting."""
    python_root = str(PYTHON_ROOT)
    if python_root not in sys.path:
        sys.path.insert(0, python_root)


def _format_size(size: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"


def _tree_size(path: Path) -> int:
    return sum(entry.stat().st_size for entry in path.rglob("*") if entry.is_file())


def warm_runtime_caches() -> None:
    """Build the deterministic local caches used during normal startup/use."""
    _add_project_to_path()

    from PiFinder import catalog_cache, utils
    from PiFinder.catalogs import CatalogBuilder
    from PiFinder.plot import _load_raw_stars
    from PiFinder.sqm.color_index import get_bv
    from PiFinder.state import SharedStateObj

    print("[runtime] Building Hipparcos star-field cache...", flush=True)
    _load_raw_stars()

    print("[runtime] Building Hipparcos B-V lookup cache...", flush=True)
    get_bv(())

    print("[runtime] Building composite catalog cache...", flush=True)
    builder = CatalogBuilder()
    builder.build(SharedStateObj(), include_dynamic_catalogs=False)

    loader = getattr(builder, "_background_loader", None)
    worker = getattr(loader, "_thread", None)
    if worker is not None:
        while worker.is_alive():
            worker.join(timeout=1)
            if worker.is_alive():
                loaded = len(loader.get_loaded_objects())
                print(
                    f"[runtime] Catalog cache: {loaded:,} deferred objects loaded",
                    flush=True,
                )

    if catalog_cache.load() is None:
        raise RuntimeError("Catalog cache was not written successfully")

    cache_root = utils.data_dir / "cache"
    print(
        f"[runtime] Complete: {cache_root} ({_format_size(_tree_size(cache_root))})",
        flush=True,
    )


def warm_catalog_images(image_sources: str, workers: int) -> None:
    """Delegate image generation to the existing resumable image module."""
    args = [sys.executable, "-m", "MFNavis.gen_images", "--workers", str(workers)]
    if image_sources == "poss":
        args.append("--poss")
    elif image_sources == "both":
        # gen_images downloads both sources when neither selector is provided.
        pass
    else:
        return

    env = os.environ.copy()
    current_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(PYTHON_ROOT) + (
        os.pathsep + current_path if current_path else ""
    )
    print(
        f"[images] Starting resumable {image_sources.upper()} image cache download...",
        flush=True,
    )
    subprocess.run(args, cwd=REPO_ROOT, env=env, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="warm_mfnavis_caches.py",
        description="Pre-populate rebuildable MFNavis runtime and catalog-image caches.",
    )
    parser.add_argument(
        "--images",
        choices=("both", "poss", "none"),
        default="both",
        help="Catalog-survey images to cache (default: both POSS and SDSS).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=10,
        help="Concurrent image downloads; ignored with --images none (default: 10).",
    )
    parser.add_argument(
        "--skip-runtime",
        action="store_true",
        help="Download only catalog images; do not build local runtime caches.",
    )
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    if os.geteuid() == 0:
        parser.error("run as the MFNavis service user, without sudo")

    started = time.monotonic()
    try:
        if not args.skip_runtime:
            warm_runtime_caches()
        warm_catalog_images(args.images, args.workers)
    except KeyboardInterrupt:
        print("\nStopped. Re-run this command to continue from the existing cache.")
        return 130
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Cache warm-up failed: {exc}", file=sys.stderr)
        return 1

    elapsed = time.monotonic() - started
    print(f"Cache warm-up complete in {elapsed:.1f} seconds.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
