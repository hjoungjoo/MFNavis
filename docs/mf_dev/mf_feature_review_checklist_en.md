# MF_PiFinder Feature Review and Test Checklist

Platform section updated 2026-09-27 for Trixie/Python 3.13. The remaining
upstream comparison is a dated review baseline. Current installation and
field-test scope are in the [Trixie guide](mf_trixie_install_en.md); unchecked
items below are not claims of completed validation.

Created: 2026-07-03 / fully refreshed: 2026-08-05

This document lists functional changes and additions in the current
`main` branch compared with `brickbots/PiFinder` `main`.  It is intended
as a review and test checklist. The KO version is authoritative.

Baseline:

- Upstream: `upstream/main` (`https://github.com/brickbots/PiFinder/tree/main`,
  `4a83d25b`, includes the 2.6.1 release merge)
- Current source: `main` (`f13fde43`)
- Comparison date: 2026-08-05 (diff: 420 files, +117,825/−9,085)
- Commands used:
  - `git fetch upstream main`
  - `git rev-list --left-right --count upstream/main...HEAD`
  - `git diff --stat upstream/main...HEAD`
  - `git diff --name-status upstream/main...HEAD`

Summary:

- Major upstream work not (fully) applied (§16):
  - Full Rev-4 battery/sound/power hardware enablement
  - bring-up bench tool, keypad matrix split, NixOS release CI
- Major MF additions or changed areas (§1–§15 = the 07-03 baseline,
  §17–§25 = added since):
  - Trixie/RPi4/RPi5/CM5 install and board profiles
  - AP+STA Wi-Fi / Bluetooth+USB HID keyboard / joystick
  - Red Night/PWA Web UI / web catalogs & unified search / Locations catalog
  - chronyd-based time management
  - INDI/OnStepX/SkySafari mount integration + LCD INDI UI +
    PointingCoordinateService (mount+IMU fusion)
  - IMU compass/calibration
  - **cedar+SEP hybrid solving + cedar full-frame primary path**
    (the light-pollution core of this fork)
  - star-count auto-exposure controller
  - SQM radiometer stack + mono colour guard
  - LiveCam RAW preview/live stack + web camera controls
  - SSD1333 auto-detection + four-axis brightness (upstream port, driver only)
  - the three MF features re-implemented on the #531 Focus screen
  - fork-owned software update channel (m-version scheme)
  - Korean UI localization

Related documents:

- `docs/mf_dev/mf_upstream_patch_reference_en.md`: upstream sync and patch reference
- `docs/mf_dev/mf_change_history_en.md`: full change history
- `docs/mf_dev/mf_pifinder_rpi4_pi5_compatibility_en.md`: Pi4/Pi5/CM5 Trixie compatibility
- `docs/mf_dev/mf_indi_mount_install_en.md`: INDI install/operation
- `docs/mf_dev/mf_wifi_apsta_en.md`: AP+STA Wi-Fi
- `docs/mf_dev/mf_time_sync_en.md`: time sync
- `docs/mf_dev/mf_keyboard_mapping_en.md`: keyboard mappings

## Test Priority

| Priority | Meaning |
| --- | --- |
| P0 | Directly affects boot/install/core observing. Must test |
| P1 | Major feature. Test on real hardware or realistic network conditions |
| P2 | Supporting feature/docs/developer convenience. Regression check |

## 1. Platform / Trixie / Raspberry Pi 4, 5, CM5 Compatibility

Priority: P0

Main changes:

- Raspberry Pi OS Trixie 64-bit install support
- Prefer `/boot/firmware/config.txt`, fallback to legacy `/boot/config.txt`
- Render `MFNavis_data`, systemd, and Samba paths for the current OS user
- GPS UART board profiles for Pi4/Pi5/CM5
- Use `uart2-pi5` on Pi5/CM5 to avoid OLED CS conflicts
- Support both `/dev/spidev0.0` and `/dev/spidev10.0`
- SSD1333 display auto-detection

Key files:

- `mfnavis_paths.sh`
- `mfnavis_setup.sh`
- `mfnavis_update.sh`
- `mfnavis_post_update.sh`
- `python/MFNavis/board_config.py`
- `python/MFNavis/boot_config.py`
- `python/MFNavis/hardware_detect.py`
- `python/MFNavis/displays.py`
- `python/MFNavis/main.py`
- `python/MFNavis/splash.py`
- `python/MFNavis/sys_utils.py`
- `pi_config_files/*.service`

Review points:

- [ ] Fresh OS install completes with `mfnavis_setup.sh` as a normal user
- [ ] Pi4 `gps_port=auto` resolves to `/dev/ttyAMA3`
- [ ] Pi5/CM5 `gps_port=auto` resolves to `/dev/ttyAMA2`
- [ ] Boot config changes go to the active boot config path
- [ ] Pi5/CM5 do not hit `uart3` vs OLED CE0/GPIO8 conflicts
- [ ] Boards with only `spidev0.0` or only `spidev10.0` both work
- [ ] SSD1333 marker detection falls back to SSD1351 when unavailable
- [ ] Splash and main UI use the same display selection

Test items:

- [ ] Pi4 Trixie 64-bit fresh install
- [ ] Pi5 or CM5 Trixie 64-bit fresh install
- [ ] `systemctl status mfnavis mfnavis_splash indiwebmanager`
- [ ] `ls /dev/spidev* /dev/ttyAMA*`
- [ ] Web UI access
- [ ] LCD/OLED splash display
- [ ] LCD/OLED main UI
- [ ] GPS port auto-selection
- [ ] Camera preview

## 2. Camera Focus Screen / Gain (refreshed 2026-08-05 — upstream #531 4-mode screen)

Priority: P1

Main changes:

- Adopted upstream #531 Focus rewrite: stars (4 tiles) / single / image /
  stats modes, raw uninterpolated crops, HFD history
- Three MF re-implementations: GuideKeyMixin (mount jog from the camera
  screen), Gain marking-menu entry (right), and the daytime/saturated
  raw-frame path (Image mode renders the 12-bit raw frame via Bayer-quad
  average + percentile stretch when the background is bright — the
  daytime-alignment path)
- Camera gain profile/runtime selection
- LCD camera preview debug script

Key files:

- `python/PiFinder/ui/preview.py`
- `python/PiFinder/focus.py`
- `python/PiFinder/camera_interface.py`
- `python/PiFinder/ui/callbacks.py`
- `scripts/camera_lcd_preview.py`

Review points:

- [ ] SQUARE cycles all four modes
- [ ] Marking menu shows EXPOSURE/GAIN and the GAIN jump works
- [ ] In daylight the Image mode shows the scene instead of washing out
- [ ] Guide keys work on the camera screen with mount_control on
- [ ] Runtime gain matches camera metadata

Test items:

- [ ] Stars mode +/− magnification
- [ ] Single mode HFD readout
- [ ] Stats mode shows star count/FWHM/exposure/gain
- [ ] Outdoor daytime Image-mode scene check (daytime alignment path)
- [ ] Tests: `test_focus_preview.py`, `test_focus.py`, `test_ui_guide_keys.py`

## 3. Korean UI Localization

Priority: P1

Main changes:

- Korean locale
- `ko` language menu entry
- CJK font handling
- Restart notice after language changes

Key files:

- `python/locale/ko/LC_MESSAGES/messages.po`
- `python/locale/ko/LC_MESSAGES/messages.mo`
- `python/PiFinder/ui/fonts.py`
- `python/PiFinder/ui/menu_structure.py`

Review points:

- [ ] Korean is selectable in the language menu
- [ ] Korean text renders correctly on LCD
- [ ] Korean text renders correctly in Web UI
- [ ] Korean `.po` does not drift after upstream i18n changes

Test items:

- [ ] Change language to Korean
- [ ] Restart and inspect LCD menu
- [ ] Inspect Web UI navigation/title/buttons
- [ ] Inspect log/error messages

## 4. Bluetooth / USB HID Keyboard

Priority: P0

Main changes:

- libinput-based HID keyboard event handling
- Bluetooth keyboard scan/pair/connect UI
- USB keyboard input support
- Additional text-entry keycodes
- `qwe/asd/zxc` direction mapping (INDI Guide page plus mount-enabled menu/status screens via `GuideKeyMixin`)
- Guide motion release/fail-safe stop handling

Key files:

- `python/PiFinder/keyboard_interface.py`
- `python/PiFinder/keyboard_pi.py`
- `python/PiFinder/ui/bluetooth_keyboard.py`
- `python/PiFinder/ui/textentry.py`
- `python/PiFinder/ui/indi.py`
- `python/PiFinder/ui/menu_structure.py`

Review points:

- [ ] Bluetooth keyboard appears as `/dev/input/event*`
- [ ] Both key press and release events arrive
- [ ] Normal menu input does not conflict with the shared guide direction mapping (`GuideKeyMixin`)
- [ ] Mount motion stops after freezes/SSH latency/missed key release
- [ ] Bluetooth keyboard reconnects after AP+STA/Wi-Fi changes

Test items:

- [ ] Pair Bluetooth keyboard
- [ ] Reconnect after reboot
- [ ] Connect USB keyboard
- [ ] LCD menu navigation
- [ ] Text entry
- [ ] INDI Guide direction press/release
- [ ] Disconnect Bluetooth during Guide motion
- [ ] Guide motion timeout stop

## 5. Web UI Red Night Theme / PWA

Priority: P1

Main changes:

- Red Night theme
- Per-browser theme storage
- PWA manifest/service worker/icons
- Android PWA fullscreen/theme-color support
- Theme selector integrated into navigation
- Locations/select/form/tooltip color fixes

Key files:

- `python/views/base.html`
- `python/views/css/style.css`
- `python/views/js/init.js`
- `python/views/manifest.webmanifest`
- `python/views/service-worker.js`
- `python/views/images/pwa-icon-192.png`
- `python/views/images/pwa-icon-512.png`
- `python/views/locations.html`
- `python/views/location_form.html`

Review points:

- [ ] Red Night theme does not leak bright/white controls
- [ ] Log content keeps semantic colors
- [ ] Installed PWA enters fullscreen
- [ ] Android navigation/status bar follows theme color
- [ ] PWA/fullscreen state is not unnecessarily lost during navigation
- [ ] Theme selector appears only in navigation

Test items:

- [ ] Change theme in desktop Chrome
- [ ] Change theme in Android Chrome
- [ ] Install Android PWA
- [ ] Navigate inside PWA fullscreen
- [ ] Check Logs page colors
- [ ] Check Locations add/edit form
- [ ] Check tooltip/action button colors

## 6. Wi-Fi AP / STA / AP+STA

Priority: P0

Main changes:

- STA/AP/AP+STA modes
- `uap0` virtual AP interface
- AP channel restart based on STA channel
- Configurable AP IP
- AP WPA2 security/password
- AP+STA internet sharing option, default OFF
- Initial OS Wi-Fi profile import
- Scan SSIDs when adding STA profiles
- STA band preference
- AP connected-device list

Key files:

- `scripts/pifinder_apsta.sh`
- `scripts/import_initial_wifi_networks.py`
- `python/PiFinder/sys_utils.py`
- `python/PiFinder/server.py`
- `python/views/network.html`
- `pi_config_files/pifinder_apsta_prepare.service`
- `pi_config_files/pifinder_apsta_monitor.service`
- `pi_config_files/dhcpcd.conf.apsta`
- `switch-apsta.sh`

Review points:

- [ ] STA only works
- [ ] AP only works
- [ ] AP+STA works
- [ ] AP clients can access PiFinder Web UI
- [ ] AP+STA internet sharing ON/OFF works
- [ ] AP channel follows STA channel changes
- [ ] DHCP/dnsmasq works after AP IP changes
- [ ] STA band preference matches NetworkManager profile
- [ ] STA-side Web access failures can be distinguished from router client isolation

Test items:

- [ ] Access `10.10.10.1` in AP mode
- [ ] STA internet in AP+STA mode
- [ ] AP client internet sharing ON
- [ ] AP client internet sharing OFF
- [ ] OnStep device on AP
- [ ] AP connected-device list
- [ ] Scan/add STA SSID
- [ ] Import existing OS Wi-Fi profiles
- [ ] Change 2.4G/5G preference
- [ ] Test STA router client-isolation environment

## 7. Locations Catalog

Priority: P1

Main changes:

- Offline location catalog
- Country/state/district/city lookup
- Coordinate/altitude/source auto-fill
- Detailed South Korea administrative data
- North Korea excluded
- Manual loaded locations usable indoors without GPS lock

Key files:

- `python/PiFinder/location_catalog.py`
- `python/PiFinder/data/location_catalog.json`
- `scripts/build_location_catalog.py`
- `python/views/locations.html`
- `python/views/location_form.html`
- `python/PiFinder/server.py`

Review points:

- [ ] Select lists filter correctly step by step
- [ ] South Korea has sufficient detail
- [ ] Location name auto-fill/update feels correct
- [ ] Save Location works
- [ ] Default location selection works
- [ ] Manual location updates PiFinder/INDI while GPS is unlocked
- [ ] Red Night theme colors remain dark red

Test items:

- [ ] Save Seoul/Songpa/Pungnap-dong
- [ ] Save another Korean location
- [ ] Save a major international city
- [ ] Change default location
- [ ] Reload location
- [ ] Confirm INDI page PiFinder Location update
- [ ] Confirm OnStep Send Location and Time

## 8. Integrated Time Sync / chronyd

Priority: P0

Main changes:

- Integrated GPS/NTP/RTC/software PPS time management
- chronyd-centered policy
- Privileged helper service split
- GPS/NTP/RTC status UI
- Custom NTP server setting
- Set Time/Date self-gates without location lock
- UTC-aware PiFinder datetime handling

Key files:

- `python/PiFinder/gps_time_sync.py`
- `python/PiFinder/gps_time_sync_helper.py`
- `python/PiFinder/ui/gps_time_sync_status.py`
- `python/PiFinder/timez.py`
- `python/PiFinder/state.py`
- `python/PiFinder/ui/timeentry.py`
- `python/PiFinder/ui/dateentry.py`
- `scripts/install_chrony_time_sync.sh`
- `scripts/install_gps_time_sync_helper.sh`
- `pi_config_files/pifinder_gps_time_sync.service`

Review points:

- [ ] chronyd is the primary clock manager
- [ ] Weak/unlocked GPS degrades gracefully
- [ ] NTP unavailable state times out cleanly
- [ ] Custom NTP server is stored/applied
- [ ] Pi5 RTC path does not cause issues
- [ ] Set Time/Date does nothing without location lock
- [ ] INDI/OnStep uses current PiFinder UTC time

Test items:

- [ ] Indoor GPS unlock
- [ ] Outdoor GPS lock
- [ ] NTP available
- [ ] NTP unavailable
- [ ] Enter custom NTP server
- [ ] Check `chronyc sources/tracking`
- [ ] LCD Time Sync status
- [ ] Web status/API
- [ ] OnStep Web UI time after sync

## 9. INDI Mount / OnStepX

Priority: P0

Main changes:

- Optional INDI mount process
- INDI install scripts
- INDI archive package/install scripts
- OnStepX custom INDI driver patch flow
- INDI Web UI page/menu
- LX200 OnStep/OnStepX network/serial setup UI
- Improved OnStep location/time sync
- INDI restart
- Active driver/profile name-based behavior
- Generic INDI mount path preserved

Key files:

- `python/PiFinder/mountcontrol_indi.py`
- `python/PiFinder/pos_server.py`
- `python/PiFinder/ui/indi.py`
- `python/views/indi_mount.html`
- `python/views/tools.html`
- `scripts/install_indi_mount_OnstepX.sh`
- `scripts/install_indi_mount_archive.sh`
- `scripts/package_indi_mount_archive.sh`
- `scripts/patches/indi-v2.2.3.1-onstepx.patch`

Review points:

- [ ] Base PiFinder install does not require INDI
- [ ] Default `install_indi_mount_archive.sh` archive install works on Pi4 and Pi5
- [ ] Full `install_indi_mount_OnstepX.sh` source-build path works when source or patch changes are required
- [ ] OnStepX does not overwrite original LX200 OnStep driver
- [ ] OnStepX-only UI appears only for active OnStepX driver
- [ ] USB serial list appears
- [ ] Network host/port list and manual entry work
- [ ] INDI restart stops/starts server/profile/driver
- [ ] Home state, Park state, and raw `:GU#` status are displayed separately
- [ ] Manual Backlash reads/writes `Backlash.Backlash RA/DEC` without mount motion
- [ ] Auto Backlash requires a fresh plate-solved `PointingCoordinateService.solved` coordinate and does not check IMU Compass/MAG calibration
- [ ] Auto Backlash syncs mount coordinates to solved RA/Dec and disables tracking before the loop
- [ ] Auto Backlash uses INDI GoTo, not timed pulse guide, for measurement motion
- [ ] Auto Backlash waits for stable INDI idle and OnStep `:GU#` `N` (`No goto`) before recording post-GoTo mount/solved samples
- [ ] Auto Backlash turns tracking Off again after every GoTo leg
- [ ] Alt/Az mounts move `AZ`/`ALT`, while EQ mounts move `RA`/`DEC`, one axis at a time with fixed GoTo start/offset points
- [ ] Auto Backlash records each GoTo leg's start mount coordinates, end mount coordinates, and start/end PiFinder solved coordinates
- [ ] Legs where mount delta and solved-coordinate delta differ by 1 degree or more are excluded, and the displayed estimate uses the middle 40% mean after trimming the lowest/highest 30%
- [ ] Auto Backlash displays separate recommendations by actual movement direction, such as `AZ+/-`, `ALT+/-` in Alt/Az mode or `RA+/-`, `DEC+/-` in EQ mode
- [ ] Auto Backlash only displays the calculated value and does not change input fields or apply anything before `Save Backlash`
- [ ] PiFinder core features survive bad mount communications

Test items:

- [ ] Base PiFinder without INDI installed
- [ ] Run `install_indi_mount_OnstepX.sh`
- [ ] Access INDI Web Manager
- [ ] Start/connect OnStepX profile
- [ ] Configure LX200 OnStepX Network TCP
- [ ] Configure LX200 OnStepX USB serial
- [ ] Restart INDI
- [ ] Compare OnStep Web UI, direct LX200 `:GU#`, and PiFinder INDI Home/Park states
- [ ] Read current Backlash RA/DEC
- [ ] Save Backlash RA/DEC manually from the UI and confirm the driver value changes
- [ ] Auto Backlash requires a fresh plate-solved coordinate and does not require Compass/NDOF or MAG calibration
- [ ] Auto Backlash disables tracking for the motion test and restores the
      original tracking state only after successful completion
- [ ] Auto Backlash does not reset, apply, or restore Backlash RA/DEC; it only
      displays calculated candidate values for the user to review
- [ ] If the solved GoTo loop cannot capture reliable mount/solved motion records,
      Auto Backlash fails without applying a value
- [ ] PiFinder UI while INDI server is stopped
- [ ] PiFinder while OnStep device is offline

## 10. LCD INDI UI

Priority: P0

Main changes:

- INDI entry at bottom of LCD Start menu
- INIT / STATUS / GUIDE pages
- INIT actions: connect/init, send location/time, reset pointing, park/unpark, set home, return home, set-park, restart
- STATUS periodic update
- GUIDE keypad overlay
- `2/4/6/8` cardinal directions + `q/e/z/c` diagonals, `9/3` slew rate layout
- press-to-move, release-to-stop
- `qwe/asd/zxc` mapping (Guide page and other mount-enabled screens)
- Top-bar `I` indicator

Key files:

- `python/PiFinder/ui/indi.py`
- `python/PiFinder/ui/menu_structure.py`
- `python/PiFinder/ui/base.py`
- `python/PiFinder/keyboard_pi.py`

Review points:

- [ ] INDI appears at bottom of Start menu
- [ ] INIT menu fits the screen
- [ ] Restart action appears in INIT
- [ ] STATUS updates periodically
- [ ] Guide overlay hints (`2/4/6/8` move, `9/3` speed, `0` guide) match actual behavior
- [ ] Key 5 is not used for guide motion
- [ ] Timeout stop works on missed key release
- [ ] Bluetooth keyboard starts and stops motion
- [ ] Top-bar `I` reflects connection state

Test items:

- [ ] LCD INIT connect/init
- [ ] LCD send location/time
- [ ] LCD park/unpark
- [ ] LCD set home/return home
- [ ] LCD restart INDI
- [ ] LCD Guide direction motion (keypad `2/4/6/8`, keyboard `q/e/z/c` diagonals)
- [ ] LCD Guide release stop
- [ ] Bluetooth keyboard Guide motion
- [ ] Web UI stop recovery

## 11. SkySafari / LX200 / Mount Mode Integration

Priority: P0

Main changes:

- Improved SkySafari LX200 `:Sr/:Sd/:MS#/:CM#` handling
- IMU fallback pointing before solving
- Optional SkySafari GoTo forwarding to INDI
- SkySafari Guide bridge to INDI guide motion
- SkySafari Align/Sync handling for PiFinder/IMU/INDI
- Mount-mode compatibility audit
- GoTo completion/moving-state handling
- Alt/Az/EQ-aware separation

Key files:

- `python/PiFinder/pos_server.py`
- `python/PiFinder/mountcontrol_indi.py`
- `python/PiFinder/imu_pi.py`
- `python/PiFinder/imu_calibration.py`
- `docs/mf_dev/mf_mount_mode_compatibility_en.md`

Review points:

- [ ] `:Sr/:Sd` only stores target coordinates
- [ ] `:MS#` handles GoTo
- [ ] `:CM#` handles Sync/Align
- [ ] `:CM#` prefers the latest parsed `Sr/Sd` target
- [ ] GoTo forwarding ON can also forward Align/Sync
- [ ] IMU correction applies before solving
- [ ] IMU correction resets after a solve
- [ ] Alt/Az and EQ modes do not show wrong horizon/coordinate state
- [ ] SkySafari GoTo completes correctly
- [ ] Targets are not incorrectly rejected as below horizon

Test items:

- [ ] SkySafari Push-To mode
- [ ] SkySafari GoTo mode
- [ ] SkySafari guide buttons
- [ ] SkySafari Align
- [ ] IMU fallback before solving
- [ ] Normal pointing after solving
- [ ] INDI GoTo forwarding OFF
- [ ] INDI GoTo forwarding ON
- [ ] Alt/Az mount
- [ ] EQ mount

## 12. IMU Compass / Calibration

Priority: P1

Main changes:

- Optional BNO055 magnetometer/compass fusion
- Existing IMU sensitivity setting retained
- Auto calibration save/load
- Manual calibration save/load/clear
- Compass/calibration UI menu

Key files:

- `python/PiFinder/imu_pi.py`
- `python/PiFinder/imu_calibration.py`
- `python/PiFinder/ui/menu_structure.py`
- `python/PiFinder/ui/callbacks.py`
- `docs/mf_dev/mf_imu_compass_calibration_en.md`

Review points:

- [ ] Default OFF keeps existing IMU behavior stable
- [ ] Compass ON improves heading when calibrated
- [ ] Indoor magnetic interference is manageable
- [ ] Calibration status matches BNO055 status
- [ ] Auto save/load survives reboot
- [ ] Manual save/load/clear works
- [ ] Does not conflict with correction reset after solving

Test items:

- [ ] Compass OFF
- [ ] Compass ON
- [ ] Calibration auto save
- [ ] Calibration load after reboot
- [ ] Manual save/load/clear
- [ ] SkySafari no-solve pointing
- [ ] Reset correction after plate solve

## 13. Observing List CSV Import

Priority: P2

Main changes:

- Upstream CSV import improvements
- Lenient headers
- Multiple coordinate formats
- Docs examples
- Object type drift guard integration

Key files:

- `python/PiFinder/obslist.py`
- `python/PiFinder/obslist_formats.py`
- `docs/ax/catalog/obslist-formats/README.md`
- `docs/ax/catalog/obslist-formats/examples/*`
- `python/tests/test_obslist_formats.py`
- `python/tests/test_obslist_resolve.py`

Review points:

- [ ] Existing `.pifinder` list import still works
- [ ] Third-party CSV import works
- [ ] RA hour/degree/sexagesimal/colon formats are parsed
- [ ] Object type filter and OBJ_TYPES agree

Test items:

- [ ] Import example CSV
- [ ] Bad header handling
- [ ] Mixed coordinate formats
- [ ] Object type filtering

## 14. OBJ_TYPES Single Source

Priority: P2

Main changes:

- Object type code set centralized in `OBJ_TYPES`
- Type filter menu generated from `OBJ_TYPES.items()`
- Docs/default_config drift guard test

Key files:

- `python/PiFinder/obj_types.py`
- `python/PiFinder/ui/menu_structure.py`
- `python/tests/test_obj_types_docs.py`
- `default_config.json`

Review points:

- [ ] Type filter menu order is acceptable
- [ ] Labels fit LCD width
- [ ] Korean translations are natural
- [ ] `default_config.json` `filter.object_types` includes every type

Test items:

- [ ] Display Type filter menu
- [ ] Select/deselect Type filters
- [ ] Catalog filtering
- [ ] `test_obj_types_docs.py`

## 15. Documentation / Test / CI / Assets

Priority: P2

Main changes:

- MF docs
- Upstream patch reference docs
- Feature-specific install/test docs
- Nox code quality, tests, and Trixie documentation CI
- case/accessory assets
- Additional tests

Key files:

- `docs/mf_dev/*.md`, `docs/mf_report/*.md`
- `.github/workflows/nox.yml`
- `.github/scripts/*`
- `case/accessories/*`
- `python/tests/test_*.py`

Review points:

- [ ] Document names/language pairs are consistent
- [ ] Korean-only docs have English counterparts where appropriate
- [ ] Setup/install docs match current script names
- [ ] GitHub Actions behaves as intended in the fork
- [ ] Asset changes do not create unnecessary PR noise

Test items:

- [ ] Check doc links
- [ ] Check install script names
- [ ] Check CI workflow syntax
- [ ] Check docs/source menu map

## 16. Upstream Rev-4 Hardware Patch: Not Applied / Partially Applied

Priority: review only

Current status:

- Only SSD1333 display auto-detection is partially applied in MF style
- battery/sound/power/latch are not applied

Not applied:

- BQ25895 battery telemetry
- BQ25895 fast-charge configuration writes
- sound/earcon buzzer subsystem
- GPIO15 hardware power button
- GPIO14 gpio-poweroff latch
- battery titlebar icon
- Raspberry Pi red power LED control
- bring-up bench tool (#552/#556 — depends on `keypad`/`battery_bq25895`/
  `sound`; fails at import here)
- keypad matrix split (#551 — MF 4-column vs upstream 5-column; taking it
  would miswire the keypad)
- all NixOS release CI (SD image / migration tarball / manifest)
- i18n `.po`/`.mo` files (never take — would drop 527 MF msgids per
  language; only #562's five string-wrapping hunks remain candidates)

Review points:

- [ ] Confirm whether Rev-4 hardware is an actual target
- [ ] Decide whether GPIO14 poweroff latch should apply only to explicitly marked boards
- [ ] Decide sound/earcon default OFF policy
- [ ] Decide whether charger writes should be separate from read-only telemetry
- [ ] Preserve current `hardware_detect.py` fallback if adding `HardwareCapabilities`

## 17. cedar+SEP Hybrid Solving / cedar Full-Frame Primary Path

Priority: P0 — the reason this fork exists (accurate solving under light pollution)

Main changes:

- Two detectors in parallel (full-frame cedar σ8 + SEP σ4) + a four-stage
  coordinate cascade (cedar centre → cedar full → SEP centre → SEP full),
  behind `solver_cedar_fullframe`
- Six quality gates (edge/saturation/warm-pixel/cluster …) + optional
  IMU horizon mask
- Warm-pixel map (`sep_warm_map.py`), shadow-CSV instrumentation
  (`sep_shadow.py`), `solver_frame_map` (native-FOV solve → 512 semantics),
  `solve_path` diagnostics field
- Design authority: `mf_cedar_sep_hybrid_design_en.md`, ADR m0023

Key files: `python/PiFinder/solver.py`, `sep_detect.py`, `sep_warm_map.py`,
`sep_shadow.py`, `solver_frame_map.py`, `horizon_mask.py`

Review points:

- [ ] `/api/status` `solve_path` matches conditions
      (centre: `cedar_center`/`sep_center`; after centre failure:
      `cedar_full`/`sep_full`)
- [ ] Warm-pixel map is current (bias-238 re-verification — open SQM-port item)
- [ ] Gates reject ground point-light clusters (building windows)

Test items:

- [ ] Live solve rate under LP sky (reference: 88–90 % measured 08-01)
- [ ] Solve RMSE and match counts via `/api/status`
- [ ] `test_solver_cedar_fullframe.py`, `test_sep_detect.py`,
      `test_sep_fullframe_solve.py`

## 18. Auto Exposure — Star-Count Controller

Priority: P1

Main changes: star-count servo selected via Camera Exp "Star"
(`camera_exp=auto_star`), solve-success hold (ADR m0022), anchor clamps.
ADR m0020/m0021/m0022.

Key files: `python/PiFinder/auto_exposure_starcount.py`, `auto_exposure.py`,
`camera_interface.py`

Review / test items:

- [ ] Star mode select/deselect without regressing the stock AE modes
- [ ] `test_auto_exposure_starcount.py`

## 19. SQM Radiometer Stack + Mono Colour Guard

Priority: P1

Main changes:

- Upstream SQM stack ported (#532/#542/#543/#544): radiometer-first
  publishing, raw-green photometry, Gaia colour correction, wizard, sweeps
- Sweep exposure settling (#561) and the sky-colour zero point (#560)
  ported **with the mono guard** — without it the measured-mono imx462
  drifts ~+0.74 mag (`mf_report/mf_mono_sqm_colour_guard_20260805_*.md`)

Key files: `python/PiFinder/sqm/*`, `python/PiFinder/ui/sqm*.py`

Review points:

- [ ] imx462 SQM keeps the constant zero point (no colour fields)
- [ ] Open items: bias-238 night re-verification + one SQM wizard run

Test items: `test_sqm.py`, `test_radiometer.py`, `test_radiometric_fit.py`,
`test_sweep_frame_record.py`

## 20. LiveCam RAW Preview / Live Stack / Web Camera Controls

Priority: P1

Main changes:

- RAW preview + rolling stack, SEP overlay, `/api/camera/controls`
  exposure/gain, 16-bit TIFF download
- Live view always streams JPEG; the format setting governs downloads only
  (UI label "Download Format")
- Downloads are grayscale (mono sensor — debayer chroma is an artifact)

Key files: `python/PiFinder/raw_live_stack.py`, `livecam_config.py`,
`api_extensions.py`, `python/views/livecam.html`

Review / test items:

- [ ] Live refresh rate holds with the PNG setting (JPEG stream)
- [ ] Downloads deliver the chosen format verbatim (incl. webp)
- [ ] `test_raw_live_stack.py`, `test_api_camera_controls.py`

## 21. Web Catalogs / Unified Search / Observing Lists

Priority: P1

Main changes: on-device web catalog pages (routes/filters/push,
designation-first search ranking); WDS lazy-load designed (not built);
Stellarium/CSV import (upstream, applied)

Key files: `python/PiFinder/web_catalogs.py`, `python/views/catalogs*.html`

Review / test items:

- [ ] Unified-search ordering (designation first) and push-to
- [ ] Manual web-UI pass

## 22. Joystick / Gamepad Input

Priority: P2

Main changes: direct evdev reading (`joystick_input.py`), Settings >
Advanced > Joystick binding UI, mount jog wiring. `python3-evdev` installed
by the setup script.

Review / test items:

- [ ] Button capture/bind/Clear All, `test_joystick_input.py`

## 23. Software Update Channel — Fork Releases / m-Version

Priority: P1

Main changes:

- Release check and NixOS migration gate URLs point at
  `hjoungjoo/MF_PiFinder`'s release branch (never brickbots — pinned by
  tests)
- `version.txt` uses the m-prefix scheme (`m2.6.0`); `_semver_tuple()`
  strips it for comparison
- An unresolvable release ("Unknown") renders an info line instead of
  "Update Now"

Key files: `python/PiFinder/ui/software.py`, `version.txt`

Review / test items:

- [ ] After cutting a release branch: version compare / Update Now /
      `pifinder_update.sh` flow
- [ ] `test_software.py` (4 m-version + Unknown branch + 2 URL pins)

## 24. Display — SSD1333 Auto-Detection + Four-Axis Brightness

Priority: P2 (P1 once the SSD1333 panel is adopted)

Main changes:

- MF auto-detection: BQ25895 (0x6A) ACK → ssd1333, fallback ssd1351
  (`hardware_detect.py`)
- Upstream #568+#570 four-axis brightness, partial port (driver + tests +
  model docs; bench harnesses/journals excluded — see the MF note in
  `docs/ax/display/ssd1333-response.md`)
- Pi5 SPI helper (`display_spi`), `bus_speed_hz` signatures, MF `rotate=0`
  preserved

Review points:

- [ ] **A non-rev4 board with an SSD1333 needs `--display ssd1333`**
      (auto-detection keys on the rev4 marker)
- [ ] Title-bar dimmest shade stays lit across the brightness range
      (no real-panel measurement yet)

Test items: `test_ssd1333_brightness.py` (17),
`test_hardware_detect_display.py` (4)

## 25. Install Script / Migrations

Priority: P0

Main changes:

- `pifinder_setup.sh` = the fork installer (clones main); the upstream
  original is preserved as `pifinder_setup.sh.bak`
- SD-wear reduction (tmpfs /tmp, indiserver logrotate, journald cap),
  python3-evdev install, console autologin (B2)
- MF migrations: `mf_apsta_wifi`, `mf_wifi_settings`, `mf_removeipc`
  (marker-file gated — not version-string gated)

Review / test items:

- [ ] Fresh-OS `pifinder_setup.sh` completes as a normal user
- [ ] On upstream merges this file conflicts → reconcile against `.bak`
- [ ] `test_wifi_apsta_static.py` (reads the setup script by path)

## Minimum Regression Commands

The full suite finishes in under a minute (1,114 tests / ~55 s on the Pi4
venv as of 2026-08-05), so run it whole instead of curating file lists:

```bash
cd python/ && source .venv/bin/activate
python -m pytest -m "smoke or unit" -q
nox -s lint && nox -s format
```

Note: without the venv the system Python lacks selenium and collection
aborts on `tests/website` — check the venv first.

## Real-Hardware Integration Test Order

Recommended order:

1. PiFinder service boot
2. Web UI access
3. LCD/OLED UI
4. Camera preview/focus
5. GPS unlocked state
6. Load saved location
7. Time sync status
8. AP+STA networking
9. Bluetooth keyboard
10. INDI server/profile/driver start
11. OnStepX connection
12. Send Location and Time
13. Web INDI guide motion
14. LCD INDI guide motion
15. SkySafari Push-To
16. SkySafari GoTo forwarding OFF
17. SkySafari GoTo forwarding ON
18. SkySafari Align/Sync
19. Correction reset after plate solving
20. Reboot persistence
21. Night: hybrid solving solve_path / solve rate (§17)
22. Night: sanity-check the radiometer SQM + run the wizard if still open (§19)
23. LiveCam preview refresh rate and TIFF/format downloads (§20)
24. Software screen: release check watches the fork, m-version shown (§23)

## Result Recording Template

```text
Date:
Device:
OS:
Branch / commit:
Network mode:
Mount / driver:
GPS state:

Feature:
Expected:
Result:
Pass/Fail:
Notes:
Logs/screenshots:
```
