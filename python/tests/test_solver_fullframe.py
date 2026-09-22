#!/usr/bin/python
# -*- coding:utf-8 -*-
"""Full-frame crop counts, centre-first solve ordering and motion recovery."""

import pytest

from PiFinder import solver

FULL_H, FULL_W = 1080, 1920
CROP_W = 980
TARGET_512 = (300.0, 340.0)


@pytest.mark.unit
def test_count_in_crop_uses_centred_window():
    # imx462: crop window is y 50..1030, x 470..1450
    centroids = [
        (540.0, 960.0),  # dead centre -> in
        (51.0, 471.0),  # just inside both edges -> in
        (49.0, 960.0),  # above the crop -> out
        (540.0, 1451.0),  # right of the crop -> out
        (1035.0, 960.0),  # below the crop -> out
    ]
    assert solver._count_in_crop(centroids, (FULL_H, FULL_W), CROP_W) == 2
    assert solver._count_in_crop([], (FULL_H, FULL_W), CROP_W) == 0
    assert solver._count_in_crop(None, (FULL_H, FULL_W), CROP_W) == 0


@pytest.mark.unit
def test_post_motion_raw_fast_path_releases_two_stationary_solves():
    bypass, remaining = solver._post_motion_raw_fast_path(
        frame_moving=True, raw_solved=False, remaining=0
    )
    assert bypass is False
    assert remaining == solver.POST_MOTION_RAW_FAST_FRAMES

    bypass, remaining = solver._post_motion_raw_fast_path(
        frame_moving=False, raw_solved=True, remaining=remaining
    )
    assert bypass is True
    assert remaining == 1

    bypass, remaining = solver._post_motion_raw_fast_path(
        frame_moving=False, raw_solved=True, remaining=remaining
    )
    assert bypass is True
    assert remaining == 0

    bypass, remaining = solver._post_motion_raw_fast_path(
        frame_moving=False, raw_solved=True, remaining=remaining
    )
    assert bypass is False


@pytest.mark.unit
def test_post_motion_fast_budget_waits_for_a_valid_raw_solve():
    bypass, remaining = solver._post_motion_raw_fast_path(
        frame_moving=False,
        raw_solved=False,
        remaining=solver.POST_MOTION_RAW_FAST_FRAMES,
    )
    assert bypass is False
    assert remaining == solver.POST_MOTION_RAW_FAST_FRAMES


@pytest.mark.unit
def test_fresh_mount_motion_status_marks_solver_frame_moving():
    status = {
        "updated": 100.0,
        "mount_motion_active": True,
        "goto_motion_active": True,
    }

    assert solver._mount_status_reports_motion(status, now=101.0) is True


@pytest.mark.unit
def test_stale_mount_motion_status_is_ignored():
    status = {"updated": 100.0, "mount_motion_active": True}

    assert solver._mount_status_reports_motion(status, now=106.0) is False


@pytest.mark.unit
def test_center_square_subset_selects_max_centered_square():
    # 1920x1080 -> square side 1080, x in [420, 1500)
    pts = [
        (540.0, 960.0),  # centre -> in
        (0.0, 420.0),  # on the left edge of the square -> in
        (1079.0, 1499.0),  # bottom-right inside corner -> in
        (540.0, 419.0),  # just left of the square -> out
        (540.0, 1500.0),  # just right of the square -> out
    ]
    kept = solver._center_square_subset(pts, (1080, 1920))
    assert len(kept) == 3
    assert solver._center_square_subset([], (1080, 1920)).shape == (0, 2)


@pytest.mark.unit
def test_center_first_remainder_prefers_sep_center_before_any_full_frame():
    calls = []

    def stage(name, solution):
        def run():
            calls.append(name)
            return solution

        return run

    solution, path = solver._solve_center_first_remainder(
        (
            ("sep_center", stage("sep_center", {"RA": 1.0})),
            ("cedar_full", stage("cedar_full", {"RA": 2.0})),
            ("sep_full", stage("sep_full", {"RA": 3.0})),
        )
    )

    assert path == "sep_center"
    assert solution["RA"] == 1.0
    assert calls == ["sep_center"]


@pytest.mark.unit
def test_center_first_remainder_uses_full_paths_only_after_center_failure():
    calls = []

    def stage(name, solution):
        def run():
            calls.append(name)
            return solution

        return run

    solution, path = solver._solve_center_first_remainder(
        (
            ("sep_center", stage("sep_center", {})),
            ("cedar_full", stage("cedar_full", {"RA": 2.0})),
            ("sep_full", stage("sep_full", {"RA": 3.0})),
        )
    )

    assert path == "cedar_full"
    assert solution["RA"] == 2.0
    assert calls == ["sep_center", "cedar_full"]


@pytest.mark.unit
def test_center_first_remainder_uses_sep_full_as_last_resort():
    calls = []

    def stage(name, solution):
        def run():
            calls.append(name)
            return solution

        return run

    solution, path = solver._solve_center_first_remainder(
        (
            ("sep_center", stage("sep_center", {})),
            ("cedar_full", stage("cedar_full", {})),
            ("sep_full", stage("sep_full", {"RA": 3.0})),
        )
    )

    assert path == "sep_full"
    assert solution["RA"] == 3.0
    assert calls == ["sep_center", "cedar_full", "sep_full"]
