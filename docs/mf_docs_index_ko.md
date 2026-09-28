# MF_PiFinder 개발 문서 인덱스

포크(`MF_PiFinder`)가 개발하며 추가한 `mf_*` 문서의 진입점이다. 작업 전
관련 문서를 먼저 읽는다(코드만 보고 의도를 역추론하지 않는다). 상위 구조
레퍼런스(용어집·아키텍처·결정 기록)는 [CONTEXT-MAP.md](../CONTEXT-MAP.md),
`docs/ax/*`, `docs/adr/*`를 참조.

문서 위치(2026-08-04 정리):

| 폴더 | 담는 것 |
|---|---|
| [`docs/mf_dev/`](mf_dev/) | 설계·구현 설명, 계획, 설치·운영 가이드, 프로세스 문서 |
| [`docs/mf_report/`](mf_report/) | 현장 테스트·실측 리포트, 1회성 장애 분석, 검토 결과 |
| `docs/` (여기) | 이 인덱스 ko/en — 두 폴더 공통 진입점이라 루트에 남긴다 |

상태 라벨: **living** = 소스에 맞춰 계속 갱신 / **install** = 설치·운영 가이드 /
**plan** = 구현 전/부분 구현 계획 / **1회성** = 완료된 분석·검증 기록(유지 대상 아님).

최종 갱신: 2026-09-28 (사용자 정렬·영상 추적 연속성 설계).

## INDI 마운트 — 좌표·포인팅 (핵심)

| 문서 | ko/en | 상태 | 요약 |
|---|---|---|---|
| [coordinate_helper_plan](mf_dev/mf_coordinate_helper_plan_ko.md) | 둘 다 | living ★ | `PointingCoordinateService` 권위 스펙 — 좌표 후보(solved/IMU/mount), 선택 우선순위, mount+IMU 델타 융합(속도 게이트·회전 tracker·추적 따라잡기 예산). **좌표 선택/telemetry 게이트 의미의 정규 소유자.** |
| [goto_mount_source_structure](mf_dev/mf_goto_mount_source_structure_ko.md) | 둘 다 | living ★ | SkySafari→마운트 전체 소스맵(프로세스/큐, `pos_server` LX200 처리, push/forwarding/multi-align 라우팅). **SkySafari `:Sr/:Sd/:MS/:CM` + GoTo/Sync forwarding의 정규 소유자.** |
| [mountcontrol_indi_flow](mf_dev/mf_mountcontrol_indi_flow_ko.md) | 둘 다 | living | `mountcontrol_indi.py` 흐름도(메인 루프, 상태 파일 스키마, 연결 순서, 명령 분배). **`mountcontrol_queue` 명령 분배 표의 정규 소유자.** |
| [indi_goto_guide_plan](mf_dev/mf_indi_goto_guide_plan_ko.md) | 둘 다 | living | `indi_goto_guide_service` GoTo/Guide 상태머신, 추적 가이드 외란 복구, 트래킹 주파수 정책. |
| [multipoint_align_flow](mf_dev/mf_multipoint_align_flow_ko.md) | 둘 다 | living | Multi-Point Align 상세 흐름(**정규 소유자**; 타 문서는 요약+참조). |
| [backlash_measurement_flow](mf_dev/mf_backlash_measurement_flow_ko.md) | 둘 다 | living | 자동 백래시 측정 `compass_goto_loop`(**정규 소유자**; 타 문서는 요약+참조). |
| [mount_mode_compatibility](mf_dev/mf_mount_mode_compatibility_ko.md) | 둘 다 | plan(대부분 구현) | Alt/Az vs EQ SkySafari 호환성 감사·체크리스트. |
| [visual_tracking_continuity_design](mf_dev/mf_visual_tracking_continuity_design_ko.md) | ko | **시험 구현 진행** | 사용자 천체 정렬·영상 추적·솔빙 연속성. 기존 행성 계산 재사용, 경위대 우선·EQ 공통 설계. 기본 Off; 운영 제어 통합·실장 검증 대기. |
| [visual_tracking_trial](mf_dev/mf_visual_tracking_trial_ko.md) | ko | **시험 안내** | 환경 확인 파일, 명령 없는 shadow/replay 실행, 구현 범위·제약·검증 상태. |
| [indi_mount_install](mf_dev/mf_indi_mount_install_ko.md) | 둘 다 | install | INDI 마운트 설치·사용 가이드. |
| [indi_serial_reconnect_design](mf_dev/mf_indi_serial_reconnect_design_ko.md) | ko | **설정 조정·USB 재삽입 구현**(2026-08-12) | INDI/PiFinder 설정 조정과 stable by-id 기반 1회 재접속 구현. 지속 통신 감시는 후속 설계. |
| [indi_serial_auto_discovery_design](mf_dev/mf_indi_serial_auto_discovery_design_ko.md) | ko | **구현·실장 검증 완료**(2026-08-13) | Web Serial Port의 Auto 선택 시 현재 장치를 지원 baud별로 `:GVP#`/`:GVN#` 검사해 OnStep stable port와 속도를 함께 찾는 설계·구현 기준. |

## 솔빙 (핵심)

| 문서 | ko/en | 상태 | 요약 |
|---|---|---|---|
| [cedar_sep_hybrid_design](mf_dev/mf_cedar_sep_hybrid_design_ko.md) | 둘 다 | living ★ | cedar+SEP 하이브리드 솔빙 **설계 정본** — 프레임 공간/좌표 정합, 검출 게이트 6종, 웜픽셀 맵, 폴백·백오프 정책, 하이브리드 정렬, AE 연동, 방어선. 결정 근거는 ADR m0023, 실측 이력은 sep_fullframe_impl. |
| [cedar_fullframe_primary_plan](mf_dev/mf_cedar_fullframe_primary_plan_ko.md) | ko | **구현·기본 활성화 완료**(2026-08-12) | cedar 풀프레임 1차 경로 전환 계획과 결정 기록 — `solver_cedar_fullframe`/게이트/중앙 우선 캐스케이드. 2026-08-12 풀프레임 4단 기본화. |
| [optical_train_fov_integration](mf_dev/mf_optical_train_fov_integration_ko.md) | ko | **기반·렌즈 선언 UI 구현됨 · 야간 검증 대기**(2026-08-19) | 센서×렌즈 optical train의 FOV 계산 기반과 Lens 선언 UI, 현행 solver/SQM 보존 경계, tetra3·cedar/SEP·SQM 단계별 병합 및 야간 검증 절차. |
| [wide_angle_solver_design](mf_dev/mf_wide_angle_solver_design_ko.md) | ko | **plan ★** | 4/6/8/10 mm 렌즈, 실측 왜곡 보정, 16 mm 등가 원본 크롭 타일, 중앙 포화 시 다중 타일 합의, LiveCam 기구 간섭 마스크의 상세 설계 정본. |
| [wide_angle_solver_implementation_plan](mf_dev/mf_wide_angle_solver_implementation_plan_ko.md) | ko | **plan** | 광각 솔빙의 P0–P7 구현/커밋 경계, 자동·야간 검증, 배포·롤백 절차와 사용자 결정 항목. |

## 카탈로그 · 웹 UI

| 문서 | ko/en | 상태 | 요약 |
|---|---|---|---|
| [web_catalogs_dev](mf_dev/mf_web_catalogs_dev_ko.md) | ko | living | 기기 웹 카탈로그 페이지(라우트·필터·push·통합검색 지정번호 정렬). |
| [large_catalog_lazy_load](mf_dev/mf_large_catalog_lazy_load_ko.md) | ko | living | 대형 카탈로그(WDS) lazy load. |
| [location_catalog](mf_dev/mf_location_catalog_ko.md) | 둘 다 | living | GeoNames 기반 오프라인 위치 카탈로그. |
| [raw_live_stack_plan](mf_dev/mf_raw_live_stack_plan_ko.md) | 둘 다 | living | LiveCam RAW 프리뷰/롤링 라이브 스택, Web 카메라 노출/게인 컨트롤(`/api/camera/controls`). |

## 설치 · 플랫폼 · 시스템

| 문서 | ko/en | 상태 | 요약 |
|---|---|---|---|
| [trixie_install](mf_dev/mf_trixie_install_ko.md) | 둘 다 | install | Trixie 64-bit / Python 3.13 설치·경로 안내. |
| [pifinder_new_device_tasks](mf_dev/mf_pifinder_new_device_tasks_ko.md) | 둘 다 | install | 신규 기기 셋업 작업 목록. |
| [pifinder_rpi4_pi5_compatibility](mf_dev/mf_pifinder_rpi4_pi5_compatibility_ko.md) | 둘 다 | living | Pi4/5/CM5 보드·GPS/UART 호환성. |
| [wifi_apsta](mf_dev/mf_wifi_apsta_ko.md) | 둘 다 | living | AP+STA 동시 Wi-Fi 모드. |
| [time_sync](mf_dev/mf_time_sync_ko.md) | 둘 다 | living | GPS/NTP/RTC/PPS 통합 시간 동기화(시스템 클럭). |
| [gps_ubx_recovery_20260909](mf_report/mf_gps_ubx_recovery_20260909_ko.md) | 둘 다 | **장애·변경 검증 보고서** | u-blox가 NMEA0183로 남는 간헐 장애의 실측, MON-VER 제한 재시도, 회귀·TCP·실장 검증. |
| [i2c_clock_stretching_fix](mf_dev/mf_i2c_clock_stretching_fix_ko.md) | 둘 다 | living | I2C 클럭 스트레칭 수정. |

## 입력 · UI · 센서

| 문서 | ko/en | 상태 | 요약 |
|---|---|---|---|
| [input_controls](mf_dev/mf_input_controls_ko.md) | 둘 다 | living | 입력 컨트롤 전반. |
| [input_keymap](mf_dev/mf_input_keymap_ko.md) | 둘 다 | living | 키맵. |
| [keyboard_mapping](mf_dev/mf_keyboard_mapping_ko.md) | 둘 다 | living | BT/USB HID 키보드 매핑. |
| [imu_current_behavior_analysis](mf_dev/mf_imu_current_behavior_analysis_ko.md) | ko | **living ★** | IMU 전체 기준선과 P0 안전 개선 — BNO055 read/filter/recovery, health·freshness 계약, camera/solver anchor, integrator, sleep/UI/API, SkySafari·mount 융합, 임계값·상태 전이·후속 우선순위. |
| [imu_compass_calibration](mf_dev/mf_imu_compass_calibration_ko.md) | 둘 다 | living | 선택형 BNO055 NDOF 지자계 보정. |

## 분석 · 검토 · 계획 (비-living, 이력/백로그)

| 문서 | ko/en | 상태 | 요약 |
|---|---|---|---|
| [field_test_20260724_analysis](mf_report/mf_field_test_20260724_analysis_ko.md) | ko | **분석+수정 진행 중**(2026-07-25) | 현장 테스트 장애 분석(무시간원 시계 오차; IMU 폴백 자동 정렬은 의도된 설계로 확정)과 수정 체크리스트. |
| [goto_tracking_recovery_analysis](mf_report/mf_goto_tracking_recovery_analysis_ko.md) | ko | **1회성**(2026-07-18) | OnStepX GoTo 무동작(wedge) 장애 분석·복구 검증. |
| [indi_onstep_driver_test_checklist](mf_report/mf_indi_onstep_driver_test_checklist_ko.md) | ko | **1회성**(2026-07-01) | INDI 드라이버 vs 직접 LX200 사전 검증 기록. |
| [solve_motion_gate_review](mf_dev/mf_solve_motion_gate_review_ko.md) | 둘 다 | **plan(미구현)** | 노출 중 이동 프레임 솔브 게이트 미배선 검토(협의 대기). |
| [auto_exposure_methods](mf_dev/mf_auto_exposure_methods_ko.md) | 둘 다 | **조사(완료)** | 자동 노출·게인 제어 방법 조사 — 현행 매치 수 기반의 문제(P1~P7)와 대안(검출 별 수 서보 등) 비교, 권고 초안. |
| [auto_exposure_plan](mf_dev/mf_auto_exposure_plan_ko.md) | ko | **구현 완료(접근법 재검토 중)** | 검출 별 수 컨트롤러 설계+구현 — 기존 기능 유지, Camera Exp 메뉴 "Star"(`camera_exp=auto_star`)로 선택. ADR m0020/m0022. |
| [auto_star_framewise_exposure_gain_research](mf_dev/mf_auto_star_framewise_exposure_gain_research_ko.md) | ko | **무중단 캡처 기반 구현·제어기 구현 전** | Triple-buffer/latest-wins 캡처와 frame pairing 구현 완료. Auto(Star) 2중 루프는 좌표/추적 우선, 주변 catalog-match 별 SNR, 중앙 달 배제, 오검출 증거 기반 gain 하향으로 설계. |
| [auto_exposure_field_review_20260726](mf_report/mf_auto_exposure_field_review_20260726_ko.md) | ko | **방향 확정(최종 방안 코퍼스 대기)** | 서울 광해 현장 검증 — 병목은 검출 감도. B+C(비크롭 12-bit+SEP) 채택, 야간 검증 요약(§7). |
| [sep_fullframe_impl](mf_dev/mf_sep_fullframe_impl_ko.md) | ko | **구현 기록(이력)** | 광해 솔빙 보강의 구현·튜닝·야간 실측 원자료(자동 노출+SEP). 설계 정본은 [cedar_sep_hybrid_design](mf_dev/mf_cedar_sep_hybrid_design_ko.md)으로 이관(2026-08-02). |
| [cedar_sep_hybrid_solve_20260728](mf_report/mf_cedar_sep_hybrid_solve_20260728_ko.md) | 둘 다 | **공지** | 커뮤니티 공유용 — cedar+SEP 하이브리드 솔빙 구조 설명과 광해 하늘 실증 요약 ([영문판](mf_report/mf_cedar_sep_hybrid_solve_20260728_en.md) 포함). |
| [solver_3path_bench_20260801](mf_report/mf_solver_3path_bench_20260801_ko.md) | 둘 다 | **1회성 실측**(2026-08-01) | 밝은 하늘(배경 87%) 동일 프레임 3경로 벤치 — cedar 크롭 0% / cedar 풀프레임 σ8 18% / 하이브리드 88%(라이브 89.5%), 정확도 1σ ~1′ (ADR m0023 재확인). |
| [solver_fullframe_field_test_20260803](mf_report/mf_solver_fullframe_field_test_20260803_ko.md) | ko | **1회성 실측**(2026-08-03) | cedar 풀프레임 1차 경로 야간 실측(섀도 CSV ~2,200시도) — LP 곡선/타임아웃 A/B. 계획은 [cedar_fullframe_primary_plan](mf_dev/mf_cedar_fullframe_primary_plan_ko.md). |
| [fullframe_solving_report_20260804](mf_report/mf_fullframe_solving_report_20260804_ko.md) | 둘 다 | **리포트**(2026-08-04) | 풀프레임 솔빙 파이프라인 실측 리포트 — 처리 구조(검출 2종 병렬 + 좌표 4단 캐스케이드)와 실측 결과 정리. |
| [solver_diagnostics_20260812](mf_report/mf_solver_diagnostics_20260812_ko.md) | ko | **1회성 실측**(2026-08-12) | 풀프레임 4단 기본 활성화 및 단계별 Cedar/SEP 검출 진단 추가 검증 — Cedar 114→90→64, `cedar_ff_center`/`cedar_ff` 실기 성공. |
| [solver_cascade_order_20260812](mf_report/mf_solver_cascade_order_20260812_ko.md) | ko | **변경 검증**(2026-08-12) | 캐스케이드를 전역 중앙 우선으로 변경하고 순서 테스트·실기 조기 종료를 검증. 경로명도 `cedar_center`/`sep_center`/`cedar_full`/`sep_full`로 명확화. |
| [indi_connection_config_reconcile_20260812](mf_report/mf_indi_connection_config_reconcile_20260812_ko.md) | ko | **변경·실장 검증**(2026-08-12) | INDI live/XML 우선 설정 조정, atomic PiFinder mirror 저장, 실장 USB/by-id/115200 migration 및 연결 상태 검증. |
| [indi_usb_reinsert_field_test_20260812](mf_report/mf_indi_usb_reinsert_field_test_20260812_ko.md) | ko | **구현·실장 검증**(2026-08-12) | OnStepX USB 실제 분리·재삽입 감지, device session 1회 복구, fresh telemetry와 상태 보존 검증. |
| [indi_serial_port_dedup_20260813](mf_report/mf_indi_serial_port_dedup_20260813_ko.md) | ko | **구현·실장 검증**(2026-08-13) | 같은 실제 tty를 가리키는 by-id와 ttyUSB 중복을 realpath로 합치고 stable by-id 하나만 표시하도록 검증. |
| [indi_serial_auto_discovery_20260813](mf_report/mf_indi_serial_auto_discovery_20260813_ko.md) | ko | **구현·자동·실장 검증**(2026-08-13) | 사용자 Auto+Apply 때만 OnStep port/baud를 읽기 전용 probe하고 유일 후보를 fresh telemetry 뒤 저장하며 실패 시 원복하는 구현. |
| [feature_test_session_20260805](mf_report/mf_feature_test_session_20260805_ko.md) | ko | **1회성**(2026-08-05) | 기능 체크리스트 자동 검증분 실행 기록 — 정적/스위트/API/헤드리스 UI 통과, 결함 3건 발견·수정(Software RIGHT 미가드, 업데이트 예외 관통, imu_fake 시그니처), 남은 수동 항목 목록. |
| [mono_sqm_colour_guard_20260805](mf_report/mf_mono_sqm_colour_guard_20260805_ko.md) | 둘 다 | **공지**(2026-08-05) | 커뮤니티 공유용 — SRGGB 라벨의 실측 모노 imx462에서 upstream #560 색보정이 SQM을 +0.74 mag 왜곡하는 함정과 `profile.mono` 가드, 모듈 자가진단법 ([영문판](mf_report/mf_mono_sqm_colour_guard_20260805_en.md)). |
| [sqm_stack_port_plan](mf_dev/mf_sqm_stack_port_plan_ko.md) | ko | **이식 완료**(2026-07-30) | upstream SQM 스택(#532/#542/#543/#544) 이식 분석·계획과 Phase별 실적. |
| [gps_aiding_plan](mf_dev/mf_gps_aiding_plan_ko.md) | 둘 다 | **plan(구현 전)** | u-blox GPS aiding(MGA-INI/DBD) 설계 초안. |
| [camera_mono_color_plan](mf_dev/mf_camera_mono_color_plan_ko.md) | ko | **구현됨**(2026-08-08) | IMX296/IMX462 mono·color 변형을 설정(Camera Type 5항목 + `camera_variant`)으로 선택 — 파생 프로파일 이름으로 전 프로세스 전파, dtoverlay 불변. 컬러 imx462 실기 전파 검증, SQM 상수는 mono 승계 미검증(§8). |

## 메타 · 이력 · 프로세스

| 문서 | ko/en | 상태 | 요약 |
|---|---|---|---|
| [change_history](mf_dev/mf_change_history_ko.md) | 둘 다 | living | 전체 소스 수정 이력(기능·파일별). PR 상태 표는 2026-06-27 스냅숏(현재 직접 main 푸시). |
| [upstream_patch_reference](mf_dev/mf_upstream_patch_reference_ko.md) | 둘 다 | living | `brickbots/PiFinder` 리베이스/머지 레퍼런스. |
| [feature_review_checklist](mf_dev/mf_feature_review_checklist_ko.md) | 둘 다 | living | 기능 리뷰 체크리스트. |
| [ko_translation_review](mf_report/mf_ko_translation_review.md) | 단일 | living | 한국어 UI 번역 리뷰. |

## 중복 주제의 정규 소유자

여러 문서가 같은 메커니즘을 다룰 때, 권위 있는 서술은 아래 한 곳에 두고 나머지는
요약+상호참조만 유지한다(수정 시 소유자를 먼저 갱신).

| 주제 | 정규 소유자 | 요약만 두는 문서 |
|---|---|---|
| SkySafari `:Sr/:Sd/:MS/:CM` + GoTo/Sync forwarding | goto_mount_source_structure | indi_goto_guide_plan, mount_mode_compatibility, coordinate_helper_plan, upstream_patch_reference |
| 좌표 선택 우선순위 · mount telemetry 게이트 의미 | coordinate_helper_plan | mountcontrol_indi_flow, goto_mount_source_structure |
| `mountcontrol_queue` 명령 분배 표 | mountcontrol_indi_flow | goto_mount_source_structure |
| Multi-Point Align 상세 | multipoint_align_flow | mountcontrol_indi_flow, indi_mount_install |
| Backlash 측정 상세 | backlash_measurement_flow | mountcontrol_indi_flow, indi_mount_install |
| Location/Time sync 규약(`:SG` 부호, PyIndi full-vector) | goto_mount_source_structure | indi_mount_install, mountcontrol_indi_flow, coordinate_helper_plan(자동 재sync만 고유) |
| cedar+SEP 하이브리드 솔빙 설계 | cedar_sep_hybrid_design | sep_fullframe_impl(이력·실측), cedar_sep_hybrid_solve_20260728(공지), solver_3path_bench_20260801(1회성 실측) |
