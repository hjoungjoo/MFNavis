# MF_PiFinder Upstream Patch Reference

> OS references below describe the dated design/migration baseline. Current
> MFNavis installation uses [Trixie 64-bit / Python 3.13](mf_trixie_install_en.md).

Created: 2026-07-03

This document is a practical reference for future sync work from
`brickbots/PiFinder` into the `mf_pifinder` branch.  It records which patches
have already been applied, which upstream changes were intentionally skipped,
and which MF-specific areas must be preserved when the original source changes.

Goals:

- Separate already-applied upstream changes from MF-specific patches.
- Identify files that are likely to conflict during future upstream syncs.
- Provide a repeatable checklist for review and verification.

## Current Baseline

Local branch:

- `mf_pifinder`

Upstream comparison target:

- `brickbots/PiFinder main`

As of 2026-07-03, the branch includes these selected upstream changes:

- NixOS PR build CI (workflow later removed on 2026-09-28 because it is unused)
- case/accessory STL changes
- observing-list CSV import improvements
- UTC-aware datetime handling
- Set Time/Date self-gating when no location lock exists
- OBJ_TYPES single-source refactor

MF-only follow-up:

- SSD1333 automatic display detection, separated from the larger Rev-4 hardware patch

Additionally reflected on 2026-07-13:

- upstream selected commits applied:
  - Stellarium 2.0 observing-list import (#527, `39412ac`)
  - catalog filter cache: skip re-filtering unchanged catalogs on list open (#526, `f704a26`)
  - UBlox GPS NAV-SVINFO/NAV-SAT decoding fix (#524, `9cb0060`) — `gps_ubx_parser.py`
    and its tests applied cleanly; `gps_ubx.py` was hand-merged so the NAV-PVT handler
    keeps both the MF time handling and the upstream numSV used-count
- reviewed but skipped this round:
  - three NixOS migration commits (#523 `e22ac48`, #521 `0621d15`, #517 `02e6b30`) —
    whether MF will support the NixOS migration is undecided
  - state datetime tz fix (#508, `e64f0b6`) — already covered via `timez.py`; reapplying
    would drag in the excluded Rev-4 `state.py` changes, so it is left out
  - Rev-4 hardware enablement (#498, `e82b809`) — kept out by policy

Additionally reflected on 2026-08-04 (upstream `a132bc36..4a83d25b`, 31
commits incl. the 2.6.1 release, reviewed — see the KO version for the full
per-item rationale; KO is authoritative):

- applied clean: catalog_objects indexes (#564, `8d357eb6`, incl. the DB
  blob), SQM sweep exposure settling (#561, `351129a3`), focus technique
  docs (#547, `3e23052b`, supersedes deferred #546), ADR 0020 collision
  fix (`0b76b3c7`, upstream renames to 0024/0025)
- applied with manual merge: GPS NAV-SAT latch/floor fix (#563,
  `e87abe49`) onto the fork's 4-element sats telemetry; the
  `ui/timeentry.py` timezone-note hunk was deliberately NOT taken (the
  fork removed that line on purpose — do not re-litigate next sync)
- skipped/deferred this round: SQM colour zero point (#560 — TRAP: applies
  clean but silently shifts this fork's mono-imx462 SQM by ~+0.74 mag;
  **applied 2026-08-05 with a `profile.mono` guard** in
  `_mosaic_phase_is_rggb`, plus an MF regression pin; imx462/imx290 keep
  the constant zero point, hq keeps the colour term), i18n 2.6.1 pass (#562 —
  never take the .po/.mo files; only 5 string-wrapping hunks are
  candidates), SSD1333 four-axis brightness (#568+#570 — deferred then
  **applied 2026-08-05 as a partial port** once adopting SSD1333 was
  decided: driver+tests+model docs only, measurement journals and bench
  harnesses excluded; MF displays.py customizations verified preserved;
  the stale MF auto-detection test was rewritten against the get_i2c
  seam and given a unit marker), the 2.6.1 release commits (version.txt moved to the m-prefix scheme, m2.6.0, 2026-08-05; note
  `ui/software.py:164` will show a spurious "Update Now" once upstream
  publishes 2.6.1 — resolved 2026-08-05: release-check and migration-gate
  URLs repointed at the fork, "Unknown" display branch added), bring-up
  tool (fails at
  import; reconfirms the #552 exclusion), keypad matrix split (#551 —
  reclassified deferred→excluded: the real blocker is the fork's 4-column
  vs upstream's 5-column matrix constants), focus multi-star (#531 —
  **applied 2026-08-05**: new 4-mode screen adopted with the fork's three
  preview features re-implemented on it — GuideKeyMixin, camera_gain
  marking menu, daytime raw-frame path in Image mode; positioning.py took
  only upstream's docstring delta after a wholesale take clobbered MF
  fields; docs converged on the post-#546 state, closing #546/#547;
  verified headless: 4 modes render, GAIN menu jumps, solver solves),
  NixOS/CI commits (not applicable)

Additionally reflected on 2026-08-09 (upstream `4a83d25b..7eaf058c`, 12
commits reviewed — see the KO version for the full per-item rationale; KO is
authoritative):

- **Policy change (2026-08-09, user decision):** adopting rev4 hardware
  changes is now **allowed**, subject to two conditions — the current
  source's behaviour must not regress, and any conflict is reported to the
  user for a decision rather than merged on judgement. This supersedes the
  previous blanket rev4 exclusion.
- Upstream branch state: `upstream/release` has converged onto
  `upstream/main` (zero commits exclusive to release; release trails main by
  `7eaf058c` alone). The `v2.6.1` tag itself (`8c6ae841`, 08-02) was already
  reviewed in the 2026-08-04 round — the recent "release update" is 11
  docs/asset commits layered onto release on 08-06..08-07.
- Character of this round: **zero runtime Python changes.** Entirely the
  rev4 user-manual rewrite, rev4 hardware design assets, and docs-skill
  improvements. Verified post-apply that nothing under `python/` changed.
- Applied (8, clean): `511b599d` (#572, rev4 docs plan + `pf_remote`
  `--display`/`-fb`), `de285d96` (#574, bring-up reference), `f71ff317`
  (#575, WP3), `746edad9` (#577, WP1 Power & Charging), `b138894f` (#578,
  SD card + new v2.5 procedure), `5460cc60` (#582), `7eaf058c` (#585, STE
  house style), `aac4a7fb` (rev4 KiCad/gerber/STL assets, ~19MB, no runtime
  impact).
  - One conflict resolved losslessly: `product-knowledge-base.md` — the fork
    has never modified it (zero diff vs merge-base), so the conflict came
    from skipping `0edff3bb`, not from MF drift; took upstream's version.
  - **Caveat: `pf_remote launch -fb` fails on this fork** — `main.py` has no
    `-fb/--fakebattery` (battery not ported). The default path
    (`--display headless_176`) works: `DisplayHeadless176` exists here.
- Three conflicts — **resolved by user decision and applied 2026-08-09**:
  - **Docs policy (user):** keep the rev4 manual **as upstream wrote it**.
    Sections now describe features this fork lacks (battery indicator,
    charging, low-battery warnings and shutdown, sounds) and deliberately
    carry no "unsupported here" note, to keep the upstream diff minimal;
    porting the rev4 software will make them true. **Do not revert these on
    accuracy grounds in a future sync — the state is intentional.**
  - `016e0282` (#576, `menu_map.rst`): kept MF's `IMU Settings` tree, took
    upstream's GPS Baud Rate wording, and **excluded the Volume entry** —
    menu_map diagrams the real menu, and this fork has neither `sound.py`
    nor a Volume item. The `Sounds` section in `user_guide.rst` was taken
    verbatim per the docs policy, so menu_map is fork-accurate while the
    prose is upstream-accurate. That asymmetry is intended.
  - `84a2fbaf` (#583, `troubleshooting.rst`): took upstream's new
    "Align (Day)" diagnostic prose and restored MF's Mono/Color sentence
    into the rewritten Camera Type bullet, converting its em-dash to a
    sentence split to match the STE style just adopted in `7eaf058c`.
  - `43200f86` (#584): confirmed a pure cascade; applied clean once
    `84a2fbaf` was resolved.
- Excluded this round: `27ca9624` (#573 — both `battery_bq25895.py` and
  `docs/adr/0020-*.md` are absent here; needs the `#498`/`#541`/`#549`
  battery port decision first), `0edff3bb` (#539 rev4 rename — touches many
  MF-modified runtime files and changes PiFinder Type identifiers; must not
  ride along with a docs round).
- Outcome: 11 of the 12 new commits applied; only `27ca9624` excluded.
- Verification (re-run after conflict resolution): zero `python/` changes;
  Sphinx unavailable locally so structural checks were run instead (244
  section labels, zero dangling `:ref:`, substitutions `min_software` and
  `v3_docs` both defined with zero undefined uses, 264 image directives all
  resolve, zero leftover conflict markers); both changed skill scripts
  compile; 12 tests pass (`test_menu_struct`,
  `test_hardware_detect_display`, `test_obj_types_docs`). Committed but not
  pushed; rollback point `5b49bc82`.
- Deferred to a future round (the rev4 body port): `#498` (hardware
  enablement), `#541`/`#549` (battery UX), `#551` (keypad matrix),
  `#552`/`#556` (bring-up), `0edff3bb` (#539 rename). Under the new policy
  these are an **undecided backlog**, not a standing exclusion. The manual
  already describes rev4, so porting closes the gap. Handle `0edff3bb`
  first to avoid repeating ordering conflicts like the
  `product-knowledge-base.md` one.

This is not a full change history.  For feature-by-feature history, see
`docs/mf_dev/mf_change_history_en.md`.

## Upstream Changes Already Applied

| Area | Status | Notes |
| --- | --- | --- |
| NixOS PR build CI | Workflow removed | Initially applied; unused workflow removed on 2026-09-28. Manifest scripts retained |
| case/accessory files | Applied | STL/JPG/README changes only |
| Observing-list CSV import | Applied | `obslist_formats.py`, docs, tests |
| Observing-list Stellarium 2.0 import | Applied | #527 `39412ac`. Extends the `obslist_formats.py` Stellarium reader |
| Catalog filter cache | Applied | #526 `f704a26`. Adds `catalog_base.py`, skips re-filtering unchanged catalogs |
| UBlox GPS NAV-SVINFO/NAV-SAT decode fix | Applied | #524 `9cb0060`. `gps_ubx_parser.py` offset fix, `gps_ubx.py` NAV-PVT hand-merge |
| UTC-aware datetime | Applied | Adds `timez.py`; touches state/server/callback time handling |
| Set Time/Date self-gate | Applied | Manual time/date UI is inert until a location lock exists |
| OBJ_TYPES single-source | Applied | Type filter menu is generated from `OBJ_TYPES` |

Do not reapply these changes during the next upstream sync.

## Rev-4 Hardware Patch: Intentionally Not Fully Applied

The upstream Rev-4 hardware enablement patch has not been merged wholesale.

Skipped features:

- BQ25895 battery telemetry
- BQ25895 fast-charge runtime configuration writes
- sound/earcon buzzer subsystem
- GPIO15 hardware power button
- GPIO14 gpio-poweroff latch
- battery titlebar icon
- Raspberry Pi red power LED control

Reason:

- The upstream patch assumes Rev-4-specific GPIO/I2C/PWM wiring.
- GPIO14 poweroff latch can be unsafe on boards without the matching circuit.
- Sound should be optional and probably default OFF for observing use.
- Charger writes should be gated and hardware-tested before becoming active.

Partially applied:

- SSD1333 display auto-detection only

Current implementation:

- `python/PiFinder/hardware_detect.py`
- `python/PiFinder/main.py`
- `python/PiFinder/splash.py`
- `python/tests/test_hardware_detect_display.py`

Behavior:

- Uses BQ25895 I2C address `0x6A` ACK as the Rev-4/SSD1333 display marker.
- Defaults to `ssd1333` when detected.
- Falls back to `ssd1351` if detection fails, Blinka import fails, or GPIO/I2C access fails.
- The `--display` command-line option still overrides auto-detection.

Future Rev-4 work should be split into small pieces.  Do not merge
battery/sound/power/latch in one step.

## MF-Specific Patch Areas

These areas are either not present upstream or intentionally differ in
`mf_pifinder`.

### Platform / Bookworm / Pi4-Pi5-CM5

Key files:

- `pifinder_paths.sh`
- `pifinder_setup.sh`
- `pifinder_update.sh`
- `pifinder_post_update.sh`
- `python/PiFinder/board_config.py`
- `python/PiFinder/boot_config.py`
- `python/PiFinder/sys_utils.py`
- `python/PiFinder/displays.py`
- `pi_config_files/*.service`

Preserve:

- Prefer `/boot/firmware/config.txt` on Bookworm, fallback to `/boot/config.txt`.
- Render `PiFinder_data`, systemd, and Samba paths for the current OS user.
- Select GPS UART defaults by board profile.
- Use `uart2-pi5` on Pi5/CM5 to avoid OLED CS conflicts.
- Support both `/dev/spidev0.0` and `/dev/spidev10.0`.

### Camera / Focus / Gain

Key files:

- `python/PiFinder/camera_interface.py`
- `python/PiFinder/ui/preview.py`
- `python/PiFinder/ui/menu_structure.py`
- `python/PiFinder/ui/callbacks.py`
- `scripts/camera_lcd_preview.py`

Preserve:

- Focus preview behavior.
- Runtime/profile camera gain controls.
- LCD camera preview debug script.

### Korean Localization

Key files:

- `python/locale/ko/LC_MESSAGES/messages.po`
- `python/locale/ko/LC_MESSAGES/messages.mo`
- `python/PiFinder/ui/fonts.py`
- `python/PiFinder/ui/menu_structure.py`

Preserve:

- `ko` in the language menu.
- CJK font handling.
- Restart notice flow for language changes.

### Bluetooth / USB HID Keyboard

Key files:

- `python/PiFinder/keyboard_interface.py`
- `python/PiFinder/keyboard_pi.py`
- `python/PiFinder/ui/bluetooth_keyboard.py`
- `python/PiFinder/ui/textentry.py`
- `python/PiFinder/ui/menu_structure.py`

Preserve:

- libinput-based HID keyboard mapping.
- Bluetooth scan/pair/connect UI.
- INDI guide `qwe/asd/zxc` mapping (Guide page and `GuideKeyMixin` passive
  screens).
- Guide motion press/release and timeout fail-safe behavior.

### Integrated Time Sync

Key files:

- `python/PiFinder/gps_time_sync.py`
- `python/PiFinder/gps_time_sync_helper.py`
- `python/PiFinder/ui/gps_time_sync_status.py`
- `scripts/install_chrony_time_sync.sh`
- `scripts/install_gps_time_sync_helper.sh`
- `pi_config_files/pifinder_gps_time_sync.service`

Preserve:

- `chronyd` is the primary clock manager.
- PiFinder UI manages GPS/NTP/RTC/helper status.
- Actual system-clock writes happen in the privileged helper/service layer.
- INDI/OnStep time sync must use the current PiFinder UTC time, not stale user
  form input.

### Wi-Fi AP+STA

Key files:

- `scripts/pifinder_apsta.sh`
- `scripts/import_initial_wifi_networks.py`
- `python/PiFinder/sys_utils.py`
- `python/PiFinder/server.py`
- `python/views/network.html`
- `pi_config_files/pifinder_apsta_prepare.service`
- `pi_config_files/pifinder_apsta_monitor.service`
- `pi_config_files/dhcpcd.conf.apsta`

Preserve:

- STA/AP/AP+STA modes.
- AP+STA AP channel follows the STA channel.
- Configurable AP IP/security/password.
- AP+STA internet sharing option is default OFF.
- User-facing warning about load and lower throughput when sharing internet.
- Initial OS Wi-Fi profiles can be imported.
- New STA entries can use scanned SSIDs.
- STA band preference policy is preserved.

### Locations Catalog

Key files:

- `python/PiFinder/location_catalog.py`
- `python/PiFinder/data/location_catalog.json`
- `scripts/build_location_catalog.py`
- `python/views/locations.html`
- `python/views/location_form.html`

Preserve:

- Country/region/district/city lookup fills coordinates and altitude.
- North Korea is excluded.
- South Korea uses more detailed administrative location data.
- Manually loaded locations can be used indoors without a GPS lock.
- Red Night theme must not leak bright select/form/action tooltip colors.

### Web Theme / PWA

Key files:

- `python/views/base.html`
- `python/views/css/style.css`
- `python/views/js/init.js`
- `python/views/manifest.webmanifest`
- `python/views/service-worker.js`
- `python/views/images/pwa-icon-192.png`
- `python/views/images/pwa-icon-512.png`

Preserve:

- Red Night theme uses dark red observing-safe UI colors.
- Log content keeps its original semantic colors.
- Android PWA fullscreen/theme-color behavior.
- No extra theme bar under navigation.

### INDI / OnStepX

Key files:

- `python/PiFinder/mountcontrol_indi.py`
- `python/PiFinder/indi_align.py`
- `python/PiFinder/indi_backlash_calibration.py`
- `python/PiFinder/indi_goto_guide_service.py`
- `python/PiFinder/indi_multipoint_align.py`
- `python/PiFinder/pos_server.py`
- `python/PiFinder/ui/indi.py`
- `python/views/indi_mount.html`
- `scripts/install_indi_mount_OnstepX.sh`
- `scripts/install_indi_mount_archive.sh`
- `scripts/package_indi_mount_archive.sh`
- `scripts/patches/indi-v2.2.3.1-onstepx.patch`

Preserve:

- INDI is optional.  A base PiFinder install must not require INDI.
- OnStepX is a custom INDI driver name; do not overwrite the original LX200
  OnStep driver.
- Read the active driver name from the INDI profile.
- Use OnStepX-specific UI/behavior only when the active driver is OnStepX.
- Location/time sync must use the current PiFinder UTC time.
- OnStepX `Backlash` supports the 0..3600 arc-sec range used by OnStep firmware.
- OnStepX `GUIDE_RATE` should remain writable and should read back the actual
  device pulse-guide rate for driver compatibility and future guide-rate
  controls. Auto Backlash currently uses INDI GoTo and no longer depends on
  `GUIDE_RATE`.
- Generic INDI mount paths must remain available for non-OnStepX mounts.
- INDI restart stops server/profile/driver and starts them again, then connects
  when possible.

### LCD INDI UI

Key files:

- `python/PiFinder/ui/indi.py`
- `python/PiFinder/ui/menu_structure.py`
- `python/PiFinder/ui/base.py`
- `python/PiFinder/keyboard_pi.py`

Preserve:

- INDI entry at the bottom of the Start menu.
- INIT/STATUS/GUIDE pages.
- Guide keypad `2/4/6/8` cardinal moves; `9/3` adjust the slew rate.
- `qwe/asd/zxc` keyboard mapping for guide motion; diagonals are on the
  keyboard letters only.
- Key 5 is not a guide-motion key.
- Motion is press-to-move, release-to-stop.
- Timeout/fail-safe stop protects against freezes or missed key releases.
- Top-bar `I` indicator reflects INDI connection health.

### SkySafari / Mount Mode Integration

Key files:

- `python/PiFinder/pos_server.py`
- `python/PiFinder/pointing_coordinate_service.py`
- `python/PiFinder/mountcontrol_indi.py`
- `python/PiFinder/imu_pi.py`
- `python/PiFinder/imu_calibration.py`

Preserve:

- Preserve the SkySafari `:Sr/:Sd` (store target) → `:MS#` (GoTo) / `:CM#`
  (Sync/Align, prefers the most recent parsed `Sr/Sd`) forwarding semantics.
  Full flow: see
  [mf_goto_mount_source_structure_en.md](mf_goto_mount_source_structure_en.md).
- If GoTo forwarding is enabled, Align/Sync can also be forwarded to INDI/OnStep.
- Before solving, IMU fallback/correction may be used.
- After a successful solve, IMU alignment correction is reset.
- Reset Pointing discards the IMU alignment correction and, when unsolved,
  re-syncs the mount to the raw (uncorrected) IMU coordinate — it is the only
  way to recover from an alignment made against the wrong target.
- OnStep-specific behavior is gated by driver capability/name.

### IMU Compass / Calibration

Key files:

- `python/PiFinder/imu_pi.py`
- `python/PiFinder/imu_calibration.py`
- `python/PiFinder/ui/menu_structure.py`
- `python/PiFinder/ui/callbacks.py`

Preserve:

- Magnetometer/compass fusion is optional.
- Default IMU behavior remains stable.
- Calibration is auto-saved/loaded when possible.
- Manual save/load/clear controls remain available.

### Docs Build Toolchain (added 2026-08-10)

Key files:

- `python/requirements_dev.txt`
- `python/noxfile.py`
- `CLAUDE.md`
- `docs/mf_dev/mf_bookworm_install_ko.md` / `_en.md`

Policies to preserve:

- Keep the trailing `-r ../docs/source/requirements.txt` line in
  `requirements_dev.txt`. It is an MF addition upstream does not have, and it
  is what makes the existing dev-setup command install Sphinx as well.
- Do not re-pin the versions in `requirements_dev.txt`. Reference
  `docs/source/requirements.txt` (what Read the Docs installs) so there is a
  single source of truth.
- Keep the `docs` session in `noxfile.py`. `-n -W --keep-going` is the point:
  without warnings-as-errors it will miss a reference broken by a partially
  applied upstream doc change.
- Do not add `docs` to the default `nox.options.sessions`.
- If upstream adds its own docs session or docs extra, check for duplication
  and consolidate on one.

## High-Conflict Files

Review these first during upstream sync:

```text
default_config.json
pifinder_setup.sh
pifinder_post_update.sh
python/PiFinder/main.py
python/PiFinder/server.py
python/PiFinder/sys_utils.py
python/PiFinder/sys_utils_fake.py
python/PiFinder/displays.py
python/PiFinder/splash.py
python/PiFinder/keyboard_interface.py
python/PiFinder/keyboard_pi.py
python/PiFinder/pos_server.py
python/PiFinder/mountcontrol_indi.py
python/PiFinder/ui/base.py
python/PiFinder/ui/callbacks.py
python/PiFinder/ui/menu_manager.py
python/PiFinder/ui/menu_structure.py
python/requirements_dev.txt
python/noxfile.py
python/views/base.html
python/views/css/style.css
python/views/network.html
python/views/locations.html
python/views/indi_mount.html
```

Most sensitive files:

- `main.py`: startup processes, display/GPS/camera/keyboard selection
- `server.py`: web routes, network/location/INDI APIs
- `sys_utils.py`: privileged system operations, Wi-Fi, chrony, INDI helpers
- `keyboard_pi.py`: GPIO keypad, HID keyboard, guide fail-safe
- `ui/menu_structure.py`: upstream menu additions often conflict with MF menus
- `ui/base.py`: titlebar/status/UI helpers
- `pos_server.py`: SkySafari LX200 protocol, GoTo/Sync/Guide/IMU fallback

## Recommended Sync Procedure

1. Check current state:

```bash
git status --short --branch
git remote -v
git fetch upstream main
git rev-list --left-right --count upstream/main...HEAD
git log --oneline --left-right --cherry-pick upstream/main...HEAD --max-count=80
```

2. Inspect upstream changes:

```bash
git diff --stat HEAD...upstream/main
git diff --name-status HEAD...upstream/main
```

3. Dry-run conflicts:

```bash
git merge-tree --write-tree HEAD upstream/main
```

4. Apply in small groups:

- Docs/CI/assets first.
- Runtime Python changes by feature.
- Hardware side effects separately.
- Always manually inspect INDI, network, time sync, and SkySafari files.

5. Minimum verification:

```bash
python -m compileall -q python/PiFinder
python -m pytest \
  python/tests/test_hardware_detect_display.py \
  python/tests/test_obj_types_docs.py \
  python/tests/test_menu_struct.py \
  python/tests/test_time_date_gate.py \
  python/tests/test_state_datetime.py \
  python/tests/test_obslist_formats.py \
  python/tests/test_obslist_resolve.py \
  python/tests/test_pos_server.py \
  python/tests/test_mountcontrol_indi.py \
  python/tests/test_web_theme_static.py \
  python/tests/test_wifi_apsta_static.py \
  python/tests/test_location_catalog.py \
  python/tests/test_sys_utils.py
```

6. Hardware verification:

- Pi4 Bookworm 64-bit
- Pi5 or CM5 Bookworm 64-bit
- Camera preview/focus
- GPS lock/unlock and manual location load
- Bluetooth keyboard key press/release
- Web Red Night theme
- AP+STA and AP client list
- INDI Web UI and LCD INDI Guide stop fail-safe
- SkySafari GoTo/Align/Guide path

## Known Test Caveats

The full `python -m pytest python/tests` suite may still include unrelated
environment/test-API failures.

Known causes as of 2026-07-03:

- `test_multiproclogging.py`: depends on `pifinder_logconf.json` path
- `test_radec_entry.py`: tests expect an older constructor/API shape
- `test_ui_modules.py`: sweeps `key_*` methods without arguments, conflicting
  with methods such as `key_number_press(number)`

Use the minimum verification list above first, then triage full-suite failures
by the first traceback.

## When To Update This Document

Update this document when:

- upstream significantly changes `main.py`, `server.py`, `sys_utils.py`,
  `ui/menu_structure.py`, or `pos_server.py`
- any Rev-4 battery/sound/power feature is partially applied
- INDI generic and OnStepX-specific paths are refactored
- SkySafari Align/GoTo/Guide policy changes
- chronyd/time-sync policy changes
- AP+STA network services or policies change
