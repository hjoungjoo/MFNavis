"""MF LiveCam tile overlay and persistent exclusion helpers.

This module owns the web-facing description only.  It does not change the
camera frame or the production solver; both remain on their established path
until the opt-in tile recovery solver is enabled separately.
"""

from __future__ import annotations

from typing import Any, cast

from PiFinder.mf_manual_lens import normalise_manual_focal_length
from PiFinder.mf_wide_tiles import (
    MFWideTilePlan,
    migrate_legacy_tile_ids,
    plan_tiles_for_focal,
)
from PiFinder.optics import get_lens, lens_is_stated, optical_train_for_profile


EXCLUDED_TILES_CONFIG_KEY = "mf_wide_excluded_tiles_by_optics"


def active_focal_length_mm(
    lens_key: str | None, manual_focal_length_mm: object = None
) -> float | None:
    """Return the selected focal length, preferring a valid manual override."""

    try:
        manual = normalise_manual_focal_length(manual_focal_length_mm, measured=True)
    except ValueError:
        manual = None
    if manual is not None:
        return manual
    if lens_is_stated(lens_key):
        return get_lens(str(lens_key)).nominal_focal_length_mm
    return None


def wide_tiles_enabled(
    lens_key: str | None, manual_focal_length_mm: object = None
) -> bool:
    """Whether LiveCam should expose tile tools for the selected lens.

    Lenses below 10 mm use the existing multi-tile wide grid.  At and above
    10 mm the same controls describe the central-crop-sized 3x3 recovery grid.
    """

    focal_length = active_focal_length_mm(lens_key, manual_focal_length_mm)
    return focal_length is not None


def optics_key(
    camera_type: str | None, lens_key: str | None, manual_focal_length_mm: object = None
) -> str:
    """Stable storage key so exclusions never leak to another optical train."""

    focal_length = active_focal_length_mm(lens_key, manual_focal_length_mm)
    focal = "unknown" if focal_length is None else f"{focal_length:.1f}mm"
    try:
        manual = normalise_manual_focal_length(manual_focal_length_mm, measured=True)
    except ValueError:
        manual = None
    lens = "manual" if manual is not None else (lens_key or "auto")
    return f"{camera_type or 'unknown'}:{lens}:{focal}"


def excluded_tile_ids(raw_value: object) -> set[str]:
    """Accept only simple tile identifiers from persisted JSON data."""

    if not isinstance(raw_value, (list, tuple, set)):
        return set()
    return {value for value in raw_value if isinstance(value, str) and value}


def overlay_payload(
    *,
    camera_type: str | None,
    lens_key: str | None,
    manual_focal_length_mm: object,
    frame_hw: tuple[int, int] | None,
    excluded_ids: object = (),
    display_rotation_degrees: int = 0,
) -> dict[str, Any]:
    """Build normalized solver-tile rectangles in LiveCam display coordinates.

    The solver operates on the native, unrotated camera frame.  LiveCam may
    subsequently rotate that frame for display, so the planned solver crops
    must be transformed before their names, hit regions and exclusion state
    are shown in the browser.
    """

    focal_length = active_focal_length_mm(lens_key, manual_focal_length_mm)
    payload: dict[str, Any] = {
        "enabled": wide_tiles_enabled(lens_key, manual_focal_length_mm),
        "focal_length_mm": focal_length,
        "optics_key": optics_key(camera_type, lens_key, manual_focal_length_mm),
        "tiles": [],
        "overlaps": [],
    }
    if not payload["enabled"] or frame_hw is None:
        return payload
    # ``enabled`` above is derived from this value, but keep the explicit
    # guard so malformed/manual inputs are also safe to type check.
    if focal_length is None:
        return payload

    try:
        display_height, display_width = (int(frame_hw[0]), int(frame_hw[1]))
        if display_height <= 0 or display_width <= 0:
            return payload
        rotation = _normalise_display_rotation(display_rotation_degrees)
        # A 90/270 degree display rotation swaps the dimensions.  Recover the
        # native solver frame shape before planning, then rotate all resulting
        # rectangles back into the displayed frame below.
        height, width = (
            (display_width, display_height)
            if rotation in (90, 270)
            else (display_height, display_width)
        )
        # resolve_camera_profile is intentionally used by the resolver in the
        # regular optics path.  Import here keeps this MF module independent
        # of the API/server lifecycle.
        from PiFinder.optics import resolve_camera_profile

        profile = resolve_camera_profile(camera_type or "")
        # Only an actual manual entry may replace a shipped lens's calibrated
        # effective focal length. ``focal_length`` is also the nominal value
        # of a selected 12mm/16mm lens, so passing it here would silently
        # discard that calibration.
        manual_override = normalise_manual_focal_length(
            manual_focal_length_mm, measured=True
        )
        full_train = optical_train_for_profile(profile, lens_key, manual_override)
        sixteen_train = optical_train_for_profile(profile, "16mm")
        plan = plan_tiles_for_focal(
            (height, width),
            full_train.fov_degrees,
            sixteen_train.fov_degrees,
            float(focal_length),
            central_tile_size_px=full_train.profile.crop_size[0],
            display_rotation_degrees=rotation,
        )
    except (TypeError, ValueError):
        return payload

    selected = migrate_legacy_tile_ids(excluded_tile_ids(excluded_ids), plan)
    payload["strategy"] = plan.strategy
    payload["display_rotation_degrees"] = rotation
    payload["tile_id_coordinate_system"] = "video_udlr"
    payload["tiles"] = _rotate_overlay_rectangles(
        _normalised_tiles(plan, selected), plan.frame_hw, rotation
    )
    payload["overlaps"] = _rotate_overlay_rectangles(
        _normalised_overlaps(plan), plan.frame_hw, rotation
    )
    return payload


def _normalise_display_rotation(rotation: object) -> int:
    """Return a supported LiveCam display rotation without raising."""

    try:
        value = int(cast(Any, rotation)) % 360
    except (TypeError, ValueError):
        return 0
    return value if value in (0, 90, 180, 270) else 0


def _rotate_normalised_rect(
    rect: dict[str, Any], source_hw: tuple[int, int], rotation: int
) -> dict[str, Any]:
    """Rotate one normalized rectangle exactly as ``numpy.rot90`` does."""

    source_height, source_width = source_hw
    x = float(rect["x"]) * source_width
    y = float(rect["y"]) * source_height
    width = float(rect["width"]) * source_width
    height = float(rect["height"]) * source_height

    if rotation == 90:  # np.rot90(frame, 1), counter-clockwise
        x, y, width, height = y, source_width - (x + width), height, width
        target_height, target_width = source_width, source_height
    elif rotation == 180:
        x, y = source_width - (x + width), source_height - (y + height)
        target_height, target_width = source_height, source_width
    elif rotation == 270:  # np.rot90(frame, 3), clockwise
        x, y, width, height = source_height - (y + height), x, height, width
        target_height, target_width = source_width, source_height
    else:
        target_height, target_width = source_height, source_width

    transformed = dict(rect)
    transformed.update(
        {
            "x": x / target_width,
            "y": y / target_height,
            "width": width / target_width,
            "height": height / target_height,
        }
    )
    return transformed


def _rotate_overlay_rectangles(
    rectangles: list[dict[str, Any]], source_hw: tuple[int, int], rotation: int
) -> list[dict[str, Any]]:
    """Rotate selection or overlap regions, preserving their metadata."""

    transformed_rectangles: list[dict[str, Any]] = []
    for rect in rectangles:
        transformed = _rotate_normalised_rect(rect, source_hw, rotation)
        if "crop_x" in rect:
            crop = _rotate_normalised_rect(
                {
                    "x": rect["crop_x"],
                    "y": rect["crop_y"],
                    "width": rect["crop_width"],
                    "height": rect["crop_height"],
                },
                source_hw,
                rotation,
            )
            transformed.update(
                {
                    "crop_x": crop["x"],
                    "crop_y": crop["y"],
                    "crop_width": crop["width"],
                    "crop_height": crop["height"],
                }
            )
        transformed_rectangles.append(transformed)
    return transformed_rectangles


def _selection_spans(
    centres: list[float], length: int
) -> dict[int, tuple[float, float]]:
    """Split an axis at the midpoint between each neighbouring tile centre."""

    boundaries = [0.0]
    boundaries.extend((left + right) / 2.0 for left, right in zip(centres, centres[1:]))
    boundaries.append(float(length))
    return {
        index: (boundaries[index], boundaries[index + 1])
        for index in range(len(centres))
    }


def _normalised_tiles(
    plan: MFWideTilePlan, excluded_ids: set[str]
) -> list[dict[str, Any]]:
    """Return non-overlapping hit regions mapped to the real crop candidates.

    Solver crops intentionally overlap.  Rendering those literal crop boxes
    makes a web editor impossible to use, because a click can hit multiple
    candidates.  The overlay therefore divides the frame at crop-centre
    midpoints: each displayed cell selects exactly one real solver crop.
    """

    height, width = plan.frame_hw
    rows = sorted({tile.row for tile in plan.tiles})
    columns = sorted({tile.column for tile in plan.tiles})
    row_centres = [
        next(
            tile.rect.y + tile.rect.height / 2.0
            for tile in plan.tiles
            if tile.row == row
        )
        for row in rows
    ]
    column_centres = [
        next(
            tile.rect.x + tile.rect.width / 2.0
            for tile in plan.tiles
            if tile.column == column
        )
        for column in columns
    ]
    y_spans = _selection_spans(row_centres, height)
    x_spans = _selection_spans(column_centres, width)
    return [
        {
            "id": tile.tile_id,
            "x": x_spans[tile.column][0] / width,
            "y": y_spans[tile.row][0] / height,
            "width": (x_spans[tile.column][1] - x_spans[tile.column][0]) / width,
            "height": (y_spans[tile.row][1] - y_spans[tile.row][0]) / height,
            # The logical cell above is a non-overlapping click target.  Keep
            # the actual native 512px crop too, so LiveCam can show exactly
            # what an exclusion affects in the future solver.
            "crop_x": tile.rect.x / width,
            "crop_y": tile.rect.y / height,
            "crop_width": tile.rect.width / width,
            "crop_height": tile.rect.height / height,
            "central": tile.is_central,
            "excluded": tile.tile_id in excluded_ids,
        }
        for tile in plan.tiles
    ]


def _normalised_overlaps(plan: MFWideTilePlan) -> list[dict[str, float]]:
    """Return non-overlapping cells covered by two or more native tiles."""

    height, width = plan.frame_hw
    xs = sorted(
        {edge for tile in plan.tiles for edge in (tile.rect.x, tile.rect.x_end)}
    )
    ys = sorted(
        {edge for tile in plan.tiles for edge in (tile.rect.y, tile.rect.y_end)}
    )
    overlaps: list[dict[str, float]] = []
    for y0, y1 in zip(ys, ys[1:]):
        for x0, x1 in zip(xs, xs[1:]):
            centre_y, centre_x = (y0 + y1) / 2.0, (x0 + x1) / 2.0
            coverage = sum(
                tile.rect.y <= centre_y < tile.rect.y_end
                and tile.rect.x <= centre_x < tile.rect.x_end
                for tile in plan.tiles
            )
            if coverage >= 2:
                overlaps.append(
                    {
                        "x": x0 / width,
                        "y": y0 / height,
                        "width": (x1 - x0) / width,
                        "height": (y1 - y0) / height,
                    }
                )
    return overlaps
