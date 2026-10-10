# Three-Path Solver Bench — cedar crop / cedar full-frame σ8 / cedar+SEP hybrid (2026-08-01)

> Field measurement from the night of 2026-08-01 comparing three solver
> configurations on identical frames under the same sky. For background
> and architecture see the
> [integrated implementation doc](../history/development/solver.md#mf_sep_fullframe_impl_ko) and
> [ADR m0023](../adr/m0023-cedar-sep-hybrid-solving.md).
> 한국어판: [mf_solver_3path_bench_20260801_ko.md](mf_solver_3path_bench_20260801_ko.md)

## 1. Conditions

- **When/where**: 2026-08-01 21:36–21:52 KST, Seoul. Southern sky
  (RA≈230°, Dec≈−29°, toward Lup), tube fixed (no tracking; RA drift
  15.2″/s = sidereal, as expected).
- **Camera**: imx462, **manual exposure 200 ms / gain 30, fixed**
  (auto-exposure off).
- **Sky brightness**: raw background p50 **3,558/4095 = 87% of full
  scale** — one of the brighter nights this fork has seen (light
  pollution + haze). The sky improved noticeably during the session
  (SEP matches med 9 → 16, live solve rate 41% → 100%).

## 2. Method

**Offline, three paths on the same 50 frames** — 50 stage dumps captured
12 s apart (10 min). Per frame:

| Path | Input | Detection | Solve |
| --- | --- | --- | --- |
| **A. cedar crop (current primary)** | `06_solver_input.png` (512², bit-exact production input) | cedar σ8 / max_size 10 / binned / hot=on (production parameters) | tetra3 (512², FOV 12°) |
| **B. cedar full-frame** | `00_raw_full.png` (1920×1080 12-bit) → production stretch (bias 238 subtract, 8-bit) | cedar **σ8 / hot=on / binned=on** (the requested configuration) | centroids rotated 90° + FOV-scale mapped, then tetra3 |
| **C. hybrid (current production)** | 12-bit raw, only when A fails | `sep_detect` σ4.0 + warm-pixel map + shape/cluster gates (production modules as-is) | tetra3 via `solver_frame_map` (production-identical) |

cedar was reached on the running cedar-detect-server (port 50551) over
**inline gRPC only** (avoids clobbering the live solver's shared-memory
segment). Scripts: session scratchpad `bench3.py` /
`aggregate_bench.py`.

**Same-exposure verification**: with a continuously changing sky, paths
are only comparable on the very same capture. A stage dump is by design
the stage-by-stage record of a single exposure; additionally, for all 50
frames, statistics recomputed from `00_raw_full` (input to B and C)
through the production chain (crop → bias subtract → 8-bit stretch) were
verified **bit-identical (50/50)** — min/max/mean/p50 — to the same
dump's 8-bit stage and `06_solver_input` (input to A). All three paths
therefore see the same single exposure per frame; C's cedar first pass
reuses A's result directly.

**Live hybrid (production untouched)** — `/api/solution` polled at
0.15 s for 15 minutes; **all 1,632 attempts** recorded. Same time window
as the offline capture.

## 3. Results

### 3.1 Solve rate and detection (offline 50 frames + live 1,632 attempts)

| Metric | A cedar crop | B cedar full-frame σ8 | C hybrid |
| --- | --- | --- | --- |
| **Solve rate (offline, 50 frames)** | **0% (0/50)** | **18% (9/50)** | **88% (44/50)** |
| Solve rate (live, 15 min) | 0/1,632 (zero direct cedar solves) | — | **89.5%** (≈100% over the last 10 min) |
| Detections med | 1 (p90 1) | 5 (p90 9) — **only 1 inside the crop window** | SEP 17 (p90 23) |
| Matches med (when solved) | — | 8 | 10 (live med 13, max 22) |
| Purity (matches/detections) | — | **89%** | 60% |
| RMSE med | — | 90″ | 81″ (live 87″) |

- Under this sky the **cedar crop path is completely blind** (0–1
  detections per frame). Not one direct cedar solve in 15 live minutes —
  SEP carried every solve.
- **cedar full-frame (requested σ8+hot+binned) reaches 18%**: it finds
  med 5 stars, but only 1 inside the crop window — i.e. most of its gain
  is real stars from the 2.16× wider field, not deeper detection. Best
  purity (89%) and best per-solve accuracy, but not enough sensitivity
  at this sky brightness. The "3× matches vs 512" potential measured in
  §6.7 (dark sky) does not materialise on a bright night.
- **The hybrid dominates**: 88% on the same frames, 89.5% live
  (a sustained ~100% for 10 minutes once the sky improved).

### 3.2 Speed

| Item | A | B | C (SEP leg) |
| --- | --- | --- | --- |
| Detection med | 13.9 ms | 66.4 ms | 143 ms (SEP: 12-bit full frame + binning + gates) |
| tetra3 T_solve med (when solved) | — | 26 ms | 64 ms |
| **Total cost per attempt med** | ~15 ms (fails fast) | ~206 ms | **280 ms** (includes the failed cedar first pass; p90 1.16 s) |
| Live attempt cadence | — | — | med 439 ms ≈ **2.3 Hz** (p90 748 ms) |

Caveat: offline numbers include **CPU contention** with the live app
running on the same Pi (uncontended reference: cedar 512 6 ms,
cedar 1920 34 ms). Relative comparison between paths remains valid.

### 3.3 Accuracy (drift-removed scatter, fixed tube)

| Metric | B cedar full-frame | C hybrid |
| --- | --- | --- |
| 1σ RA / Dec | 27″ / 36″ (n=9, offline) | **57″ / 49″** (1,461 live solves, median over 2-min windows; per-window range 31–69″) |
| radial p95 | 62″ | **155″** |
| B↔C same-frame centre disagreement | med 101″ (n=9) | |

- Tonight's hybrid accuracy is **1σ ≈ 1′, p95 ≈ 2.6′** — clearly worse
  than the dark-night measurements (1σ 7–17″, §6.5/§6.7). Consistent
  with the low SNR of the bright background: solve RMSE rose from the
  25″ range to 87″. Still ample for finder use (0.5–1° eyepiece field).
- B (full-frame cedar) has only 9 samples but beats C on both scatter
  and purity — the classic "fewer but cleaner" profile. At an 18% solve
  rate it cannot stand alone.
- Warm-pixel mask behaviour: masked med 0 — the bright background
  drowns warm pixels below σ4 (same as the twilight observation in
  §6.5; working as designed).

### 3.4 Follow-up — path-B preprocessing variant: raw fed directly (added 2026-08-01)

Answers "what if the RAW image goes straight into full-frame cedar?"
First, the premise: **no variant involves debayering** — the imx462 is
mono in practice (§6.4) and the solve chain is luminance-only
throughout, so the original path B already fed the raw mosaic without
debayering. The comparison is therefore about preprocessing. cedar's
gRPC `Image` is 8-bit only, so "direct" is defined as truncation to the
upper 8 bits (>>4):

- **B1** (the report's path B): production stretch, (raw − 238) × 255/3857
- **B2** (raw direct): raw >> 4 — no bias subtraction, no stretch

Re-run on the same 50 frames (same exposure per row):

| Metric | B1 stretch | B2 raw direct |
| --- | --- | --- |
| Solve rate | 18% (9/50) | **18% (9/50)** |
| Detections med (in-crop) | 5 (1) | 5 (1) — **per-frame detection delta med/p10/p90 all 0** |
| Matches med / purity | 8 / 89% | 8 / 89% |
| RMSE med | 90″ | 92″ |
| Detection time med | 72 ms | 66 ms (within contention noise) |
| Same-frame solve overlap | 8 common, 1 B1-only, 1 B2-only (quantisation jitter on marginal frames) | |
| Centre disagreement on common solves | med **0.7″** (p90 17″) | |

**Verdict: cedar detection is effectively invariant to affine intensity
transforms** — its σ threshold is relative to its own noise estimate, so
bias subtraction/stretch neither helps nor hurts detection or solving.
The full-frame cedar bottleneck is **physical SNR** (bright background),
not preprocessing; the practical takeaway is only that the full-frame
path could skip preprocessing CPU (the stretch runs in the camera
process for the crop path regardless). Scripts: `bench_b_variants.py` /
`aggregate_b.py`, results `bench_b_variants.jsonl`.

## 4. Verdict

1. **ADR m0023 (hybrid always-on) reconfirmed**: under the target
   (light-polluted) sky, cedar crop solves 0% and the hybrid 88–90%.
   Tonight was not a role split between the two paths — it was **SEP
   carrying everything**.
2. **cedar full-frame σ8 is not an alternative at this brightness**
   (18%). The §6.7 verdict stands — a high-purity auxiliary path for
   dark skies only; no grounds to revisit the "deferred" decision.
3. **Accuracy degradation on bright skies (1σ ~1′) is a new data
   point**: the 7–17″ figures to date were measured on darker nights.
   Exposure was pinned at manual 200 ms — auto-exposure might have
   avoided the 87%-of-full-scale background and improved SNR/scatter
   (worth re-measuring with AE on during the next bright night).

## 5. Reproduction and data locations

- 50-frame corpus + results: session scratchpad
  (`corpus/`, `bench3_results.jsonl`, `live_solution_log.jsonl`,
  `bench3.py`, `aggregate_bench.py`, `analyze_live.py`) — on SD, not
  tmpfs: `~/.cache/piptmp/.../088e4027-*/scratchpad/`.
- Live path attribution caveat: `/api/solution`'s **FOV cannot
  distinguish cedar from SEP** (a SEP solve also reports ~11.46°), and
  a fallback solve publishes `Centroids` as the **SEP detection count**
  (`solver.py`, `_build_successful_solve` centroid_count). Attribution
  here was verified by re-solving the identical dumped frames offline
  and matching RA.
