"""Unit coverage for the optional MF wide-angle LiveCam overlay."""

import pytest

from PiFinder.mf_livecam_tiles import (
    active_focal_length_mm,
    excluded_tile_ids,
    optics_key,
    overlay_payload,
    wide_tiles_enabled,
)


pytestmark = pytest.mark.unit


def test_every_stated_lens_enables_its_livecam_tile_plan():
    assert wide_tiles_enabled("10mm")
    assert wide_tiles_enabled("16mm", 8.5)
    assert wide_tiles_enabled("12mm")
    assert wide_tiles_enabled("12mm", 10.1)
    assert not wide_tiles_enabled("")
    assert active_focal_length_mm("16mm", 7.64) == 7.64


def test_overlay_payload_is_normalized_and_keeps_exclusions():
    payload = overlay_payload(
        camera_type="imx296",
        lens_key="8mm",
        manual_focal_length_mm=None,
        frame_hw=(1080, 1920),
        excluded_ids=["C", "UR", 3],
    )

    assert payload["enabled"]
    assert payload["focal_length_mm"] == 8.0
    assert payload["tiles"]
    assert any(tile["id"] == "C" and tile["excluded"] for tile in payload["tiles"])
    assert all(0 <= tile["x"] <= 1 for tile in payload["tiles"])
    assert all(0 < tile["width"] <= 1 for tile in payload["tiles"])
    assert all(
        tile["crop_width"] == pytest.approx(512 / 1920) for tile in payload["tiles"]
    )
    assert all(
        tile["crop_height"] == pytest.approx(512 / 1080) for tile in payload["tiles"]
    )
    # Display cells are deliberately non-overlapping hit targets, unlike the
    # real crops used by the eventual solver.
    top = min(tile["y"] for tile in payload["tiles"])
    left = min(tile["x"] for tile in payload["tiles"])
    assert sum(
        tile["width"] for tile in payload["tiles"] if tile["y"] == top
    ) == pytest.approx(1.0)
    assert sum(
        tile["height"] for tile in payload["tiles"] if tile["x"] == left
    ) == pytest.approx(1.0)
    centre = next(tile for tile in payload["tiles"] if tile["id"] == "C")
    assert centre["x"] <= 0.5 <= centre["x"] + centre["width"]
    assert centre["y"] <= 0.5 <= centre["y"] + centre["height"]
    assert payload["overlaps"]
    assert all(0 < overlap["width"] <= 1 for overlap in payload["overlaps"])


def test_normal_lens_overlay_uses_recovery_grid_and_missing_frame_emits_none():
    normal = overlay_payload(
        camera_type="imx296",
        lens_key="12mm",
        manual_focal_length_mm=None,
        frame_hw=(1200, 1600),
    )
    assert normal["strategy"] == "recovery_grid"
    assert len(normal["tiles"]) == 9
    assert {tile["id"] for tile in normal["tiles"]} == {
        "UL",
        "U",
        "UR",
        "L",
        "C",
        "R",
        "DL",
        "D",
        "DR",
    }
    assert all(
        tile["crop_width"] * 1600 == pytest.approx(tile["crop_height"] * 1200)
        for tile in normal["tiles"]
    )
    assert (
        overlay_payload(
            camera_type="imx296",
            lens_key="8mm",
            manual_focal_length_mm=None,
            frame_hw=None,
        )["tiles"]
        == []
    )


def test_selected_calibrated_lens_keeps_its_effective_focal_length_for_tile_size():
    # The 12mm shipped lens is calibrated to 13.04mm effective focal length;
    # it must not be replaced by its 12.0mm nominal label in the LiveCam plan.
    payload = overlay_payload(
        camera_type="imx462_color",
        lens_key="12mm",
        manual_focal_length_mm=None,
        frame_hw=(1080, 1920),
    )

    assert {round(tile["crop_width"] * 1920) for tile in payload["tiles"]} == {914}


def test_six_mm_overlay_uses_field_validated_640px_solver_crops():
    payload = overlay_payload(
        camera_type="imx462_color",
        lens_key="6mm",
        manual_focal_length_mm=None,
        frame_hw=(1080, 1920),
    )

    assert payload["strategy"] == "wide_grid"
    assert len(payload["tiles"]) == 15
    assert {round(tile["crop_width"] * 1920) for tile in payload["tiles"]} == {640}
    assert {round(tile["crop_height"] * 1080) for tile in payload["tiles"]} == {640}


def test_display_rotation_names_native_solver_crops_in_video_coordinates():
    """A 90-degree Preview names every crop by its visible UDLR location."""

    # LiveCam rotates this IMX462 frame counter-clockwise after the solver
    # receives its native 1080x1920 image. The raw E crop is therefore the
    # visible U crop, while raw SW is visible at DR.
    payload = overlay_payload(
        camera_type="imx462_color",
        lens_key="16mm",
        manual_focal_length_mm=None,
        frame_hw=(1920, 1080),
        display_rotation_degrees=90,
    )

    assert payload["display_rotation_degrees"] == 90
    up = next(tile for tile in payload["tiles"] if tile["id"] == "U")
    down_right = next(tile for tile in payload["tiles"] if tile["id"] == "DR")

    assert payload["tile_id_coordinate_system"] == "video_udlr"
    assert up["crop_x"] == pytest.approx(50 / 1080)
    assert up["crop_y"] == pytest.approx(0)
    assert up["crop_width"] == pytest.approx(980 / 1080)
    assert up["crop_height"] == pytest.approx(980 / 1920)
    assert down_right["crop_x"] == pytest.approx(100 / 1080)
    assert down_right["crop_y"] == pytest.approx(940 / 1920)

    # Old raw-coordinate exclusions migrate to the same physical crop.
    migrated = overlay_payload(
        camera_type="imx462_color",
        lens_key="16mm",
        manual_focal_length_mm=None,
        frame_hw=(1920, 1080),
        display_rotation_degrees=90,
        excluded_ids=["E"],
    )
    assert next(tile for tile in migrated["tiles"] if tile["id"] == "U")["excluded"]


def test_persistent_exclusions_are_scoped_to_optical_train():
    assert optics_key("imx296", "8mm") != optics_key("imx296", "10mm")
    assert optics_key("imx296", "16mm", 8.0) != optics_key("imx296", "8mm")
    assert excluded_tile_ids(["C", "UR", "", 4]) == {"C", "UR"}
