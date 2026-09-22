"""Tests for native-coordinate MF Brown--Conrady centroid correction."""

import numpy as np
import pytest

from PiFinder.mf_wide_distortion import (
    active_coefficients,
    distort_global_centroids,
    undistort_global_centroids,
)


pytestmark = pytest.mark.unit


def test_invalid_profile_never_activates_a_correction():
    assert active_coefficients(None) is None
    assert active_coefficients({"model": "none"}) is None
    assert (
        active_coefficients({"model": "brown_conrady", "coefficients": {"k1": "bad"}})
        is None
    )


def test_zero_profile_preserves_native_centroids():
    points = np.array([[10.0, 20.0], [300.0, 400.0]])
    corrected = undistort_global_centroids(
        points, (512, 512), {"k1": 0.0, "k2": 0.0, "k3": 0.0, "p1": 0.0, "p2": 0.0}
    )
    assert np.allclose(corrected, points)


def test_barrel_profile_moves_an_edge_centroid_outward_when_undistorting():
    point = np.array([[255.5, 500.0]])
    corrected = undistort_global_centroids(
        point, (512, 512), {"k1": -0.1, "k2": 0.0, "k3": 0.0, "p1": 0.0, "p2": 0.0}
    )
    assert corrected[0, 1] > point[0, 1]


@pytest.mark.parametrize("k1", [-0.11, -0.05, 0.0, 0.05])
def test_restoring_distortion_returns_top_and_bottom_stars_to_sensor(k1):
    points = np.array([[80.0, 180.0], [999.0, 1739.0], [539.5, 959.5]])
    coefficients = {"k1": k1, "k2": 0.005, "p1": 0.001, "p2": -0.002}
    corrected = undistort_global_centroids(points, (1080, 1920), coefficients)
    restored = distort_global_centroids(corrected, (1080, 1920), coefficients)
    np.testing.assert_allclose(restored, points, atol=0.05)


def test_forward_distortion_uses_sensor_axes_and_corner_radius():
    # On this frame the corner radius is 5 and the centre is (2.5, 3.5).
    # At (y, x) = (0, 1) in normalised units, radial=1.13;
    # tangential offsets are y=0.02, x=-0.03.
    corrected = np.array([[2.5, 8.5]])
    restored = distort_global_centroids(
        corrected,
        (6, 8),
        {"k1": 0.1, "k2": 0.02, "k3": 0.01, "p1": 0.02, "p2": -0.01},
    )
    np.testing.assert_allclose(restored, [[2.6, 9.0]])
