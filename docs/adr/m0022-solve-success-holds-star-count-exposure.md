---
status: accepted
---

# A successful solve holds the star-count exposure

Field measurement (Seoul, 2026-07-26, imx462, gain 30): sweeping manual
exposures while reading the live solver's diagnostics gave a sharp sweet spot
under heavy light pollution —

| exposure | detections (sigma 8) | solved |
| --- | --- | --- |
| 25–50 ms | 0–6 | 0/12 |
| 100 ms | 4–9 | 4/6 |
| 200 ms | 9–13 | 6/6 |
| 400 ms | 2–6 | 1/6 |
| 800 ms | 0–6 | 0/6 |

Two facts break the star-count controller's assumptions at such a site:

1. **The reachable star count tops out below `target_stars`.** The best
   exposure detects ~9–14 stars against a target of 20, so `f < deadband_low`
   and the servo raises exposure — away from the only regime that solves.
2. **Past the sweet spot the count/exposure model inverts.** More exposure
   means *fewer* detections (sky glow eats star contrast), so the raise loses
   stars, which lowers `f`, which raises exposure further: positive feedback
   in the wrong direction. The bright-sky guard that should break this never
   fires — the processed frame's centre mean stays far below the 240 (8-bit)
   threshold on this pipeline even at 1 s.

## Decision

`ExposureStarCountController.update()` takes a `solve_success` flag (wired
from `solve_source == "CAM"`). When the attempt solved and the star fraction
is not *above* the deadband, the controller learns the current exposure as the
anchor, retires any bright ceiling, and holds — a star-count shortfall alone
never pulls the exposure away from a solving regime. Excess stars
(`f > deadband_high`) still step down: shortening a solving exposure keeps the
solve and reduces motion blur.

Convergence from a cold start needs no new mechanism: the recovery ladder
(ADR 0010/0021) already visits 200 ms and shorter rungs, and the first rung
that solves is captured by the hold.

## Addendum — same-night follow-ups (2026-07-26 field session)

Three more failures surfaced while testing this decision under moving
cloud, each fixed the same night:

1. **AE froze under IMU solve source** (80443cc6). The dispatch gated on
   `CAM`/`CAM_FAILED`; after any successful solve the IMU progresses the
   estimate, failed attempts surface as `IMU`, and auto-exposure stopped
   exactly when frames stopped solving (observed: saturated all-white
   frames pinned at 500 ms). The gate now admits `IMU`, and per-attempt
   success is `last_solve_success == last_solve_attempt` — which also
   corrects this ADR's original `solve_source == "CAM"` wiring.
2. **Raises jumped into saturation** (0b314906). A marginal sky (few
   stars) computed f ≈ 0.25 and raised 3–20× in one step, saturating the
   sensor and collapsing detections. Raises are now capped by brightness
   headroom: predicted background mean after the raise must stay ≤ the
   bright threshold (linear pipeline ⇒ mean scales with exposure).
3. **Low-star frames parked at the anchor forever** (24292966). The
   <4-star fallback assumed a transient; a sky that only ever shows 1–3
   stars at the anchor never expired the assumption. After 4 consecutive
   low-star attempts at the anchor the servo searches (safe under the
   headroom cap) until the count recovers. Bright low-star frames step
   down instead of returning to a bright anchor, and anchor returns
   respect an active bright ceiling.

4. **The exposure never sat still under broken cloud** (dd010295,
   2026-07-28). Solving worked — 34 solves in 2 minutes — but every
   passing cloud sent the controller hunting away from the exposure
   that had solved seconds earlier. A solve now opens a 90 s **anchor
   trust window** (refreshed by each solve): inside it, failed attempts
   hold the solved anchor — up to 8 consecutive zero-detection attempts
   wait out the cloud before the ladder engages, low-star frames skip
   the escape, shortfalls do not raise. The saturation defence and the
   excess-star trim still override the hold.

**Outcome**: the controller no longer freezes, saturates, parks, or
jitters — but the first night also showed the deeper limit: with only
1–3 detectable stars, no exposure policy can produce a solve (tetra3
needs ≥4). The binding constraint moved from control to detection
sensitivity; see
[mf_auto_exposure_field_review_20260726_ko.md](../mf_report/mf_auto_exposure_field_review_20260726_ko.md)
and the SEP full-frame detection path built in response
([mf_sep_fullframe_impl_ko.md](../history/development/solver.md#mf_sep_fullframe_impl_ko)).

## Alternatives considered

- **Lower `target_stars`.** Fixes this site, mistunes dark sky, and still
  leaves the inverted-model feedback in place at some other site.
- **Lower the bright-sky guard threshold.** The processed-frame mean depends
  on sensor profile stretch; no single constant is right, and the guard would
  still be a proxy. Solve success is the ground truth the proxy approximates.
- **Hill-climbing on the count/exposure slope.** Strictly more general, but
  stateful and noise-sensitive (a passing cloud looks like an inversion).
  Not needed once solving itself anchors the servo.
