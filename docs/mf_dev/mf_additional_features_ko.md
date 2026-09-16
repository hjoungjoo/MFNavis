# MF PiFinder 추가 기능 안내

[English](mf_additional_features_en.md) | [한국어](mf_additional_features_ko.md)

이 문서는 원본 PiFinder에 없거나 MF PiFinder에서 크게 확장한 기능을 사용자
관점에서 요약하고, 상세 문서의 시작점 역할을 한다. 기능의 설계·제한·검증 상태는
각 링크한 문서를 기준으로 한다.

## 사용 전 확인

- 장비 제어, 정렬, 카메라 보정 기능은 실제 망원경과 연결되므로 실내에서 먼저
  검증한다.
- INDI 마운트 제어는 선택 기능이며 기본값으로 꺼져 있다.
- 개발·실험 상태 기능은 안정 기능과 구분되어 있다. 실제 관측 전에는 해당 상세
  문서의 제한 사항을 확인한다.

## 설치와 플랫폼

| 기능 | 설명 | 문서 |
| --- | --- | --- |
| Bookworm 64-bit 설치 | Pi 4, Pi 5, CM5 환경의 설치·서비스·부트 설정 | [릴리즈/main 설치](../../README_ko.md#2-mf-pifinder-설치-릴리즈-또는-main) |
| 보드 호환성 | Pi 4/Pi 5/CM5별 SPI, UART, 카메라 차이 | [플랫폼 호환성](mf_pifinder_rpi4_pi5_compatibility_ko.md) |
| AP+STA 네트워크 | 액세스 포인트와 기존 Wi-Fi 연결을 함께 다루는 네트워크 구성 | [AP+STA Wi-Fi](mf_wifi_apsta_ko.md) |
| 시간 동기화 | chronyd와 GPS 기반 시간 관리 | [시간 동기화](mf_time_sync_ko.md) |

## 웹과 카탈로그

![MF PiFinder 웹 UI와 LCD 화면](../source/images/mf/web_ui_home_lcd.png)

| 기능 | 설명 | 문서 |
| --- | --- | --- |
| Red Night/PWA 웹 UI | 휴대기기에서 상태·원격 조작·도구를 사용하는 웹 인터페이스 | [웹 카탈로그 및 UI](mf_web_catalogs_dev_ko.md) |
| 웹 카탈로그 | 카탈로그 탐색, 이름 검색, 상세 정보, PiFinder로 대상 전송 | [웹 카탈로그 및 UI](mf_web_catalogs_dev_ko.md) |
| 위치 카탈로그 | 국가·지역·도시를 이용한 관측 위치 선택 | [위치 카탈로그](mf_location_catalog_ko.md) |
| 오프라인 캐시 | 별·카탈로그 런타임 캐시와 POSS/SDSS 이미지 사전 다운로드 | [캐시 다운로드](mf_cache_download_ko.md) |
| 대형 카탈로그 로딩 | WDS 등 대형 카탈로그의 초기화·검색 성능 개선 | [대형 카탈로그 로딩](mf_large_catalog_lazy_load_ko.md) |

## 마운트와 입력

| 기능 | 설명 | 문서 |
| --- | --- | --- |
| INDI/OnStepX | INDI 서버 연결, Sync, GoTo, 수동 이동, 백래시 보정 | [INDI 마운트 설정](mf_indi_mount_install_ko.md) |
| 마운트 동작 모드 | PiFinder·INDI·SkySafari 연동 시 모드와 제약 | [마운트 모드 호환성](mf_mount_mode_compatibility_ko.md) |
| 다점 정렬 | 여러 점을 사용한 정렬 절차 | [다점 정렬 흐름](mf_multipoint_align_flow_ko.md) |
| 키패드·키보드 | LCD의 전역/화면별 키 조작과 USB·Bluetooth HID 입력 | [입력 조작](mf_input_controls_ko.md), [키보드 매핑](mf_keyboard_mapping_ko.md) |

## 촬영·솔빙·관측 보조

| 기능 | 설명 | 문서 |
| --- | --- | --- |
| MFDS 별 검출 | 설치 스크립트로 자동 설치하며 버전별 설치 방식은 해당 릴리즈 노트 참고 | [MFDS 설치](../MFDS_BINARY_DISTRIBUTION_ko.md) |
| 자동 노출 | 별 수를 기준으로 한 자동 노출 제어 | [자동 노출](mf_auto_exposure_methods_ko.md) |
| SQM·색 보정 | 하늘 밝기 측정 및 센서 색 보정 | [SQM 스택](mf_sqm_stack_port_plan_ko.md) |
| LiveCam/라이브 스택 | 웹 RAW 프리뷰와 라이브 스택 기능 | [Live Stack 연구](mf_live_stack_stabilization_research_ko.md), [RAW Live Stack](mf_raw_live_stack_plan_ko.md) |
| IMU 나침반 보정 | IMU 방향·나침반 보정 절차 | [IMU 보정](mf_imu_compass_calibration_ko.md) |

## 변경 이력과 개발 참고

- 전체 기능 검토와 현재 검증 우선순위: [기능 검토 체크리스트](mf_feature_review_checklist_ko.md)
- 변경 이력: [MF 변경 이력](mf_change_history_ko.md)
- 원본과의 동기화·패치 참고: [upstream 패치 참고](mf_upstream_patch_reference_ko.md)

새 기능을 사용하거나 문제를 보고할 때에는 이 문서에서 해당 상세 문서로 이동한 뒤,
사용 중인 보드, PiFinder 버전, 마운트/카메라 종류와 재현 절차를 함께 기록한다.
