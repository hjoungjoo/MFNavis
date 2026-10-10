# MF_PiFinder Update — cedar + SEP Hybrid Solving, Field-Proven Under Light Pollution (2026-07-28)

> Community summary. Technical details live in the
> [integrated implementation document](../history/development/solver.md#mf_sep_fullframe_impl_ko) (Korean).
> 한국어판: [mf_cedar_sep_hybrid_solve_20260728_ko.md](mf_cedar_sep_hybrid_solve_20260728_ko.md)

## What this project is about

PiFinder is a device you attach to a telescope that figures out where it
is pointing by plate solving. Under heavy urban light pollution, though,
the camera only picks up a handful of stars and the stock solver
(cedar-detect) fails most of the time. This fork (MF_PiFinder) targets
**a finder that keeps solving accurately in skies where light pollution
leaves only a few visible stars** — and this week the core of that
capability was verified under a real sky.

## How it works — the cedar + SEP hybrid

The key idea: **don't replace the stock solver — combine the strengths
of two detectors.**

**1) The stock path (cedar) still runs first, unchanged.** Every frame
goes through the original PiFinder pipeline: crop, 8-bit conversion,
512×512 resize → cedar-detect → tetra3 solve. In star-rich skies this
path is as fast and proven as ever. **Stock behaviour is untouched.**

**2) When cedar fails, the SEP path takes over.** The camera also shares
each frame's **uncropped 12-bit sensor original**, and on attempts where
the cedar solve failed, a second detection runs on that original:

- **Why the original**: the stock path's 8-bit stretch crushes faint
  stars over a light-polluted background into 2–3 grey levels, and the
  crop cuts the field of view (star count) by more than half. The SEP
  path works on the full 12-bit data across the whole frame (2.16×
  the field).
- **How it detects**: 2×2 binning (2× SNR) → SEP (Source Extractor)
  mesh background subtraction — locally removes light-pollution
  gradients and cloud glow so faint stars survive → σ4.0 threshold
  extraction.
- **Four layers of false-positive defence**: a static warm-pixel map
  (47 sensor-defect positions, auto-generated), a point-source shape
  gate (rejects extended cloud fragments), a cluster gate (rejects the
  tight clumps of "detections" cloud edges produce — at this plate
  scale real stars are always isolated), and finally tetra3's pattern
  matching rejects whatever is left (zero false solves across the
  entire night).
- **Coordinate integrity**: SEP solutions are mapped by rotation and
  scale back into the original 512-space coordinate system (verified:
  solving the same sky through both paths gives 0° roll deviation and
  target-pixel agreement within 1 px), so tracking, push-to and
  alignment consume them **in exactly the same form as before**.
  Downstream code cannot tell which path solved.

**3) Alignment is hybrid too.** In skies cedar can handle, alignment
works exactly as stock; in skies it can't, the SEP solve computes the
alignment coordinate and feeds it back into the normal alignment chain
— making alignment possible under light pollution for the first time.

**4) No wasted effort.** When the sky stays unsolvable (clouds), the
second-stage attempts back off exponentially, and re-arm instantly the
moment stars reappear (detection count jump) — cloud-gap rescues are
never delayed.

**5) Coupled with auto-exposure.** The star-count auto-exposure anchors
on "the exposure that actually solved", so exposure stays locked in the
sweet spot instead of hunting while clouds pass.

## What was verified (central Seoul, twilight through night)

**Solving really works in a sky with only a handful of visible stars.**

- In this sky cedar found on average just 1 star and made zero direct
  solves, while the SEP path found 15–20 and **carried all of the
  solving**. During the better stretches the 5-minute solve rate hit
  88–98%.
- **Measured accuracy**: solve-to-solve scatter of RA 11″ / Dec 16″
  (1σ) — about a third of a camera pixel, ample for a finder.
- The hybrid alignment passed a quick field check as well.

## What else got fixed along the way

- **Warm pixels eliminated**: more than half of the night-sky
  detections turned out to be static sensor warm pixels; an
  auto-generated bad-pixel map now filters them.
- **Cloud false-positives eliminated**: cloud edges being mistaken for
  stars are rejected using the measured shape/distribution split
  between real stars and junk (real stars are always isolated point
  sources). Detection purity: 46% → 91%.
- **4.5× faster response**: solve cycle 1.35 s → 0.3 s (fixed
  per-frame costs removed from the pipeline).
- **Mono sensor cleanup**: the imx462 module measures as true mono
  despite its driver label — the "colour noise" in RAW was a debayer
  artifact. Preview and downloads are now full-resolution grayscale,
  with a lossless 16-bit TIFF download added.
- **Web LiveCam improvements**: an SEP overlay marks detections on the
  preview — **green = confirmed as a real star by the solver**
  (guaranteed no false positives), orange = unconfirmed candidate. One
  glance tells you whether the sky is solvable or clouded out.

## What's next

1. Final tuning validation on a long clear-night run (data accumulates
   automatically)
2. Precise alignment and push-to verification on an actual telescope
3. Once verified, finalize the division of labour with the stock
   solver and prepare a release

Feedback and questions welcome — especially from anyone using PiFinder
under light-polluted skies. Your real-world conditions (sky brightness,
situations where it struggles) will feed directly into tuning.
