# MF_PiFinder Development Docs Index

Entry point for the `mf_*` docs the `MF_PiFinder` fork added during
development. Read the relevant doc before working in an area (don't reverse-infer
intent from code alone). For the higher-level structural reference (glossary,
architecture, decision records) see [CONTEXT-MAP.md](../CONTEXT-MAP.md),
`docs/ax/*`, `docs/adr/*`.

Layout (reorganised 2026-08-04):

| Folder | Holds |
|---|---|
| [`docs/mf_dev/`](mf_dev/) | Design & implementation write-ups, plans, install/ops guides, process docs |
| [`docs/mf_report/`](mf_report/) | Field-test and measurement reports, one-off failure analyses, review outputs |
| `docs/` (here) | This index, ko/en — the shared entry point for both folders, so it stays at the root |

Status labels: **living** = kept in sync with source / **install** = install &
ops guide / **plan** = pre- or partial implementation / **one-time** = completed
analysis/verification record (not maintained).

Last updated: 2026-10-04 (target tracking implementation and separate field-test handoff). The KO version (`mf_docs_index_ko.md`) is authoritative.

## INDI mount — coordinates & pointing (core)

| Doc | ko/en | Status | Summary |
|---|---|---|---|
| [coordinate_helper_plan](mf_dev/mf_coordinate_helper_plan_en.md) | both | living ★ | Authoritative `PointingCoordinateService` spec — coordinate candidates (solved/IMU/mount), selection priority, mount+IMU delta fusion (velocity gate, rotation tracker, tracking catch-up budget). **Canonical owner of coordinate selection / telemetry-gate semantics.** |
| [goto_mount_source_structure](mf_dev/mf_goto_mount_source_structure_en.md) | both | living ★ | Full SkySafari→mount source map (processes/queues, `pos_server` LX200 handling, push/forwarding/multi-align routing). **Canonical owner of SkySafari `:Sr/:Sd/:MS/:CM` + GoTo/Sync forwarding.** |
| [mountcontrol_indi_flow](mf_dev/mf_mountcontrol_indi_flow_en.md) | both | living | `mountcontrol_indi.py` flow (main loop, status-file schema, connect sequence, command dispatch). **Canonical owner of the `mountcontrol_queue` dispatch table.** |
| [indi_goto_guide_plan](mf_dev/mf_indi_goto_guide_plan_en.md) | both | living | `indi_goto_guide_service` GoTo/Guide state machine, tracking-guide disturbance recovery, tracking-frequency policy. |
| [multipoint_align_flow](mf_dev/mf_multipoint_align_flow_en.md) | both | living | Multi-Point Align detailed flow (**canonical owner**; others summarize + cite). |
| [backlash_measurement_flow](mf_dev/mf_backlash_measurement_flow_en.md) | both | living | Auto-backlash `compass_goto_loop` (**canonical owner**; others summarize + cite). |
| [mount_mode_compatibility](mf_dev/mf_mount_mode_compatibility_en.md) | both | plan (mostly built) | Alt/Az vs EQ SkySafari compatibility audit/checklist. |
| [visual_tracking_continuity_design](mf_dev/mf_visual_tracking_continuity_design_ko.md) | ko | **experimental implementation** | Target alignment and visual/solve continuity; existing planet calculations, Alt/Az first with shared EQ design. Default off; production control integration and hardware validation pending. |
| [visual_tracking_trial](mf_dev/mf_visual_tracking_trial_ko.md) | ko | **trial guide** | Confirmed environment manifests, command-free shadow/replay, implementation boundaries and validation status. |
| [smooth_tracking_environment_design](mf_dev/mf_smooth_tracking_environment_design_ko.md) | ko | **control implemented, hardware validation pending** | Catalog star ROIs, one pulse/prediction controller, equipment profiles, ownership, cancellation and bounded recovery. Default active remains separate from explicit Start. |
| [smooth_tracking_implementation_20261003](mf_report/mf_smooth_tracking_implementation_20261003_ko.md) | ko | **implementation and simulated/indoor validation** (2026-10-03) | Smooth visual correction, legacy control handover and removal of legacy predictive pulses. Lunar integration and sky validation remain follow-up work. |
| [moon_smooth_tracking_integration_plan_20261003](mf_dev/mf_moon_smooth_tracking_integration_plan_20261003_ko.md) | ko | **design and pre-implementation review** | Immediate solved alignment, motion-based bounded waiting, user center confirmation and target-specific tracking. Implementation status is maintained in the handoff report below. |
| [target_tracking_integration_20261004](mf_report/mf_target_tracking_integration_20261004_ko.md) | ko | **code integrated, automated tests, hardware pending** | Common asynchronous Align, lunar centre, planetary motion, relative stars and solve recovery. The new integration defaults to false, separating existing final tests from the new field-test group. |
| [indi_mount_install](mf_dev/mf_indi_mount_install_en.md) | both | install | INDI mount install/usage guide. |
| [indi_serial_reconnect_design](mf_dev/mf_indi_serial_reconnect_design_ko.md) | ko | **config reconciliation / USB reinsertion implemented** (2026-08-12) | INDI/PiFinder reconciliation and stable-by-id one-shot reconnect; continuous communication health remains follow-up work. |
| [indi_serial_auto_discovery_design](mf_dev/mf_indi_serial_auto_discovery_design_ko.md) | ko | **implemented / live-device verified** (2026-08-13) | When Auto is selected in the Web serial-port field, probe attached devices across supported baud rates with `:GVP#`/`:GVN#` and persist the unique verified stable port and speed. |

## Solving (core)

| Doc | ko/en | Status | Summary |
|---|---|---|---|
| [cedar_sep_hybrid_design](mf_dev/mf_cedar_sep_hybrid_design_en.md) | both | living ★ | **Design authority** for cedar+SEP hybrid solving — frame spaces / coordinate mapping, the six detection gates, warm-pixel map, fallback & backoff policy, hybrid alignment, AE coupling, defence layers. Decision rationale: ADR m0023; measurement history: sep_fullframe_impl (ko). |
| [cedar_fullframe_primary_plan](mf_dev/mf_cedar_fullframe_primary_plan_ko.md) | ko | **implemented, default-on** (2026-08-12) | Full-frame cedar primary transition plan and decision history — `solver_cedar_fullframe`, gates and centre-first cascade; the four-tier path is now the default. |

## Catalog · web UI

| Doc | ko/en | Status | Summary |
|---|---|---|---|
| [web_catalogs_dev](mf_dev/mf_web_catalogs_dev_ko.md) | ko | living | On-device web catalog pages (routes, filters, push, unified search with designation-prefix ranking). |
| [large_catalog_lazy_load](mf_dev/mf_large_catalog_lazy_load_ko.md) | ko | living | Large catalog (WDS) lazy load. |
| [location_catalog](mf_dev/mf_location_catalog_en.md) | both | living | GeoNames offline location catalog. |
| [raw_live_stack_plan](mf_dev/mf_raw_live_stack_plan_en.md) | both | living | LiveCam RAW preview / rolling live stack, web camera exposure/gain controls (`/api/camera/controls`). |

## Install · platform · system

| Doc | ko/en | Status | Summary |
|---|---|---|---|
| [trixie_install](mf_dev/mf_trixie_install_en.md) | both | install | Trixie 64-bit / Python 3.13 installation and paths. |
| [pifinder_new_device_tasks](mf_dev/mf_pifinder_new_device_tasks_en.md) | both | install | New-device setup task list. |
| [pifinder_rpi4_pi5_compatibility](mf_dev/mf_pifinder_rpi4_pi5_compatibility_en.md) | both | living | Pi4/5/CM5 board + GPS/UART compatibility. |
| [wifi_apsta](mf_dev/mf_wifi_apsta_en.md) | both | living | Simultaneous AP+STA Wi-Fi mode. |
| [time_sync](mf_dev/mf_time_sync_en.md) | both | living | GPS/NTP/RTC/PPS integrated time sync (system clock). |
| [i2c_clock_stretching_fix](mf_dev/mf_i2c_clock_stretching_fix_en.md) | both | living | I2C clock-stretching fix. |

## Input · UI · sensors

| Doc | ko/en | Status | Summary |
|---|---|---|---|
| [input_controls](mf_dev/mf_input_controls_en.md) | both | living | Input controls overview. |
| [input_keymap](mf_dev/mf_input_keymap_en.md) | both | living | Key map. |
| [keyboard_mapping](mf_dev/mf_keyboard_mapping_en.md) | both | living | BT/USB HID keyboard mapping. |
| [imu_compass_calibration](mf_dev/mf_imu_compass_calibration_en.md) | both | living | Optional BNO055 NDOF magnetometer calibration. |

## Analysis · review · plans (non-living, history/backlog)

| Doc | ko/en | Status | Summary |
|---|---|---|---|
| [field_test_20260724_analysis](mf_report/mf_field_test_20260724_analysis_ko.md) | ko | **analysis + fixes in progress** (2026-07-25) | Field-test failure analysis (no-time-source clock error; IMU-fallback auto sync confirmed as intended design) with fix checklist. |
| [goto_tracking_recovery_analysis](mf_report/mf_goto_tracking_recovery_analysis_ko.md) | ko | **one-time** (2026-07-18) | OnStepX GoTo no-op (wedge) failure analysis + recovery verification. |
| [indi_onstep_driver_test_checklist](mf_report/mf_indi_onstep_driver_test_checklist_ko.md) | ko | **one-time** (2026-07-01) | INDI driver vs raw LX200 pre-integration verification record. |
| [solve_motion_gate_review](mf_dev/mf_solve_motion_gate_review_en.md) | both | **plan (unbuilt)** | Unwired solve gate for frames exposed during motion (pending decision). |
| [auto_exposure_methods](mf_dev/mf_auto_exposure_methods_en.md) | both | **survey (done)** | Survey of auto exposure/gain control methods — problems of the current match-count approach (P1–P7), alternatives (detected-star-count servo etc.), draft recommendation. |
| [auto_exposure_plan](mf_dev/mf_auto_exposure_plan_ko.md) | ko | **implemented (field validation pending)** | Detected-star-count controller design+implementation — existing behavior kept, selected via the Camera Exp menu's "Star" item (`camera_exp=auto_star`). ADR m0020. |
| [auto_star_framewise_exposure_gain_research](mf_dev/mf_auto_star_framewise_exposure_gain_research_ko.md) | ko | **continuous-capture foundation implemented; controller pending** | Triple-buffer/latest-wins capture and frame pairing are implemented. The Auto(Star) design prioritises pointing/tracking, peripheral catalog-matched-star SNR, Moon exclusion, and evidence-based gain reduction. |
| [solver_3path_bench_20260801](mf_report/mf_solver_3path_bench_20260801_en.md) | both | **one-time measurement** (2026-08-01) | Bright-sky (87% background) same-frame bench of three solver paths — cedar crop 0% / cedar full-frame σ8 18% / hybrid 88% (live 89.5%), accuracy 1σ ~1′ (reconfirms ADR m0023). |
| [solver_fullframe_field_test_20260803](mf_report/mf_solver_fullframe_field_test_20260803_ko.md) | ko | **one-time measurement** (2026-08-03) | Night measurement of the cedar full-frame primary path (~2,200 shadow-CSV attempts) — LP curve and timeout A/B. Plan: [cedar_fullframe_primary_plan](mf_dev/mf_cedar_fullframe_primary_plan_ko.md). |
| [fullframe_solving_report_20260804](mf_report/mf_fullframe_solving_report_20260804_en.md) | both | **report** (2026-08-04) | Full-frame solving pipeline measurement report — processing structure (two detectors in parallel + four-stage coordinate cascade) and measured results. |
| [solver_diagnostics_20260812](mf_report/mf_solver_diagnostics_20260812_ko.md) | ko | **one-time measurement** (2026-08-12) | Default-on four-tier full-frame path and per-stage Cedar/SEP diagnostics verification — live `cedar_ff_center` and `cedar_ff` successes. |
| [solver_cascade_order_20260812](mf_report/mf_solver_cascade_order_20260812_ko.md) | ko | **change verification** (2026-08-12) | Globally centre-first cascade with call-order/live verification; path names clarified as `cedar_center`/`sep_center`/`cedar_full`/`sep_full`. |
| [indi_connection_config_reconcile_20260812](mf_report/mf_indi_connection_config_reconcile_20260812_ko.md) | ko | **change/live-device verification** (2026-08-12) | Live/XML-first INDI reconciliation, atomic PiFinder mirror writes, and live USB/by-id/115200 migration plus connection verification. |
| [indi_usb_reinsert_field_test_20260812](mf_report/mf_indi_usb_reinsert_field_test_20260812_ko.md) | ko | **implementation/live verification** (2026-08-12) | Actual OnStepX USB removal/reinsertion, one-shot device-session recovery, fresh telemetry, and mount-state preservation verification. |
| [indi_serial_port_dedup_20260813](mf_report/mf_indi_serial_port_dedup_20260813_ko.md) | ko | **implementation/live verification** (2026-08-13) | Realpath-based collapse of duplicate by-id and ttyUSB aliases, retaining one stable by-id entry in the Web list. |
| [indi_serial_auto_discovery_20260813](mf_report/mf_indi_serial_auto_discovery_20260813_ko.md) | ko | **implementation/automated/live verification** (2026-08-13) | User-triggered read-only OnStep port/baud discovery with unique-candidate selection, fresh-telemetry save gate, and rollback. |
| [feature_test_session_20260805](mf_report/mf_feature_test_session_20260805_ko.md) | ko | **one-time** (2026-08-05) | Automated portion of the checklist re-test — static/suite/API/headless UI pass; three defects found & fixed (ungated Software RIGHT, update exception unwinding the UI, imu_fake signature); remaining manual items listed. |
| [mono_sqm_colour_guard_20260805](mf_report/mf_mono_sqm_colour_guard_20260805_en.md) | both | **announcement** (2026-08-05) | Community share — how upstream #560's sky-colour SQM correction silently shifts a mislabeled mono imx462 by +0.74 mag, the `profile.mono` guard, and how to test your own module. |
| [sqm_stack_port_plan](mf_dev/mf_sqm_stack_port_plan_ko.md) | ko | **port complete** (2026-07-30) | Analysis and plan for porting the upstream SQM stack (#532/#542/#543/#544), with per-phase outcomes. |
| [gps_ubx_recovery_20260909](mf_report/mf_gps_ubx_recovery_20260909_en.md) | both | **incident / change report** | Intermittent NMEA-only u-blox identification stall, bounded MON-VER retry, regression, TCP and live-device verification. |
| [gps_aiding_plan](mf_dev/mf_gps_aiding_plan_en.md) | both | **plan (pre-impl)** | u-blox GPS aiding (MGA-INI/DBD) design draft. |
| [camera_mono_color_plan](mf_dev/mf_camera_mono_color_plan_ko.md) | ko | **implemented** (2026-08-08) | Make the IMX296/IMX462 mono·colour variant a setting (5-entry Camera Type menu + `camera_variant`) — variant-suffixed profile names propagate to every process, dtoverlay untouched. Propagation verified on a real colour imx462; SQM constants still inherited from mono, unverified (§8). |

## Meta · history · process

| Doc | ko/en | Status | Summary |
|---|---|---|---|
| [change_history](mf_dev/mf_change_history_en.md) | both | living | Full source-change history (by feature/file). The PR-status table is a 2026-06-27 snapshot (now: direct-to-main). |
| [upstream_patch_reference](mf_dev/mf_upstream_patch_reference_en.md) | both | living | `brickbots/PiFinder` rebase/merge reference. |
| [feature_review_checklist](mf_dev/mf_feature_review_checklist_en.md) | both | living | Feature review checklist. |
| [ko_translation_review](mf_report/mf_ko_translation_review.md) | single | living | Korean UI translation review. |

## Canonical owners for overlapping topics

When several docs cover the same mechanism, the authoritative description lives in
one place and the rest keep only a summary + cross-reference (update the owner
first when editing).

| Topic | Canonical owner | Docs that only summarize |
|---|---|---|
| SkySafari `:Sr/:Sd/:MS/:CM` + GoTo/Sync forwarding | goto_mount_source_structure | indi_goto_guide_plan, mount_mode_compatibility, coordinate_helper_plan, upstream_patch_reference |
| Coordinate selection priority · mount telemetry-gate semantics | coordinate_helper_plan | mountcontrol_indi_flow, goto_mount_source_structure |
| `mountcontrol_queue` command dispatch table | mountcontrol_indi_flow | goto_mount_source_structure |
| Multi-Point Align detail | multipoint_align_flow | mountcontrol_indi_flow, indi_mount_install |
| Backlash measurement detail | backlash_measurement_flow | mountcontrol_indi_flow, indi_mount_install |
| Location/Time sync convention (`:SG` sign, PyIndi full-vector) | goto_mount_source_structure | indi_mount_install, mountcontrol_indi_flow, coordinate_helper_plan (auto-resync only is unique) |
| cedar+SEP hybrid solving design | cedar_sep_hybrid_design | sep_fullframe_impl (history/measurements, ko), cedar_sep_hybrid_solve_20260728 (post), solver_3path_bench_20260801 (one-time bench) |
