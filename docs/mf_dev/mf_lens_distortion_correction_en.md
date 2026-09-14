# Lens Distortion Correction in the Current Source

## Applied method

The current implementation does not resample the image into a rectified image.
Cedar or SEP first detects star centroids in each original RAW tile, and only
those coordinates are undistorted in the full-sensor coordinate system. This
avoids changing stellar intensity or PSF through image interpolation.

The processing sequence is:

1. Detect star centroids `(y, x)` in the original tile.
2. Add the tile origin to obtain full-frame coordinates.
3. Load an active calibration profile matching the camera, lens, RAW/crop
   geometry, and pixel pitch.
4. Numerically invert the Brown–Conrady model with eight fixed-point iterations.
5. Convert the corrected points back to tile-local coordinates and pass them to
   the tetra3 solver.

The core implementation is in `python/PiFinder/mf_wide_distortion.py`; it is
called from `python/PiFinder/solver.py`, and its position in the solve pipeline
is defined in `python/PiFinder/mf_wide_solver.py`.

## Formula

For a frame of size `(H, W)`, the optical centre and normalization scale are:

```text
cy = (H - 1) / 2
cx = (W - 1) / 2
s  = sqrt((H/2)^2 + (W/2)^2)     # centre-to-corner radius
yd = (Yd - cy) / s
xd = (Xd - cx) / s
```

Let `(xu, yu)` be the undistorted normalized coordinates and
`r² = xu² + yu²`. The forward Brown–Conrady model is:

```text
radial = 1 + k1*r² + k2*r⁴ + k3*r⁶

x_model = xu*radial + 2*p1*xu*yu + p2*(r² + 2*xu²)
y_model = yu*radial + p1*(r² + 2*yu²) + 2*p2*xu*yu
```

Because the input `(xd, yd)` is already distorted, the implementation uses the
following fixed-point update for eight iterations instead of a closed-form
inverse:

```text
xu <- xu + (xd - x_model)
yu <- yu + (yd - y_model)
```

It starts with `xu = xd` and `yu = yd`, then converts the result back to pixels:

```text
Yu = yu*s + cy
Xu = xu*s + cx
```

`k1`, `k2`, and `k3` are radial coefficients; `p1` and `p2` are tangential
coefficients. This project normalizes coordinates so that the frame-corner
radius is one; it does not use a focal-length-based camera matrix `K` here.

## Manual TV-distortion seed

When a provisional profile is created from a lens data sheet, the first-order
radial coefficient is scaled to the physical sensor footprint:

```text
r_sensor = sqrt((crop_width*pitch/2)^2 + (crop_height*pitch/2)^2)
k1_initial = sign * abs(TV_percent)/100 * (r_sensor/r_reference)^2
```

The sign is `-1` for barrel distortion and `+1` for pincushion distortion.
Unknown `k2`, `k3`, `p1`, and `p2` values are set to zero. This is a provisional
seed, not a final measured calibration.

## Current stored profile and runtime state

`PiFinder_data/config.json` selects an on-sky profile for
`imx462_color + 6mm`:

```text
model = brown_conrady
k1 = -0.04389242740018018
k2 = k3 = p1 = p2 = 0
evidence = 6 frames, 2 sky directions, 138 matched stars
central/mid/edge samples = 26/75/37
median RMSE = 97.0 arcsec -> 56.09 arcsec (42.18% improvement)
```

However, `wide_solver_enabled` is currently `false` in the same configuration.
The profile is stored and selected, but the wide-tile solver and its centroid
correction are inactive at runtime. The correction is used only when this flag
is enabled and the tile-solver eligibility conditions are met.

The current runtime source also does not contain the coefficient-fitting
algorithm itself. It implements validation and persistence of externally
produced/on-sky coefficients, plus the correction algorithm that consumes them.

## Safety behavior

- Correction is skipped unless the model is `brown_conrady` and all
  coefficients are finite numbers.
- Empty centroid lists and invalid frame dimensions preserve the input.
- If an iteration produces NaN or infinity, all original coordinates are
  returned unchanged.
- A profile is not loaded when its fingerprint does not match the camera,
  lens, RAW/crop geometry, and pixel pitch.

## Auto measurement and manual lenses (2026-09-14)

Advanced → Lens → **Auto (Measure)** opens a live progress page. A separate blind
plate solve measures the central crop without the previous FOV or distortion
correction. Five fresh, stationary, quality-qualified frames with consistent
focal lengths (within 1%) are required before the measured scale is saved as a
**Manual** lens. The effective focal length is derived from sensor pixel pitch
and crop width and retained to four decimal places in mm. The completion page
shows the measured crop FOV and applied manual focal length.

The page reports accepted frames, stars and waiting/measuring status. Back cancels
without changing the current optics. Motion resets confirmation; camera/lens
changes invalidate pending results. A session times out after three minutes of
processing without a stable fit. If the camera stops delivering frames entirely,
the page remains waiting and Back can cancel it.

Both entered and automatically measured manual lenses support **Distortion →
Measure Sky**. Their calibration profiles are isolated by camera and precise
manual focal length, persist across restarts, and are not reused for another
manual value or a named lens. Selecting a named lens clears the manual override.
Auto measures optical scale; distortion fitting and eyepiece alignment remain
separate measurements.

While Auto or distortion measurement is active, automatic sleep is held so the
progress page remains visible and camera frames keep arriving. Normal sleep
policy resumes after completion or cancellation.
