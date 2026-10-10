# 개발 문서 통합 이력과 이전 경로 대응표

2026-10-10 정리. 현재 구현은 [개발 기준 문서](../../mf_dev/README.md)를 따른다.
한국어 설계·조사 원문을 아래 9개 주제에 합쳤다. 원문 본문은 링크 경로·제목 깊이를 조정했으며 작성 당시의 수치와 판단을 보존했다.
중복 영문 개별 문서는 제거하고 현재 영문 설치와 GoTo 요약을 유지했다. 이전 영문은 `git show <revision>:docs/mf_dev/<filename>`으로 조회한다.

- [설치·개발 환경](setup.md)
- [마운트·GoTo·정렬](mount.md)
- [포인팅·IMU](positioning.md)
- [솔빙·검출·전처리](solver.md)
- [카메라·광학·영상](camera.md)
- [입력·웹·카탈로그](interfaces.md)
- [연결·GPS·시간·네트워크](connectivity.md)
- [검증·현장 수집](validation.md)
- [변경·업스트림 통합](maintenance.md)

## 이전 파일과 새 위치

| 이전 파일 | 현재 기준 | 원문 이력 |
|---|---|---|
| `TRIXIE_20260926_ko.md` | [setup_ko.md](../../mf_dev/setup_ko.md) | [한국어 원문 보관](setup.md#TRIXIE_20260926_ko) |
| `TRIXIE_DEVELOPMENT_ko.md` | [setup_ko.md](../../mf_dev/setup_ko.md) | [한국어 원문 보관](setup.md#TRIXIE_DEVELOPMENT_ko) |
| `gpsd_stable_ko.md` | [connectivity_ko.md](../../mf_dev/connectivity_ko.md) | [한국어 원문 보관](connectivity.md#gpsd_stable_ko) |
| `mf_adaptive_solver_scheduling_ko.md` | [solver_ko.md](../../mf_dev/solver_ko.md) | [한국어 원문 보관](solver.md#mf_adaptive_solver_scheduling_ko) |
| `mf_additional_features_en.md` | [README.md](../../mf_dev/README.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](maintenance.md#mf_additional_features_ko) |
| `mf_additional_features_ko.md` | [README.md](../../mf_dev/README.md) | [한국어 원문 보관](maintenance.md#mf_additional_features_ko) |
| `mf_auto_exposure_methods_en.md` | [camera_ko.md](../../mf_dev/camera_ko.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](camera.md#mf_auto_exposure_methods_ko) |
| `mf_auto_exposure_methods_ko.md` | [camera_ko.md](../../mf_dev/camera_ko.md) | [한국어 원문 보관](camera.md#mf_auto_exposure_methods_ko) |
| `mf_auto_exposure_plan_ko.md` | [camera_ko.md](../../mf_dev/camera_ko.md) | [한국어 원문 보관](camera.md#mf_auto_exposure_plan_ko) |
| `mf_auto_star_framewise_exposure_gain_research_ko.md` | [camera_ko.md](../../mf_dev/camera_ko.md) | [한국어 원문 보관](camera.md#mf_auto_star_framewise_exposure_gain_research_ko) |
| `mf_backlash_measurement_flow_en.md` | [alignment_ko.md](../../mf_dev/alignment_ko.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](mount.md#mf_backlash_measurement_flow_ko) |
| `mf_backlash_measurement_flow_ko.md` | [alignment_ko.md](../../mf_dev/alignment_ko.md) | [한국어 원문 보관](mount.md#mf_backlash_measurement_flow_ko) |
| `mf_bookworm_install_en.md` | [setup_ko.md](../../mf_dev/setup_ko.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](setup.md#mf_bookworm_install_ko) |
| `mf_bookworm_install_ko.md` | [setup_ko.md](../../mf_dev/setup_ko.md) | [한국어 원문 보관](setup.md#mf_bookworm_install_ko) |
| `mf_cache_download_en.md` | [interfaces_ko.md](../../mf_dev/interfaces_ko.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](interfaces.md#mf_cache_download_ko) |
| `mf_cache_download_ko.md` | [interfaces_ko.md](../../mf_dev/interfaces_ko.md) | [한국어 원문 보관](interfaces.md#mf_cache_download_ko) |
| `mf_camera_mono_color_plan_ko.md` | [camera_ko.md](../../mf_dev/camera_ko.md) | [한국어 원문 보관](camera.md#mf_camera_mono_color_plan_ko) |
| `mf_cedar_fullframe_primary_plan_ko.md` | [solver_ko.md](../../mf_dev/solver_ko.md) | [한국어 원문 보관](solver.md#mf_cedar_fullframe_primary_plan_ko) |
| `mf_cedar_sep_hybrid_design_en.md` | [solver_ko.md](../../mf_dev/solver_ko.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](solver.md#mf_cedar_sep_hybrid_design_ko) |
| `mf_cedar_sep_hybrid_design_ko.md` | [solver_ko.md](../../mf_dev/solver_ko.md) | [한국어 원문 보관](solver.md#mf_cedar_sep_hybrid_design_ko) |
| `mf_change_history_en.md` | [README.md](../../mf_dev/README.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](maintenance.md#mf_change_history_ko) |
| `mf_change_history_ko.md` | [README.md](../../mf_dev/README.md) | [한국어 원문 보관](maintenance.md#mf_change_history_ko) |
| `mf_coordinate_helper_plan_en.md` | [positioning_ko.md](../../mf_dev/positioning_ko.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](positioning.md#mf_coordinate_helper_plan_ko) |
| `mf_coordinate_helper_plan_ko.md` | [positioning_ko.md](../../mf_dev/positioning_ko.md) | [한국어 원문 보관](positioning.md#mf_coordinate_helper_plan_ko) |
| `mf_false_solve_evening_validation_ko.md` | [solver_ko.md](../../mf_dev/solver_ko.md) | [한국어 원문 보관](solver.md#mf_false_solve_evening_validation_ko) |
| `mf_feature_review_checklist_en.md` | [validation_ko.md](../../mf_dev/validation_ko.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](validation.md#mf_feature_review_checklist_ko) |
| `mf_feature_review_checklist_ko.md` | [validation_ko.md](../../mf_dev/validation_ko.md) | [한국어 원문 보관](validation.md#mf_feature_review_checklist_ko) |
| `mf_goto_mount_source_structure_en.md` | [mount_control_ko.md](../../mf_dev/mount_control_ko.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](mount.md#mf_goto_mount_source_structure_ko) |
| `mf_goto_mount_source_structure_ko.md` | [mount_control_ko.md](../../mf_dev/mount_control_ko.md) | [한국어 원문 보관](mount.md#mf_goto_mount_source_structure_ko) |
| `mf_gps_aiding_plan_en.md` | [connectivity_ko.md](../../mf_dev/connectivity_ko.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](connectivity.md#mf_gps_aiding_plan_ko) |
| `mf_gps_aiding_plan_ko.md` | [connectivity_ko.md](../../mf_dev/connectivity_ko.md) | [한국어 원문 보관](connectivity.md#mf_gps_aiding_plan_ko) |
| `mf_i2c_clock_stretching_fix_en.md` | [connectivity_ko.md](../../mf_dev/connectivity_ko.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](connectivity.md#mf_i2c_clock_stretching_fix_ko) |
| `mf_i2c_clock_stretching_fix_ko.md` | [connectivity_ko.md](../../mf_dev/connectivity_ko.md) | [한국어 원문 보관](connectivity.md#mf_i2c_clock_stretching_fix_ko) |
| `mf_imu_compass_calibration_en.md` | [positioning_ko.md](../../mf_dev/positioning_ko.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](positioning.md#mf_imu_compass_calibration_ko) |
| `mf_imu_compass_calibration_ko.md` | [positioning_ko.md](../../mf_dev/positioning_ko.md) | [한국어 원문 보관](positioning.md#mf_imu_compass_calibration_ko) |
| `mf_imu_current_behavior_analysis_ko.md` | [positioning_ko.md](../../mf_dev/positioning_ko.md) | [한국어 원문 보관](positioning.md#mf_imu_current_behavior_analysis_ko) |
| `mf_imu_relative_magnetic_drift_plan_ko.md` | [positioning_ko.md](../../mf_dev/positioning_ko.md) | [한국어 원문 보관](positioning.md#mf_imu_relative_magnetic_drift_plan_ko) |
| `mf_imx678_ko.md` | [setup_ko.md](../../mf_dev/setup_ko.md) | [한국어 원문 보관](setup.md#mf_imx678_ko) |
| `mf_indi_goto_guide_plan_en.md` | [mount_control_en.md](../../mf_dev/mount_control_en.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](mount.md#mf_indi_goto_guide_plan_ko) |
| `mf_indi_goto_guide_plan_ko.md` | [mount_control_ko.md](../../mf_dev/mount_control_ko.md) | [한국어 원문 보관](mount.md#mf_indi_goto_guide_plan_ko) |
| `mf_indi_mount_install_en.md` | [setup_en.md](../../mf_dev/setup_en.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](mount.md#mf_indi_mount_install_ko) |
| `mf_indi_mount_install_ko.md` | [setup_ko.md](../../mf_dev/setup_ko.md) | [한국어 원문 보관](mount.md#mf_indi_mount_install_ko) |
| `mf_indi_serial_auto_discovery_design_ko.md` | [connectivity_ko.md](../../mf_dev/connectivity_ko.md) | [한국어 원문 보관](connectivity.md#mf_indi_serial_auto_discovery_design_ko) |
| `mf_indi_serial_reconnect_design_ko.md` | [connectivity_ko.md](../../mf_dev/connectivity_ko.md) | [한국어 원문 보관](connectivity.md#mf_indi_serial_reconnect_design_ko) |
| `mf_input_controls_en.md` | [interfaces_ko.md](../../mf_dev/interfaces_ko.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](interfaces.md#mf_input_controls_ko) |
| `mf_input_controls_ko.md` | [interfaces_ko.md](../../mf_dev/interfaces_ko.md) | [한국어 원문 보관](interfaces.md#mf_input_controls_ko) |
| `mf_input_keymap_en.md` | [interfaces_ko.md](../../mf_dev/interfaces_ko.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](interfaces.md#mf_input_keymap_ko) |
| `mf_input_keymap_ko.md` | [interfaces_ko.md](../../mf_dev/interfaces_ko.md) | [한국어 원문 보관](interfaces.md#mf_input_keymap_ko) |
| `mf_keyboard_mapping_en.md` | [interfaces_ko.md](../../mf_dev/interfaces_ko.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](interfaces.md#mf_keyboard_mapping_ko) |
| `mf_keyboard_mapping_ko.md` | [interfaces_ko.md](../../mf_dev/interfaces_ko.md) | [한국어 원문 보관](interfaces.md#mf_keyboard_mapping_ko) |
| `mf_large_catalog_lazy_load_ko.md` | [interfaces_ko.md](../../mf_dev/interfaces_ko.md) | [한국어 원문 보관](interfaces.md#mf_large_catalog_lazy_load_ko) |
| `mf_lcd_operation_errors_ko.md` | [interfaces_ko.md](../../mf_dev/interfaces_ko.md) | [한국어 원문 보관](interfaces.md#mf_lcd_operation_errors_ko) |
| `mf_lens_distortion_correction_en.md` | [camera_ko.md](../../mf_dev/camera_ko.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](camera.md#mf_lens_distortion_correction_ko) |
| `mf_lens_distortion_correction_ko.md` | [camera_ko.md](../../mf_dev/camera_ko.md) | [한국어 원문 보관](camera.md#mf_lens_distortion_correction_ko) |
| `mf_live_stack_stabilization_research_ko.md` | [camera_ko.md](../../mf_dev/camera_ko.md) | [한국어 원문 보관](camera.md#mf_live_stack_stabilization_research_ko) |
| `mf_location_catalog_en.md` | [interfaces_ko.md](../../mf_dev/interfaces_ko.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](interfaces.md#mf_location_catalog_ko) |
| `mf_location_catalog_ko.md` | [interfaces_ko.md](../../mf_dev/interfaces_ko.md) | [한국어 원문 보관](interfaces.md#mf_location_catalog_ko) |
| `mf_moon_safe_goto_handoff_design_ko.md` | [tracking_ko.md](../../mf_dev/tracking_ko.md) | [한국어 원문 보관](mount.md#mf_moon_safe_goto_handoff_design_ko) |
| `mf_moon_smooth_tracking_integration_plan_20261003_ko.md` | [tracking_ko.md](../../mf_dev/tracking_ko.md) | [한국어 원문 보관](mount.md#mf_moon_smooth_tracking_integration_plan_20261003_ko) |
| `mf_mount_mode_compatibility_en.md` | [mount_control_ko.md](../../mf_dev/mount_control_ko.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](mount.md#mf_mount_mode_compatibility_ko) |
| `mf_mount_mode_compatibility_ko.md` | [mount_control_ko.md](../../mf_dev/mount_control_ko.md) | [한국어 원문 보관](mount.md#mf_mount_mode_compatibility_ko) |
| `mf_mountcontrol_indi_flow_en.md` | [mount_control_ko.md](../../mf_dev/mount_control_ko.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](mount.md#mf_mountcontrol_indi_flow_ko) |
| `mf_mountcontrol_indi_flow_ko.md` | [mount_control_ko.md](../../mf_dev/mount_control_ko.md) | [한국어 원문 보관](mount.md#mf_mountcontrol_indi_flow_ko) |
| `mf_multipoint_align_flow_en.md` | [alignment_ko.md](../../mf_dev/alignment_ko.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](mount.md#mf_multipoint_align_flow_ko) |
| `mf_multipoint_align_flow_ko.md` | [alignment_ko.md](../../mf_dev/alignment_ko.md) | [한국어 원문 보관](mount.md#mf_multipoint_align_flow_ko) |
| `mf_optical_train_fov_integration_ko.md` | [camera_ko.md](../../mf_dev/camera_ko.md) | [한국어 원문 보관](camera.md#mf_optical_train_fov_integration_ko) |
| `mf_pifinder_new_device_tasks_en.md` | [setup_ko.md](../../mf_dev/setup_ko.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](setup.md#mf_pifinder_new_device_tasks_ko) |
| `mf_pifinder_new_device_tasks_ko.md` | [setup_ko.md](../../mf_dev/setup_ko.md) | [한국어 원문 보관](setup.md#mf_pifinder_new_device_tasks_ko) |
| `mf_pifinder_rpi4_pi5_compatibility_en.md` | [setup_ko.md](../../mf_dev/setup_ko.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](setup.md#mf_pifinder_rpi4_pi5_compatibility_ko) |
| `mf_pifinder_rpi4_pi5_compatibility_ko.md` | [setup_ko.md](../../mf_dev/setup_ko.md) | [한국어 원문 보관](setup.md#mf_pifinder_rpi4_pi5_compatibility_ko) |
| `mf_raw_live_stack_plan_en.md` | [camera_ko.md](../../mf_dev/camera_ko.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](camera.md#mf_raw_live_stack_plan_ko) |
| `mf_raw_live_stack_plan_ko.md` | [camera_ko.md](../../mf_dev/camera_ko.md) | [한국어 원문 보관](camera.md#mf_raw_live_stack_plan_ko) |
| `mf_sep_fullframe_impl_ko.md` | [solver_ko.md](../../mf_dev/solver_ko.md) | [한국어 원문 보관](solver.md#mf_sep_fullframe_impl_ko) |
| `mf_slew_rate_feedback_en.md` | [mount_control_ko.md](../../mf_dev/mount_control_ko.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](mount.md#mf_slew_rate_feedback_ko) |
| `mf_slew_rate_feedback_ko.md` | [mount_control_ko.md](../../mf_dev/mount_control_ko.md) | [한국어 원문 보관](mount.md#mf_slew_rate_feedback_ko) |
| `mf_smooth_tracking_environment_design_ko.md` | [tracking_ko.md](../../mf_dev/tracking_ko.md) | [한국어 원문 보관](mount.md#mf_smooth_tracking_environment_design_ko) |
| `mf_solve_motion_gate_review_en.md` | [solver_ko.md](../../mf_dev/solver_ko.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](solver.md#mf_solve_motion_gate_review_ko) |
| `mf_solve_motion_gate_review_ko.md` | [solver_ko.md](../../mf_dev/solver_ko.md) | [한국어 원문 보관](solver.md#mf_solve_motion_gate_review_ko) |
| `mf_solver_goto_field_sheet_20260908_ko.md` | [validation_ko.md](../../mf_dev/validation_ko.md) | [한국어 원문 보관](validation.md#mf_solver_goto_field_sheet_20260908_ko) |
| `mf_solver_goto_observation_workplan_20260908_ko.md` | [validation_ko.md](../../mf_dev/validation_ko.md) | [한국어 원문 보관](validation.md#mf_solver_goto_observation_workplan_20260908_ko) |
| `mf_solver_performance_capture_workplan_20260907_ko.md` | [validation_ko.md](../../mf_dev/validation_ko.md) | [한국어 원문 보관](validation.md#mf_solver_performance_capture_workplan_20260907_ko) |
| `mf_sqm_stack_port_plan_ko.md` | [camera_ko.md](../../mf_dev/camera_ko.md) | [한국어 원문 보관](camera.md#mf_sqm_stack_port_plan_ko) |
| `mf_star_only_preprocess_design_ko.md` | [solver_ko.md](../../mf_dev/solver_ko.md) | [한국어 원문 보관](solver.md#mf_star_only_preprocess_design_ko) |
| `mf_stellarium_push_port_analysis_ko.md` | [interfaces_ko.md](../../mf_dev/interfaces_ko.md) | [한국어 원문 보관](interfaces.md#mf_stellarium_push_port_analysis_ko) |
| `mf_time_sync_en.md` | [connectivity_ko.md](../../mf_dev/connectivity_ko.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](connectivity.md#mf_time_sync_ko) |
| `mf_time_sync_ko.md` | [connectivity_ko.md](../../mf_dev/connectivity_ko.md) | [한국어 원문 보관](connectivity.md#mf_time_sync_ko) |
| `mf_trixie_install_en.md` | [setup_en.md](../../mf_dev/setup_en.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](setup.md#mf_trixie_install_ko) |
| `mf_trixie_install_ko.md` | [setup_ko.md](../../mf_dev/setup_ko.md) | [한국어 원문 보관](setup.md#mf_trixie_install_ko) |
| `mf_upstream_patch_reference_en.md` | [README.md](../../mf_dev/README.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](maintenance.md#mf_upstream_patch_reference_ko) |
| `mf_upstream_patch_reference_ko.md` | [README.md](../../mf_dev/README.md) | [한국어 원문 보관](maintenance.md#mf_upstream_patch_reference_ko) |
| `mf_visual_tracking_continuity_design_ko.md` | [tracking_ko.md](../../mf_dev/tracking_ko.md) | [한국어 원문 보관](mount.md#mf_visual_tracking_continuity_design_ko) |
| `mf_visual_tracking_trial_ko.md` | [tracking_ko.md](../../mf_dev/tracking_ko.md) | [한국어 원문 보관](mount.md#mf_visual_tracking_trial_ko) |
| `mf_web_catalogs_dev_ko.md` | [interfaces_ko.md](../../mf_dev/interfaces_ko.md) | [한국어 원문 보관](interfaces.md#mf_web_catalogs_dev_ko) |
| `mf_wide_angle_solver_design_ko.md` | [solver_ko.md](../../mf_dev/solver_ko.md) | [한국어 원문 보관](solver.md#mf_wide_angle_solver_design_ko) |
| `mf_wide_angle_solver_implementation_plan_ko.md` | [solver_ko.md](../../mf_dev/solver_ko.md) | [한국어 원문 보관](solver.md#mf_wide_angle_solver_implementation_plan_ko) |
| `mf_wide_tiles_livecam_ko.md` | [solver_ko.md](../../mf_dev/solver_ko.md) | [한국어 원문 보관](solver.md#mf_wide_tiles_livecam_ko) |
| `mf_wifi_apsta_en.md` | [connectivity_ko.md](../../mf_dev/connectivity_ko.md) | [번역 사본 정리; 한국어 기록 / 영문 원문은 Git 이력](connectivity.md#mf_wifi_apsta_ko) |
| `mf_wifi_apsta_ko.md` | [connectivity_ko.md](../../mf_dev/connectivity_ko.md) | [한국어 원문 보관](connectivity.md#mf_wifi_apsta_ko) |
