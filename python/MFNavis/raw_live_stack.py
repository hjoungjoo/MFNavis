#!/usr/bin/python
# -*- coding:utf-8 -*-
"""RAW LiveCam preview and lightweight live-stack helpers.

This module keeps the new RAW preview/stack behavior away from the existing
camera and solver paths. Camera backends publish one selected RAW frame here;
the web API then turns that frame into a display-sized PNG/JPEG/WebP image.
"""

from __future__ import annotations

import io
import json
import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from PiFinder.observation import observation_snapshot
from PiFinder.solver_capture import json_value
from PiFinder.livecam_config import (
    solver_preprocess_status,
    COLOR_MODE_COLOR,
    COLOR_MODE_MONO,
    COLOR_MODE_THEME,
    OUTPUT_LATEST,
    PREVIEW_MODE_RAW,
    SOURCE_CROPPED,
    SOURCE_ORIGINAL,
    SOURCE_STAR_ONLY,
    STAGE_SOURCES,
    VALID_IMAGE_FORMATS,
    normalize_settings,
)

RESAMPLE_BILINEAR = getattr(getattr(Image, "Resampling", Image), "BILINEAR")


@dataclass
class RawFrameInfo:
    source: str
    shape: tuple[int, int]
    dtype: str
    raw_format: str | None
    rotation_90: int
    display_rotation_degrees: int
    min_value: float
    max_value: float
    p01: float
    p50: float
    p995: float
    camera_type: str | None = None
    exposure_us: float | None = None
    gain: float | None = None
    timestamp: float | None = None
    frame_id: int | None = None
    # Sensor delivers plain luminance (CameraProfile.mono): the raw_format
    # label keeps its bit-depth meaning for Raw Display scaling, but its
    # Bayer pattern must NOT trigger a debayer -- that would halve the
    # display resolution and fabricate chroma from noise.
    mono: bool = False

    @classmethod
    def from_array(
        cls,
        frame: np.ndarray,
        *,
        source: str,
        rotation_90: int,
        display_rotation_degrees: int = 0,
        raw_format: str | None = None,
        camera_type: str | None = None,
        exposure_us: float | None = None,
        gain: float | None = None,
        timestamp: float | None = None,
        frame_id: int | None = None,
        mono: bool = False,
    ) -> "RawFrameInfo":
        arr = np.asarray(frame)
        if arr.size == 0:
            min_value = max_value = p01 = p50 = p995 = 0.0
        else:
            min_value = float(np.min(arr))
            max_value = float(np.max(arr))
            p01, p50, p995 = [float(v) for v in np.percentile(arr, [1.0, 50.0, 99.5])]
        return cls(
            source=source,
            shape=(int(arr.shape[0]), int(arr.shape[1])),
            dtype=str(arr.dtype),
            raw_format=raw_format,
            rotation_90=rotation_90,
            display_rotation_degrees=display_rotation_degrees,
            min_value=min_value,
            max_value=max_value,
            p01=p01,
            p50=p50,
            p995=p995,
            camera_type=camera_type,
            exposure_us=exposure_us,
            gain=gain,
            timestamp=timestamp,
            frame_id=frame_id,
            mono=mono,
        )


@dataclass
class StackState:
    processing_enabled: bool
    input_frame_source: str
    stack_enabled: bool
    output_source: str
    mode: str
    frame_limit: int
    frame_count: int
    accepted_count: int
    rejected_count: int
    raw_shape: tuple[int, int] | None
    display_shape: tuple[int, int] | None
    web_image_format: str
    last_error: str | None
    last_reject_reason: str | None


def publish_selected_frame(
    shared_state,
    settings: dict[str, Any],
    profile,
    camera_type: str,
    original_raw: np.ndarray | None,
    cropped_raw: np.ndarray | None,
    metadata: dict[str, Any] | None = None,
    stage_frames: dict[str, np.ndarray] | None = None,
) -> None:
    """Publish the currently selected RAW frame for LiveCam consumers.

    Disabled processing returns before touching shared state. The control API
    clears any previous shared frame once when the top-level switch is turned
    off, so the camera loop does not pay a per-frame manager write cost.

    ``stage_frames`` carries the post-processing pipeline stages
    (``STAGE_SOURCES``); when the selected source is a stage the caller does
    not have, nothing is published for this frame -- a later call site in the
    pipeline owns it (``solver_input`` is published by the camera loop, after
    rotation, not by ``capture()``).
    """

    normalized = normalize_settings(settings)
    if not normalized["processing_enabled"]:
        return

    metadata = metadata or {}
    source = normalized["input_frame_source"]
    rotation_90 = int(getattr(profile, "rotation_90", 0) or 0)
    display_rotation = int(normalized.get("display_rotation_degrees", 0) or 0) % 360
    raw_format = getattr(profile, "format", None)
    mono = bool(getattr(profile, "mono", False))

    if source == SOURCE_CROPPED:
        selected = cropped_raw
    elif source in STAGE_SOURCES:
        selected = (stage_frames or {}).get(source)
        # 8-bit stages are no longer in sensor ADU: leave raw_format out so
        # the Raw Display preview scales by the frame's own dtype.
        if selected is not None and np.asarray(selected).dtype == np.uint8:
            raw_format = None
    else:
        selected = original_raw
        if selected is not None and rotation_90:
            selected = np.rot90(selected, rotation_90)
    if source == SOURCE_STAR_ONLY and selected is not None and rotation_90:
        selected = np.rot90(selected, rotation_90)
    if selected is None:
        return

    selected = _rotate_display(selected, display_rotation)
    selected = np.ascontiguousarray(selected).copy()
    timestamp = float(metadata.get("timestamp") or time.time())
    frame_id = int(metadata.get("frame_id") or time.time_ns())
    info = RawFrameInfo.from_array(
        selected,
        source=source,
        rotation_90=rotation_90 if source in {SOURCE_ORIGINAL, SOURCE_STAR_ONLY} else 0,
        display_rotation_degrees=display_rotation,
        raw_format=raw_format,
        camera_type=camera_type,
        exposure_us=_optional_float(metadata.get("ExposureTime")),
        gain=_optional_float(metadata.get("AnalogueGain")),
        timestamp=timestamp,
        frame_id=frame_id,
        mono=mono,
    )
    shared_state.set_raw_live_frame({"frame": selected, "info": asdict(info)})


def publish_solver_preprocessed_frame(
    shared_state,
    frame: np.ndarray,
    profile,
    camera_type: str,
    metadata: dict[str, Any] | None = None,
    *,
    preprocess_frames: int,
    display_rotation_degrees: int = 0,
) -> None:
    """Cache the exact star-only frame being consumed by Cedar+SEP.

    This runs in the solver process, never the capture process. LiveCam can
    therefore switch to the already-warm production preprocessor without
    creating a duplicate five-frame accumulator or adding camera latency.
    """

    metadata = metadata or {}
    display_rotation = int(display_rotation_degrees or 0) % 360
    selected = _rotate_display(np.asarray(frame), display_rotation)
    selected = np.ascontiguousarray(selected).copy()
    timestamp = float(
        metadata.get("timestamp") or metadata.get("exposure_end") or time.time()
    )
    frame_id = int(metadata.get("frame_id") or time.time_ns())
    info = RawFrameInfo.from_array(
        selected,
        source=SOURCE_STAR_ONLY,
        # The solver RAW was already rotated into the same orientation as the
        # original LiveCam input before preprocessing.
        rotation_90=0,
        display_rotation_degrees=display_rotation,
        raw_format=getattr(profile, "format", None),
        camera_type=camera_type,
        exposure_us=_optional_float(
            metadata.get("actual_exposure_us", metadata.get("exposure_time"))
        ),
        gain=_optional_float(metadata.get("actual_gain", metadata.get("gain"))),
        timestamp=timestamp,
        frame_id=frame_id,
        mono=bool(getattr(profile, "mono", False)),
    )
    info_payload = asdict(info)
    info_payload.update(
        {
            "producer": "solver_preprocessor",
            "preprocess_state": "ready",
            "preprocess_frames": int(preprocess_frames),
        }
    )
    shared_state.set_solver_preprocessed_frame(
        {"frame": selected, "info": info_payload}
    )


class DisplayFrameBuilder:
    def __init__(
        self,
        low_percentile: float = 1.0,
        high_percentile: float = 99.5,
        display_size: int = 0,
        preview_mode: str = "raw_display",
        color_mode: str = COLOR_MODE_THEME,
        web_theme: str = "grey",
        raw_format: str | None = None,
        mono: bool = False,
        native_resolution: bool = False,
    ) -> None:
        self.low_percentile = low_percentile
        self.high_percentile = high_percentile
        self.display_size = display_size
        self.preview_mode = preview_mode
        self.color_mode = color_mode
        self.web_theme = web_theme
        self.raw_format = raw_format
        self.mono = mono
        self.native_resolution = native_resolution

    def build(self, frame: np.ndarray) -> Image.Image:
        arr = _prepare_display_frame(
            np.asarray(frame),
            self.preview_mode,
            self.raw_format,
            self.mono,
            native_resolution=self.native_resolution,
        )

        if self.preview_mode == PREVIEW_MODE_RAW:
            # "Raw Display" means what it says: a fixed linear mapping of the
            # sensor's ADU range to 8 bit, no per-frame normalization. The
            # percentile stretch below rescales every frame to the same
            # display range, which cancels a global multiplication -- with it,
            # changing gain or exposure produced a visually identical preview.
            scaled = _linear_scale(arr, self.raw_format)
        else:
            scaled = _percentile_stretch(
                arr,
                low_percentile=self.low_percentile,
                high_percentile=self.high_percentile,
            )
        if self.color_mode == COLOR_MODE_THEME:
            image = Image.fromarray(
                _theme_tint(_luminance(scaled), self.web_theme), mode="RGB"
            )
        elif self.color_mode == COLOR_MODE_MONO:
            image = Image.fromarray(_luminance(scaled), mode="L")
        elif scaled.ndim == 3:
            image = Image.fromarray(scaled, mode="RGB")
        else:
            image = Image.fromarray(scaled, mode="L")
        if self.display_size > 0 and not self.native_resolution:
            image.thumbnail((self.display_size, self.display_size), RESAMPLE_BILINEAR)
        return image


class RawLiveStackProcessor:
    def __init__(self) -> None:
        self._frames: deque[np.ndarray] = deque()
        self._accumulator: np.ndarray | None = None
        self._max_frame: np.ndarray | None = None
        self._frame_count = 0
        self._accepted_count = 0
        self._rejected_count = 0
        self._last_frame_id: int | None = None
        self._raw_shape: tuple[int, int] | None = None
        self._input_source: str | None = None
        self._mode = "mean"
        self._frame_limit = 10
        self._last_error: str | None = None
        self._last_reject_reason: str | None = None
        self._last_display_shape: tuple[int, int] | None = None

    def reset(self) -> None:
        self._frames.clear()
        self._accumulator = None
        self._max_frame = None
        self._frame_count = 0
        self._accepted_count = 0
        self._rejected_count = 0
        self._last_frame_id = None
        self._raw_shape = None
        self._input_source = None
        self._frame_limit = 10
        self._last_error = None
        self._last_reject_reason = None
        self._last_display_shape = None

    def status(self, shared_state, settings: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_settings(settings)
        info = (
            _shared_info(shared_state, normalized)
            if normalized["processing_enabled"]
            else None
        )
        preprocess = solver_preprocess_status(shared_state, normalized)
        return {
            "settings": normalized,
            "frame": info,
            "stack": asdict(
                StackState(
                    processing_enabled=normalized["processing_enabled"],
                    input_frame_source=normalized["input_frame_source"],
                    stack_enabled=normalized["stack_enabled"],
                    output_source=normalized["output_source"],
                    mode=normalized["stack_mode"],
                    frame_limit=normalized["stack_frame_limit"],
                    frame_count=self._frame_count,
                    accepted_count=self._accepted_count,
                    rejected_count=self._rejected_count,
                    raw_shape=self._raw_shape,
                    display_shape=self._last_display_shape,
                    web_image_format=normalized["web_image_format"],
                    last_error=self._last_error,
                    last_reject_reason=self._last_reject_reason,
                )
            ),
            "enabled": normalized["processing_enabled"],
            "has_frame": bool(info),
            "preprocess": preprocess,
        }

    def render_image(
        self,
        shared_state,
        settings: dict[str, Any],
        *,
        image_format: str | None = None,
        web_theme: str = "grey",
        color_mode: str | None = None,
        accept_new_frame: bool = True,
        overlay_sep: bool = False,
        overlay_mark: bool = False,
        native_resolution: bool = False,
    ) -> tuple[bytes, str] | None:
        normalized = normalize_settings(settings)
        if not normalized["processing_enabled"]:
            return None
        if color_mode is not None:
            normalized["color_mode"] = color_mode

        entry = _shared_entry(shared_state, normalized)
        if not entry:
            self._last_reject_reason = "no-frame"
            return None

        frame = np.asarray(entry["frame"])
        info = entry.get("info") or {}
        display_source = self._resolve_display_source(
            normalized, frame, info, accept_new_frame
        )

        builder = DisplayFrameBuilder(
            low_percentile=normalized["low_percentile"],
            high_percentile=normalized["high_percentile"],
            display_size=normalized["display_size"],
            preview_mode=normalized["preview_mode"],
            color_mode=normalized["color_mode"],
            web_theme=web_theme,
            raw_format=info.get("raw_format"),
            mono=bool(info.get("mono")),
            native_resolution=native_resolution,
        )
        image = builder.build(display_source)
        if overlay_sep and info.get("source") == SOURCE_ORIGINAL:
            overlay = None
            if hasattr(shared_state, "sep_overlay"):
                try:
                    overlay = shared_state.sep_overlay()
                except Exception:
                    overlay = None
            # Stale markers (SEP off, solver stalled) are worse than none.
            if overlay and (
                abs(
                    float(info.get("timestamp") or 0)
                    - float(overlay.get("timestamp") or 0)
                )
                < 10.0
            ):
                image = _draw_sep_overlay(image, overlay, info)
        if overlay_mark:
            from PiFinder.livecam_mark import draw_mark_overlay

            image = draw_mark_overlay(image, info, shared_state, web_theme)
        if not native_resolution:
            self._last_display_shape = (int(image.size[1]), int(image.size[0]))
        return encode_image(image, image_format or normalized["web_image_format"])

    def _resolve_display_source(
        self,
        normalized: dict[str, Any],
        frame: np.ndarray,
        info: dict[str, Any],
        accept_new_frame: bool,
    ) -> np.ndarray:
        """Pick the frame the viewer/downloader should see (latest vs stack),
        optionally feeding the new frame into the stack first."""
        frame_id = info.get("frame_id")
        if normalized["stack_enabled"] and accept_new_frame:
            self._accept_frame(frame, info, normalized)
            display_source = self._stack_display_frame(normalized)
            if display_source is None:
                display_source = frame
        elif normalized["stack_enabled"]:
            display_source = self._stack_display_frame(normalized)
            if display_source is None:
                display_source = frame
        else:
            display_source = frame
            self._last_frame_id = frame_id

        if (
            normalized["output_source"] == OUTPUT_LATEST
            or not normalized["stack_enabled"]
        ):
            display_source = frame
        return display_source

    def render_raw_tiff(
        self, shared_state, settings: dict[str, Any]
    ) -> tuple[bytes, str] | None:
        """Lossless 16-bit grayscale TIFF of the current display source.

        Unlike ``render_image`` this skips the display pipeline entirely:
        no percentile stretch, no 8-bit conversion, no debayer -- the raw
        ADU values (or the stack: mean/max stay in sensor range, ``sum``
        clips at 65535) go straight into the file for offline processing.
        Never feeds the stack (download semantics, like accept_new_frame
        False).
        """
        normalized = normalize_settings(settings)
        if not normalized["processing_enabled"]:
            return None
        entry = _shared_entry(shared_state, normalized)
        if not entry:
            self._last_reject_reason = "no-frame"
            return None
        frame = np.asarray(entry["frame"])
        info = entry.get("info") or {}
        source = self._resolve_display_source(
            normalized, frame, info, accept_new_frame=False
        )
        arr = np.asarray(source, dtype=np.float32)
        if arr.ndim != 2:
            return None
        arr16 = np.clip(np.rint(arr), 0, 65535).astype(np.uint16)
        image = Image.fromarray(arr16, mode="I;16")
        buf = io.BytesIO()
        description = {
            "observation": observation_snapshot(shared_state),
            "input_frame_info": json_value(info),
            "stack_enabled": normalized["stack_enabled"],
            "output_source": normalized["output_source"],
            "stack_note": "input_frame_info identifies latest input, not all stacked exposures",
        }
        image.save(
            buf, format="TIFF", tiffinfo={270: json.dumps(description, allow_nan=False)}
        )
        return buf.getvalue(), "image/tiff"

    def _accept_frame(
        self, frame: np.ndarray, info: dict[str, Any], settings: dict[str, Any]
    ) -> None:
        frame_id = info.get("frame_id")
        source = info.get("source")
        shape = (int(frame.shape[0]), int(frame.shape[1]))
        mode = settings["stack_mode"]
        frame_limit = int(settings["stack_frame_limit"])

        if frame_id is not None and frame_id == self._last_frame_id:
            return

        reset_needed = (
            self._raw_shape != shape
            or self._input_source != source
            or self._mode != mode
            or self._frame_limit != frame_limit
        )
        if reset_needed:
            self.reset()
            self._raw_shape = shape
            self._input_source = source
            self._mode = mode
            self._frame_limit = frame_limit

        self._last_frame_id = frame_id

        frame_sample = np.asarray(frame).copy()
        frame_f = frame_sample.astype(np.float32, copy=False)

        if mode == "max":
            self._frames.append(frame_sample)
            self._max_frame = _max_from_frames(self._frames)
        else:
            if self._accumulator is None:
                self._accumulator = np.zeros(shape, dtype=np.float32)
            self._frames.append(frame_sample)
            self._accumulator += frame_f

        while len(self._frames) > frame_limit:
            old = self._frames.popleft()
            if mode == "max":
                self._max_frame = _max_from_frames(self._frames)
            elif self._accumulator is not None:
                self._accumulator -= old.astype(np.float32, copy=False)

        self._frame_count = len(self._frames)
        self._accepted_count += 1
        self._last_reject_reason = None

    def _stack_display_frame(self, settings: dict[str, Any]) -> np.ndarray | None:
        if settings["stack_mode"] == "max":
            return self._max_frame
        if self._accumulator is None:
            return None
        if settings["stack_mode"] == "sum":
            return self._accumulator
        return self._accumulator / max(1, len(self._frames))


MATCHED_MARK_RGB = (0, 255, 128)  # tetra3-confirmed star
CANDIDATE_MARK_RGB = (255, 150, 0)  # unconfirmed detection


def _draw_sep_overlay(
    image: Image.Image, overlay: dict[str, Any], info: dict[str, Any]
) -> Image.Image:
    """Mark SEP detections (post warm-pixel mask) on the preview image.

    Two tiers: centroids the last solve actually MATCHED are drawn green
    (confirmed stars -- zero false positives by construction); everything
    else is orange, INCLUDING all detections on frames with no solve.
    Green strictly means "tetra3 confirmed this" -- an unsolvable cloudy
    frame must never wear the trusted colour (field lesson 2026-07-28).

    Detection centroids are in solver_raw full-frame (y, x); the published
    frame additionally has the display rotation applied, so the centroids
    get the same rotation (solver_frame_map's pinned convention) and are
    then scaled to the rendered image. A mismatch between the rotated
    canvas and the displayed frame shape (source switched mid-flight,
    stack of another geometry) skips the overlay rather than mislabel.
    """
    from PiFinder import solver_frame_map as sfm

    try:
        cents = np.asarray(overlay.get("centroids") or [], dtype=np.float64)
        matched = np.asarray(overlay.get("matched") or [], dtype=np.float64)
        frame_hw = tuple(overlay.get("frame_hw") or ())
        if cents.ndim != 2 or len(cents) == 0 or len(frame_hw) != 2:
            return image
        rotation = float(info.get("display_rotation_degrees") or 0)
        rotated, canvas = sfm.rotate_centroids(cents, frame_hw, rotation)
        if tuple(info.get("shape") or ()) != tuple(canvas):
            return image
        rmatched = np.empty((0, 2))
        if matched.ndim == 2 and len(matched):
            rmatched, _ = sfm.rotate_centroids(matched, frame_hw, rotation)
        sx = image.size[0] / canvas[1]
        sy = image.size[1] / canvas[0]
        if image.mode != "RGB":
            image = image.convert("RGB")
        draw = ImageDraw.Draw(image)
        radius = max(3.0, 90.0 * sx / 16.0)

        def _circle(y, x, color):
            cx, cy = float(x) * sx, float(y) * sy
            draw.ellipse(
                [cx - radius, cy - radius, cx + radius, cy + radius],
                outline=color,
                width=1,
            )

        for y, x in rotated:
            near = (
                np.hypot(rmatched[:, 0] - y, rmatched[:, 1] - x).min()
                if len(rmatched)
                else np.inf
            )
            # 8 px: cedar-solved frames map matched stars from 512 space
            # (scale ~1.9x), so the SEP detection of the same star can sit
            # a few px off the mapped position.
            if near > 8.0:  # not among the matched (or nothing matched)
                _circle(y, x, CANDIDATE_MARK_RGB)
        for y, x in rmatched:
            _circle(y, x, MATCHED_MARK_RGB)
        return image
    except Exception:
        return image


def encode_image(image: Image.Image, image_format: str) -> tuple[bytes, str]:
    fmt = image_format if image_format in VALID_IMAGE_FORMATS else "jpeg"
    pil_format = {"jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}[fmt]
    mimetype = {"jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}[fmt]
    buf = io.BytesIO()
    if fmt == "jpeg":
        if image.mode not in {"L", "RGB"}:
            image = image.convert("RGB")
        image.save(buf, format=pil_format, quality=85, optimize=True)
    else:
        image.save(buf, format=pil_format)
    return buf.getvalue(), mimetype


def download_image_format(settings: dict[str, Any]) -> str:
    """The web_image_format setting governs downloads only -- the live
    preview always streams JPEG (PNG encoding drops the refresh rate), so
    the format picked in the UI is delivered exactly as chosen here."""
    normalized = normalize_settings(settings)
    return normalized["web_image_format"]


def download_color_mode(shared_state, settings: dict[str, Any] | None = None) -> str:
    """Grayscale for mono frames, real colour for declared colour variants.

    A mono sensor's Bayer label is a driver artifact: the RGB it debayers
    into is pure chroma noise (docs/mf_dev/mf_sep_fullframe_impl_ko.md §6.4),
    so luminance keeps the data and drops the artifact. A device declared as
    the real CFA variant (CameraProfile.mono False, carried on the published
    frame info) keeps its measured chroma. No frame info defaults to mono --
    the conservative side."""
    info = _shared_info(shared_state, settings) or {}
    return COLOR_MODE_MONO if info.get("mono", True) else COLOR_MODE_COLOR


def _theme_tint(luminance: np.ndarray, web_theme: str) -> np.ndarray:
    theme_rgb = {
        "red": (232.0, 75.0, 63.0),
        "grey": (224.0, 224.0, 224.0),
    }.get(web_theme, (224.0, 224.0, 224.0))
    alpha = np.asarray(luminance, dtype=np.float32) / 255.0
    tinted = np.empty((*alpha.shape, 3), dtype=np.uint8)
    for channel, color in enumerate(theme_rgb):
        tinted[..., channel] = np.clip(alpha * color, 0, 255).astype(np.uint8)
    return tinted


def _prepare_display_frame(
    frame: np.ndarray,
    preview_mode: str,
    raw_format: str | None,
    mono: bool = False,
    *,
    native_resolution: bool = False,
) -> np.ndarray:
    arr = np.asarray(frame)
    if arr.ndim == 3:
        return arr
    # A mono sensor's Bayer label is a driver artifact (CameraProfile.mono):
    # debayering luminance halves the resolution and fabricates chroma from
    # noise, so keep the full-resolution 2D frame. The explicit
    # bayer_2x2_average preview (plain 2x2 binning on mono) stays available.
    if _is_bayer_format(raw_format) and not mono:
        if native_resolution:
            return _bayer_native_rgb(arr, raw_format)
        return _bayer_2x2_rgb(arr, raw_format)
    if preview_mode == "bayer_2x2_average" and not native_resolution:
        return _bayer_2x2_average(arr)
    return arr


def _is_bayer_format(raw_format: str | None) -> bool:
    return _bayer_pattern(raw_format) is not None


def _bayer_pattern(raw_format: str | None) -> str | None:
    if not raw_format:
        return None
    normalized = str(raw_format).upper()
    for pattern in ("RGGB", "BGGR", "GRBG", "GBRG"):
        if pattern in normalized:
            return pattern
    return None


def _bayer_native_rgb(frame: np.ndarray, raw_format: str | None) -> np.ndarray:
    """Bilinear demosaic at sensor resolution, including odd-sized edges.

    Keep floating-point stack values until the existing display scaling step.
    Normalized interpolation preserves measured samples and handles edges
    without introducing black borders or changing channel brightness.
    """
    from scipy.ndimage import convolve

    arr = np.asarray(frame, dtype=np.float32)
    pattern = _bayer_pattern(raw_format) or "RGGB"
    kernel = np.array([[1, 2, 1], [2, 4, 2], [1, 2, 1]], dtype=np.float32)
    rgb = np.empty((*arr.shape, 3), dtype=np.float32)
    for channel, color in enumerate("RGB"):
        mask = np.zeros(arr.shape, dtype=np.float32)
        for index, sample in enumerate(pattern):
            if sample == color:
                mask[index // 2 :: 2, index % 2 :: 2] = 1
        weights = convolve(mask, kernel, mode="mirror")
        values = convolve(arr * mask, kernel, mode="mirror")
        rgb[..., channel] = np.divide(
            values, weights, out=arr.copy(), where=weights > 0
        )
    return rgb


def _bayer_2x2_rgb(frame: np.ndarray, raw_format: str | None) -> np.ndarray:
    """Convert a Bayer mosaic into a half-resolution RGB image."""

    arr = np.asarray(frame, dtype=np.float32)
    h = arr.shape[0] - (arr.shape[0] % 2)
    w = arr.shape[1] - (arr.shape[1] % 2)
    if h <= 0 or w <= 0:
        return np.zeros((1, 1, 3), dtype=np.float32)
    arr = arr[:h, :w]
    pattern = _bayer_pattern(raw_format) or "RGGB"
    if pattern == "BGGR":
        red = arr[1::2, 1::2]
        green = (arr[0::2, 1::2] + arr[1::2, 0::2]) / 2.0
        blue = arr[0::2, 0::2]
    elif pattern == "GRBG":
        red = arr[0::2, 1::2]
        green = (arr[0::2, 0::2] + arr[1::2, 1::2]) / 2.0
        blue = arr[1::2, 0::2]
    elif pattern == "GBRG":
        red = arr[1::2, 0::2]
        green = (arr[0::2, 0::2] + arr[1::2, 1::2]) / 2.0
        blue = arr[0::2, 1::2]
    else:
        red = arr[0::2, 0::2]
        green = (arr[0::2, 1::2] + arr[1::2, 0::2]) / 2.0
        blue = arr[1::2, 1::2]
    return np.dstack((red, green, blue))


def _max_from_frames(frames: deque[np.ndarray]) -> np.ndarray | None:
    if not frames:
        return None
    max_frame = np.asarray(frames[0], dtype=np.float32).copy()
    for frame in list(frames)[1:]:
        np.maximum(max_frame, np.asarray(frame, dtype=np.float32), out=max_frame)
    return max_frame


def _rotate_display(frame: np.ndarray, degrees: int) -> np.ndarray:
    if degrees == 90:
        return np.rot90(frame, 1)
    if degrees == 180:
        return np.rot90(frame, 2)
    if degrees == 270:
        return np.rot90(frame, 3)
    return frame


def _solver_preprocessed_selected(settings: dict[str, Any] | None) -> bool:
    if not settings:
        return False
    normalized = normalize_settings(settings)
    return bool(
        normalized["input_frame_source"] == SOURCE_STAR_ONLY
        and normalized["solver_preprocess_enabled"]
    )


def _shared_entry(
    shared_state, settings: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    if _solver_preprocessed_selected(settings) and hasattr(
        shared_state, "solver_preprocessed_frame"
    ):
        entry = shared_state.solver_preprocessed_frame()
        if not entry or not isinstance(entry, dict) or "frame" not in entry:
            return None
        return entry
    if not hasattr(shared_state, "raw_live_frame"):
        return None
    entry = shared_state.raw_live_frame()
    if not entry or not isinstance(entry, dict) or "frame" not in entry:
        return None
    return entry


def _shared_info(
    shared_state, settings: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Frame metadata only -- the cheap path for status polls.

    The dedicated accessor keeps the multi-MB frame out of the manager
    pickle; fall back to the full entry for shared-state doubles that
    don't implement it."""
    if _solver_preprocessed_selected(settings) and hasattr(
        shared_state, "solver_preprocessed_frame_info"
    ):
        try:
            info = shared_state.solver_preprocessed_frame_info()
            return info if isinstance(info, dict) else None
        except Exception:
            return None
    if hasattr(shared_state, "raw_live_frame_info"):
        try:
            info = shared_state.raw_live_frame_info()
            return info if isinstance(info, dict) else None
        except Exception:
            return None
    entry = _shared_entry(shared_state, settings)
    return entry.get("info") if entry else None


def _bit_depth_from_raw_format(raw_format: str | None) -> int | None:
    """Sensor bit depth parsed from a raw format name ("SRGGB12" -> 12)."""
    if not raw_format:
        return None
    digits = "".join(ch for ch in str(raw_format) if ch.isdigit())
    if not digits:
        return None
    try:
        depth = int(digits)
    except ValueError:
        return None
    return depth if 8 <= depth <= 16 else None


def _linear_scale(frame: np.ndarray, raw_format: str | None) -> np.ndarray:
    """Fixed linear ADU -> 8-bit mapping (no per-frame normalization).

    The white point comes from the sensor bit depth, not the frame content,
    so a brighter capture renders brighter instead of being renormalized
    away. A stack in ``sum`` mode can exceed the sensor range and clips
    white -- that is inherent to summing onto a fixed scale; use the
    stretched preview to inspect a sum stack.
    """
    arr = np.asarray(frame, dtype=np.float32)
    if arr.size == 0:
        return np.zeros((1, 1), dtype=np.uint8)
    depth = _bit_depth_from_raw_format(raw_format)
    if depth is None:
        dtype = np.asarray(frame).dtype
        depth = 8 if dtype == np.uint8 else 16
    max_adu = float(2**depth - 1)
    scaled = arr * (255.0 / max_adu)
    return np.clip(scaled, 0, 255).astype(np.uint8)


def _percentile_stretch(
    frame: np.ndarray, *, low_percentile: float, high_percentile: float
) -> np.ndarray:
    arr = np.asarray(frame, dtype=np.float32)
    if arr.size == 0:
        return np.zeros((1, 1), dtype=np.uint8)
    low, high = [
        float(v) for v in np.percentile(arr, [low_percentile, high_percentile])
    ]
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        low = float(np.min(arr))
        high = float(np.max(arr))
    if high <= low:
        high = low + 1.0
    scaled = (arr - low) * (255.0 / (high - low))
    return np.clip(scaled, 0, 255).astype(np.uint8)


def _luminance(frame: np.ndarray) -> np.ndarray:
    arr = np.asarray(frame)
    if arr.ndim != 3:
        return arr
    return (
        arr[..., 0].astype(np.float32) * 0.299
        + arr[..., 1].astype(np.float32) * 0.587
        + arr[..., 2].astype(np.float32) * 0.114
    ).astype(np.uint8)


def _bayer_2x2_average(frame: np.ndarray) -> np.ndarray:
    arr = np.asarray(frame, dtype=np.float32)
    h = arr.shape[0] - (arr.shape[0] % 2)
    w = arr.shape[1] - (arr.shape[1] % 2)
    if h <= 0 or w <= 0:
        return arr
    arr = arr[:h, :w]
    return (arr[0::2, 0::2] + arr[1::2, 0::2] + arr[0::2, 1::2] + arr[1::2, 1::2]) / 4.0


def _optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
