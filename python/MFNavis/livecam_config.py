#!/usr/bin/python
# -*- coding:utf-8 -*-
"""Lightweight LiveCam settings helpers.

This module intentionally avoids importing numpy/Pillow so disabled LiveCam
status/control paths do not load the heavier RAW processing stack.
"""

from __future__ import annotations

from typing import Any


CONFIG_PREFIX = "livecam_"
STACK_FRAME_LIMIT_MAX = 500

# LiveCam preview processing remains session-only because it can be CPU-heavy
# and is only needed while that page is being inspected. Solver preprocessing
# is a production solve setting: it is persisted separately and restored after
# a restart.
SESSION_ONLY_KEYS = {"processing_enabled"}
SOURCE_ORIGINAL = "original_raw"
SOURCE_CROPPED = "cropped_raw"
# Post-processing pipeline stages between the cropped raw and the solver
# (camera_pi.capture() order). Selecting one shows that stage live, so the
# step that loses the stars can be found by eye instead of via one-shot
# stage dumps (camera_stage_dump).
SOURCE_BIAS_SUBTRACTED = "bias_subtracted"
SOURCE_DIGITAL_GAIN = "digital_gain"
SOURCE_STRETCHED_8BIT = "stretched_8bit"
SOURCE_RESIZED_512 = "resized_512"
SOURCE_SOLVER_INPUT = "solver_input"
SOURCE_STAR_ONLY = "star_only"
STAGE_SOURCES = (
    SOURCE_BIAS_SUBTRACTED,
    SOURCE_DIGITAL_GAIN,
    SOURCE_STRETCHED_8BIT,
    SOURCE_RESIZED_512,
    SOURCE_SOLVER_INPUT,
    SOURCE_STAR_ONLY,
)
OUTPUT_LATEST = "latest_selected_raw"
OUTPUT_STACK = "stack"
VALID_SOURCES = {SOURCE_ORIGINAL, SOURCE_CROPPED, *STAGE_SOURCES}
VALID_OUTPUTS = {OUTPUT_LATEST, OUTPUT_STACK}
VALID_STACK_MODES = {"mean", "sum", "max"}
# Raw Display = fixed linear ADU->8bit mapping (gain/exposure changes stay
# visible); the other modes percentile-stretch each frame for inspection.
PREVIEW_MODE_RAW = "raw_display"
VALID_PREVIEW_MODES = {PREVIEW_MODE_RAW, "stretched", "bayer_2x2_average"}
VALID_IMAGE_FORMATS = {"png", "jpeg", "webp"}
COLOR_MODE_THEME = "theme"
COLOR_MODE_COLOR = "color"
# Plain grayscale (mode "L"), no theme tint and no fabricated chroma.
COLOR_MODE_MONO = "mono"
VALID_COLOR_MODES = {COLOR_MODE_THEME, COLOR_MODE_COLOR, COLOR_MODE_MONO}


DEFAULT_SETTINGS: dict[str, Any] = {
    "processing_enabled": False,
    "solver_preprocess_enabled": True,
    "input_frame_source": SOURCE_ORIGINAL,
    "output_source": OUTPUT_LATEST,
    "stack_enabled": False,
    "stack_mode": "mean",
    "stack_frame_limit": 10,
    "preview_mode": "raw_display",
    "color_mode": COLOR_MODE_THEME,
    "low_percentile": 1.0,
    "high_percentile": 99.5,
    "display_size": 0,
    "web_image_format": "jpeg",
}


def normalize_settings(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = dict(DEFAULT_SETTINGS)
    if settings:
        merged.update(settings)

    merged["processing_enabled"] = _coerce_bool(merged.get("processing_enabled"))
    merged["solver_preprocess_enabled"] = _coerce_bool(
        merged.get("solver_preprocess_enabled")
    )

    if merged.get("input_frame_source") not in VALID_SOURCES:
        merged["input_frame_source"] = SOURCE_ORIGINAL
    if merged.get("output_source") not in VALID_OUTPUTS:
        merged["output_source"] = OUTPUT_LATEST
    merged["stack_enabled"] = merged["output_source"] == OUTPUT_STACK
    if merged.get("stack_mode") not in VALID_STACK_MODES:
        merged["stack_mode"] = "mean"
    if merged.get("preview_mode") not in VALID_PREVIEW_MODES:
        merged["preview_mode"] = "raw_display"
    if str(merged.get("color_mode")).lower() == "thema":
        merged["color_mode"] = COLOR_MODE_THEME
    if merged.get("color_mode") not in VALID_COLOR_MODES:
        merged["color_mode"] = COLOR_MODE_THEME
    if merged.get("web_image_format") not in VALID_IMAGE_FORMATS:
        merged["web_image_format"] = "jpeg"

    merged["low_percentile"] = _coerce_float(merged.get("low_percentile"), 1.0)
    merged["high_percentile"] = _coerce_float(merged.get("high_percentile"), 99.5)
    merged["stack_frame_limit"] = max(
        1, min(STACK_FRAME_LIMIT_MAX, _coerce_int(merged.get("stack_frame_limit"), 10))
    )
    merged["display_size"] = max(
        0, min(4096, _coerce_int(merged.get("display_size"), 0))
    )
    return merged


def settings_from_config(cfg) -> dict[str, Any]:
    values = {}
    for key, default in DEFAULT_SETTINGS.items():
        if key in SESSION_ONLY_KEYS:
            # Never read the persisted value; a fresh session always starts off.
            values[key] = default
        else:
            values[key] = cfg.get_option(f"{CONFIG_PREFIX}{key}", default)
    values["display_rotation_degrees"] = display_rotation_degrees(cfg)
    return normalize_settings(values)


def default_settings_for_config(cfg) -> dict[str, Any]:
    values = dict(DEFAULT_SETTINGS)
    values["display_rotation_degrees"] = display_rotation_degrees(cfg)
    return normalize_settings(values)


def save_settings_to_config(cfg, settings: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_settings(settings)
    for key in DEFAULT_SETTINGS:
        if key in SESSION_ONLY_KEYS:
            # Session-only switch: keep it in the returned/live settings but do
            # not persist it, so it cannot auto-resume on the next restart.
            continue
        cfg.set_option(f"{CONFIG_PREFIX}{key}", normalized[key])
    return normalized


def display_rotation_degrees(cfg) -> int:
    camera_rotation = cfg.get_option("camera_rotation")
    if camera_rotation is not None:
        return (int(camera_rotation) * -1) % 360

    screen_direction = cfg.get_option("screen_direction")
    if screen_direction in ["right", "straight", "flat3", "as_bloom"]:
        return 90
    return 270


def processing_enabled(settings: dict[str, Any] | None = None) -> bool:
    """Return whether the LiveCam pipeline should touch RAW frames."""

    return bool(normalize_settings(settings)["processing_enabled"])


def disabled_status(settings: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_settings(settings)
    return {
        "settings": normalized,
        "frame": None,
        "stack": {
            "processing_enabled": normalized["processing_enabled"],
            "input_frame_source": normalized["input_frame_source"],
            "stack_enabled": normalized["stack_enabled"],
            "output_source": normalized["output_source"],
            "mode": normalized["stack_mode"],
            "frame_limit": normalized["stack_frame_limit"],
            "frame_count": 0,
            "accepted_count": 0,
            "rejected_count": 0,
            "raw_shape": None,
            "display_shape": None,
            "web_image_format": normalized["web_image_format"],
            "last_error": None,
            "last_reject_reason": "disabled",
        },
        "enabled": False,
        "has_frame": False,
    }


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", ""}
    return bool(value)


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
