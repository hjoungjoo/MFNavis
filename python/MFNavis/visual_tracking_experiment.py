"""Command-free preflight/replay and live shadow intent CLI.

Run with: python -m PiFinder.visual_tracking_experiment --help
No command in this module imports a mount controller or opens its queues.
"""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import platform
import sys

import numpy as np

from PiFinder.visual_tracking import CameraGeometry, TrackingSession, plate_basis
from PiFinder.visual_tracking_images import detect_test_stars, measure_moon
from PiFinder.visual_tracking_runtime import read_manifest, write_request


def replay(events, base_dir=None):
    session = None
    for number, row in enumerate(events, 1):
        event = row.get("input", row)
        if "event" not in event:
            continue  # status-only entries carry no new observation
        kind = event["event"]
        if kind == "align":
            geometry = CameraGeometry(
                **{
                    **event["geometry"],
                    "target_yx": tuple(event["geometry"]["target_yx"]),
                }
            )
            session = TrackingSession(
                geometry, generation=session.generation if session else 0
            )
            session.align(
                event["target_id"],
                event["timestamp"],
                event["expected_basis"],
                event.get("centroids", []),
            )
            result = session.status("user_alignment")
        elif session is None:
            raise ValueError(f"line {number}: alignment must precede measurements")
        elif kind in {"stop", "manual_move", "mount_changed", "geometry_changed"}:
            session.cancel() if kind == "stop" else session.suspend(kind)
            result = session.status(kind)
        elif kind == "frame":
            observation = {
                key: event[key]
                for key in (
                    "generation",
                    "frame_id",
                    "timestamp",
                    "expected_basis",
                    "centroids",
                    "solved_basis",
                    "moon_yx",
                )
                if key in event
            }
            if "image" in event:
                path = Path(event["image"])
                if not path.is_absolute():
                    if base_dir is None:
                        raise ValueError("relative image requires a dataset directory")
                    path = Path(base_dir) / path
                image = np.load(path, allow_pickle=False)
                if image.shape != (session.geometry.height, session.geometry.width):
                    raise ValueError("image geometry differs from alignment")
                lunar = None
                excluded = None
                if event.get("moon_radius_px") is not None:
                    lunar = measure_moon(
                        image, session.geometry.target_yx, event["moon_radius_px"]
                    )
                    yy, xx = np.indices(image.shape)
                    y, x = session.geometry.target_yx
                    excluded = np.hypot(yy - y, xx - x) < event["moon_radius_px"] * 1.5
                observation.setdefault(
                    "centroids", detect_test_stars(image, excluded=excluded)
                )
                if lunar is not None:
                    observation["moon_yx"] = lunar["center_yx"]
            result = session.observe(**observation)
        else:
            raise ValueError(f"line {number}: unknown event {kind}")
        yield result


def demo_events():
    """Known geometry with lunar-like RA/Dec motion, cloud gaps and reacquisition."""
    geometry = CameraGeometry(512, 512, 10, (256, 256), "synthetic-v1")
    points = np.array([[90, 100], [100, 390], [220, 170], [370, 80], [400, 420]])
    first = plate_basis(359.99, 20, 15)
    world = geometry.rays(points) @ first
    yield {
        "event": "align",
        "geometry": asdict(geometry),
        "target_id": "MOON",
        "timestamp": 1000.0,
        "expected_basis": first.tolist(),
        "centroids": points.tolist(),
    }
    for index in range(1, 9):
        expected = plate_basis(
            (359.99 + index * 0.002) % 360, 20 + index * 0.001, 15 + index * 0.02
        )
        observed = (
            [] if index in {3, 4, 7} else geometry.project(world, expected).tolist()
        )
        yield {
            "event": "frame",
            "generation": 1,
            "frame_id": index,
            "timestamp": 1000.0 + index,
            "expected_basis": expected.tolist(),
            "centroids": observed,
            "solved_basis": expected.tolist() if index == 6 else None,
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="write a deterministic replay dataset")
    demo.add_argument("--output", type=Path, required=True)
    play = commands.add_parser("replay", help="replay JSONL; sends no commands")
    play.add_argument("dataset", type=Path)
    play.add_argument("--output", type=Path, required=True)
    check = commands.add_parser(
        "preflight", help="validate configuration/dependencies only"
    )
    check.add_argument("manifest", type=Path)
    align = commands.add_parser("align", help="align the SHADOW session only")
    align.add_argument("manifest", type=Path)
    align.add_argument("--ra", type=float, required=True)
    align.add_argument("--dec", type=float, required=True)
    align.add_argument("--body")
    align.add_argument("--frame", choices=("catalog", "of_date"), required=True)
    for name in ("stop", "manual_move", "status"):
        command = commands.add_parser(name)
        command.add_argument("manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            # Refuse accidental replacement of a captured field dataset.
            with args.output.open("x") as stream:
                for row in demo_events():
                    stream.write(json.dumps(row) + "\n")
            print(json.dumps({"dataset": str(args.output), "commands_sent": 0}))
        elif args.command == "replay":
            if args.dataset.resolve() == args.output.resolve():
                raise ValueError("output must differ from dataset")
            counts = {}
            with args.dataset.open() as source, args.output.open("x") as dest:
                events = (json.loads(line) for line in source if line.strip())
                for result in replay(events, args.dataset.parent):
                    dest.write(json.dumps(result, allow_nan=False) + "\n")
                    counts[result["state"]] = counts.get(result["state"], 0) + 1
            print(json.dumps({"states": counts, "commands_sent": 0}))
        elif args.command == "preflight":
            import scipy

            manifest = read_manifest(args.manifest)
            print(
                json.dumps(
                    {
                        "configuration_valid": True,
                        "hardware_verified": False,
                        "python": platform.python_version(),
                        "numpy": np.__version__,
                        "scipy": scipy.__version__,
                        "mode": manifest["mode"],
                        "mount_type": manifest["mount_type"],
                        "commands_sent": 0,
                    }
                )
            )
        elif args.command == "status":
            manifest = json.loads(args.manifest.read_text())
            print((Path(manifest["output_dir"]) / "status.json").read_text())
        else:
            payload = (
                {"ra": args.ra, "dec": args.dec, "body": args.body, "frame": args.frame}
                if args.command == "align"
                else {}
            )
            request = write_request(args.manifest, args.command, **payload)
            print(json.dumps({"shadow_request": request["id"], "commands_sent": 0}))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Experiment unavailable: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
