# MFNavis m3.0.1 — GoTo approach and tracking recovery

## GoTo and tracking

- An explicit new GoTo can clear a previous limit latch after the violation has
  cleared and fresh stopped telemetry confirms safe current and target coordinates.
  Matching acknowledgements, live limit checks and stop priority remain enforced.
- Near-target approach uses bounded manual-axis movements instead of repeated short
  GoTos. Distance selects 4×, 8×, 20× or 48×; each movement drives one axis for at
  most 1.2 seconds. Completion and user takeover restore the original manual speed.
- Pulse guiding takes over comfortably inside its range: 1.5 arcmin for the default
  1 arcmin accuracy. Arrival requires a fresh observation after motion stops.
- Failed post-arrival pulses no longer leave correction disabled in `settling`
  until the target drifts farther away. Fresh observations start near recovery and
  a pulse finish, then restore normal optical correction and solve-loss holdover.
- Failed near recovery waits 10 seconds between attempts, with at most three
  attempts before reporting failure and requiring a new GoTo or verified optical
  arrival. User actions, parking, tracking-off and limit protection take priority.
- Finder camera GoTo supports displayed IMU coordinates before solving and waits
  one second for keypress vibration to settle.

## Interface

- Increased LCD title-bar status-icon spacing and prevented title overlap.
- Moved Smooth optical tracking settings to the bottom of the web INDI page.

## Installation and validation

Baseline: Raspberry Pi OS Trixie 64-bit / Python 3.13, pinned MFDS v0.4.4.
Run as the installation user and reboot after installation:

```bash
wget -O /tmp/mfnavis-m3.0.1-setup.sh https://raw.githubusercontent.com/hjoungjoo/MFNavis/m3.0.1/mfnavis_setup.sh &&
MFNAVIS_INSTALL_BRANCH=m3.0.1 bash /tmp/mfnavis-m3.0.1-setup.sh
```

[Installation](https://github.com/hjoungjoo/MFNavis/blob/m3.0.1/README.md) ·
[Validation record](https://github.com/hjoungjoo/MFNavis/blob/m3.0.1/docs/mf_report/m3.0.1_validation_ko.md) ·
[Full comparison](https://github.com/hjoungjoo/MFNavis/compare/m3.0.0...m3.0.1)

The user confirmed manual near-target approach on hardware. Post-arrival stall
recovery passed reproduction and simulation tests and was deployed with a service
restart; extended hardware tracking and mechanical response still need field
validation. This release provides software source and installation materials,
not an OS image.
