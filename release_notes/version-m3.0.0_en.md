# MFNavis m3.0.0 — Finder and IMU charts

Finder lets you position the telescope manually using a chart or camera image,
then send GoTo to the coordinates at the displayed reticle centre.

## Finder

- Added Finder immediately above Chart in the main menu.
- Square cycles between camera and chart modes. Camera mode shows the image and
  circular reticle without title or information bands; `+` / `-` select 1×, 2× or 4×.
- In either mode, `5` and ALIGN send the displayed reticle's RA/Dec as the GoTo
  target. Manual movement and Stop remain available.
- Short and long RIGHT stay in Finder. Object-details shortcuts and the
  object-details arrow have been removed from Finder.

## Chart pointing

- Both the standalone Chart and Finder retain plate-anchored IMU estimates after
  a failed solve.
- Before a successful solve, a usable IMU orientation, GPS or saved default
  observing site, and current time provide chart coordinates. Finder GoTo can
  use this displayed centre too.
- No usable coordinate means no GoTo command. Display-only IMU estimates never
  overwrite shared pointing or count as successful optical solves.

## Other improvements since m2.6.16

- Improved GoTo approach and settling, PID pulse corrections, tracking recovery,
  and priority for manual movement.
- Improved tracking through solve loss, mount limit checks, indoor initialization,
  and OnStep reconnection.
- Improved Push tracking/arrival indicators and camera guidance.
- Added Korean and English user manuals with LCD examples; improved resumable web
  cache downloads, catalog search, and Nearby sorting.
- Uses the pinned MFDS v0.4.4 package. Installation baseline: Raspberry Pi OS
  Trixie 64-bit / Python 3.13.

## Installation

Run as the installation user:

```bash
wget -O /tmp/mfnavis-m3.0.0-setup.sh https://raw.githubusercontent.com/hjoungjoo/MFNavis/m3.0.0/mfnavis_setup.sh &&
MFNAVIS_INSTALL_BRANCH=m3.0.0 bash /tmp/mfnavis-m3.0.0-setup.sh
```

Reboot after installation. See the [installation guide](https://github.com/hjoungjoo/MFNavis/blob/m3.0.0/README.md).
This release provides software source and installation materials.

Automated tests cover Finder rendering, input handling, and GoTo command routing.
No physical mount was connected during this Finder validation; physical slewing
and tracking during observation were not verified.

[Full comparison](https://github.com/hjoungjoo/MFNavis/compare/m2.6.16...m3.0.0)
