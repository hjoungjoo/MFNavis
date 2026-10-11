"""Offline-only visual fallback benchmark. No mount, camera or runtime writes.

Run with PYTHONPATH=python using the development venv. Recorded solves are
held out: the tracker receives only centroids, geometry and exposure timestamps.
The first suitable stationary frame simulates a user alignment, not a recorded
Align action. A second run is required to evaluate a different reference.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import platform
import time
from zoneinfo import ZoneInfo

import numpy as np
import scipy
from scipy.spatial.transform import Rotation

from PiFinder import solver_frame_map as sfm
from PiFinder.mf_wide_distortion import undistort_global_centroids
from PiFinder.visual_tracking import (
    CameraGeometry,
    TrackingLimits,
    clean_centroids,
    fit_star_pose,
    plate_basis,
)
from PiFinder.visual_tracking_images import detect_test_stars


class RelativeReplay:
    """Test harness for fixed local-image reference; never publishes sky coords."""

    def __init__(self, geometry, *, max_gap_s=10.0, min_stars=5):
        if min_stars < 3 or not math.isfinite(max_gap_s) or max_gap_s <= 0:
            raise ValueError("invalid replay limits")
        self.geometry = geometry
        self.limits = TrackingLimits(max_gap_s=max_gap_s)
        self.min_stars = min_stars
        self.world = None
        self.pose = np.eye(3)
        self.last_frame = -1
        self.last_time = -math.inf
        self.last_valid = -math.inf
        self.enabled = False

    def align(self, points, frame_id, stamp):
        points = clean_centroids(points, self.geometry)
        if len(points) < self.min_stars or not math.isfinite(stamp):
            return False
        # Validate independent star support before accepting a new baseline.
        world = self.geometry.rays(points)
        pose, count, _ = fit_star_pose(
            world, points, np.eye(3), self.geometry, self.limits
        )
        if pose is None or count < self.min_stars:
            return False
        self.world, self.pose = world, np.eye(3)
        self.last_frame, self.last_time, self.last_valid = frame_id, stamp, stamp
        self.enabled = True
        return True

    def stop(self):
        self.enabled = False

    def measure(self, points, frame_id, stamp):
        start = time.perf_counter_ns()
        result = dict(valid=False, reason="not_aligned", matches=0, rmse_px=None)
        if not self.enabled:
            pass
        elif (
            not math.isfinite(stamp)
            or frame_id <= self.last_frame
            or stamp <= self.last_time
        ):
            result["reason"] = "stale_frame"
        else:
            self.last_frame, self.last_time = frame_id, stamp
            if stamp - self.last_valid > self.limits.max_gap_s:
                result["reason"] = "gap_exceeded"
            else:
                points = clean_centroids(points, self.geometry)
                pose, count, rmse = fit_star_pose(
                    self.world, points, self.pose, self.geometry, self.limits
                )
                result.update(matches=count, rmse_px=rmse)
                if pose is None or count < self.min_stars:
                    result["reason"] = "insufficient_or_inconsistent_stars"
                else:
                    self.pose, self.last_valid = pose, stamp
                    target = self.geometry.rays([self.geometry.target_yx])
                    error = self.geometry.project(target, pose)[0]
                    result.update(
                        valid=True,
                        reason="observed",
                        residual_yx_px=(error - self.geometry.target_yx).tolist(),
                    )
        result["fit_ms"] = (time.perf_counter_ns() - start) / 1e6
        return result


def stats(values):
    array = np.asarray([v for v in values if v is not None], dtype=float)
    if not len(array):
        return {"n": 0, "median": None, "p95": None, "max": None}
    if not np.isfinite(array).all():
        raise ValueError("nonfinite benchmark metric")
    return dict(
        n=len(array),
        median=float(np.median(array)),
        p95=float(np.percentile(array, 95)),
        max=float(array.max()),
    )


def fingerprint(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rows(path):
    with Path(path).open() as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def write_json(path, value):
    Path(path).write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    )


def write_rows(path, records):
    with Path(path).open("w") as stream:
        for record in records:
            stream.write(json.dumps(record, allow_nan=False) + "\n")


def synthetic_benchmark(seed=20261011, frames=240):
    """Independent known camera rotations, noise, lost stars and false points."""
    rng = np.random.default_rng(seed)
    geometry = CameraGeometry(1080, 1920, 38.0, (490, 980), "synthetic")
    yy, xx = np.meshgrid(np.linspace(120, 940, 6), np.linspace(160, 1750, 8))
    reference = np.column_stack((yy.ravel(), xx.ravel()))
    tracker = RelativeReplay(geometry)
    assert tracker.align(reference, 0, 0)
    # Independent projection for truth; don't call the production projector.
    focal = geometry.width / (2 * np.tan(np.deg2rad(geometry.fov_deg) / 2))
    rays = np.column_stack(
        (
            np.ones(len(reference)),
            (960 - reference[:, 1]) / focal,
            (540 - reference[:, 0]) / focal,
        )
    )
    target_ray = np.array([1, (960 - 980) / focal, (540 - 490) / focal])
    records = []
    for index in range(1, frames + 1):
        rotation = Rotation.from_rotvec(
            np.array([0.0005 * index, 0.00001 * index, -0.00002 * index])
        ).as_matrix()
        camera = rays @ rotation.T
        points = np.column_stack(
            (
                540 - focal * camera[:, 2] / camera[:, 0],
                960 - focal * camera[:, 1] / camera[:, 0],
            )
        )
        points += rng.normal(0, 0.10, points.shape)
        phase = index % 60
        if 20 <= phase < 25:
            points = np.empty((0, 2))
            case = "no_stars"
        elif 25 <= phase < 28:
            points = points[:2]
            case = "two_stars"
        elif 30 <= phase < 45:
            points = points[rng.choice(len(points), 24, replace=False)]
            points = np.vstack((points, rng.uniform([10, 10], [1070, 1910], (8, 2))))
            case = "partial_cloud_and_outliers"
        else:
            case = "clear"
        result = tracker.measure(points, index, index * 0.5)
        projected = target_ray @ rotation.T
        truth = (
            np.array(
                [
                    540 - focal * projected[2] / projected[0],
                    960 - focal * projected[1] / projected[0],
                ]
            )
            - geometry.target_yx
        )
        result.update(frame=index, case=case, truth_yx_px=truth.tolist())
        result["error_px"] = (
            float(np.linalg.norm(np.asarray(result["residual_yx_px"]) - truth))
            if result["valid"]
            else None
        )
        records.append(result)
    visible = [r for r in records if r["case"] not in {"no_stars", "two_stars"}]
    invalid = [r for r in records if r["case"] in {"no_stars", "two_stars"}]
    summary = dict(
        seed=seed,
        frames=frames,
        geometry=asdict(geometry),
        visible_frames=len(visible),
        tracked_visible=sum(r["valid"] for r in visible),
        invalid_frames=len(invalid),
        false_accepts=sum(r["valid"] for r in invalid),
        error_px=stats(r["error_px"] for r in records),
        fit_ms=stats(r["fit_ms"] for r in records),
        valid_fit_ms=stats(r["fit_ms"] for r in records if r["valid"]),
        timing_scope="centroid cleanup + correspondence + pose fit; no detector or IO",
        closed_loop=False,
    )
    return summary, records


def audit_runtime(path):
    records = list(rows(path))
    stamps = [float(r["wall"]) for r in records]
    if not stamps:
        raise ValueError("empty runtime log")
    start, end = min(stamps), max(stamps)
    solves = set()
    sources, phases = Counter(), Counter()
    for r in records:
        current = (r.get("pointing_coordinate") or {}).get("current") or {}
        sources[current.get("source", "missing")] += 1
        guide = r.get("indi_goto_guide") or {}
        phases[guide.get("phase", "missing")] += 1
        success = (current.get("metadata") or {}).get("last_solve_success")
        if current.get("source") == "solve" and success is not None:
            if start <= success <= end:
                solves.add(success)
    gaps = np.diff(sorted({start, end, *solves})).tolist()
    return dict(
        path=str(Path(path).resolve()),
        sha256=fingerprint(path),
        start_kst=datetime.fromtimestamp(start, ZoneInfo("Asia/Seoul")).isoformat(),
        end_kst=datetime.fromtimestamp(end, ZoneInfo("Asia/Seoul")).isoformat(),
        status_samples=len(records),
        duration_s=end - start,
        sampled_sources=dict(sources),
        sampled_phases=dict(phases),
        unique_success_epochs_seen=len(solves),
        success_epoch_gaps_including_edges_s=stats(gaps),
        visual_replay_available=False,
        limitation=(
            "Runtime status snapshots contain no paired images or detected "
            "centroid lists. Counts are polling samples, not solver attempts; "
            "success epochs are only those visible in sampled solve state."
        ),
    )


def prepare_capture(record, directory):
    """Extract independently from recorded RAW; never use matched_centroids."""
    artifact = record["artifact"]
    path = (directory / artifact["file"]).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise ValueError("artifact outside capture directory")
    digest = fingerprint(path)
    if digest != artifact["sha256"]:
        raise ValueError(f"artifact hash mismatch: {path}")
    metadata = record["metadata"]
    if record.get("raw_metadata", {}).get("frame_id") != metadata["frame_id"]:
        raise ValueError("RAW/metadata frame mismatch")
    result = record["result"]
    optics = result["optics"]
    with np.load(path, allow_pickle=False) as archive:
        raw = archive["raw"]
    if raw.ndim != 2:
        raise ValueError("expected monochrome RAW plane")
    start = time.perf_counter_ns()
    points = detect_test_stars(raw)
    detector_ms = (time.perf_counter_ns() - start) / 1e6
    start = time.perf_counter_ns()
    if optics.get("distortion_coefficients"):
        points = undistort_global_centroids(
            points, raw.shape, optics["distortion_coefficients"]
        )
    points, canvas = sfm.rotate_centroids(points, raw.shape, optics["rotation_deg"])
    target = sfm.map_target_pixel_to_frame(
        result["target_pixel"], canvas, optics["crop_width_px"]
    )
    geometry = CameraGeometry(
        *canvas,
        sfm.fov_estimate_deg(
            canvas[1], optics["crop_width_px"], optics["base_fov_degrees"]
        ),
        target,
        "recorded-optics",
    )
    context = json.dumps(
        [
            asdict(geometry),
            optics,
            metadata.get("capture_epoch"),
            result.get("generation"),
        ],
        sort_keys=True,
    )
    transform_ms = (time.perf_counter_ns() - start) / 1e6
    return geometry, points, context, detector_ms, transform_ms


def solve_basis(record, geometry):
    """Held-out evaluator only; the tracker never receives this matrix."""
    result = record["result"]
    candidate = result.get("candidate") or {}
    if result.get("accepted") is not True:
        return None
    frame = candidate.get("_alignment_frame")
    if not frame or tuple(frame[:2]) != (geometry.height, geometry.width):
        return None
    if not all(key in candidate for key in ("RA", "Dec", "Roll")):
        return None
    return plate_basis(candidate["RA"], candidate["Dec"], candidate["Roll"])


def replay_capture(directory, max_gap_s=10.0):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    tracker, context, anchor_basis = None, None, None
    records = []
    previous_stamp = None
    last_seen = None
    anchor_record = None
    for record in rows(directory / "solver.jsonl"):
        if record.get("kind") != "solver" or not record.get("artifact"):
            continue
        metadata, result = record["metadata"], record["result"]
        stamp, frame_id = metadata["exposure_end"], metadata["frame_id"]
        sample = dict(
            sequence=record["sequence"],
            frame_id=frame_id,
            timestamp=stamp,
            recorded_solve_accepted=result.get("accepted") is True,
            artifact=record["artifact"]["file"],
            valid=False,
            solve_comparison_px=None,
            detector_ms=None,
            fit_ms=None,
        )
        epoch = metadata.get("capture_epoch")
        if not math.isfinite(stamp) or (
            last_seen is not None
            and (
                stamp <= last_seen[0]
                or (epoch == last_seen[2] and frame_id <= last_seen[1])
            )
        ):
            sample["reason"] = "stale_capture"
            # Do not serialize invalid numeric input or let a changed context
            # turn an old frame into a new simulated alignment.
            sample["timestamp"] = stamp if math.isfinite(stamp) else None
            records.append(sample)
            continue
        last_seen = stamp, frame_id, epoch
        moving = result.get("frame_moving") or (metadata.get("imu") or {}).get("moving")
        if moving:
            tracker, context, anchor_basis = None, None, None
            sample["reason"] = "recorded_motion"
            records.append(sample)
            continue
        geometry, points, identity, detector_ms, transform_ms = prepare_capture(
            record, directory
        )
        sample.update(
            stars=len(points), detector_ms=detector_ms, transform_ms=transform_ms
        )
        if identity != context:
            tracker = RelativeReplay(geometry, max_gap_s=max_gap_s)
            context, anchor_basis = identity, None
            anchor_record = None
        if not tracker.enabled:
            start = time.perf_counter_ns()
            aligned = tracker.align(points, frame_id, stamp)
            sample.update(
                reason="simulated_align" if aligned else "awaiting_reference",
                fit_ms=(time.perf_counter_ns() - start) / 1e6,
            )
            if aligned:
                anchor_record = record["sequence"]
                anchor_basis = solve_basis(record, geometry)
        else:
            sample.update(tracker.measure(points, frame_id, stamp))
            basis = solve_basis(record, geometry)
            if sample["valid"] and anchor_basis is not None and basis is not None:
                # Identical reference point, using recorded poses only for scoring.
                reference_target = geometry.rays([geometry.target_yx]) @ anchor_basis
                held_out = geometry.project(reference_target, basis)[0]
                held_out -= geometry.target_yx
                sample["solve_comparison_px"] = float(
                    np.linalg.norm(np.asarray(sample["residual_yx_px"]) - held_out)
                )
        sample["anchor_sequence"] = anchor_record
        sample["compute_ms"] = detector_ms + transform_ms + sample["fit_ms"]
        sample["saved_frame_gap_s"] = (
            stamp - previous_stamp if previous_stamp is not None else None
        )
        previous_stamp = stamp
        records.append(sample)
    measured = [
        r
        for r in records
        if r["reason"]
        not in {"simulated_align", "awaiting_reference", "recorded_motion"}
    ]
    failed = [r for r in measured if not r["recorded_solve_accepted"]]
    summary = dict(
        directory=str(directory.resolve()),
        solver_log_sha256=fingerprint(directory / "solver.jsonl"),
        manifest_sha256=fingerprint(directory / "manifest.json"),
        session_date_kst=datetime.fromtimestamp(
            manifest["requested_at"], ZoneInfo("Asia/Seoul")
        ).isoformat(),
        session_note=manifest.get("note"),
        saved_frames=len(records),
        evaluated_frames=len(measured),
        tracked_frames=sum(r["valid"] for r in measured),
        real_solve_failure_frames=len(failed),
        tracked_real_solve_failure_frames=sum(r["valid"] for r in failed),
        reasons=dict(Counter(r["reason"] for r in records)),
        solve_comparison_px=stats(r["solve_comparison_px"] for r in records),
        fit_ms=stats(r["fit_ms"] for r in measured),
        detector_ms=stats(r["detector_ms"] for r in records),
        compute_ms=stats(r.get("compute_ms") for r in records),
        saved_frame_gap_s=stats(r.get("saved_frame_gap_s") for r in records),
        max_gap_s=max_gap_s,
        min_stars=5,
        detector="detect_test_stars (offline fallback)",
        solves_hidden_from_tracker=True,
        closed_loop=False,
        limitation=(
            "Sparse stored RAW frames, not yesterday's cloud run. "
            "First suitable stationary frame simulates Align. No mount output. "
            "Recorded solves are noisy comparison measurements, not ground truth. "
            "CPU times exclude disk/hash/load and do not benchmark live MFDS."
        ),
    )
    return summary, records


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--runtime", type=Path, action="append", default=[])
    parser.add_argument("--capture", type=Path, action="append", default=[])
    parser.add_argument("--max-gap-s", type=float, default=10)
    args = parser.parse_args(argv)
    if not (args.synthetic or args.runtime or args.capture):
        parser.error("select at least one input")
    args.output.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).resolve().parents[1] / "MFNavis"
    report = dict(
        schema=1,
        host=platform.platform(),
        python=platform.python_version(),
        numpy=np.__version__,
        scipy=scipy.__version__,
        source_sha256={
            name: fingerprint(source / name)
            for name in (
                "visual_tracking.py",
                "visual_tracking_images.py",
                "solver_frame_map.py",
                "mf_wide_distortion.py",
            )
        },
        benchmark_sha256=fingerprint(__file__),
        runtime_audits=[],
        captures=[],
    )
    if args.synthetic:
        report["synthetic"], result = synthetic_benchmark()
        write_rows(args.output / "synthetic.jsonl", result)
        print("synthetic complete", flush=True)
    for path in args.runtime:
        report["runtime_audits"].append(audit_runtime(path))
    for index, path in enumerate(args.capture):
        summary, result = replay_capture(path, max_gap_s=args.max_gap_s)
        report["captures"].append(summary)
        write_rows(args.output / f"capture_{index}.jsonl", result)
        print(
            f"capture {path.name}: {summary['tracked_frames']}/"
            f"{summary['evaluated_frames']} measured",
            flush=True,
        )
    write_json(args.output / "summary.json", report)
    print(args.output / "summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
