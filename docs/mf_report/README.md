# MFNavis 현장·검증 보고서

날짜와 장비 조건에 묶인 관측 사실, 실측, 장애 분석과 배포 검증을 보존한다.
이전 결과의 수치·조건은 그대로 읽고 현재 코드의 정책은 [개발 기준 문서](../mf_dev/README.md)를 따른다.
과거 설계·조사는 [통합 이력](../history/development/README.md)에 있다.

## 현재 코드 검증

2026-10-10 GoTo 시작부터 추적·보정까지의 881개 자동 회귀 기록은
[마운트 기준 문서](../mf_dev/mount_control_ko.md)에 통합했다.
이는 장비를 움직인 현장 보고서와 구분한다. 검사 실행과 남은 실장 항목은
[검증 안내](../mf_dev/validation_ko.md)를 참조한다.

## 날짜·주제별 기록

### 마운트·GoTo·추적·정렬

| 날짜 | 보고서 |
|---|---|
| 문서 참조 | [INDI LX200 OnStepX Driver Test Checklist](mf_indi_onstep_driver_test_checklist_ko.md) |
| 문서 참조 | [SkySafari GoTo 무동작 장애 분석 및 복구 검증 (2026-07-18)](mf_goto_tracking_recovery_analysis_ko.md) |
| 20261004 | [대상별 영상 추적 구현과 최종 시험 인계](mf_target_tracking_integration_20261004_ko.md) |
| 20261003 | [부드러운 추적 보정 구현 및 실내 검증 — 2026-10-03](mf_smooth_tracking_implementation_20261003_ko.md) |
| 20261002 | [렌즈 재보정 후 보정 반복 진단 (2026-10-02)](mf_guide_resume_20261002_ko.md) |
| 20260929 | [토성 수동 정렬과 중심점 갱신 — 2026-09-29](mf_saturn_imu_alignment_20260929_ko.md) |
| 20260929 | [정지 상태 IMU GoTo 차단 수정 — 2026-09-29](mf_goto_stationary_imu_20260929_ko.md) |
| 20260927 | [2026-09-27 INDI Settings 제한값 조회·변경](mfnavis_trixie_indi_limits_20260927_ko.md) |
| 20260927 | [2026-09-27 Trixie GoTo 실테스트 사용자 결과](mfnavis_trixie_goto_field_20260927_ko.md) |
| 20260918 | [GOTO 이후 펄스 보정 발산과 재획득 수정 (2026-09-18)](mf_goto_drift_recovery_20260918_ko.md) |
| 20260917 | [GOTO 이동 중 PUSH·SkySafari 표시 갱신 — 2026-09-17](mf_goto_display_motion_20260917_ko.md) |
| 20260914 | [GOTO 완료·지속 보정·수동 정렬의 LCD 기준 통일](mf_alignment_tracking_hold_20260914_ko.md) |
| 20260909 | [수동 이동 / 펄스 가이드 속도 분리 — 2026-09-09](mf_motion_rate_profiles_20260909_ko.md) |
| 20260908 | [2026-09-08 토성 추적 실측: 저고도 지연과 GoTo 관측 시각 보호](mf_solver_goto_field_test_20260908_ko.md) |
| 20260908 | [첫 GoTo의 정렬 완료 검증 — 2026-09-08](mf_goto_sync_verification_20260908_ko.md) |
| 20260906 | [SkySafari 정렬 응답 지연: 직전 솔빙으로 즉시 계산](mf_skysafari_cached_align_20260906_ko.md) |

### 솔빙·검출·노출·카메라

| 날짜 | 보고서 |
|---|---|
| 20260927 | [2026-09-27 Trixie 실내 GoTo: 솔빙 실패 시 IMU·마운트 전환](mfnavis_trixie_solve_fallback_20260927_ko.md) |
| 20260917 | [Solver CPU·메모리 개선 — 2026-09-17](solver_optimization_20260917_ko.md) |
| 20260916 | [밝은 포화 별 보존과 프레임 전달 수정 — 2026-09-16](mf_compact_saturation_frame_pair_fix_20260916_ko.md) |
| 20260908 | [2026-09-08 솔빙 속도 후속 개선](mf_solver_speed_followup_20260908_ko.md) |
| 20260906 | [2026-09-06 관측 튜닝의 설치 기본값](mf_observing_defaults_20260906_ko.md) |
| 20260906 | [낮은 고도 지상 조명에 의한 Auto(Star) 노출 축소](mf_low_altitude_auto_star_20260906_ko.md) |
| 20260906 | [저고도 Auto(Star) 재획득 및 밝은 배경 진동 수정](mf_auto_star_reacquisition_20260906_ko.md) |
| 20260906 | [비동기 전처리 결과 미반영으로 인한 솔빙 불가](mf_async_preprocess_pointing_starvation_20260906_ko.md) |
| 20260812 | [풀프레임 4단 기본 활성화·솔버 진단 개선 실기 리포트 (2026-08-12)](mf_solver_diagnostics_20260812_ko.md) |
| 20260812 | [솔버 캐스케이드 전역 중앙 우선 순서 변경 리포트 (2026-08-12)](mf_solver_cascade_order_20260812_ko.md) |
| 20260805 | [베이어 라벨이 거짓말할 때 — 모노 IMX462와 하늘색 기반 SQM zero point (2026-08-05)](mf_mono_sqm_colour_guard_20260805_ko.md) |
| 20260805 | [When the Bayer label lies: a mono IMX462 and the sky-colour SQM zero point (2026-08-05)](mf_mono_sqm_colour_guard_20260805_en.md) |
| 20260804 | [MF_PiFinder 테스트 리포트 — 풀프레임 솔빙 파이프라인 실측 (2026-08-04)](mf_fullframe_solving_report_20260804_ko.md) |
| 20260804 | [MF_PiFinder Test Report — Full-Frame Solving Pipeline, Field Measurements (2026-08-04)](mf_fullframe_solving_report_20260804_en.md) |
| 20260803 | [cedar 풀프레임 1차 경로 — 야간 실측 리포트 (2026-08-03)](mf_solver_fullframe_field_test_20260803_ko.md) |
| 20260801 | [3경로 솔빙 실측 벤치 — cedar 크롭 / cedar 풀프레임 σ8 / cedar+SEP 하이브리드 (2026-08-01)](mf_solver_3path_bench_20260801_ko.md) |
| 20260801 | [Three-Path Solver Bench — cedar crop / cedar full-frame σ8 / cedar+SEP hybrid (2026-08-01)](mf_solver_3path_bench_20260801_en.md) |
| 20260728 | [MF_PiFinder 개발 소식 — cedar + SEP 하이브리드 솔빙, 광해 하늘 실증 (2026-07-28)](mf_cedar_sep_hybrid_solve_20260728_ko.md) |
| 20260728 | [MF_PiFinder Update — cedar + SEP Hybrid Solving, Field-Proven Under Light Pollution (2026-07-28)](mf_cedar_sep_hybrid_solve_20260728_en.md) |
| 20260726 | [자동 노출 현장 검증 (2026-07-26 서울) — 결과와 접근법 재검토](mf_auto_exposure_field_review_20260726_ko.md) |

### 설치·연결·장비·배포

| 날짜 | 보고서 |
|---|---|
| 문서 참조 | [MFNavis m2.6.12 — 푸시 카메라 확대 및 로고 색상 수정](mfnavis_m2.6.12_ko.md) |
| 문서 참조 | [MFNavis m2.6.16 검증 기록](m2.6.16_validation_ko.md) |
| 문서 참조 | [MFNavis m2.6.15 검증 기록](m2.6.15_validation_ko.md) |
| 문서 참조 | [MFNavis m2.6.14 검증 기록](m2.6.14_validation_ko.md) |
| 문서 참조 | [MFNavis m2.6.13 검증 — 2026-09-24](m2.6.13_validation_ko.md) |
| 20260928 | [Trixie INDI 설치 안전성 수정 및 검증](mfnavis_trixie_indi_install_safety_20260928_ko.md) |
| 20260927 | [2026-09-27 실내 GoTo Sync 거절 및 확인 응답 수정](mfnavis_trixie_sync_ack_20260927_ko.md) |
| 20260927 | [Trixie 실내 OnStepX 시리얼 Auto 적용 복구 — 2026-09-27](mfnavis_trixie_serial_auto_20260927_ko.md) |
| 20260927 | [2026-09-27 Trixie → main 병합 점검](mfnavis_trixie_main_merge_20260927_ko.md) |
| 20260926 | [Trixie 구름 많은 하늘·고정 장비 점검 후 수정 — 2026-09-26](mfnavis_trixie_cloudy_fixes_20260926_ko.md) |
| 20260926 | [Trixie 구름 많은 하늘·고정 장비 점검 — 2026-09-26](mfnavis_trixie_cloudy_fixed_20260926_ko.md) |
| 20260926 | [개발용 INDI·캐시 스크립트 추가 점검 (2026-09-26)](mfnavis_extended_script_audit_20260926_ko.md) |
| 20260925 | [MFNavis 설치·운영 스크립트 점검 (2026-09-25)](mfnavis_script_audit_20260925_ko.md) |
| 20260925 | [MFNavis 홈 자료 통합 — 2026-09-25](mfnavis_home_consolidation_20260925_ko.md) |
| 20260923 | [MFNavis 전체 검증 및 기기 적용 — 2026-09-23](mfnavis_validation_20260923_ko.md) |
| 20260923 | [MFNavis 저장소 이전 및 m2.6.10 릴리즈](mfnavis_repository_release_20260923_ko.md) |
| 20260923 | [기기의 PiFinder 잔여 표기 조사 — 2026-09-23](mfnavis_remaining_pifinder_audit_20260923_ko.md) |
| 20260923 | [MFNavis 설치·업데이트 경로 점검](mfnavis_install_update_review_20260923_ko.md) |
| 20260923 | [MFNavis 판매 구성 정리 결과 — 2026-09-23](mfnavis_commercial_20260923_ko.md) |
| 20260923 | [MFNavis 제품명 적용 결과 — 2026-09-23](mfnavis_branding_applied_20260923_ko.md) |
| 20260916 | [MFDS 빌드 산출물 소비 전환](mfds_binary_distribution_20260916_ko.md) |
| 20260909 | [u-blox GPS 간헐적 식별 실패 — 장애 분석 및 자동 복구 개선 보고서](mf_gps_ubx_recovery_20260909_ko.md) |
| 20260909 | [Intermittent u-blox GPS Identification Failure — Incident Analysis and Automatic Recovery Report](mf_gps_ubx_recovery_20260909_en.md) |
| 20260813 | [2026-08-13 NOX 실패 원인 및 복구 리포트](mf_nox_recovery_20260813_ko.md) |
| 20260813 | [INDI USB Serial 포트 목록 중복 제거](mf_indi_serial_port_dedup_20260813_ko.md) |
| 20260813 | [INDI OnStep 시리얼 포트·통신속도 자동찾기 구현 리포트](mf_indi_serial_auto_discovery_20260813_ko.md) |
| 20260812 | [INDI OnStepX USB 분리·재삽입 현장 테스트](mf_indi_usb_reinsert_field_test_20260812_ko.md) |
| 20260812 | [INDI OnStepX 연결 설정 불일치 수정·실장 검증](mf_indi_connection_config_reconcile_20260812_ko.md) |

### 기능 검토·번역·정책

| 날짜 | 보고서 |
|---|---|
| 문서 참조 | [PiFinder 한국어 번역 검토표 (영어 ↔ 한글)](mf_ko_translation_review.md) |
| 20260917 | [SEP를 최종 비상 복구로 제한 — 2026-09-17](mf_sep_emergency_only_20260917_ko.md) |
| 20260916 | [MFDS v0.2.0 / PiFinder m2.6.5 릴리즈](mf_versioned_releases_20260916_ko.md) |
| 20260916 | [MFDS 공개 전환 후 정리 — 2026-09-16](mf_post_publication_cleanup_20260916_ko.md) |
| 20260916 | [MFDS 라이선스 표기 정리 패치 릴리즈](mf_license_identity_release_20260916_ko.md) |
| 20260805 | [기능 체크리스트 테스트 세션 — 자동 검증분 (2026-08-05)](mf_feature_test_session_20260805_ko.md) |
| 20260724 | [2026-07-24 현장 테스트 장애 분석 및 수정 계획](mf_field_test_20260724_analysis_ko.md) |
