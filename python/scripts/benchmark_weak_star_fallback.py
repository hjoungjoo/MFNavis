"""Test-only weak-star ROI tracking and pixel-level A/B benchmark.

No production module changes, camera capture, mount output or pointing writes.
Baseline is the previous five-star full-detection replay. Candidate searches
known star ROIs and still requires three spatially distributed inliers for pose.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import math
from pathlib import Path
import platform
import time

import numpy as np
from scipy import ndimage
from scipy.spatial.transform import Rotation

from PiFinder.visual_tracking import CameraGeometry, TrackingLimits, fit_star_pose
from PiFinder.visual_tracking_images import detect_test_stars
from scripts.benchmark_visual_fallback import (
    RelativeReplay,
    fingerprint,
    stats,
    write_json,
    write_rows,
)


def roi_centroid(image, expected, *, search=6, snr_min=5.5):
    """Background-rejected local matched filter with PSF and ambiguity checks."""
    center = np.rint(expected).astype(int)
    radius = search + 6
    y, x = center
    if (
        min(y, x) < radius
        or y + radius >= image.shape[0]
        or x + radius >= image.shape[1]
    ):
        return None, "outside_frame"
    patch = np.asarray(
        image[y - radius : y + radius + 1, x - radius : x + radius + 1], dtype=float
    )
    if not np.isfinite(patch).all():
        return None, "invalid_pixels"
    differences = np.diff(patch, axis=1)
    noise = max(
        1e-6,
        float(np.median(np.abs(differences - np.median(differences))))
        / (0.67449 * math.sqrt(2)),
    )
    signal = patch - ndimage.gaussian_filter(patch, 5)
    response = ndimage.gaussian_filter(signal, 1.2)
    region = response[6:-6, 6:-6]
    iy, ix = np.unravel_index(np.argmax(region), region.shape)
    iy, ix = iy + 6, ix + 6
    peak = response[iy, ix]
    if peak * math.sqrt(4 * math.pi * 1.2**2) / noise < snr_min:
        return None, "low_snr"
    yy, xx = np.indices(response.shape)
    competitors = response[
        (np.hypot(yy - iy, xx - ix) >= 4)
        & (np.abs(yy - radius) <= search)
        & (np.abs(xx - radius) <= search)
    ]
    if len(competitors) and np.max(competitors) > peak * 0.8:
        return None, "ambiguous_peak"
    offset = []
    for left, right in [
        (response[iy - 1, ix], response[iy + 1, ix]),
        (response[iy, ix - 1], response[iy, ix + 1]),
    ]:
        curvature = left - 2 * peak + right
        if curvature >= 0:
            return None, "flat_peak"
        offset.append(float(0.5 * (left - right) / curvature))
    if max(abs(v) for v in offset) > 0.75:
        return None, "unstable_peak"
    # A narrow hot pixel and a broad cloud lump may have a strong filter peak.
    # Compete explicit width models instead of accepting strength alone.
    local = signal[iy - 4 : iy + 5, ix - 4 : ix + 5]
    sy, sx = np.indices((9, 9)) - 4
    observed = local - local.mean()
    fits = []
    for width in (0.35, 0.9, 1.3, 1.8, 4.0):
        template = np.exp(
            -((sy - offset[0]) ** 2 + (sx - offset[1]) ** 2) / (2 * width**2)
        )
        template -= template.mean()
        energy = float(np.sum(template**2))
        amplitude = float(np.sum(template * observed) / energy)
        error = float(np.sum((observed - amplitude * template) ** 2))
        fits.append((error, width, amplitude * math.sqrt(energy) / noise))
    _, width, fitted_snr = min(fits)
    if width in (0.35, 4.0):
        return None, "nonstellar_shape"
    if fitted_snr < snr_min:
        return None, "low_snr"
    return center - radius + np.array([iy, ix]) + offset, "accepted"


class WeakStarReplay:
    """Fixed-reference experimental ROI tracker; not a deployed control policy."""

    def __init__(self, geometry, *, max_gap_s=5, max_stars=16):
        self.geometry = geometry
        self.limits = TrackingLimits(max_gap_s=max_gap_s, residual_px=0.8)
        self.max_stars = max_stars
        self.pose = np.eye(3)
        self.world = None
        self.enabled = False
        self.pending = []
        self.last_frame = -1
        self.last_time = -math.inf
        self.last_valid = -math.inf

    @staticmethod
    def distributed(points):
        if len(points) < 3:
            return False
        axes = np.linalg.svd(points - np.mean(points, axis=0), compute_uv=False)
        return axes[-1] >= 8.0

    def align(self, images, frame_id, stamp):
        """One clear frame or three settled weak frames; no truth star positions."""
        images = np.asarray(images, dtype=float)
        if images.ndim == 2:
            images = images[None]
        if (
            images.ndim != 3
            or len(images) not in (1, 3)
            or images.shape[1:] != (self.geometry.height, self.geometry.width)
            or not np.isfinite(images).all()
            or not math.isfinite(stamp)
        ):
            return False
        mean = np.mean(images, axis=0)
        candidates = detect_test_stars(mean, max_points=self.max_stars)
        accepted = []
        for candidate in candidates:
            point, _ = roi_centroid(mean, candidate)
            if point is None:
                continue
            if len(images) == 3:
                confirmations = [
                    roi_centroid(im, point, snr_min=4.5)[0] for im in images
                ]
                confirmed = [p for p in confirmations if p is not None]
                if len(confirmed) < 2 or any(
                    np.linalg.norm(p - point) > 0.8 for p in confirmed
                ):
                    continue
            if all(np.linalg.norm(point - p) >= 8 for p in accepted):
                accepted.append(point)
        points = np.asarray(accepted).reshape(-1, 2)
        if not self.distributed(points):
            return False
        self.world, self.pose = self.geometry.rays(points), np.eye(3)
        self.last_frame, self.last_time, self.last_valid = frame_id, stamp, stamp
        self.pending.clear()
        self.enabled = True
        return True

    def stop(self):
        self.enabled = False
        self.pending.clear()

    def _estimate(self, image):
        result = dict(
            valid=False,
            reason="insufficient_distributed_stars",
            matches=0,
            roll_measured=False,
            rejections={},
        )
        pose = None
        expected = self.geometry.project(self.world, self.pose)
        points, indices, reasons = [], [], Counter()
        for i, position in enumerate(expected):
            if not np.isfinite(position).all():
                reasons["outside_frame"] += 1
                continue
            point, reason = roi_centroid(image, position)
            reasons[reason] += 1
            if point is not None and all(
                np.linalg.norm(point - p) >= 8 for p in points
            ):
                points.append(point)
                indices.append(i)
        points = np.asarray(points).reshape(-1, 2)
        result.update(matches=len(points), rejections=dict(reasons))
        if not self.distributed(points):
            result["reason"] = "insufficient_distributed_stars"
        else:
            world = self.world[indices]
            pose, count, rmse = fit_star_pose(
                world, points, self.pose, self.geometry, self.limits
            )
            result.update(matches=count, rmse_px=rmse)
            if pose is None:
                result["reason"] = "inconsistent_motion"
            else:
                error = np.linalg.norm(
                    self.geometry.project(world, pose) - points, axis=1
                )
                if not self.distributed(points[error <= self.limits.residual_px]):
                    result["reason"] = "poor_inlier_distribution"
                else:
                    target = self.geometry.rays([self.geometry.target_yx])
                    residual = (
                        self.geometry.project(target, pose)[0] - self.geometry.target_yx
                    )
                    result.update(
                        valid=True,
                        reason="observed",
                        roll_measured=True,
                        residual_yx_px=residual.tolist(),
                    )
        return result, pose

    def measure(self, image, frame_id, stamp):
        start = time.perf_counter_ns()
        result = dict(
            valid=False,
            reason="not_aligned",
            matches=0,
            roll_measured=False,
            rejections={},
            coadded=False,
        )
        if not self.enabled:
            pass
        elif (
            not math.isfinite(stamp)
            or frame_id <= self.last_frame
            or stamp <= self.last_time
        ):
            result["reason"] = "stale_frame"
        elif np.shape(image) != (self.geometry.height, self.geometry.width):
            self.pending.clear()
            result["reason"] = "geometry_changed"
        else:
            self.last_frame, self.last_time = frame_id, stamp
            if stamp - self.last_valid > self.limits.max_gap_s:
                self.pending.clear()
                result["reason"] = "gap_exceeded"
            else:
                result, pose = self._estimate(image)
                result["coadded"] = False
                measurement_time = stamp
                if not result["valid"]:
                    # Non-overlapping, bounded temporal integration. It produces
                    # a delayed observation, never a fresh current-frame solve.
                    if self.pending and stamp - self.pending[0][0] > 0.4:
                        self.pending.clear()
                    self.pending.append(
                        (stamp, frame_id, np.asarray(image, dtype=float).copy())
                    )
                    if len(self.pending) == 3:
                        combined = np.mean([entry[2] for entry in self.pending], axis=0)
                        integrated, integrated_pose = self._estimate(combined)
                        if integrated["valid"] and self._confirm_current(
                            image, integrated_pose
                        ):
                            result, pose = integrated, integrated_pose
                            result["coadded"] = True
                            result["source_frame_ids"] = [
                                entry[1] for entry in self.pending
                            ]
                            measurement_time = float(
                                np.mean([entry[0] for entry in self.pending])
                            )
                        self.pending.clear()
                if result["valid"]:
                    self.pending.clear()
                    self.pose, self.last_valid = pose, measurement_time
                    result.update(
                        measurement_time=measurement_time,
                        age_s=stamp - measurement_time,
                    )
        result["compute_ms"] = (time.perf_counter_ns() - start) / 1e6
        return result

    def _confirm_current(self, image, pose):
        """Old photons in a stack must not invent stars in a newly blank frame."""
        confirmed = []
        for position in self.geometry.project(self.world, pose):
            if not np.isfinite(position).all():
                continue
            point, _ = roi_centroid(image, position, search=2, snr_min=4.0)
            if point is not None and np.linalg.norm(point - position) <= 0.8:
                confirmed.append(point)
        return self.distributed(np.asarray(confirmed).reshape(-1, 2))


POINTS = np.array(
    [
        [80, 90],
        [95, 405],
        [400, 110],
        [390, 390],
        [220, 190],
        [300, 320],
        [175, 330],
        [320, 65],
    ],
    dtype=float,
)


def truth_scene(index, count, shape=(512, 512)):
    """Independent pinhole projection, fixed stars and target, known rotation."""
    focal = shape[1] / (2 * np.tan(np.deg2rad(12) / 2))
    p = POINTS[:count]
    rays = np.column_stack(
        (
            np.ones(len(p)),
            (shape[1] / 2 - p[:, 1]) / focal,
            (shape[0] / 2 - p[:, 0]) / focal,
        )
    )
    rotation = Rotation.from_rotvec(
        [index * 0.0001, index * 0.00002, -index * 0.00003]
    ).as_matrix()
    camera = rays @ rotation.T
    points = np.column_stack(
        (
            shape[0] / 2 - focal * camera[:, 2] / camera[:, 0],
            shape[1] / 2 - focal * camera[:, 1] / camera[:, 0],
        )
    )
    center = np.array([1, 0, 0]) @ rotation.T
    residual = -focal * np.array([center[2] / center[0], center[1] / center[0]])
    return points, residual


def render(
    points, rng, *, peak=25, noise=5, index=0, nuisance="cloud", shape=(512, 512)
):
    yy, xx = np.indices(shape)
    background = (
        400 + 45 * np.sin((xx + index * 3) / 70) + 35 * np.cos((yy - index * 2) / 100)
    )
    if nuisance == "cloud":
        background += 90 * np.exp(
            -((xx - 170 - index) ** 2 + (yy - 220) ** 2) / (2 * 70**2)
        )
    image = background + rng.normal(0, noise, shape)
    for y, x in points:
        image += peak * np.exp(-((yy - y) ** 2 + (xx - x) ** 2) / (2 * 1.3**2))
    # Hot pixels remain fixed on sensor; independent of true star positions.
    for y, x in [(160, 160), (340, 240), (70, 440)]:
        image[y, x] += 600
    return image


def weak_benchmark(seed=41011, frames=32):
    geometry = CameraGeometry(512, 512, 12, (256, 256), "weak-synthetic")
    summaries, records = [], []
    for count in (0, 1, 2, 3, 4, 8):
        for peak in (8, 15, 25, 60):
            rng = np.random.default_rng(np.random.SeedSequence([seed, count, peak]))
            # Warm reference contains eight clear stars; later only count survive.
            reference = render(POINTS, rng, peak=100, index=0)
            baseline = RelativeReplay(geometry, max_gap_s=5)
            baseline.align(detect_test_stars(reference), 0, 0)
            candidate = WeakStarReplay(geometry)
            assert candidate.align(reference, 0, 0)
            group = []
            for index in range(1, frames + 1):
                points, truth = truth_scene(index, count)
                image = render(points, rng, peak=peak, index=index)
                started = time.perf_counter_ns()
                old = baseline.measure(detect_test_stars(image), index, index * 0.1)
                old_ms = (time.perf_counter_ns() - started) / 1e6
                new = candidate.measure(image, index, index * 0.1)
                row = dict(
                    stars=count,
                    peak=peak,
                    frame=index,
                    baseline_valid=old["valid"],
                    candidate_valid=new["valid"],
                    reason=new["reason"],
                    matches=new["matches"],
                    rejections=new["rejections"],
                    baseline_ms=old_ms,
                    candidate_ms=new["compute_ms"],
                    coadded=new.get("coadded", False),
                    observation_age_s=new.get("age_s"),
                    baseline_error_px=None,
                    candidate_error_px=None,
                    candidate_current_frame_error_px=None,
                )
                for label, result in (("baseline", old), ("candidate", new)):
                    if result["valid"]:
                        comparison = truth
                        if label == "candidate":
                            row["candidate_current_frame_error_px"] = float(
                                np.linalg.norm(
                                    np.asarray(result["residual_yx_px"]) - truth
                                )
                            )
                            _, comparison = truth_scene(
                                result["measurement_time"] / 0.1, count
                            )
                        row[label + "_error_px"] = float(
                            np.linalg.norm(
                                np.asarray(result["residual_yx_px"]) - comparison
                            )
                        )
                group.append(row)
            summaries.append(
                dict(
                    stars=count,
                    peak_adu=peak,
                    noise_sigma_adu=5,
                    frames=frames,
                    baseline_accepted=sum(r["baseline_valid"] for r in group),
                    candidate_accepted=sum(r["candidate_valid"] for r in group),
                    coadded_accepted=sum(
                        r["candidate_valid"] and r["coadded"] for r in group
                    ),
                    observation_age_s=stats(r["observation_age_s"] for r in group),
                    candidate_wrong_over_1px=sum(
                        r["candidate_error_px"] is not None
                        and r["candidate_error_px"] > 1
                        for r in group
                    ),
                    candidate_error_px=stats(r["candidate_error_px"] for r in group),
                    candidate_current_frame_error_px=stats(
                        r["candidate_current_frame_error_px"] for r in group
                    ),
                    baseline_ms=stats(r["baseline_ms"] for r in group),
                    candidate_ms=stats(r["candidate_ms"] for r in group),
                    reasons=dict(Counter(r["reason"] for r in group)),
                )
            )
            records.extend(group)
    return dict(
        seed=seed,
        geometry=asdict(geometry),
        cases=summaries,
        timing_scope="baseline full detector+fit versus candidate ROI+fit",
        note="Synthetic pixels, not the missing October 10 cloud images",
        closed_loop=False,
    ), records


def cold_start_benchmark(seed=41011, trials=10):
    geometry = CameraGeometry(512, 512, 12, (256, 256), "weak-synthetic")
    results = []
    for count in (0, 2, 3, 4, 8):
        for peak in (8, 15, 25):
            old_count, new_count, follow_count, within_three = 0, 0, 0, 0
            for trial in range(trials):
                rng = np.random.default_rng(
                    np.random.SeedSequence([seed, 99, count, peak, trial])
                )
                images = [
                    render(POINTS[:count], rng, peak=peak, index=0) for _ in range(3)
                ]
                baseline = RelativeReplay(geometry)
                old_count += baseline.align(detect_test_stars(images[-1]), 0, 0)
                candidate = WeakStarReplay(geometry)
                aligned = candidate.align(images, 0, 0)
                new_count += aligned
                # Fresh independent frame is required; stacking alone is not tracking.
                subsequent = [
                    candidate.measure(
                        render(POINTS[:count], rng, peak=peak), i, i * 0.1
                    )
                    for i in range(1, 4)
                ]
                follow_count += subsequent[0]["valid"]
                within_three += any(result["valid"] for result in subsequent)
            results.append(
                dict(
                    stars=count,
                    peak_adu=peak,
                    trials=trials,
                    baseline_aligned=old_count,
                    candidate_aligned=new_count,
                    candidate_tracked_next_frame=follow_count,
                    candidate_tracked_within_three=within_three,
                )
            )
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=41011)
    parser.add_argument("--frames", type=int, default=32)
    parser.add_argument("--cold-trials", type=int, default=10)
    args = parser.parse_args(argv)
    if args.frames < 1 or args.cold_trials < 1:
        parser.error("positive frames and cold trials required")
    args.output.mkdir(parents=True, exist_ok=False)
    report, records = weak_benchmark(args.seed, args.frames)
    write_rows(args.output / "frames.jsonl", records)
    print("warm-reference benchmark complete", flush=True)
    report["cold_start"] = cold_start_benchmark(args.seed, args.cold_trials)
    report.update(
        host=platform.platform(),
        python=platform.python_version(),
        benchmark_sha256=fingerprint(__file__),
        reference_code_sha256={
            name: fingerprint(Path(__file__).parents[1] / name)
            for name in (
                "scripts/benchmark_visual_fallback.py",
                "MFNavis/visual_tracking.py",
                "MFNavis/visual_tracking_images.py",
            )
        },
    )
    write_json(args.output / "summary.json", report)
    print(args.output / "summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
