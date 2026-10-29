"""Coarse full-field acquisition and bounded native-pixel focus tracking."""

from dataclasses import replace
import math
import time

import numpy as np

from PiFinder import focus


class FocusTracker:
    def __init__(self, scan_interval=2.0):
        self.scan_interval = scan_interval
        self._last_scan = -float("inf")
        self._signature = None
        self._targets = ()

    @staticmethod
    def _coarse(frame):
        factor = 1
        while max(frame.shape) / factor > 640:
            factor *= 2
        h, w = frame.shape
        padded = np.pad(frame, ((0, (-h) % factor), (0, (-w) % factor)), mode="edge")
        coarse = padded.reshape(
            padded.shape[0] // factor, factor, padded.shape[1] // factor, factor
        ).mean(axis=(1, 3), dtype=np.float32)
        return coarse, factor

    def _acquire(self, frame, sigma_k):
        coarse, factor = self._coarse(frame)
        small, large, _, _, _ = focus._find_blobs(
            coarse,
            max_blob_px=max(2, math.ceil(50 / factor)),
            sigma_k=sigma_k,
            min_size_px=1,
        )
        # Broad donuts get reserved slots; isolated hot pixels fail native refinement.
        return tuple(
            replace(
                b,
                y=(b.y + 0.5) * factor - 0.5,
                x=(b.x + 0.5) * factor - 0.5,
                extent=b.extent * factor,
            )
            for b in (*small[:12], *large[:4])
        )

    @staticmethod
    def _refine(frame, seeds, sigma_k):
        found = []
        h, w = frame.shape
        for seed in seeds:
            radius = max(64, min(192, int(seed.extent * 1.5) + 20))
            top, left = max(0, int(seed.y) - radius), max(0, int(seed.x) - radius)
            bottom, right = (
                min(h, int(seed.y) + radius + 1),
                min(w, int(seed.x) + radius + 1),
            )
            patch = frame[top:bottom, left:right]
            small, large, _, _, _ = focus._find_blobs(
                patch, max_blob_px=50, sigma_k=sigma_k
            )
            for blob in (*small, *large):
                blob = replace(blob, y=blob.y + top, x=blob.x + left)
                # Keep a margin for unbiased background/apertures. Edge-of-sensor
                # stars use the same clipped apertures as the legacy detector.
                if (
                    abs(blob.y - seed.y) > radius / 2
                    or abs(blob.x - seed.x) > radius / 2
                ):
                    continue
                if any(math.hypot(blob.y - b.y, blob.x - b.x) < 4 for b in found):
                    continue
                # A small ROI can raise its background threshold inside a large
                # donut. Never turn that truncated core into a sharp-star HFD.
                extent = (
                    max(blob.extent, seed.extent) if seed.extent > 50 else blob.extent
                )
                blob = replace(
                    blob,
                    extent=extent,
                    background=focus._local_background(frame, blob.y, blob.x, extent),
                )
                found.append(blob)
        return tuple(
            sorted(found, key=lambda b: b.peak - b.background, reverse=True)[:16]
        )

    def measure(self, frame, *, sigma_k=5.0, reset=False, now=None):
        frame = np.asarray(frame)
        if frame.ndim != 2 or frame.size == 0:
            raise ValueError("Focus requires a non-empty 2D frame")
        if max(frame.shape) <= 640:
            return focus.focus_hfd(frame, sigma_k=sigma_k)
        now = time.monotonic() if now is None else now
        signature = (frame.shape, sigma_k)
        acquire = (
            reset
            or signature != self._signature
            or not self._targets
            or now - self._last_scan >= self.scan_interval
        )
        old_targets = self._targets
        seeds = self._acquire(frame, sigma_k) if acquire else old_targets
        targets = self._refine(frame, seeds, sigma_k)
        # Loss or a sudden move triggers acquisition now, never stale HFD display.
        lost = any(
            not any(math.hypot(a.y - b.y, a.x - b.x) < 24 for b in targets)
            for a in old_targets[:4]
        )
        if not acquire and (lost or not targets):
            acquire = True
            targets = self._refine(frame, self._acquire(frame, sigma_k), sigma_k)
        if acquire:
            self._last_scan = now
        self._signature = signature
        self._targets = targets
        small = [b for b in targets if b.extent <= 50]
        large = [b for b in targets if b.extent > 50]
        result = focus.measure_blobs(
            frame,
            small,
            large,
            float(np.median(frame[::8, ::8])),
            max((b.peak for b in targets), default=None),
            len(targets),
        )
        return replace(result, measurement_mode="scan" if acquire else "tracked")
