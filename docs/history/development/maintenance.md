# 변경·업스트림 통합 — 이전 설계와 조사 기록

> 2026-10-10 통합 보관. 아래 본문의 “현재/현행”, 기본값, 완료 상태와 명령은 원문 작성 당시 기준이다.
> 오늘의 동작은 [개발 기준 문서](../../mf_dev/README.md)를 따른다. 이력에 적힌 절차를 현재 설치 절차로 사용하지 않는다.

- [mf_additional_features_ko.md](#mf_additional_features_ko)
- [mf_change_history_ko.md](#mf_change_history_ko)
- [mf_upstream_patch_reference_ko.md](#mf_upstream_patch_reference_ko)


---

<a id="mf_additional_features_ko"></a>

## mf_additional_features_ko.md

<a id="mf_additional_features_ko--mf-pifinder-추가-기능-안내"></a>
## MF PiFinder 추가 기능 안내

[English](maintenance.md#mf_additional_features_ko) | [한국어](maintenance.md#mf_additional_features_ko)

이 문서는 원본 PiFinder에 없거나 MF PiFinder에서 크게 확장한 기능을 사용자
관점에서 요약하고, 상세 문서의 시작점 역할을 한다. 기능의 설계·제한·검증 상태는
각 링크한 문서를 기준으로 한다.

<a id="mf_additional_features_ko--사용-전-확인"></a>
### 사용 전 확인

- 장비 제어, 정렬, 카메라 보정 기능은 실제 망원경과 연결되므로 실내에서 먼저
  검증한다.
- INDI 마운트 제어는 선택 기능이며 기본값으로 꺼져 있다.
- 개발·실험 상태 기능은 안정 기능과 구분되어 있다. 실제 관측 전에는 해당 상세
  문서의 제한 사항을 확인한다.

<a id="mf_additional_features_ko--설치와-플랫폼"></a>
### 설치와 플랫폼

| 기능 | 설명 | 문서 |
| --- | --- | --- |
| Trixie 64-bit 설치 | Pi 4, Pi 5, CM5 환경의 설치·서비스·부트 설정 | [릴리즈/main 설치](../../../README_ko.md#2-mfnavis-설치-릴리즈-또는-main) |
| 보드 호환성 | Pi 4/Pi 5/CM5별 SPI, UART, 카메라 차이 | [플랫폼 호환성](setup.md#mf_pifinder_rpi4_pi5_compatibility_ko) |
| AP+STA 네트워크 | 액세스 포인트와 기존 Wi-Fi 연결을 함께 다루는 네트워크 구성 | [AP+STA Wi-Fi](connectivity.md#mf_wifi_apsta_ko) |
| 시간 동기화 | chronyd와 GPS 기반 시간 관리 | [시간 동기화](connectivity.md#mf_time_sync_ko) |

<a id="mf_additional_features_ko--웹과-카탈로그"></a>
### 웹과 카탈로그

![MF PiFinder 웹 UI와 LCD 화면](../../source/images/mf/web_ui_home_lcd.png)

| 기능 | 설명 | 문서 |
| --- | --- | --- |
| Red Night/PWA 웹 UI | 휴대기기에서 상태·원격 조작·도구를 사용하는 웹 인터페이스 | [웹 카탈로그 및 UI](interfaces.md#mf_web_catalogs_dev_ko) |
| 웹 카탈로그 | 카탈로그 탐색, 이름 검색, 상세 정보, PiFinder로 대상 전송 | [웹 카탈로그 및 UI](interfaces.md#mf_web_catalogs_dev_ko) |
| 위치 카탈로그 | 국가·지역·도시를 이용한 관측 위치 선택 | [위치 카탈로그](interfaces.md#mf_location_catalog_ko) |
| 오프라인 캐시 | 별·카탈로그 런타임 캐시와 POSS/SDSS 이미지 사전 다운로드 | [캐시 다운로드](interfaces.md#mf_cache_download_ko) |
| 대형 카탈로그 로딩 | WDS 등 대형 카탈로그의 초기화·검색 성능 개선 | [대형 카탈로그 로딩](interfaces.md#mf_large_catalog_lazy_load_ko) |

<a id="mf_additional_features_ko--마운트와-입력"></a>
### 마운트와 입력

| 기능 | 설명 | 문서 |
| --- | --- | --- |
| INDI/OnStepX | INDI 서버 연결, Sync, GoTo, 수동 이동, 백래시 보정 | [INDI 마운트 설정](mount.md#mf_indi_mount_install_ko) |
| 마운트 동작 모드 | PiFinder·INDI·SkySafari 연동 시 모드와 제약 | [마운트 모드 호환성](mount.md#mf_mount_mode_compatibility_ko) |
| 다점 정렬 | 여러 점을 사용한 정렬 절차 | [다점 정렬 흐름](mount.md#mf_multipoint_align_flow_ko) |
| 키패드·키보드 | LCD의 전역/화면별 키 조작과 USB·Bluetooth HID 입력 | [입력 조작](interfaces.md#mf_input_controls_ko), [키보드 매핑](interfaces.md#mf_keyboard_mapping_ko) |

<a id="mf_additional_features_ko--촬영솔빙관측-보조"></a>
### 촬영·솔빙·관측 보조

| 기능 | 설명 | 문서 |
| --- | --- | --- |
| MFDS 별 검출 | 설치 스크립트로 자동 설치하며 버전별 설치 방식은 해당 릴리즈 노트 참고 | [MFDS 설치](../../MFDS_BINARY_DISTRIBUTION_ko.md) |
| 자동 노출 | 별 수를 기준으로 한 자동 노출 제어 | [자동 노출](camera.md#mf_auto_exposure_methods_ko) |
| SQM·색 보정 | 하늘 밝기 측정 및 센서 색 보정 | [SQM 스택](camera.md#mf_sqm_stack_port_plan_ko) |
| LiveCam/라이브 스택 | 웹 RAW 프리뷰와 라이브 스택 기능 | [Live Stack 연구](camera.md#mf_live_stack_stabilization_research_ko), [RAW Live Stack](camera.md#mf_raw_live_stack_plan_ko) |
| IMU 나침반 보정 | IMU 방향·나침반 보정 절차 | [IMU 보정](positioning.md#mf_imu_compass_calibration_ko) |

<a id="mf_additional_features_ko--변경-이력과-개발-참고"></a>
### 변경 이력과 개발 참고

- 전체 기능 검토와 현재 검증 우선순위: [기능 검토 체크리스트](validation.md#mf_feature_review_checklist_ko)
- 변경 이력: [MF 변경 이력](maintenance.md#mf_change_history_ko)
- 원본과의 동기화·패치 참고: [upstream 패치 참고](maintenance.md#mf_upstream_patch_reference_ko)

새 기능을 사용하거나 문제를 보고할 때에는 이 문서에서 해당 상세 문서로 이동한 뒤,
사용 중인 보드, PiFinder 버전, 마운트/카메라 종류와 재현 절차를 함께 기록한다.


---

<a id="mf_change_history_ko"></a>

## mf_change_history_ko.md

<a id="mf_change_history_ko--mf_pifinder-소스-수정-히스토리"></a>
## MF_PiFinder 소스 수정 히스토리

작성일: 2026-06-25
최종 업데이트: 2026-08-10

이 문서는 Raspberry Pi CM5, Raspberry Pi 4, Raspberry Pi 5 계열의 Bookworm
64-bit 환경에서 `mf_pifinder` 브랜치를 동작시키기 위해 PiFinder 저장소 안에 적용한
소스 수정 사항을 파일별로 기록한다.

upstream 원본 소스가 변경되었을 때 재동기화와 패치 재적용 기준으로 사용할 요약은
`docs/mf_dev/mf_upstream_patch_reference_ko.md`를 참고한다.

범위:

- PiFinder 저장소 내부 코드와 문서
- CM5/Pi4/Pi5, Bookworm, IMX462, SSD1351 OLED 대응을 위해 바꾼 PiFinder 코드
- 나중에 같은 변경을 검토하거나 upstream 반영 여부를 판단할 때 필요한 수준의 상세 기록

제외:

- Debian 패키지 설치 과정
- OS 네트워크 설정
- 실제 배선 변경 과정
- 재부팅, 서비스 시작/중지 같은 운영 절차
- 중간 테스트값과 폐기한 설정

<a id="mf_change_history_ko--작업-단위-목차-및-pr-상태"></a>
### 작업 단위 목차 및 PR 상태

> **참고 (2026-07-23):** 아래 PR 상태와 "PR 재편성 제안"은 2026-06-27 스냅숏이며
> 더 이상 현행이 아니다. 현재는 릴리즈 전이라 `main`에 직접 커밋/푸시한다
> (CLAUDE.md의 pre-release 예외, 2026-07-21). 릴리즈 후 첫 수정부터 브랜치/PR
> 흐름으로 복귀한다. 아래 표는 기능별 범위 파악용 이력으로만 참고할 것.

상태 기준: 2026-06-27 현재 `brickbots/PiFinder`에 열린 `hjoungjoo` Draft PR과
로컬 `mf_pifinder` 통합 브랜치 기준이다.

| 작업 단위 | 현재 상태 | PR/브랜치 | 주요 범위 |
| --- | --- | --- | --- |
| Bookworm 설치/경로 기반 | Draft PR 있음 | [#499](https://github.com/brickbots/PiFinder/pull/499), `pr/bookworm-install-foundation` | `pifinder_paths.sh`, 설치/업데이트/마이그레이션 스크립트, systemd 서비스, Bookworm 경로 문서 |
| Raspberry Pi 4/5/CM5 보드 및 GPS/UART 프로파일 | Draft PR 있음 | [#505](https://github.com/brickbots/PiFinder/pull/505), `pr/board-gps-uart-profile` | `board_config.py`, `gps_port=auto`, GPSD 장치/baud 동기화, GPS Port 메뉴 |
| 카메라 preview/focus/gain 제어 | Draft PR 있음 | [#501](https://github.com/brickbots/PiFinder/pull/501), `pr/focus-gain-preview` | focus preview, 밝은 배경 threshold, camera gain profile/runtime 제어, LCD preview script |
| 한국어 UI localization | Draft PR 있음 | [#500](https://github.com/brickbots/PiFinder/pull/500), `pr/korean-localization` | `python/locale/ko`, 언어 메뉴의 `ko`, CJK font/restart 처리 |
| Bluetooth/USB HID 키보드 지원 | Draft PR 있음 | [#506](https://github.com/brickbots/PiFinder/pull/506), `pr/bluetooth-keyboard-support` | libinput 키 매핑, 텍스트 입력 키코드, Bluetooth keyboard scan/pair/connect UI, 재연결 |
| INDI 마운트 제어 | Draft PR 있음 | [#503](https://github.com/brickbots/PiFinder/pull/503), `pr/indi-mount-control` | optional INDI mount process, object details sync, LX200 OnStepX 커스텀 드라이버 패치, 설치 스크립트, INDI 문서 |
| INDI Multi Align 공통 흐름 | Draft PR 없음 | 로컬 `mf_pifinder` 작업트리 | 공통 `MultiPointAlignController`, Web/LCD/SkySafari session 통합, OnStepX native align 시작 지연, stale native align `:SX09,0#` reset, PiFinder 좌표 sync 검증, GoTo 실패 시 session 유지/target clear, 실제 OnStepX 장비 테스트 |
| GPS/NTP/RTC/Software PPS 통합 시간 동기화 | Draft PR 있음 | [#504](https://github.com/brickbots/PiFinder/pull/504), `pr/time-sync-sources` | GPS/NTP best-source 선택, helper service, dry-run/real clock sync, status UI, time sync 문서 |
| Wi-Fi AP+STA 동시 모드 및 AP 설정 | Draft PR 없음 | 로컬 `mf_pifinder` 작업트리 | `wlan0` STA + `uap0` AP, STA 채널 추적, STA 밴드 선호, AP IP 설정, AP WPA2 암호 설정, AP+STA 인터넷 공유 옵션, OS Wi-Fi 프로파일 가져오기, 스캔된 SSID 선택, Pi 4/5 공통 Wi-Fi 모드 |
| Locations 위치 카탈로그 | Draft PR 없음 | 로컬 `mf_pifinder` 작업트리 | GeoNames 기반 오프라인 위치 카탈로그, 국가/지역/군구/도시 선택, 좌표/고도/source 자동 입력, 북한 제외 |
| Web UI 적색 야간 테마 및 PWA 전체화면 앱 모드 | Draft PR 없음 | 로컬 `mf_pifinder` 작업트리 | red night theme, 브라우저별 theme 저장, PWA manifest, service worker, PWA icon |
| 선택형 IMU compass 방위 개선 | Draft PR 없음 | 로컬 `mf_pifinder` 작업트리 | 선택형 BNO055 NDOF 지자계 fusion mode, IMU calibration 상태 표시, 자동 calibration 저장/로드, 수동 calibration 메뉴 |
| SkySafari/INDI 마운트 모드 호환성 | Draft PR 없음 | 로컬 `mf_pifinder` 작업트리 | Alt/Az/EQ SkySafari LX200 status, optional GoTo/Sync forwarding, SkySafari guide keepalive bridge, no-solve IMU alignment correction, mount-mode compatibility checklist |
| Pointing Coordinate Service | Draft PR 없음 | 로컬 `mf_pifinder` 작업트리 | SkySafari/Web/LCD/INDI Multi Align 공통 좌표 서비스, 요청 좌표 그대로 사용, IMU smoothing, GoTo/수동 이동 중 mount readback 우선, Reset Pointing 시 SkySafari IMU alignment 보정 해제 후 raw IMU 좌표로 mount re-sync, 마운트 슬루 격리 보강(INDI 2.x updateProperty 1Hz readback, 누출 롤백, raw-IMU 델타 추적, post-motion settle 게이트; 2026-07-17, `mf_coordinate_helper_plan` 참고) |
| INDI GoTo/Guide 서비스 | Draft PR 없음 | 로컬 `mf_pifinder` 작업트리 | `mountcontrol_indi` executor 위에 얹는 별도 `indi_goto_guide_service` 프로세스(GoTo/Guide 정책 상태머신), SkySafari GoTo를 서비스로 라우팅, PiFinder 수동 접근 loop + correction pass 후 최종 INDI GoTo, tracking guide target을 서비스가 관리, 트래킹 가이드 외란 복구(정착 감지 후 3° 경계로 pulse-guide vs sync+GoTo 재획득, GoTo 복구 별도 On/Off), 웹 GoTo/Guide 상태 패널 + LCD GoTo Recovery 토글, 10° 복구 오차 상한 제거·GoTo Type 라벨 통일(2026-07-17), SkySafari/GoTo 설정 개편(2026-07-19: GoTo Type에 `off` 추가로 GoTo 전달 일원화, `skysafari_indi_goto`·`indi_goto_refine_once` 옵션과 LCD 가이드 화면 5번 Refine 토글 제거, `skysafari_indi_sync` 기본 켜짐, solve 전 SkySafari Align IMU 정렬 상시 켜짐, Refine Accuracy 입력을 GoTo/Guide 설정으로 이동, SkySafari Mount Mode 카드를 GoTo/Guide 설정 위로 이동, Object Details 5번 GoTo를 GoTo/Guide 서비스 경유로 변경), 트래킹 주파수 정책 통합(2026-07-20: 웹 카탈로그 push·LCD 키패드 5·SkySafari `:MS#` 세 진입점이 `track_freq_policy` 공유, SkySafari는 천체 종류가 없어 좌표를 에페메리스와 대조해 판별[허용오차 6′, `skysafari_planet_track_freq` 기본 켜짐], 웹/LCD는 `obj_type` 유지, 경로별 큐 검사 분리로 GoTo/Guide 큐 부재 시 multi-point align GoTo가 사라지던 결함 수정, `test_pos_server.py` 전체에 `unit` 마커 부여, 매칭 전용 `planet_positions_of_date()`로 equinox-of-date 위치를 계산해 SkySafari(JNow)와 `calc_planets()`(J2000)의 세차 22′ 불일치 수정[요청 좌표는 변환하지 않고 에페메리스만 맞춤], 진단용 `logconf_indi.json`에 `TrackFreqPolicy: INFO` 추가 — `mf_web_catalogs_dev_ko` P6-2 참고), `mf_indi_goto_guide_plan`·`mf_goto_mount_source_structure` 참고 |
| LiveCam RAW 프리뷰/라이브 스택 | Draft PR 없음 | 로컬 `mf_pifinder` 작업트리 | solver 경로와 분리된 `raw_live_stack`/`livecam_config` RAW 프리뷰·롤링 라이브 스택, 카메라 백엔드가 RAW 프레임 1장 publish → web API가 display용 PNG/JPEG/WebP 렌더링, 스택 모드(mean/sum/max)·크기/줌·기본값 reset 컨트롤, Web 카메라 노출/게인 컨트롤(`camera_controls`, `/api/camera/controls`, `camera_command_queue` 웹 배선), `mf_raw_live_stack_plan` 참고 |
| 변경 히스토리/PR 재편성 문서화 | Draft PR 없음 | 로컬 `mf_pifinder` 작업트리 | 이 문서의 작업 단위 목차, PR 상태, 재편성 기준 |
| 최종 통합 브랜치 | Upstream PR 아님 | `origin/mf_pifinder` + 로컬 미커밋 변경 | 위 기능들을 통합해 실제 장치에서 설치/테스트하는 기준 브랜치 |

<a id="mf_change_history_ko--pr-재편성-제안"></a>
### PR 재편성 제안

기존 Draft PR은 기능을 매우 작게 나누었기 때문에 리뷰 맥락을 보존하기 어렵다.
다음 기준으로 재정리하면 관리하기 쉽다.

| 새 PR 묶음 제안 | 포함 후보 | 기존 Draft PR 처리 |
| --- | --- | --- |
| Platform/Bookworm/RPi4-RPi5 compatibility | Bookworm 설치/경로 기반 + 보드/GPS UART 프로파일 | #499와 #505를 하나로 합치거나, #499를 확장하고 #505를 닫는 방식 |
| Camera usability | focus preview, camera gain, camera LCD preview | #501 유지 또는 camera 관련 문서와 함께 확장 |
| Input devices | Bluetooth keyboard, USB HID key mapping, keyboard mapping docs | #506 중심으로 정리 |
| Optional INDI mount integration | INDI mount process, install script, object sync, keyboard mapping의 INDI 항목 | #503 유지 |
| INDI Multi Align refinement | Multi Align 공통 session controller, OnStepX stale align reset, Web/LCD/SkySafari 흐름 문서 | INDI PR에 포함하거나 OnStepX 고급 기능 PR로 분리 |
| Integrated time sync | GPS/NTP/RTC/software PPS, helper service, status UI | #504 유지 |
| Network connectivity | AP/Client/AP+STA Wi-Fi modes, virtual AP services, STA 밴드 선호, AP IP 설정, AP 보안/암호, 선택형 AP+STA 인터넷 공유, OS Wi-Fi 프로파일 가져오기, 스캔된 SSID 선택, web/device network UI | 새 Draft PR 필요 |
| Locations catalog | GeoNames 기반 오프라인 위치 카탈로그, 국가/지역/군구/도시 선택, 좌표 자동 입력 | 새 Draft PR 필요 |
| Web observing UI | red night theme, PWA/fullscreen app mode | 새 Draft PR 필요 |
| 선택형 IMU compass 방위 개선 | BNO055 NDOF 옵션, 자동/수동 calibration, status UI | 새 Draft PR 필요 |
| SkySafari/INDI 마운트 모드 호환성 | Alt/Az/EQ SkySafari LX200 status, SkySafari GoTo/Sync forwarding, guide keepalive bridge, no-solve IMU 보정, INDI mount mode 검증 문서 | 새 Draft PR 필요 |
| Pointing Coordinate Service | `pointing.aligned.estimate`, IMU fallback, INDI mount readback을 통합하는 상시 좌표 서비스, SkySafari 좌표 응답, GoTo/수동 이동 중 mount progress readback | SkySafari/INDI 마운트 모드 PR 또는 별도 좌표 서비스 PR |
| INDI GoTo/Guide 서비스 | `indi_goto_guide_service` 프로세스, SkySafari GoTo 라우팅, PiFinder 수동 접근 + correction GoTo, tracking guide target 관리 | INDI PR에 포함하거나 GoTo/Guide 서비스 PR로 분리 |
| LiveCam RAW 프리뷰/라이브 스택 | `raw_live_stack`/`livecam_config`, RAW 프리뷰 + 롤링 스택, web 렌더 endpoint, 스택/크기/줌/reset 컨트롤, Web 카메라 노출/게인 컨트롤 | 새 Draft PR 필요 |
| Korean localization | Korean locale and CJK language handling | #500은 파일 규모가 커서 별도 유지 권장 |

문서는 각 기능 PR에 필요한 설치/사용 문서를 함께 넣는 방식을 권장한다. 예를 들어
INDI 문서는 INDI PR에, Time Sync 문서는 Time Sync PR에 포함한다.

<a id="mf_change_history_ko--최종-소스-변경-목록"></a>
### 최종 소스 변경 목록

변경 또는 추가된 PiFinder 파일:

```text
python/PiFinder/boot_config.py
python/PiFinder/board_config.py
python/PiFinder/api_extensions.py
python/PiFinder/camera_interface.py
python/PiFinder/main.py
python/PiFinder/gps_gpsd.py
python/PiFinder/gps_ubx.py
python/PiFinder/gps_ubx_parser.py
python/PiFinder/gps_time_sync.py
python/PiFinder/gps_time_sync_helper.py
python/PiFinder/indi_multipoint_align.py
python/PiFinder/pointing_coordinate_service.py
python/PiFinder/mountcontrol_indi.py
python/PiFinder/server.py
python/PiFinder/sys_utils.py
python/PiFinder/switch_camera.py
python/PiFinder/keyboard_interface.py
python/PiFinder/keyboard_pi.py
python/PiFinder/ui/base.py
python/PiFinder/ui/callbacks.py
python/PiFinder/ui/fonts.py
python/PiFinder/ui/bluetooth_keyboard.py
python/PiFinder/ui/menu_manager.py
python/PiFinder/ui/menu_structure.py
python/PiFinder/ui/gps_time_sync_status.py
python/PiFinder/ui/object_details.py
python/PiFinder/ui/textentry.py
python/PiFinder/displays.py
python/PiFinder/ui/preview.py
python/locale/ko/LC_MESSAGES/messages.po
python/locale/ko/LC_MESSAGES/messages.mo
python/views/base.html
python/views/css/style.css
python/views/js/init.js
python/views/manifest.webmanifest
python/views/service-worker.js
python/views/images/pwa-icon-192.png
python/views/images/pwa-icon-512.png
python/tests/test_web_theme_static.py
python/tests/test_wifi_apsta_static.py
python/tests/test_sys_utils.py
python/tests/test_pointing_coordinate_service.py
python/views/network.html
python/views/tools.html
pi_config_files/pifinder.service
pi_config_files/pifinder_apsta_prepare.service
pi_config_files/pifinder_apsta_monitor.service
pi_config_files/pifinder_gps_time_sync.service
pi_config_files/pifinder_splash.service
pi_config_files/cedar_detect.service
pi_config_files/smb.conf
pifinder_paths.sh
pifinder_setup.sh
pifinder_update.sh
pifinder_post_update.sh
switch-ap.sh
switch-apsta.sh
switch-cli.sh
migration_source/v1.x.x.sh
migration_source/v2.1.0.sh
migration_source/v2.2.1.sh
migration_source/v2.2.2.sh
migration_source/v2.4.0.sh
migration_source/v2.6.0.sh
migration_source/mf_apsta_wifi.sh
migration_source/mf_wifi_settings.sh
migrate_db.sql
default_config.json
scripts/camera_lcd_preview.py
scripts/import_initial_wifi_networks.py
scripts/pifinder_apsta.sh
scripts/install_indi_mount.sh
scripts/install_indi_mount_OnstepX.sh
scripts/patches/indi-v2.2.3.1-onstepx.patch
scripts/install_chrony_time_sync.sh
scripts/install_gps_time_sync_helper.sh
docs/mf_dev/mf_bookworm_install_ko.md
docs/mf_dev/mf_bookworm_install_en.md
docs/mf_dev/mf_change_history_ko.md
docs/mf_dev/mf_change_history_en.md
docs/mf_dev/mf_indi_mount_install_ko.md
docs/mf_dev/mf_indi_mount_install_en.md
docs/mf_dev/mf_multipoint_align_flow_ko.md
docs/mf_dev/mf_multipoint_align_flow_en.md
docs/mf_dev/mf_wifi_apsta_ko.md
docs/mf_dev/mf_wifi_apsta_en.md
docs/mf_dev/mf_keyboard_mapping_ko.md
docs/mf_dev/mf_keyboard_mapping_en.md
docs/mf_dev/mf_pifinder_new_device_tasks_ko.md
docs/mf_dev/mf_pifinder_new_device_tasks_en.md
docs/mf_dev/mf_pifinder_rpi4_pi5_compatibility_ko.md
docs/mf_dev/mf_pifinder_rpi4_pi5_compatibility_en.md
docs/mf_dev/mf_time_sync_ko.md
docs/mf_dev/mf_time_sync_en.md
docs/mf_dev/mf_mount_mode_compatibility_ko.md
docs/mf_dev/mf_mount_mode_compatibility_en.md
docs/mf_dev/mf_coordinate_helper_plan_ko.md
docs/mf_dev/mf_coordinate_helper_plan_en.md
```

원본 대비 재검토 결과:

```text
비교 기준: 현재 checkout된 PiFinder Git HEAD

Tracked source diff:
default_config.json              modified
migrate_db.sql                   modified
pi_config_files/*.service        modified
pi_config_files/smb.conf         modified
pifinder_setup.sh                modified
pifinder_update.sh               modified
pifinder_post_update.sh          modified
switch-ap.sh                     modified
switch-cli.sh                    modified
migration_source/*.sh            modified
python/PiFinder/api_extensions.py modified
python/PiFinder/camera_interface.py  modified
python/PiFinder/displays.py       modified
python/PiFinder/main.py           modified
python/PiFinder/switch_camera.py  modified
python/PiFinder/keyboard_interface.py modified
python/PiFinder/keyboard_pi.py    modified
python/PiFinder/sys_utils.py      modified
python/PiFinder/ui/base.py        modified
python/PiFinder/ui/callbacks.py   modified
python/PiFinder/ui/fonts.py       modified
python/PiFinder/ui/menu_manager.py modified
python/PiFinder/ui/menu_structure.py modified
python/PiFinder/ui/textentry.py   modified
python/PiFinder/ui/preview.py     modified
python/views/tools.html           modified

New PiFinder files:
python/PiFinder/boot_config.py
python/PiFinder/ui/bluetooth_keyboard.py
python/locale/ko/LC_MESSAGES/messages.po
python/locale/ko/LC_MESSAGES/messages.mo
pifinder_paths.sh
scripts/camera_lcd_preview.py
docs/mf_dev/mf_bookworm_install_ko.md
docs/mf_dev/mf_bookworm_install_en.md
docs/mf_dev/mf_change_history_ko.md
docs/mf_dev/mf_change_history_en.md
```

이 재검토에서 위 목록 밖의 PiFinder 소스 변경은 발견되지 않았다. 아래 파일별
기록은 현재 작업트리와 원본 소스의 실제 diff를 기준으로 정리했다.

주요 최종값:

```text
SSD1351 SPI speed: 32000000 Hz
Focus bright-background threshold: 220.0
Pi camera startup gain: camera profile analog_gain 사용
camera_exp config value in use: auto
Default gps_port: auto
Resolved gps_port: CM5/Pi5 -> /dev/ttyAMA2, Pi4 -> /dev/ttyAMA3, fallback -> /dev/ttyAMA1
Keyboard HID input: GPIO keypad + USB/Bluetooth libinput
Menu languages: en, de, fr, es, ko, zh
Install user/path model: current OS user, not hard-coded pifinder
```

<a id="mf_change_history_ko--pythonpifinderboot_configpy"></a>
### `python/PiFinder/boot_config.py`

새로 추가한 파일이다.

<a id="mf_change_history_ko--추가한-api"></a>
#### 추가한 API

```python
def get_boot_config_path() -> Path:
    firmware_config = Path("/boot/firmware/config.txt")
    if firmware_config.exists():
        return firmware_config
    return Path("/boot/config.txt")
```

<a id="mf_change_history_ko--수정-목적"></a>
#### 수정 목적

PiFinder 기존 코드 일부는 Raspberry Pi boot config 경로를 `/boot/config.txt`로
고정해서 사용한다. Raspberry Pi OS Bookworm에서는 실제 설정 파일이
`/boot/firmware/config.txt`이므로, CM5 Bookworm에서 카메라 전환이나 카메라 타입
표시 기능이 실제 부팅 설정을 보지 못하는 문제가 생긴다.

<a id="mf_change_history_ko--동작-변화"></a>
#### 동작 변화

- `/boot/firmware/config.txt`가 있으면 그것을 우선 사용한다.
- 없으면 기존 Raspberry Pi OS Legacy 계열과 호환되도록 `/boot/config.txt`를 사용한다.
- OS 버전별 경로 차이를 `switch_camera.py`, `callbacks.py`에 흩뿌리지 않고 한 곳에 모았다.

<a id="mf_change_history_ko--pythonpifinderswitch_camerapy"></a>
### `python/PiFinder/switch_camera.py`

카메라 오버레이 전환 코드가 Bookworm boot config 경로와 IMX462 오버레이를 다루도록 수정했다.

<a id="mf_change_history_ko--변경-전"></a>
#### 변경 전

- `/boot/config.txt`를 직접 읽고 썼다.
- `imx462` 요청을 내부에서 `imx290`으로 바꿨다.
- 새 카메라 오버레이를 추가할 때 `imx290`에만 `clock-frequency=74250000`을 붙였다.

<a id="mf_change_history_ko--변경-후"></a>
#### 변경 후

- `get_boot_config_path()`를 사용해 실제 boot config 파일을 찾는다.
- `imx462`를 더 이상 강제로 `imx290`으로 바꾸지 않는다.
- `imx290`, `imx462` 모두에 대해 필요 시 `clock-frequency=74250000`을 붙인다.
- 기존 `dtoverlay=imx...` 줄을 주석 처리하고 선택한 카메라 오버레이를 활성화하는 기존 흐름은 유지한다.
- `switch_boot()` docstring을 실제 동작에 맞게 boot config/root 표현으로 정리했다.

<a id="mf_change_history_ko--코드-수준-변경"></a>
#### 코드 수준 변경

```python
from PiFinder.boot_config import get_boot_config_path

boot_config_path = get_boot_config_path()
```

기존:

```python
with open("/boot/config.txt", "r") as boot_in:
```

수정:

```python
with open(boot_config_path, "r") as boot_in:
```

기존:

```python
if cam_type == "imx462":
    cam_type = "imx290"
```

수정:

```python
# imx462를 imx290으로 강제 변환하지 않음
```

<a id="mf_change_history_ko--기대-효과"></a>
#### 기대 효과

- CM5 Bookworm에서 카메라 전환 코드가 실제 `/boot/firmware/config.txt`를 수정한다.
- Bookworm firmware에 있는 `imx462.dtbo`를 직접 사용할 수 있다.
- 오래된 imx290 대체 방식과 새 imx462 직접 오버레이 방식을 모두 수용할 수 있다.

<a id="mf_change_history_ko--pythonpifinderuicallbackspy"></a>
### `python/PiFinder/ui/callbacks.py`

카메라 타입 표시 callback이 Bookworm boot config 경로를 읽도록 수정했고,
카메라 gain 메뉴와 GPS 포트 메뉴에 필요한 callback을 추가했다.

<a id="mf_change_history_ko--변경-전-1"></a>
#### 변경 전

- `get_camera_type()`가 `/boot/config.txt`를 직접 열었다.
- CM5 Bookworm에서는 실제 active config가 `/boot/firmware/config.txt`라 UI 표시가 실제 설정과 어긋날 수 있었다.

<a id="mf_change_history_ko--변경-후-1"></a>
#### 변경 후

- `get_boot_config_path()`를 사용한다.
- 기존 설치에서 `dtoverlay=imx290...`로 IMX462를 쓰던 경우를 고려해 UI 표시에서는 `imx290`을 `imx462`로 매핑하는 동작을 유지한다.
- gain 메뉴용으로 현재 runtime gain을 `shared_state.last_image_metadata()`에서 읽는다.
- `Profile` gain 표시용으로 현재 카메라 타입의 `CameraProfile.analog_gain`을 읽는다.
- gain 메뉴에서 선택한 값을 카메라 queue로 `set_gain:<value>` 형태로 보낸다.
- `Profile` 항목을 선택하면 `set_gain:profile`을 보낸다.
- `update_gpsd_baud_rate()`가 `gps_baud_rate`뿐 아니라 `gps_port`도 함께 읽는다.
- GPS baud나 port 메뉴에서 선택이 바뀌면 `sys_utils.check_and_sync_gpsd_config(baud_rate, gps_port)`를 호출한다.
- `switch_language()`가 `ko`와 `zh`를 CJK 언어로 처리해 언어 변경 뒤 PiFinder를 재시작한다.

<a id="mf_change_history_ko--코드-수준-변경-1"></a>
#### 코드 수준 변경

```python
from PiFinder.boot_config import get_boot_config_path
```

```python
with open(get_boot_config_path(), "r") as boot_in:
    boot_lines = list(boot_in)
```

<a id="mf_change_history_ko--기대-효과-1"></a>
#### 기대 효과

- 카메라 설정 메뉴나 상태 표시가 Bookworm의 실제 boot config와 일치한다.
- IMX462를 imx290 호환 오버레이로 쓰던 기존 사용자의 표시도 깨지지 않는다.
- gain 메뉴의 checkmark가 저장된 `camera_gain` 값이 아니라 실제 runtime gain 기준으로 표시된다.
- GPS 포트와 baud rate를 UI에서 선택하면 gpsd 설정이 같은 callback으로 갱신된다.
- 한국어 선택 시 OLED에서 한글 glyph가 깨지지 않도록 CJK 폰트로 다시 시작된다.

<a id="mf_change_history_ko--pythonpifindersys_utilspy"></a>
### `python/PiFinder/sys_utils.py`

gpsd 설정 동기화가 baud rate만 보던 구조에서 serial device와 baud rate를 함께 보도록 확장했다.

<a id="mf_change_history_ko--변경-전-2"></a>
#### 변경 전

- `check_and_sync_gpsd_config(baud_rate)`는 `/etc/default/gpsd`의 `GPSD_OPTIONS`만 비교했다.
- `update_gpsd_config(baud_rate)`도 `GPSD_OPTIONS`만 수정했다.
- `DEVICES="/dev/ttyAMA1"` 같은 포트 설정은 UI에서 바꿀 수 없었다.

<a id="mf_change_history_ko--변경-후-2"></a>
#### 변경 후

- `DEFAULT_GPSD_DEVICE` fallback을 추가했다.
- `check_and_sync_gpsd_config(baud_rate, device=DEFAULT_GPSD_DEVICE)` 형태로 확장했다.
- `/etc/default/gpsd`의 `DEVICES`와 `GPSD_OPTIONS`를 모두 비교한다.
- 둘 중 하나라도 다르면 `update_gpsd_config(baud_rate, device)`를 호출한다.
- `update_gpsd_config()`는 `DEVICES=...`와 `GPSD_OPTIONS=...` 줄을 함께 갱신한다.
- 기존 파일에 해당 줄이 없으면 새 줄을 추가한다.
- 설정을 쓴 뒤 기존처럼 gpsd 서비스를 재시작한다.

<a id="mf_change_history_ko--기대-효과-2"></a>
#### 기대 효과

- CM5처럼 GPS UART가 `/dev/ttyAMA2`에 잡히는 보드도 UI 설정으로 유지할 수 있다.
- PiFinder 재시작 시 `/etc/default/gpsd`가 선택한 포트와 baud로 자동 동기화된다.
- 후속 Pi4/Pi5 호환성 정리 뒤 기본 설정은 `gps_port: auto`가 되었고,
  `board_config` profile이 보드별 기본 포트를 결정한다.

<a id="mf_change_history_ko--bluetooth-keyboard-helper-추가"></a>
#### Bluetooth keyboard helper 추가

Bluetooth 키보드 연결 UI에서 사용할 수 있도록 `bluetoothctl` wrapper와 장치 파싱 함수를 추가했다.

추가한 주요 함수:

```python
def list_bluetooth_devices() -> list[dict[str, Any]]
def scan_bluetooth_devices(scan_seconds: int = 12) -> list[dict[str, Any]]
def connect_bluetooth_device(address: str) -> str
def disconnect_bluetooth_device(address: str) -> str
def remove_bluetooth_device(address: str) -> str
def reconnect_bluetooth_keyboards() -> int
def auto_reconnect_bluetooth_keyboards(...) -> int
```

구현 세부:

- `subprocess`로 `bluetoothctl`을 실행한다.
- ANSI escape와 prompt가 섞인 출력을 정리한 뒤 `Device <MAC> <name>` 형식을 파싱한다.
- 스캔 중 stdout을 버리지 않고 보존해 `[CHG] Device <MAC> Name: ...`와
  `[CHG] Device <MAC> Alias: ...` 형태의 scan response/name change 이벤트를 함께 파싱한다.
- 광고 목록의 초기 이름이 MAC 주소뿐이어도 scan response로 실제 이름이 들어오면 실제 이름을 우선 사용한다.
- 각 장치에 대해 `info <MAC>`를 호출해 `paired`, `trusted`, `connected`, `blocked`, `icon` 상태를 읽는다.
- 스캔 시 `agent KeyboardDisplay`, `default-agent`, `pairable on`, `scan on`을 순서대로 실행한다.
- `reconnect_bluetooth_keyboards()`는 paired 장치 중 keyboard로 보이는 장치를 우선 연결하고, 명확한 keyboard 장치가 없으면 paired 장치를 fallback으로 시도한다.
- `auto_reconnect_bluetooth_keyboards()`는 PiFinder 시작 직후 Bluetooth controller나 HID 장치가 늦게 준비되는 경우를 고려해 여러 번 재시도한다.
- 자동 재접속은 이미 connected인 장치는 건너뛰고, paired/trusted 장치 중 연결되지 않은 장치만 `connect`를 시도한다.

기대 효과:

- PiFinder UI에서 Bluetooth 키보드를 스캔, 연결, 재연결, 해제, 삭제할 수 있다.
- USB 키보드는 별도 설정 없이 기존 libinput 경로로 동작하고, Bluetooth 키보드는 페어링 뒤 같은 입력 경로로 동작한다.
- PiFinder 서비스 재시작이나 OS 재부팅 뒤 paired/trusted Bluetooth 키보드가 있으면 자동 재접속을 시도한다.

<a id="mf_change_history_ko--사용자명홈-경로-hardcode-제거"></a>
#### 사용자명/홈 경로 hardcode 제거

기존 설치/런타임 일부는 OS 사용자가 항상 `pifinder`이고 데이터 경로가
`/home/pifinder/PiFinder_data`라고 가정했다. 여러 대의 PiFinder를 같은 네트워크에서
운영하기 위해 OS username과 hostname을 장비별로 다르게 지정할 수 있도록 이 가정을
줄였다.

변경 내용:

- `BACKUP_PATH`를 `utils.data_dir / "PiFinder_backup.zip"` 기반으로 변경했다.
- WiFi mode 전환은 `/home/pifinder/PiFinder/switch-*.sh` 대신
  `utils.pifinder_dir / "switch-*.sh"`를 호출한다.
- backup 대상 파일은 `utils.data_dir`에서 계산한다.
- software update script 경로는 `utils.pifinder_dir / "pifinder_update.sh"`에서 계산한다.
- NixOS migration script 경로도 `utils.pifinder_dir` 기반으로 변경했다.

기대 효과:

- OS 사용자를 `scope-a`, `scope-b`처럼 다르게 만들어도 backup, restore, update,
  WiFi mode 전환 경로가 현재 사용자의 PiFinder 설치 위치를 따른다.
- hostname은 Raspberry Pi OS에서 지정한 값을 유지하고, 웹 Network 화면에서 계속
  변경할 수 있다.

<a id="mf_change_history_ko--pifinder_pathssh-설치업데이트마이그레이션-스크립트"></a>
### `pifinder_paths.sh`, 설치/업데이트/마이그레이션 스크립트

새 공통 helper인 `pifinder_paths.sh`를 추가하고, 설치/업데이트 관련 shell script의
`/home/pifinder` 의존성을 제거했다.

<a id="mf_change_history_ko--추가한-helper"></a>
#### 추가한 helper

```bash
PIFINDER_USER
PIFINDER_HOME
PIFINDER_REPO_DIR
PIFINDER_DATA_DIR
pifinder_render_config <template> <target>
pifinder_boot_config_path
```

<a id="mf_change_history_ko--변경한-파일"></a>
#### 변경한 파일

```text
pifinder_setup.sh
pifinder_update.sh
pifinder_post_update.sh
switch-ap.sh
switch-cli.sh
migration_source/v1.x.x.sh
migration_source/v2.1.0.sh
migration_source/v2.2.1.sh
migration_source/v2.2.2.sh
migration_source/v2.4.0.sh
migration_source/v2.6.0.sh
migrate_db.sql
```

구현 세부:

- `pifinder_setup.sh`는 root로 직접 실행하지 못하게 막고, 현재 OS 사용자 기준으로 설치한다.
- 필요한 시스템 작업은 스크립트 내부에서만 `sudo`로 실행한다.
- repo 경로는 기본적으로 `$HOME/PiFinder`, 데이터 경로는 `$HOME/PiFinder_data`를 사용한다.
- `pifinder_update.sh`와 `pifinder_post_update.sh`는 스크립트 자신의 위치에서 repo 경로를 계산한다.
- 마이그레이션 스크립트는 `PIFINDER_REPO_DIR`, `PIFINDER_DATA_DIR`, `PIFINDER_USER`를 사용한다.
- `switch-ap.sh`, `switch-cli.sh`는 스크립트 위치 기준으로 `wifi_status.txt`를 갱신한다.
- Bookworm에서는 `/boot/firmware/config.txt`, legacy에서는 `/boot/config.txt`를 사용하도록 helper를 공유한다.

기대 효과:

- Raspberry Pi Imager에서 OS user와 hostname을 `pifinder`가 아닌 원하는 이름으로 만들어도 설치 스크립트가 동작한다.
- 여러 대를 `scope-a.local`, `scope-b.local`처럼 분리해 mDNS 충돌을 줄일 수 있다.
- update/migration도 `/home/pifinder`에 묶이지 않는다.

<a id="mf_change_history_ko--mdns-안정화-2026-08-06"></a>
#### mDNS 안정화 (2026-08-06)

안드로이드에서 `<hostname>.local` 접속이 됐다 안 됐다 하는 문제를 잡기 위해
`pifinder_setup.sh`에 두 가지 설정을 추가했다.

- WiFi 절전모드 해제: brcmfmac이 절전 중 멀티캐스트(mDNS 질의)를 유실한다.
  PC는 캐시·재시도로 가려지지만 안드로이드 `.local` 리졸버는 타임아웃이 짧아
  간헐 실패로 드러난다. `/etc/NetworkManager/conf.d/wifi-powersave.conf`에
  `wifi.powersave = 2`(끔)를 기록한다.
- avahi IPv6 광고 차단: wlan0에 link-local(`fe80::`)뿐인데 AAAA로 광고되면
  IPv6를 우선하는 안드로이드가 zone 없는 `fe80::`로 접속을 시도해 실패한다.
  `avahi-daemon.conf`에 `use-ipv6=no`, `publish-aaaa-on-ipv4=no`를 적용한다.

<a id="mf_change_history_ko--pi_config_filesservice-pi_config_filessmbconf"></a>
### `pi_config_files/*.service`, `pi_config_files/smb.conf`

service와 Samba 설정 파일을 설치 시 렌더링하는 템플릿으로 변경했다.

<a id="mf_change_history_ko--변경-전-3"></a>
#### 변경 전

```text
User=pifinder
WorkingDirectory=/home/pifinder/PiFinder/python
guest account = pifinder
path=/home/pifinder/PiFinder_data
```

<a id="mf_change_history_ko--변경-후-3"></a>
#### 변경 후

```text
User=__PIFINDER_USER__
WorkingDirectory=__PIFINDER_REPO_DIR__/python
guest account = __PIFINDER_USER__
path=__PIFINDER_DATA_DIR__
```

`pifinder_render_config()`가 설치 시 placeholder를 실제 값으로 치환한다.

<a id="mf_change_history_ko--기대-효과-3"></a>
#### 기대 효과

- systemd service가 custom OS user로 실행된다.
- Samba 공유도 custom user와 custom home 아래의 `PiFinder_data`를 사용한다.

<a id="mf_change_history_ko--pythonpifinderapi_extensionspy-pythonviewstoolshtml"></a>
### `python/PiFinder/api_extensions.py`, `python/views/tools.html`

custom user 환경에서 웹/API 경로와 안내 문구가 어긋나지 않도록 수정했다.

변경 내용:

- `/api/camera/debug`의 debug dump 경로를 `/home/pifinder/...` 대신 `utils.debug_dump_dir`로 변경했다.
- Tools 화면의 비밀번호 변경 안내 문구에서 고정 계정명 `pifinder`를 제거하고 “현재 시스템 사용자 계정”으로 표현했다.
- 한국어 locale의 해당 문구도 함께 갱신했다.

기대 효과:

- OS 사용자명이 `pifinder`가 아니어도 debug frame API와 비밀번호 변경 안내가 실제 설치 상태와 맞다.

<a id="mf_change_history_ko--pythonpifindermainpy"></a>
### `python/PiFinder/main.py`

PiFinder 시작 시 gpsd 동기화에 GPS 포트를 포함했다.

<a id="mf_change_history_ko--변경-후-4"></a>
#### 변경 후

- `gps_baud_rate`와 함께 `gps_port`를 읽는다.
- `gps_port`가 없으면 `sys_utils.DEFAULT_GPSD_DEVICE`를 fallback으로 사용한다.
- `sys_utils.check_and_sync_gpsd_config(baud_rate, gps_port)`를 호출한다.
- 개발/테스트용 `--lang` 인자 허용 목록에 `ko`와 `zh`를 추가했다.

<a id="mf_change_history_ko--기대-효과-4"></a>
#### 기대 효과

- 메뉴에서 선택한 GPS 포트가 서비스 재시작 뒤에도 `/etc/default/gpsd`에 유지된다.
- `python -m PiFinder.main --lang ko`처럼 한국어 UI를 직접 지정해 실행할 수 있다.

<a id="mf_change_history_ko--pythonpifindercamera_interfacepy"></a>
### `python/PiFinder/camera_interface.py`

카메라 gain을 런타임에 조정하는 기존 `set_gain` 명령을 확장했다.

<a id="mf_change_history_ko--변경-전-4"></a>
#### 변경 전

- `set_gain:<정수>` 명령만 처리했다.
- gain 값을 `int()`로 변환했다.
- 카메라 프로파일 기본 gain으로 되돌리는 명령은 없었다.

<a id="mf_change_history_ko--변경-후-5"></a>
#### 변경 후

- `get_default_gain()`을 추가했다.
- Pi camera처럼 `self.profile.analog_gain`이 있는 backend는 그 값을 기본 gain으로 반환한다.
- profile이 없는 debug/none backend는 현재 `self.gain`이 있으면 그 값을, 없으면 `1.0`을 fallback으로 사용한다.
- `set_gain:profile` 명령을 지원한다.
- 숫자 gain은 `float()`로 처리해 정수 외 값도 받을 수 있게 했다.
- console/log 표시는 `g` format을 사용해 `30.0` 대신 `30`처럼 표시한다.

<a id="mf_change_history_ko--코드-수준-변경-2"></a>
#### 코드 수준 변경

```python
def get_default_gain(self) -> float:
    profile = getattr(self, "profile", None)
    if profile is not None and hasattr(profile, "analog_gain"):
        return float(profile.analog_gain)
    return float(getattr(self, "gain", 1.0))
```

```python
if gain_value == "profile":
    self.gain = self.get_default_gain()
else:
    self.gain = float(gain_value)
```

<a id="mf_change_history_ko--기대-효과-5"></a>
#### 기대 효과

- PiFinder 시작 시 gain은 원본처럼 프로파일 기본값을 유지한다.
- 사용자가 메뉴에서 gain을 바꿀 때만 현재 실행 중인 카메라 gain이 바뀐다.
- `Profile`을 선택하면 저장된 `camera_gain` 값과 무관하게 카메라 프로파일 기본 gain으로 돌아간다.

<a id="mf_change_history_ko--pythonpifinderkeyboard_interfacepy"></a>
### `python/PiFinder/keyboard_interface.py`

물리 키보드에서 들어온 실제 문자 입력을 UI까지 전달하기 위해 text keycode 영역을 추가했다.

추가한 API:

```python
TEXT_BASE = 1000

def text_key(char: str) -> int
def is_text_key(keycode: int) -> bool
def text_from_keycode(keycode: int) -> str
```

기대 효과:

- 숫자/방향/특수키 중심이던 기존 입력 큐에 알파벳 문자 입력을 안전하게 실을 수 있다.
- 기존 `ALT_*`, `LNG_*`, 숫자 keycode와 충돌하지 않는다.

<a id="mf_change_history_ko--pythonpifinderkeyboard_pipy"></a>
### `python/PiFinder/keyboard_pi.py`

GPIO 키패드와 함께 USB/Bluetooth HID 키보드를 PiFinder 입력으로 사용할 수 있도록 libinput 키 매핑을 확장했다.

<a id="mf_change_history_ko--변경-전-5"></a>
#### 변경 전

- libinput 물리 키보드 매핑은 방향키, Enter, 일부 keypad `+/-` 정도만 처리했다.
- 숫자키, 숫자패드, Space, Esc, Backspace, long/alt shortcut에 대응하지 않았다.
- 기존 keypad `+/-` event code 매핑이 Linux input code 기준으로 서로 뒤바뀔 수 있었다.

<a id="mf_change_history_ko--변경-후-6"></a>
#### 변경 후

- Linux input key code 상수를 파일 상단에 명시했다.
- `self.physical_pressed`를 추가해 Alt/Ctrl/Shift 조합 상태를 추적한다.
- `self.physical_press_times`, `self.physical_last_repeat_times`, `self.physical_hold_sent`,
  `self.physical_press_modifiers`를 추가해 USB/Bluetooth 키보드의 실제 hold 시간을 추적한다.
- `self.text_physical_key_mapping`에 알파벳 키를 실제 문자 입력으로 매핑했다.
- `self.physical_key_mapping`에 USB/Bluetooth 키보드용 기본 매핑을 추가했다.
- `self.alt_physical_key_mapping`에 `Alt+키` 조합을 PiFinder `ALT_*` 입력으로 매핑했다.
- `self.long_physical_key_mapping`은 실제 long press와 호환용 `Shift/Ctrl+키` 조합에서 함께 사용한다.
- `Left`, `Right`, `Enter/KP Enter`는 1초 이상 누르면 실제 long key로 처리하고, release 시 일반키 중복 입력을 막는다.
- `Up`, `Down`은 GPIO 키패드처럼 1초 이상 누르면 일반 `UP/DOWN` 반복 입력으로 처리한다.
- `Alt+키` 조합은 long press보다 우선하며, `Alt`를 먼저 떼더라도 처음 눌렀을 때의 modifier 상태를 보존해 `ALT_*`로 처리한다.

주요 매핑:

```text
Arrow keys          -> LEFT/UP/DOWN/RIGHT
Enter/KP Enter      -> SQUARE
Space               -> actual space text input
Esc                 -> LEFT
Backspace           -> MINUS/Delete
0-9 top row         -> number input
0-9 keypad          -> number input
= or KP+            -> PLUS
- or KP-            -> MINUS
a-z                 -> actual text input
Shift+a-z           -> uppercase text input
Alt+Arrow           -> ALT_LEFT/ALT_UP/ALT_DOWN/ALT_RIGHT
Alt+= or Alt+KP+    -> ALT_PLUS
Alt+- or Alt+KP-    -> ALT_MINUS
Alt+0               -> ALT_0
Alt+Enter           -> ALT_SQUARE
Hold Left/Right 1s  -> LNG_LEFT/LNG_RIGHT
Hold Enter 1s       -> LNG_SQUARE
Hold Up/Down 1s     -> repeated UP/DOWN
Shift/Ctrl+Arrow    -> LNG_* compatibility shortcut
Shift/Ctrl+Enter    -> LNG_SQUARE compatibility shortcut
```

이전의 `q/a/z`, `w/s/e/d/r/f/g`, `i/j/k/l/m` compact single-key shortcut은
실제 알파벳 입력을 방해하므로 USB/Bluetooth libinput 경로에서는 사용하지 않는다.

기대 효과:

- PiFinder service가 기본 `keyboard_pi` backend를 유지한 상태에서 USB 키보드와 Bluetooth 키보드를 모두 입력 장치로 사용할 수 있다.
- X11/Wayland DISPLAY가 필요한 `keyboard_local.py`를 사용하지 않아도 된다.
- GPIO 키패드 동작은 기존 matrix scan 경로를 그대로 유지한다.
- 객체 검색이나 이름 입력 화면에서 알파벳 키를 누르면 multi-tap 변환 없이 실제 문자가 입력된다.
- USB/Bluetooth 키보드도 실제로 키를 길게 눌러 marking menu, top menu 복귀, recent object 이동을 실행할 수 있다.

<a id="mf_change_history_ko--pythonpifindermainpy-pythonpifinderuibasepy-pythonpifinderuimenu_managerpy-pythonpifinderuitextentrypy"></a>
### `python/PiFinder/main.py`, `python/PiFinder/ui/base.py`, `python/PiFinder/ui/menu_manager.py`, `python/PiFinder/ui/textentry.py`

Bluetooth 키보드 자동 재접속과 알파벳 키코드를 UI text entry까지 전달하는 경로를 추가했다.

변경 내용:

- `threading`을 import했다.
- `start_bluetooth_keyboard_autoreconnect()`를 추가했다.
- 실제 Pi 하드웨어 모드에서만 `sys_utils.auto_reconnect_bluetooth_keyboards()`를 daemon thread로 실행한다.
- 이 thread는 PiFinder 하위 process들이 시작된 뒤 실행해 startup과 UI 표시를 막지 않는다.
- main loop에서 `KeyboardInterface.is_text_key(keycode)`를 특수키보다 먼저 검사한다.
- text keycode면 `KeyboardInterface.text_from_keycode(keycode)`로 실제 문자를 복원한다.
- `MenuManager.key_text(char)`를 추가해 현재 활성 UI module로 문자를 전달한다.
- `UIModule.key_text(char)` 기본 hook을 추가했다.
- `UITextEntry.key_text(char)`는 받은 문자를 `current_text`에 바로 추가하고 검색 결과를 갱신한다.

기대 효과:

- Bluetooth/USB 키보드에서 입력한 알파벳이 PiFinder 검색/텍스트 입력 화면에 실제 글자로 들어간다.
- 기존 숫자 keypad 기반 multi-tap 입력은 그대로 유지된다.
- paired/trusted Bluetooth 키보드는 PiFinder 시작 후 자동 재접속이 시도된다.

<a id="mf_change_history_ko--pythonpifinderdisplayspy"></a>
### `python/PiFinder/displays.py`

CM5/Pi 5 계열에서 SPI 장치 번호가 기존 Pi 4와 다를 수 있는 점과 SSD1351 OLED의 안정 SPI 속도를 반영했다.

<a id="mf_change_history_ko--변경-전-6"></a>
#### 변경 전

- 각 디스플레이 클래스가 직접 `spi(device=0, port=0, bus_speed_hz=...)`를 호출했다.
- `/dev/spidev0.0`가 없는 환경에서는 OLED/LCD 초기화가 실패할 수 있었다.
- SSD1351 기본 SPI 속도는 `40000000` Hz였다.

<a id="mf_change_history_ko--변경-후-7"></a>
#### 변경 후

- `display_spi(bus_speed_hz)` 헬퍼를 추가했다.
- `/dev/spidev0.0`, `/dev/spidev10.0` 순서로 존재 여부를 확인하고 사용한다.
- 둘 다 발견되지 않으면 기존처럼 `port=0`, `device=0`으로 fallback한다.
- `DisplaySSD1351`의 기본 SPI 속도를 `32000000` Hz로 조정했다.
- `DisplaySSD1351` 생성자가 `bus_speed_hz` 인자를 받을 수 있게 했다.
- `DisplaySSD1333`, `DisplayST7789_128`, `DisplayST7789`도 같은 `display_spi()` 헬퍼를 사용하도록 정리했다.
- SPI 장치 파일 존재 확인을 위해 `pathlib.Path` import를 추가했다.

<a id="mf_change_history_ko--추가한-헬퍼"></a>
#### 추가한 헬퍼

```python
def display_spi(bus_speed_hz: int):
    for port, device in ((0, 0), (10, 0)):
        if Path(f"/dev/spidev{port}.{device}").exists():
            return spi(device=device, port=port, bus_speed_hz=bus_speed_hz)
    return spi(device=0, port=0, bus_speed_hz=bus_speed_hz)
```

<a id="mf_change_history_ko--ssd1351-변경"></a>
#### SSD1351 변경

기존:

```python
serial = spi(device=0, port=0, bus_speed_hz=40000000)
```

수정:

```python
def __init__(self, bus_speed_hz=32000000):
    serial = display_spi(bus_speed_hz=bus_speed_hz)
```

<a id="mf_change_history_ko--기대-효과-6"></a>
#### 기대 효과

- CM5에서 SPI 장치가 `/dev/spidev10.0`으로 잡혀도 디스플레이가 초기화된다.
- SSD1351 OLED가 40MHz에서 화면 깨짐이 발생하는 환경에서 32MHz를 기본 안정값으로 사용한다.
- 테스트 스크립트에서는 `DisplaySSD1351(bus_speed_hz=...)`로 SPI 속도를 바꿔 비교할 수 있다.

<a id="mf_change_history_ko--카메라-gain-초기화-동작"></a>
### 카메라 gain 초기화 동작

이 항목은 최종 소스 변경 사항이 아니라, 검토 후 원본 동작으로 되돌린 내용이다.
최종 작업트리 기준으로 `python/PiFinder/camera_pi.py`는 원본 소스와 동일하며
Git diff가 없다.

최종 유지한 동작:

- `CameraPI.__init__()`는 원본처럼 `exposure_time`만 받는다.
- 초기 gain은 설정 파일의 `camera_gain`이 아니라 카메라 프로파일의 `analog_gain`을 사용한다.
- IMX462 프로파일 기준 초기 gain은 `30.0`이다.
- `/home/pifinder/PiFinder_data/config.json`과 `default_config.json`에 `camera_gain: 20`이 있어도 Pi camera 최초 초기화에는 적용하지 않는다.
- `set_gain` 같은 런타임 명령은 사용할 수 있지만, 최초 시작 gain을 바꾸지는 않는다.
- `exp_save`에서 `camera_gain`을 저장하는 기존 흐름은 그대로 둔다.

원본과 같게 유지한 코드 형태:

```python
def __init__(self, exposure_time) -> None:
```

```python
self.gain = self.profile.analog_gain
```

```python
camera_hardware = CameraPI(exposure_time)
```

이 결정으로 PiFinder의 관측용 자동 노출은 원본처럼 프로파일 gain을 기준으로 시작한다.

<a id="mf_change_history_ko--pythonpifinderuifontspy"></a>
### `python/PiFinder/ui/fonts.py`

한국어 메뉴 표시를 위해 CJK glyph를 포함한 폰트를 한국어에서도 사용하도록 수정했다.

<a id="mf_change_history_ko--변경-전-7"></a>
#### 변경 전

- `language == "zh"`일 때만 `sarasa-mono-sc-light-nerd-font+patched.ttf`를 사용했다.
- 한국어 locale을 추가해도 기본 Roboto Mono 계열 폰트로는 한글이 표시되지 않을 수 있었다.

<a id="mf_change_history_ko--변경-후-8"></a>
#### 변경 후

- `lang in ["ko", "zh"]`일 때 Sarasa CJK 폰트를 사용한다.
- CJK 폰트 사용 시 기존 중국어 처리와 같이 Pillow layout engine을 끈다.
- 관련 주석은 영어로 유지했다.

<a id="mf_change_history_ko--기대-효과-7"></a>
#### 기대 효과

- `ko` 언어를 선택하면 OLED 메뉴에서 한글 glyph가 표시된다.
- 중국어 UI의 기존 폰트 처리도 그대로 유지된다.

<a id="mf_change_history_ko--pythonpifinderuimenu_structurepy"></a>
### `python/PiFinder/ui/menu_structure.py`

노출 설정 메뉴 바로 뒤에 카메라 gain 메뉴를 추가했고, GPS 설정 안에 GPS 포트 메뉴를 추가했다.
또한 `Settings > Advanced`에 키보드 설정 메뉴를 추가했고, 언어 메뉴에 한국어를 추가했다.

<a id="mf_change_history_ko--추가한-언어-메뉴"></a>
#### 추가한 언어 메뉴

```text
Settings > User Pref... > Language > 한국어
```

구현:

- gettext 추출용 marker에 `Language: ko`를 추가했다.
- Language 메뉴 항목에 `name: _("Korean")`, `value: "ko"`를 추가했다.
- 키보드 입력 방식은 변경하지 않았고, USB/Bluetooth 키보드의 알파벳 입력은 계속 영문 문자 입력으로 동작한다.

기대 효과:

- PiFinder 본체 메뉴에서 한국어 UI를 선택할 수 있다.
- 언어 선택 후 callback이 PiFinder를 재시작하면서 한국어용 CJK 폰트가 적용된다.

<a id="mf_change_history_ko--추가한-메뉴"></a>
#### 추가한 메뉴

```text
Camera Gain
```

위치:

- `Camera Exp` 메뉴 바로 다음
- `WiFi Mode` 메뉴 바로 이전

<a id="mf_change_history_ko--메뉴-방식"></a>
#### 메뉴 방식

- `Camera Exp`와 같은 `UITextMenu` 기반 single-select 메뉴다.
- `label`은 `camera_gain`으로 지정해 Focus 화면 marking menu에서 바로 이동할 수 있게 했다.
- `config_option`은 사용하지 않는다.
- 선택값은 저장 config가 아니라 `callbacks.get_camera_gain_selection`에서 읽은 runtime gain 기준으로 표시한다.
- 선택 후 `callbacks.set_gain`을 통해 카메라 프로세스에 명령을 보낸다.

<a id="mf_change_history_ko--선택-항목"></a>
#### 선택 항목

```text
Profile
1x
2x
4x
8x
12x
15x
16x
20x
22x
24x
30x
```

`Profile` 항목은 현재 카메라 프로파일 기본 gain으로 돌아가는 항목이다. IMX462에서는
`30x`가 표시된다.

<a id="mf_change_history_ko--추가한-gps-메뉴"></a>
#### 추가한 GPS 메뉴

```text
GPS Settings > GPS Port
```

선택 항목:

```text
ttyAMA1  -> /dev/ttyAMA1
ttyAMA2  -> /dev/ttyAMA2
serial0  -> /dev/serial0
ttyAMA0  -> /dev/ttyAMA0
ttyAMA10 -> /dev/ttyAMA10
ttyS0    -> /dev/ttyS0
ttyACM0  -> /dev/ttyACM0
ttyUSB0  -> /dev/ttyUSB0
```

`GPS Port`와 `GPS Baud Rate`는 같은 post callback을 사용해 `/etc/default/gpsd`를 갱신한다.

<a id="mf_change_history_ko--추가한-키보드-메뉴"></a>
#### 추가한 키보드 메뉴

```text
Settings > Advanced > Keyboard
```

구현:

- `UIBluetoothKeyboard` 클래스를 import했다.
- `label`은 `keyboard_settings`로 지정했다.
- 메뉴 진입 시 Bluetooth 장치 목록을 읽고, 장치별 action menu를 제공한다.

기대 효과:

- Advanced 설정 안에서 Bluetooth 키보드를 연결할 수 있다.
- USB 키보드는 연결만 하면 같은 `keyboard_pi` 입력 backend에서 바로 동작한다.

<a id="mf_change_history_ko--pythonlocalekolc_messagesmessagespo-messagesmo"></a>
### `python/locale/ko/LC_MESSAGES/messages.po`, `messages.mo`

한국어 UI를 위한 gettext catalog를 새로 추가했다.

<a id="mf_change_history_ko--생성-방식"></a>
#### 생성 방식

- 현재 Python 소스에서 Babel로 메시지를 추출했다.
- `messages.po`에는 한국어 번역을 기록했다.
- `messages.mo`는 `pybabel compile -d python/locale -l ko`로 컴파일했다.

<a id="mf_change_history_ko--번역-기준"></a>
#### 번역 기준

- 천문 분야에서 일반적으로 쓰는 용어를 우선 사용했다.
- `은하`, `산개성단`, `구상성단`, `성운`, `암흑성운`, `행성상성운`, `이중성`, `삼중성`, `시상`, `투명도`, `극축정렬`, `성도` 같은 용어는 한국어로 번역했다.
- `RA/DEC`, `DSO`, `SQM`, `Gain`, `Profile`, `T9`, `Multi-Tap`, 카탈로그명, 장치명, 포트명처럼 한국어로 바꾸면 어색하거나 식별성이 떨어지는 항목은 영문을 유지했다.
- 전체 추출 문자열 712개 중 핵심 PiFinder UI와 메뉴 중심으로 380개를 한국어로 번역했고, 나머지는 빈 문자열이 아니라 영어 원문을 표시하도록 두었다.

<a id="mf_change_history_ko--기대-효과-8"></a>
#### 기대 효과

- 한국어 메뉴 선택 시 주요 본체 UI가 한국어로 표시된다.
- 아직 번역하지 않은 문자열도 빈 화면이 되지 않고 원문 영어로 표시된다.

<a id="mf_change_history_ko--pythonpifinderuibluetooth_keyboardpy"></a>
### `python/PiFinder/ui/bluetooth_keyboard.py`

Bluetooth 키보드 페어링과 연결을 위한 새 UI 모듈이다.

<a id="mf_change_history_ko--네트워크-웹-ui-저장적용-분리--sta-우선순위수동접속-2026-08-07"></a>
#### 네트워크 웹 UI 저장/적용 분리 + STA 우선순위·수동접속 (2026-08-07)

STA 목록/AP 설정 편집이 즉시 적용되면서 수시 끊김·재접속 실패를 유발하던
것을 저장(파일 기록)과 적용(네트워크 재구성)으로 분리하고, STA 우선순위
편집과 SSID 수동 접속을 추가했다. 상세는 `mf_wifi_apsta_ko.md` 참조.

- `sys_utils.Network`: add/delete/밴드변경이 저장만 하고 `sta_dirty` 표시
  (기존엔 즉시 `nmcli con delete`+`wpa_cli reconfigure`로 끊김 유발).
  `apply_sta_changes()`(NM 동기화+reconfigure), `move_wifi_network()`
  (priority 재기록, 목록은 priority 내림차순 정렬·id 재부여),
  `connect_wifi_network()`(nmcli con up 즉시 전환) 신설. NM 동기화에
  `connection.autoconnect-priority` 반영, wpa 파서에 `priority` 추가.
- `server.py`: `/network/update`에 `apply` 플래그(0=저장만, 1=저장+모드
  전환+재시작), `/network/apply_sta`·`/network/move/<id>/<dir>`·
  `/network/connect/<id>` 라우트 신설.
- `network.html`/`network_item.html`: Save Settings/Apply & Restart 버튼
  분리, sta_dirty 시 주황 "Apply Now" 배너, 행별 ▲▼/Wi-Fi 접속 아이콘,
  삭제 문구를 "적용 시 반영"으로 수정. status_message 표시 블록 추가.
- 테스트: priority 파싱, move 재정렬·dirty, add/delete가 nmcli/wpa_cli를
  건드리지 않음(3종 추가, 50 passed). 신규 UI 문자열은 영문 상태(다음 i18n
  패스에서 번역 예정).

<a id="mf_change_history_ko--5ghz-대역-인지형-wifi-pause-2026-08-07"></a>
#### 5GHz 대역 인지형 WiFi pause (2026-08-07)

BT 페어링/재연결 시 WiFi를 무조건 끄던 것을 대역 인지형으로 개선.
Bluetooth는 2.4GHz 전용이므로, 활성 WiFi 링크가 전부 5GHz이거나(현 운용:
STA·uap0 모두 ch153/5765MHz — 단일 라디오라 AP가 STA를 따라감) 링크가
없으면 공존 간섭이 없어 pause를 건너뛴다.

- `sys_utils.bt_pairing_needs_wifi_pause()` 신설 — `iw dev <iface> info`의
  채널 주파수로 판정, 판정 불가 시 보수적으로 pause 유지.
- `pause_wifi_for_bt_pairing()`이 실제 pause 여부를 bool로 반환; 호출부
  (bluetooth_keyboard의 링크 컨텍스트·페어링)는 반환값으로 resume 여부 결정
  — 스킵 시 `nmcli connection up`/hostapd 재시작류 복구 부작용도 없음.
- 실장비 검증: 5GHz 상태에서 실제 호출 → 스킵(False)·journal 무흔적·WiFi
  유지. 단위테스트 5종(대역 조합·iw 실패 보수 동작 포함).
- 효과: 5GHz 망 운용 시 원격(SSH/웹) 세션이 BT 연결 작업 중에도 안 끊긴다.
  2.4GHz 링크가 하나라도 있으면 기존 pause 동작 그대로.

<a id="mf_change_history_ko--ui-하니스-sys_utils-mock-누락-수정-2026-08-07"></a>
#### UI 하니스 sys_utils mock 누락 수정 (2026-08-07)

실장비에서 `nox -s ui_tests`(전 화면 키 스위프)를 돌리면 Bluetooth 화면의
Reconnect가 **실물** `pause_wifi_for_bt_pairing()`을 실행해 WiFi가 60~90초
끊기는 사고가 실측됨(2026-08-07 08:15, SSH 세션 단절). 원인:
`test_ui_modules.py`의 `_inert_sys_utils` fixture가 모듈 3곳만 하드코딩
패치하는데, 화면들은 임포트 시점에 `sys_utils = utils.get_sys_utils()`로
실물을 바인딩하므로 이후 추가된 화면(bluetooth_keyboard, sqm, equipment)이
mock 밖에 있었다. 수정: `sys_utils` 모듈 속성을 가진 모든 로드된 PiFinder
모듈을 동적으로 찾아 일괄 패치 — 새 화면이 생겨도 자동 커버. 검증: 장비에서
전체 스위프 277 통과 + journal에 nmcli/WiFi 조작 무흔적. 참고: 장비에서
스위트를 돌릴 때는 `PIFINDER_USE_FAKE_SYS_UTILS=1` 안전망 병용 권장.

<a id="mf_change_history_ko--메뉴-항목"></a>
#### 메뉴 항목

```text
Scan / Pair
Reconnect
Refresh
<cached or scanned Bluetooth devices>
```

장치 표시 prefix:

```text
* connected device
+ paired device
- discovered/unpaired device
```

목록에서는 작은 OLED 폭을 고려해 장치명을 우선 표시하고 MAC 주소 suffix는 붙이지 않는다.
장치명이 없거나 장치명이 MAC 주소로만 들어오면 `Unknown 12:34`처럼 짧은 fallback을 표시한다.
MAC 주소는 장치를 선택한 뒤 action menu의 보조 줄에 `MAC ...12:34:56` 형태로 표시한다.

<a id="mf_change_history_ko--장치-action-menu"></a>
#### 장치 action menu

선택한 장치에 대해 다음 동작을 제공한다.

```text
Pair+Connect 또는 Pair Again
Connect
Disconnect
Remove
Cancel
```

<a id="mf_change_history_ko--페어링-처리"></a>
#### 페어링 처리

- `bluetoothctl`을 별도 process로 실행한다.
- `agent KeyboardDisplay`, `default-agent`, `pairable on`을 설정한 뒤 `pair <MAC>`을 실행한다.
- output을 non-blocking으로 읽어 OLED에 진행 상태를 표시한다.
- `Passkey: 123456` 형태의 출력이 나오면 `Type 123456`처럼 표시해 사용자가 Bluetooth 키보드에서 입력할 수 있게 한다.
- `Confirm passkey`, `Authorize service`, `Accept pairing` prompt가 나오면 `yes`를 보낸다.
- pairing이 성공하거나 이미 paired 상태이면 `trust <MAC>`, `connect <MAC>`를 이어서 보낸다.
- 왼쪽 키를 누르면 pairing process를 종료하고 목록으로 돌아간다.

기대 효과:

- 원격 접속 없이 PiFinder 화면과 키패드만으로 Bluetooth 키보드 연결을 시도할 수 있다.
- Bluetooth 연결 뒤에는 해당 키보드가 `/dev/input/event*`로 나타나며 `keyboard_pi.py`의 libinput 매핑을 통해 PiFinder 입력으로 동작한다.

<a id="mf_change_history_ko--pythonpifindermountcontrol_indipy-indi-마운트-제어"></a>
### `python/PiFinder/mountcontrol_indi.py`, INDI 마운트 제어

INDI 마운트 제어는 선택 기능이다. 기본 PiFinder 설치만으로는 기존 기능이 동작하고,
`scripts/install_indi_mount.sh`를 실행해 INDI 의존성을 추가 설치한 사용자가
`mount_control`을 켰을 때만 별도 process가 시작된다.

<a id="mf_change_history_ko--주요-설정"></a>
#### 주요 설정

```json
"mount_control": false,
"mount_control_indi_host": "localhost",
"mount_control_indi_port": 7624
```

<a id="mf_change_history_ko--동작-방식"></a>
#### 동작 방식

- `main.py`가 `mount_control` 설정을 확인한 뒤 `mountcontrol_indi.run()` process를 시작한다.
- INDI 서버 접속 실패, PyIndi 미설치, 마운트 미검출 상태는 상태 파일과 console 메시지로 기록하고 PiFinder 본 기능은 계속 실행한다.
- `mount_control_status.json`에 compact 상태를 기록해 로그/디버그/웹 확인에 사용할 수 있게 했다.
- object details 화면에서 현재 대상에 대한 sync/goto/stop/manual step 명령을 mount queue로 보낸다.
- 종료 시 mount-control process에 shutdown command를 보내고, 응답하지 않으면 terminate한다.

<a id="mf_change_history_ko--웹-indi-메뉴와-lx200-onstep-제어"></a>
#### 웹 INDI 메뉴와 LX200 OnStep 제어

`python/views/indi_mount.html`을 추가하고 `python/PiFinder/server.py`에 `/indi`
라우트를 추가해 INDI를 `Equipment`와 `Tools` 사이의 독립 웹 메뉴로 분리했다.

- `INDI Web Manager` 버튼은 현재 PiFinder host의 `:8624`로 연결한다.
- `Current INDI Driver State`는 LX200 OnStep의 연결 방식, serial/network 설정,
  위치, UTC 시간, Park 상태, Slew Rate 상태를 `indi_getprop`으로 읽어 표시한다.
- `LX200 OnStep Driver Connection`은 USB Serial과 Network TCP를 선택할 수 있다.
  USB는 `/dev/serial/by-id`, `/dev/ttyUSB*`, `/dev/ttyACM*` 후보를 표시하고,
  네트워크는 AP 접속 장치 목록에서 IP를 선택하거나 수동 입력할 수 있다.
- `Location and Time`은 GPS lock이 있으면 GPS/loaded location을, 없으면
  PiFinder 기본 location을 사용한다. `Reload Current Values`로 PiFinder와 OnStep
  현재값을 다시 읽을 수 있고, 화면의 UTC 입력값은 초 단위로 계속 갱신된다.
- `Send Location and Time`은 browser가 보낸 시간을 그대로 쓰지 않고,
  Flask route가 POST를 받은 시점의 PiFinder system UTC를 다시 계산해 OnStep에
  전송한다.
- `Mount Control`에는 `At Home`을 `Parked`로 혼동하지 않도록 Home 상태,
  Park 상태, 원시 `:GU#` 마운트 상태를 분리 표시하고, At Home, Return Home,
  Park, Unpark, Set-Park 명령, OnStep 0-9 Slew Rate 선택, press-and-hold 방향
  이동을 추가했다.
- OnStepX `Settings` 영역에는 driver의 `Backlash.Backlash RA`,
  `Backlash.Backlash DEC` 속성을 사용하는 수동 Backlash 읽기/쓰기 제어를
  추가했다. 수동 저장은 마운트 이동 없이 설정값만 쓴다. Alt/Az 모드에서는
  같은 driver property를 `AZ`/`ALT`로, EQ 모드에서는 `RA`/`DEC`로 표시한다.
- 실제 백래시 테스트 중 tracking이 측정값에 섞일 수 있음을 확인했다. 자동
  Backlash는 시작 전 tracking을 끄고 정상 완료 후에만 원래 tracking 상태를
  복구하도록 보강했다.
- Auto Backlash는 호환성을 위해 내부 이름 `compass_goto_loop`를 유지하지만,
  현재 측정 이동은 다시 INDI GoTo를 사용한다. PiFinder는 테스트 시작 전과
  각 GoTo leg 이후 tracking을 다시 끄므로, OnStep이 GoTo 뒤 자동으로 tracking을
  켜더라도 측정 좌표 delta에 섞이지 않도록 한다. Alt/Az에서는 `AZ`와 `ALT`,
  EQ에서는 `RA`와 `DEC`를 한 축씩 분리 측정한다.
- GoTo 완료 처리는 stable idle window와, OnStep status를 읽을 수 있는 경우
  `:GU#`의 `N`(`No goto`) 상태를 기다린 뒤 Backlash mount/solved 샘플을
  기록하도록 보강했다. OnStepX가 근처 목표점에서 settle wait 후 최종 미세
  접근을 다시 수행하는 동안 측정하는 문제를 막기 위한 처리다.
- Auto Backlash는 더 이상 IMU Compass/NDOF 모드나 MAG calibration을 요구하지
  않는다. 대신 fresh plate-solved `PointingCoordinateService.solved` 좌표를
  요구하고, GoTo loop 전에 solved RA/Dec로 mount 좌표를 sync한다. 각 GoTo
  leg의 mount 시작/종료 좌표와 PiFinder solved 시작/종료 좌표를 기록하고,
  mount-solved 이동 차이가 1도 이상인 leg를 제외한 뒤 하위/상위 30%를 버리고
  가운데 40% 평균을 이동 방향별 추천값으로 표시한다.
- Auto Backlash는 더 이상 Backlash를 0으로 초기화하지 않고, 계산값을 자동
  적용하지 않으며, 주기적 UI 갱신 중 입력칸을 바꾸지 않는다. 사용자가 추천값을
  확인한 뒤 `Save Backlash`로 저장한다.
- 2026-07-03 실제 RA/DE GoTo 왕복 테스트에서는 두 축 모두 20도 왕복에서도
  당시 PiFinder/INDI write 제한이던 `999 arc-sec` 상한에 도달했다. 이후
  OnStep 펌웨어와 INDI property 표시 범위에 맞춰 PiFinder, Web UI, OnStepX
  driver write 제한을 모두 `3600 arc-sec`으로 통일했다. 상한 도달 시 자동
  계산값은 바로 적용하지 않고 낮은 신뢰도로 표시한다.
- OnStepX driver patch는 이제 OnStepX 장치의 `GUIDE_RATE`를 writable로 만들고,
  요청값을 OnStep rate selector로 변환한 뒤 실제 pulse-guide rate를 다시
  읽어 검증한다. Auto Backlash는 더 이상 `GUIDE_RATE`에 의존하지 않지만,
  writable/readback 동작은 OnStepX driver 호환성 패치로 유지한다. 소스 설치
  스크립트는 이 패치를 적용하며, 바이너리 아카이브도 패치된 OnStepX driver로
  다시 생성했다.
- INDI 바이너리 아카이브는 이제 git에 `.tar.gz.part-*` 조각 파일로 저장할 수
  있다. 아카이브 설치 스크립트는 조각을 다시 합친 뒤 `.sha256` checksum을
  검증하고, 패키지 생성 스크립트는 큰 아카이브의 조각 파일을 자동 생성한다.
- 방향 이동은 버튼을 누르고 있는 동안 motion 명령을 보내고, pointer up/cancel/leave
  시 stop 명령을 보내도록 AJAX로 처리한다.
- Red Night theme에서도 select/dropdown/table이 흰색으로 뜨지 않도록 CSS를
  보정했고, Materialize select input의 글자 잘림을 줄이기 위해 높이와 label
  위치를 조정했다.

<a id="mf_change_history_ko--문서설치-파일"></a>
#### 문서/설치 파일

```text
docs/mf_dev/mf_indi_mount_install_ko.md
docs/mf_dev/mf_indi_mount_install_en.md
scripts/install_indi_mount.sh
docs/mf_dev/mf_keyboard_mapping_ko.md
docs/mf_dev/mf_keyboard_mapping_en.md
```

<a id="mf_change_history_ko--pythonpifindergps_time_syncpy-통합-시간-동기화"></a>
### `python/PiFinder/gps_time_sync.py`, 통합 시간 동기화

GPS, Chrony, PiFinder SNTP, RTC, software PPS를 하나의 Time Sync 기능으로 관리하도록 추가했다.
기본값은 전체 `Off`이며, 사용자가 UI에서 켰을 때 기본 system clock 관리는 `chronyd`가 담당한다.

<a id="mf_change_history_ko--주요-설정-1"></a>
#### 주요 설정

```json
"time_sync_enabled": false,
"time_sync_source_mode": "chrony",
"time_sync_clock_manager": "chrony",
"chrony_time_sync": true,
"gps_time_sync": true,
"ntp_time_sync": false,
"ntp_server": "pool.ntp.org",
"software_pps": false,
"rtc_sync": false
```

<a id="mf_change_history_ko--동작-방식-1"></a>
#### 동작 방식

- 기본 `chrony` 모드에서는 `chronyc tracking` 상태를 읽고, Linux system clock은 chronyd가 관리한다.
- `best` 모드에서는 Chrony, GPS, PiFinder SNTP 후보를 비교한다.
- PiFinder 자체 SNTP는 chronyd와 중복되지 않도록 기본 `Off`이며 fallback/check 용도로 사용할 수 있다.
- PiFinder 본체는 일반 권한으로 실행하고, RTC 쓰기와 명시적 `Clock Manager = PiFinder` fallback system clock 쓰기는 `gps_time_sync_helper.py` root helper service가 처리한다.
- helper는 dry-run 모드와 실제 적용 모드를 분리하며, 기본 chrony 구성에서는 system clock을 직접 쓰지 않는다.
- 상태 UI는 `Tools > Place & Time > Time Sync`에서 확인한다.
- 설정 UI는 `Settings > Advanced > Time Sync`에 추가했다.

<a id="mf_change_history_ko--문서설치-파일-1"></a>
#### 문서/설치 파일

```text
docs/mf_dev/mf_time_sync_ko.md
docs/mf_dev/mf_time_sync_en.md
pi_config_files/pifinder_gps_time_sync.service
scripts/install_chrony_time_sync.sh
scripts/install_gps_time_sync_helper.sh
```

<a id="mf_change_history_ko--wi-fi-apsta-동시-모드"></a>
### Wi-Fi AP+STA 동시 모드

기존 `Client` 또는 `AP` 단일 선택 구조에 `AP+STA` 모드를 추가했다.
이 모드는 `wlan0`을 STA로 유지해 인터넷/업데이트에 사용하고, `uap0` 가상 AP
인터페이스로 스마트폰/태블릿 제어용 PiFinder AP를 동시에 제공한다.

<a id="mf_change_history_ko--주요-동작"></a>
#### 주요 동작

- 웹 `Tools > Network`와 기기 `Settings > WiFi Mode`에 `AP+STA` 선택지를 추가했다.
- `switch-apsta.sh`는 `/etc/dhcpcd.conf.apsta`를 적용하고 `pifinder_apsta_prepare`,
  `pifinder_apsta_monitor`, `dnsmasq`, `hostapd`를 활성화한다.
- `scripts/pifinder_apsta.sh prepare`는 `uap0`를 만들고 `10.10.10.1/24`를 설정한다.
- `scripts/pifinder_apsta.sh monitor`는 STA 채널을 감시하고 채널이 바뀌면
  `hostapd.conf`의 `channel`/`hw_mode`를 갱신한 뒤 `hostapd`를 재시작한다.
- `switch-ap.sh`와 `switch-cli.sh`는 AP+STA monitor service를 중지하고 `uap0`를 정리한다.
- Pi 4와 Pi 5 모두 기본 `wlan0` 위에 `uap0`를 추가하는 동일 구조를 사용한다.

<a id="mf_change_history_ko--문서설치-파일-2"></a>
#### 문서/설치 파일

```text
docs/mf_dev/mf_wifi_apsta_ko.md
docs/mf_dev/mf_wifi_apsta_en.md
pi_config_files/dhcpcd.conf.apsta
pi_config_files/pifinder_apsta_prepare.service
pi_config_files/pifinder_apsta_monitor.service
scripts/pifinder_apsta.sh
switch-apsta.sh
```

<a id="mf_change_history_ko--locations-위치-카탈로그"></a>
### Locations 위치 카탈로그

웹 `Locations > Add New Location`에 국가/지역/군구/도시 선택 기반 좌표 입력 기능을
추가했다.

<a id="mf_change_history_ko--주요-파일"></a>
#### 주요 파일

```text
python/PiFinder/data/location_catalog.json
python/PiFinder/location_catalog.py
python/views/location_form.html
python/views/locations.html
scripts/build_location_catalog.py
docs/mf_dev/mf_location_catalog_ko.md
docs/mf_dev/mf_location_catalog_en.md
python/tests/test_location_catalog.py
```

<a id="mf_change_history_ko--동작"></a>
#### 동작

- GeoNames `cities5000`, `countryInfo`, `admin1CodesASCII`, `admin2Codes`를
  가공해 오프라인 JSON 카탈로그를 만들었다.
- 한국은 GeoNames 국가별 전체 덤프 `KR.zip`을 추가로 섞어 서울/구/동 단위 선택을
  더 자세하게 제공한다.
- 북한은 국가 코드 `KP`를 생성 단계에서 제외했다.
- 서버는 전체 JSON을 브라우저에 직접 보내지 않고, 국가/지역/군구/장소 단계별
  API를 제공한다.
- 장소를 선택하면 기존 위치 추가 form의 이름, 위도, 경도, 고도, 오차, 출처
  필드를 기본값으로 채운다.
- 수동 좌표 입력과 DMS 입력은 그대로 유지한다.
- `scripts/build_location_catalog.py`로 catalog를 다시 생성할 수 있다.

<a id="mf_change_history_ko--web-ui-적색-야간-테마-및-pwa-앱-모드"></a>
### Web UI 적색 야간 테마 및 PWA 앱 모드

관측 중 웹 UI가 암시야를 덜 해치도록 적색 야간 테마를 추가했고, 모바일/태블릿에서
홈 화면에 추가해 앱처럼 열 수 있도록 PWA 구성을 추가했다.

<a id="mf_change_history_ko--주요-파일-1"></a>
#### 주요 파일

```text
python/PiFinder/server.py
python/views/base.html
python/views/css/style.css
python/views/js/init.js
python/views/manifest.webmanifest
python/views/service-worker.js
python/views/images/pwa-icon-192.png
python/views/images/pwa-icon-512.png
python/tests/test_web_theme_static.py
```

<a id="mf_change_history_ko--동작-방식-2"></a>
#### 동작 방식

- `Gray`와 `Red Night` 테마를 선택할 수 있다.
- 선택값은 브라우저 `localStorage`에 저장되므로 장치별로 유지된다.
- 상단 메뉴와 모바일 메뉴에 `Fullscreen` 버튼을 추가해 사용자가 직접 전체화면 모드에 진입할 수 있다.
- Fullscreen API는 페이지 이동 시 해제될 수 있으므로, 전체화면 상태에서 내부 메뉴로 이동하면 다음 페이지에 `Resume Fullscreen` 복구 버튼을 표시한다.
- 로그 페이지의 로그 본문 색상은 기존 level 색상 그대로 유지한다.
- manifest는 `display: fullscreen`을 사용하되, PiFinder 웹 UI 내부의 nav/footer는 유지한다.
- service worker는 캐싱 없이 네트워크 요청을 통과시키는 최소 형태로 두어 실시간 UI 동작에 영향을 주지 않는다.
- (2026-07-25) Materialize의 밝은 기본 위젯 스타일을 **두 테마 공통**으로 바꿨다.
  기존에는 `html[data-theme="red"]` 아래에만 덮어써서, Gray 테마에서
  `select.browser-default`가 흰 상자(`rgba(255,255,255,0.9)`)에 밝은 글자로 나와
  읽을 수 없었다(LiveCam/Logs). 같은 원인으로 Gray 테마에서 select caret(검정),
  dropdown 패널(`#fff`), modal(`#fafafa`), sidenav도 밝은 기본값이었다. 규칙이 모두
  테마 변수 기반이라 `html[data-theme="red"]` 접두사만 떼어 공통 규칙으로 승격했고,
  browser-default select에는 catalogs.css(`.pfcat`)에서 검증된 방식(커스텀 화살표 +
  `color-scheme: dark`)을 전 페이지로 확장했다. Materialize가 비활성 입력을
  `rgba(0,0,0,0.42)`(어두운 배경에서 안 보임)로 칠하는 것도 함께 수정했다.
- (2026-07-25) 같은 원인으로 남아 있던 두 가지를 추가로 고쳤다(INDI 페이지에서 발견).
  ① `table.striped` 홀수 행이 `rgba(242,242,242,0.5)` — 어두운 카드 위에서 밝은 띠가
  되어 `.grey-text` 본문이 밝은 회색 위 회색(1.2:1)이었다. 행 배경을 테마 변수로
  바꾸고, striped 테이블 안의 `.grey-text`는 적색 테마와 동일하게 `--pf-text`로
  승격했다(4.7~5.7:1). ② 체크박스 빈 상자가 `2px solid #5a5a5a` — Gray 테마 카드
  대비 1.1:1로 사실상 안 보였다(INDI GoTo/Guide 옵션들). 외곽선을 `--pf-text`
  (Gray 4.7:1 / Red 5.2:1), 체크 표시를 `--pf-link`로 바꾸고 체크박스 캡션도
  Materialize의 `#9e9e9e` label 색 대신 본문 색을 쓰게 했다. 단, 외곽선 색은
  **`:not(:checked)`로 한정해야 한다** — Materialize는 체크 표시를 같은 `::before`를
  40도 회전시키고 위/왼쪽 테두리를 `transparent`로 두어 만들기 때문에, 네 변을 모두
  칠하면 체크가 기울어진 사각형으로 보인다(실제로 한 번 발생시켰고 회귀 테스트
  `test_checkbox_outline_colour_never_reaches_the_checked_state`로 고정했다).
  `base.html`의 `style.css?v=` 캐시 버스터를 7로 올렸다.

<a id="mf_change_history_ko--default_configjson"></a>
### `default_config.json`

GPS 포트 설정 기본값을 추가했다.

```json
"gps_port": "auto"
```

기본값 `auto`는 보드 모델에 따라 CM5/Pi5는 `/dev/ttyAMA2`, Pi4는 `/dev/ttyAMA3`,
그 외 보드는 `/dev/ttyAMA1`로 해석된다.

<a id="mf_change_history_ko--pythonpifinderuipreviewpy"></a>
### `python/PiFinder/ui/preview.py`

포커스 화면에서 밝은 장면이나 포화에 가까운 장면이 검정 또는 단색처럼 보이는 문제를 해결했다.
또한 Focus 화면 marking menu에서 gain 메뉴로 바로 이동할 수 있게 했다.

<a id="mf_change_history_ko--문제-원인"></a>
#### 문제 원인

기존 포커스 화면은 어두운 밤하늘에서 별을 보기 좋게 하기 위해 detector가 계산한 배경값을 검정에 맞추는 stretch를 사용했다. 이 방식은 밤하늘에는 적합하지만, 밝은 장면에서는 배경 자체가 매우 높아서 전체 화면이 검정으로 눌리거나 8-bit 처리 프레임이 포화되어 디테일이 사라질 수 있다.

카메라 raw 프레임은 정상적으로 들어오고 있었으므로, 카메라 노출/게인을 바꾸는 대신 포커스 화면의 표시 경로만 보완했다.

<a id="mf_change_history_ko--추가한-상수"></a>
#### 추가한 상수

```python
STRETCH_BRIGHT_BACKGROUND = 220.0
```

의미:

- focus detector가 계산한 배경값이 이 값 이상이면 밝은/포화 프레임으로 판단한다.
- 이 경우 기존 dark-sky stretch를 적용하지 않는다.

<a id="mf_change_history_ko--_apply_stretch-변경"></a>
#### `_apply_stretch()` 변경

밝은 배경이면 기존 stretch를 건너뛴다.

```python
if black >= STRETCH_BRIGHT_BACKGROUND:
    return image_obj
```

이 변경은 display-only 처리이며, focus 측정이나 카메라 설정을 변경하지 않는다.

<a id="mf_change_history_ko--_orient_camera_image-추가"></a>
#### `_orient_camera_image()` 추가

raw 기반 표시 이미지에도 기존 camera image와 같은 회전 규칙을 적용하기 위해 추가했다.

동작:

- `camera_rotation` 설정이 있으면 그 값을 우선 사용한다.
- 없으면 `screen_direction`에 따라 기존 camera loop와 같은 방향으로 회전한다.

<a id="mf_change_history_ko--_raw_display_image-추가"></a>
#### `_raw_display_image()` 추가

밝은 장면에서 포커스 화면 배경으로 사용할 raw 기반 표시 이미지를 생성한다.

처리 순서:

1. `self.shared_state.cam_raw()`에서 최신 raw 배열을 가져온다.
2. 2차원 raw 배열이 아니면 fallback하지 않는다.
3. `float32`로 변환한다.
4. 배열 크기를 짝수 크기로 맞춘다.
5. nominal Bayer 2x2 블록을 평균한다.
6. 1.0 percentile과 99.5 percentile 기준으로 표시용 8-bit stretch를 만든다.
7. 두 percentile 값의 차이가 1 ADU 이하이면 포화되었거나 거의 평평한 밝은 raw로 보고 흰색 프레임으로 표시한다.
8. `_orient_camera_image()`로 화면 방향을 맞춘다.

2x2 평균을 넣은 이유:

- IMX462가 드라이버에서는 `SRGGB12` 계열로 보고되지만 실제 하드웨어가 모노 센서처럼 동작할 수 있다.
- 2x2 nominal Bayer 블록을 평균하면 모노 센서에서 보이는 checker pattern이 줄어든다.
- 표시용 처리일 뿐, solver나 focus 측정용 raw 데이터를 바꾸지 않는다.

평평한 밝은 raw를 별도로 처리한 이유:

- 밝은 환경에서 raw가 거의 포화되면 1.0 percentile과 99.5 percentile이 같은 값이 될 수 있다.
- 이때 기존처럼 `high = low + 1`로 stretch하면 `(arr - low)`가 0이 되어 전체 화면이 검정으로 매핑된다.
- 포커스 화면의 raw fallback은 이미 밝은 배경으로 분류된 경우에만 사용하므로, percentile span이 없는 프레임은 검정이 아니라 밝은 프레임으로 표시한다.

<a id="mf_change_history_ko--update-표시-경로-변경"></a>
#### `update()` 표시 경로 변경

기존 흐름:

```text
camera_image copy -> resize_for_display -> _apply_stretch -> red mask -> screen
```

수정 후 밝은 배경일 때:

```text
shared_state.cam_raw -> 2x2 average -> percentile stretch -> orientation
-> resize_for_display -> red mask -> screen
```

수정 후 어두운 관측 프레임일 때:

```text
기존 camera_image 기반 focus stretch 경로 유지
```

실제 분기 조건:

- `display_image = raw_image`, `stretch_display = True`로 시작한다.
- `_stretch_black >= STRETCH_BRIGHT_BACKGROUND`이면 `_raw_display_image()`를 시도한다.
- raw fallback 이미지 생성에 성공하면 `display_image`를 raw 기반 이미지로 바꾸고 `stretch_display = False`로 설정한다.
- raw fallback을 만들 수 없으면 기존 이미지를 사용하되, `_apply_stretch()`의 밝은 배경 bypass 때문에 dark-sky stretch는 적용하지 않는다.
- 이후 공통으로 display 크기 resize, `L` 변환, red mask 적용 흐름을 통과한다.

<a id="mf_change_history_ko--기대-효과-9"></a>
#### 기대 효과

- 포커스 화면에서 밝은 장면도 검정으로 눌리지 않는다.
- 8-bit 처리 프레임이 이미 포화되어도 raw 기반 표시 fallback으로 디테일을 볼 수 있다.
- 노출과 gain은 그대로 유지된다.
- 관측용 어두운 장면에서는 기존 포커스 화면 동작을 유지한다.
- Focus 화면에서 기존 `Exposure` shortcut처럼 `Gain` shortcut으로 `Camera Gain` 메뉴에 진입할 수 있다.

<a id="mf_change_history_ko--scriptscamera_lcd_previewpy"></a>
### `scripts/camera_lcd_preview.py`

PiFinder 본 서비스와 분리해서 카메라 raw 입력과 SSD1351 OLED 표시를 확인하기 위한 테스트 도구를 추가했다.

<a id="mf_change_history_ko--스크립트-성격"></a>
#### 스크립트 성격

- PiFinder 런타임의 핵심 코드가 아니라 하드웨어 진단용 스크립트다.
- 카메라와 OLED를 직접 점유하므로 PiFinder 서비스와 동시에 실행하면 안 된다.
- 이후 LCD, SPI, 카메라 raw 입력을 빠르게 재검증할 수 있도록 저장했다.

<a id="mf_change_history_ko--주요-기능"></a>
#### 주요 기능

- `Picamera2`를 직접 열어 raw stream을 캡처한다.
- `PiFinder.sqm.camera_profiles`의 camera profile을 사용해 crop/rotate를 적용한다.
- nominal Bayer 2x2 블록을 평균해 모노 표시 이미지를 만든다.
- percentile stretch로 LCD 표시용 8-bit 프레임을 만든다.
- temporal smoothing으로 표시용 노이즈를 줄일 수 있다.
- SSD1351 SPI 속도를 `--spi-hz`로 지정할 수 있다.
- 자동 노출은 `--auto-exposure`로 켤 수 있다.
- 마지막 표시 프레임을 `/tmp/camera_lcd_preview_latest.png`에 저장한다.

<a id="mf_change_history_ko--구현-세부"></a>
#### 구현 세부

- 스크립트를 저장소 루트 밖에서 실행해도 `PiFinder` 패키지를 import할 수 있도록 `REPO_ROOT/python`을 `sys.path`에 추가한다.
- `--display ssd1351`일 때만 `DisplaySSD1351(bus_speed_hz=args.spi_hz)`를 직접 호출해 SPI 속도 테스트가 가능하게 했다.
- 카메라 설정은 `create_still_configuration({"size": (512, 512)}, raw={"size": profile.raw_size, "format": profile.format})`를 사용한다.
- 자동 노출을 켜면 `AeEnable=True`만 설정하고, 자동 노출을 끄면 `AnalogueGain`과 `ExposureTime`을 수동값으로 설정한다.
- raw 캡처는 `request.make_array("raw").copy().view(np.uint16)`로 가져오고, 노출/gain overlay에는 request metadata를 사용한다.
- `SIGINT`, `SIGTERM`을 처리해 카메라를 정리하고 종료한다.
- `--duration`이 0보다 크면 지정 시간 뒤 종료하고, 0이면 사용자가 중지할 때까지 계속 실행한다.
- snapshot 경로의 parent directory를 만들고, 최신 표시 프레임을 약 1초 간격으로 저장한다.

<a id="mf_change_history_ko--주요-옵션"></a>
#### 주요 옵션

```text
--display          기본값 ssd1351
--spi-hz           기본값 32000000
--auto-exposure    libcamera native AE 사용
--exposure-us      수동 노출 시간, 기본값 100
--gain             수동 analogue gain, 기본값 1.0
--fps              표시 갱신 제한, 기본값 2
--brightness       디스플레이 밝기
--denoise          표시용 temporal smoothing, 기본값 0.70
--min-contrast     표시 stretch 최소 contrast window, 기본값 256.0
--snapshot         최신 표시 프레임 저장 경로
--duration         지정 시간 후 종료, 기본값 0.0
--red              빨간 night-vision 표시
--no-overlay       FPS/노출/gain 오버레이 숨김
```

<a id="mf_change_history_ko--최종-권장-실행값"></a>
#### 최종 권장 실행값

```bash
sudo systemctl stop pifinder
cd /home/pifinder/PiFinder
python3 scripts/camera_lcd_preview.py \
  --display ssd1351 \
  --spi-hz 32000000 \
  --auto-exposure \
  --fps 4 \
  --brightness 255 \
  --denoise 0.82 \
  --min-contrast 512 \
  --snapshot /tmp/camera_lcd_preview_latest.png
```

<a id="mf_change_history_ko--pifinder-복귀"></a>
#### PiFinder 복귀

```bash
sudo systemctl start pifinder
```

<a id="mf_change_history_ko--기대-효과-10"></a>
#### 기대 효과

- PiFinder UI나 solver를 거치지 않고 LCD와 카메라를 직접 확인할 수 있다.
- OLED SPI 속도 문제와 카메라 입력 문제를 분리해서 볼 수 있다.
- 이번 작업에서 결정한 SSD1351 `32MHz` 값을 이후에도 쉽게 재확인할 수 있다.

<a id="mf_change_history_ko--자동-노출--검출-별-수-컨트롤러-옵션-2026-07-25"></a>
### 자동 노출 — 검출 별 수 컨트롤러 옵션 (2026-07-25)

기존 매치 수 기반 자동 노출의 구조적 문제(원인 미구분, 카탈로그 의존,
밝은 하늘 가드 부재 — [mf_auto_exposure_methods_ko.md](camera.md#mf_auto_exposure_methods_ko))
대응으로, cedar-server 방식의 검출 별 수 서보를 **옵트인 옵션**으로 추가했다.
기존 컨트롤러/복구/기본값은 무수정 유지. 설계:
[mf_auto_exposure_plan_ko.md](camera.md#mf_auto_exposure_plan_ko), 결정:
[ADR m0020](../../adr/m0020-star-count-controller-opt-in.md).

- 신규 `python/PiFinder/auto_exposure_starcount.py`:
  `ExposureStarCountController` (목표 검출 20, EMA α=0.5, 데드밴드 0.8~1.6,
  나눗셈 스텝, 앵커 ±3스톱 클램프, 중앙 ROI 평균>240 가드, <4개 앵커 폴백,
  검출 0 → 기존 사다리 재사용).
- `types/positioning.py`: `SolveDiagnostics.Centroids` 추가(모든 시도 게시).
- `solver.py`: 성공/실패 빌더에 `centroid_count` 배선(예외 경로는 0).
- `camera_interface.py`·`camera_pi.py`: `camera_exp`의 새 값
  `"auto_star"` 처리 — `set_exp:auto_star`로 star_count 컨트롤러 선택,
  디스패치 분기(lazy 생성). 별도 config 키 없음.
- `ui/menu_structure.py`·`ui/callbacks.py`: Camera Exp 메뉴에
  "Star" 항목 추가(라이브 노출 서픽스 포함) — 포커스 화면 마킹
  메뉴(롱키 → Exposure)에서 그대로 접근·전환 가능.
- i18n: de/es/fr/ko/zh "Star" 번역(AI-TRANSLATED 마커), .mo 재컴파일.
- 테스트: `tests/test_auto_exposure_starcount.py` 21종 + 기존 754 unit 통과.

<a id="mf_change_history_ko--bt-페어링-중-wifi-미복구-수정-2026-07-26"></a>
### BT 페어링 중 WiFi 미복구 수정 (2026-07-26)

실장비 사고: 조이스틱(VR-PARK) 페어링 중 화면이 멈추고 SSH/웹이 죽은 채
복구되지 않아 재부팅. 페어링 자체는 성공해 있었다. WiFi 정지는 BLE 공존
문제 때문에 의도된 동작이지만(35초 상한 + 60초 워치독), 복구가 안 됐다.

원인 분석(이전 부팅 저널은 휘발되어 코드 검증으로 확정):

- 이 장비는 RTC가 없어(`timedatectl` RTC n/a) 부팅 후 GPS/NTP가 시계를
  맞출 때 `time.time()`이 점프한다. 페어링 화면의 모든 타임아웃
  (`pair_started` 기준 35초 WiFi 복구·90초 페어 타임아웃·완료 후 정리)이
  벽시계 기준이라, 뒤로 점프하면 전부 얼어붙는다 — 멈춘 화면과 WiFi 미복구
  증상 그대로. 60초 워치독(`sleep`은 단조 시계)이 남지만 재시도로 pause가
  반복되면 창이 계속 밀린다.
- 35초 복구는 페어링 화면의 update 루프 안에서만 검사되어, 화면이 갱신을
  멈추면(다른 화면 이동 등) 워치독 하나에만 의존하게 된다.

수정:

- `ui/bluetooth_keyboard.py`: 페어링 타이밍 전부 `time.monotonic()`으로 전환.
- `sys_utils.py`: `pause_wifi_for_bt_pairing()`이 프로세스 내
  `threading.Timer`(35초, `BT_PAIRING_WIFI_APP_RESUME_SECONDS`)로 복구를
  예약 — UI 루프 생존 여부와 무관하게 동작하고, resume은 멱등이라 정상
  경로 복구 후 발화해도 무해. 기존 60초 분리 프로세스 워치독은 유지(최후
  안전망).

참고: 페어링을 웹 원격(/remote)에서 시작하면 WiFi 정지로 조작 화면 자체가
끊긴다 — 공존 제약상 불가피하며, 페어링은 LCD에서 하는 것을 권장.

<a id="mf_change_history_ko--조이스틱-버튼-매핑-2026-07-26"></a>
### 조이스틱 버튼 매핑 (2026-07-26)

블루투스로 페어링한 조이스틱/게임패드의 버튼을 PiFinder 기능에 매핑하는 기능.
libinput(`keyboard_pi.py`)은 조이스틱 클래스 장치를 무시하므로, 연결은 되어도
버튼 입력이 UI에 전달되지 않던 간극을 메운다.

- 신규 `python/PiFinder/joystick_input.py`: evdev 기반 리더 스레드(main 프로세스
  데몬). 3초마다 장치 재검색(BT 연결로 늦게 생기는 event 노드 대응), EV_KEY
  버튼과 ABS_HAT0X/Y 햇 축(십자키를 축으로 보내는 패드용, `HAT0X-` 형식 의사
  버튼) 처리. 순수 매핑/디스패치 로직은 `JoystickDispatcher`로 분리(테스트
  가능). 매핑은 config `joystick_mapping`({action: button_id})에 저장.
- 액션 두 계열(의도적 구분):
  - **키패드 계열** — 키보드 큐에 일반 키코드 주입: 상하좌우 화살표,
    GoTo(키패드 5와 동일 — Object Details에서 GoTo 시작, 다른 화면에서는
    키패드 5의 원래 의미 유지).
  - **마운트 계열** — 화면과 무관하게 mountcontrol 큐 직행: 수동 이동
    상/하/좌/우(north/south/west/east, LCD 가이드 화면과 동일한
    lease 1.2s + keepalive 0.4s 방식이라 리더가 죽어도 마운트가 스스로 정지),
    슬루 속도 +/-, 트래킹 Off(`set_tracking` 명령 신설 — 기존에 호출자 없던
    readback 확인형 `set_tracking()` 메서드를 큐에 배선). `mount_control`
    꺼져 있으면 마운트 계열은 무시.
- 신규 `python/PiFinder/ui/joystick.py`: Settings > Advanced > Joystick(조이스틱)
  메뉴 — 기능별 현재 바인딩 표시, 선택 시 캡처 모드(15초 내 누른 버튼 할당,
  한 버튼은 한 기능만 — 재할당 시 기존 기능에서 회수), "버튼 확인"(눌린 버튼
  id와 커널 이벤트 코드 숫자를 함께 실시간 표시 — 서로 다른 물리 버튼이 같은
  코드를 보내 이름이 겹치는 경우를 숫자로 구분, 캡처 모드라 기존 매핑 발동
  억제), "전체 지우기".
- `mf_pifinder_setup.sh`: python3-evdev 설치 추가(장비에는 설치 완료).
- i18n: ko 9개 문자열(조이스틱/버튼 확인 등), zh 游戏手柄, de/es/fr.
- 테스트: 신규 `tests/test_joystick_input.py` 12종(매핑 정규화, 키패드/마운트
  디스패치, keepalive, 방향 교체 시 이전 릴리스 무시, mount off 무시, 요청
  기능 전체 커버). 전체 799 unit 통과.

<a id="mf_change_history_ko--수동이동-8초-재전송-추가-2026-08-07"></a>
#### 수동이동 8초 재전송 추가 (2026-08-07)

버튼/키를 계속 눌러도 조이스틱은 ~11초, LCD 가이드 화면은 ~10초에 이동이
멈추던 결함 수정. mountcontrol은 연속이동 상한
(`MANUAL_MOTION_MAX_CONTINUOUS_SECONDS` 10초)을 넘겨서는 keepalive로 lease를
연장해 주지 않으므로, 송신 측이 `manual_movement`를 주기 재전송해야 한다
(ui/base.py 가이드 키·pos_server는 준수, 이 두 곳은 keepalive만 보냄).

- `joystick_input.py`·`ui/indi.py`: `MANUAL_MOTION_RESTART_INTERVAL = 8.0`
  추가 — 홀드 중 8초마다 keepalive 대신 `manual_movement`를 재전송해 10초
  카운터를 리셋.
- 진단 과정에서 OnStep 펌웨어 자체의 ~7초 가이드 자동정지(전 경로 공통 원인)
  도 실측·확인 — 펌웨어 측에서 수정됨(2026-08-07). 펌웨어 수정 후 남아 있던
  조이스틱/LCD 11초 정지가 이 재전송 누락이다.
- 테스트: `test_joystick_input.py`에 장시간 홀드 재전송 1종 추가(13종).

<a id="mf_change_history_ko--bluetooth-설정-메뉴--조이스틱-지원-이름-변경-2026-07-26"></a>
### Bluetooth 설정 메뉴 — 조이스틱 지원, 이름 변경 (2026-07-26)

Settings > Advanced의 "Keyboard" 항목을 "Bluetooth"(ko: 블루투스)로 바꾸고,
키보드 전용이던 재연결 필터를 조이스틱/게임패드까지 넓혔다. 페어링/연결 UI
자체는 원래 장치 종류를 가리지 않았고, 키보드 전용이던 부분은 이름과 재연결
필터뿐이었다.

- `ui/menu_structure.py`·`ui/bluetooth_keyboard.py`: 메뉴/타이틀 "Bluetooth"로
  변경(레이블 `keyboard_settings`와 모듈/클래스명은 유지 — 코드 식별자까지
  바꾸면 diff만 커짐).
- `sys_utils.py`: `is_bluetooth_input_device()` 추가 — 키보드 키워드에 더해
  joystick/joypad/gamepad/controller와 흔한 컨트롤러 브랜딩(8BitDo, DualShock,
  DualSense, Joy-Con), 아이콘 `input-gaming`/`input-mouse` 인식. 재연결
  (`reconnect_bluetooth_keyboards`)과 부팅 자동 재연결이 이 필터를 사용.
  기존 `is_bluetooth_keyboard()`는 호환용으로 유지.
- i18n: "Bluetooth" msgid를 ko(블루투스)/zh(蓝牙)/de/es/fr에 추가, .mo 재컴파일.
- 테스트: 감지 필터 4종 추가(`tests/test_bluetooth_keyboard.py`), 전체 787
  unit 통과.

주의: 이 변경은 **연결 관리**(스캔/페어/자동 재연결)까지다. 연결된 조이스틱의
버튼 입력을 UI 키로 매핑하는 것은 별도 작업 — 현재 입력 계층(`keyboard_pi.py`)은
libinput 키보드 이벤트만 처리하며, libinput은 조이스틱 장치를 키보드로 분류하지
않는 경우가 많다(키보드 모드를 지원하는 컨트롤러는 예외).

<a id="mf_change_history_ko--locations-수정-폼-라벨-겹침-수정-2026-07-26"></a>
### Locations 수정 폼 라벨 겹침 수정 (2026-07-26)

Location Management의 Edit Location 모달에서 라벨("Latitude (Decimal)" 등)이
서버에서 미리 채워진 값 위에 겹쳐 보이던 문제. Materialize는 라벨에 `active`
클래스가 있어야 값 위로 띄우는데, 수정 모달 라벨에 없었고 페이지에서
`M.updateTextFields()`도 호출하지 않았다.

- `views/locations.html`: 미리 채워지는 6개 라벨(name/lat/lon/alt/error/source)에
  `class="active"` 추가, DOMContentLoaded와 모달 `onOpenEnd`에서
  `M.updateTextFields()` 호출, DMS 전환(`toggleFormat`)이 프로그램적으로 채운
  필드도 같은 방식으로 라벨 활성화.
- `views/location_form.html`: 추가 폼의 미리 채워지는 2개 라벨
  (`error_in_m`=10, `source`="Manual Entry")에 `class="active"` 추가.

<a id="mf_change_history_ko--livecam-raw-display-모드가-이름대로-동작-2026-07-26"></a>
### LiveCam Raw Display 모드가 이름대로 동작 (2026-07-26)

프리뷰 모드가 `raw_display`인데도 밝기가 정규화된다는 지적으로 확인한 결과,
`DisplayFrameBuilder.build()`가 preview_mode와 무관하게 percentile stretch를
무조건 적용하고 있었다 — `raw_display`와 `stretched`가 코드상 완전히 동일했다
(모드 분기는 `bayer_2x2_average` 하나뿐). 설계 문서(`mf_raw_live_stack_plan_ko.md`
§설정 후보)에는 두 모드가 별개로 나열되어 있으나 구분이 구현되지 않은 상태였다.

- `raw_live_stack.py`: `raw_display`는 센서 비트심도 기반 고정 선형 매핑
  (`ADU × 255/(2^bit_depth−1)`, 비트심도는 raw 포맷명 "SRGGB12"에서 파싱,
  실패 시 dtype 폴백)으로 렌더링 — 게인/노출 변화가 화면 밝기에 그대로
  보인다. `stretched`/`bayer_2x2_average`는 종전 percentile stretch 유지.
  sum 스택은 고정 스케일에서 포화될 수 있음(합산의 본질) — sum 확인은
  stretched 모드 사용.
- `livecam_config.py`: `PREVIEW_MODE_RAW` 상수 추가.
- 테스트: 선형성(2배 신호→2배 픽셀)·stretched 정규화 유지·비트심도 폴백 3종
  추가, 전체 783 unit 통과.

<a id="mf_change_history_ko--livecam-상태에-센서-적용값raw-레벨-표시-2026-07-26"></a>
### LiveCam 상태에 센서 적용값/RAW 레벨 표시 (2026-07-26)

게인을 바꿔도 LiveCam 화면에 변화가 없다는 관측을 실측으로 확인했다. 결론:
게인은 정상 적용되고 있었다(요청 1/15/20/30 → 드라이버 1.0/14.79/19.5/29.51,
RAW p50 332→3022). 프리뷰의 percentile stretch가 프레임 자체 히스토그램을 화면
전체 범위로 정규화하므로 **전역 곱(게인)은 수학적으로 표시에서 소거**된다 —
이미지가 안 변하는 게 정상이다. LCD 포커스 화면은 절대 스케일(bias 차감 →
digital gain → 255/4095)이라 변화가 보이고, 배경 앵커 EMA stretch가 게인 전환
직후 과도기 프레임을 이상하게 보이게 할 수 있다. 절전 모드에서는 프레임 갱신이
~1분 간격이라 전환 중의 오래된 프레임이 한동안 남는 것도 "이상함"의 큰 몫이다.

- `views/livecam.html`: 상태 패널에 "센서 (적용값)"(드라이버 보고 게인/노출)과
  "RAW 레벨 (p1/p50/p99.5)" 행 추가 — stretch가 지워버리는 게인/노출 변화를
  숫자로 확인할 수 있다. 데이터는 `/api/camera/raw-stack/status`의 frame 필드에
  이미 있었고 표시만 없었다.
- i18n: ko 두 문자열 추가(AI-TRANSLATED), .mo 재컴파일.

<a id="mf_change_history_ko--자동-노출--빠른-셔터속도-도달-2026-07-26"></a>
### 자동 노출 — 빠른 셔터속도 도달 (2026-07-26)

현장 관측(서울, imx462): 수동 25ms에서는 solve가 반복 성공하는데, `auto_star`로
바꾸면 그 셔터속도로 돌아가지 못했다. 노출을 위쪽에 묶어 두는 경계가 둘이었고
둘 다 완화했다. 결정: [ADR m0021](../../adr/m0021-auto-exposure-reaches-fast-shutter.md)
(ADR 0010의 200ms 하한을 "첫 순회 한정"으로 축소).

- `auto_exposure.py` — 복구 사다리가 하한 아래를 탐색하지 않았다.
  ADR 0010은 "밝은 하늘에서도 200ms보다 짧게 가서 얻을 게 없다"는 전제로
  사다리를 `[400, 800, 1000, 200]ms`로 깔았는데, 광害가 심한 곳에서는 이 전제가
  깨진다(이 현장은 25ms에서 solve, 400ms~1s에서는 검출 0). 결과적으로 400ms↔1s를
  무한 왕복했다(실측). 이제 긴 rung을 한 바퀴 다 실패하면 같은 rung을 재생하지 않고
  `[100, 50, 25]ms`로 이어서 내려간다. 어두운 하늘의 흔한 경로(8회)는 그대로다.
- `auto_exposure_starcount.py` — 앵커 경계가 구조적으로 도달 불가였다.
  조정폭은 앵커/8~앵커×8로 제한되는데 앵커 초기값은 400ms 추정치이고 데드밴드에
  들어와야만 갱신된다. 실제 적정 노출이 앵커/8보다 짧으면(25ms < 400ms/8 = 50ms)
  서보는 매 프레임 더 짧게 요청하지만 50ms에 고정되고 "변경 없음"만 반환한다 →
  데드밴드에 못 들어가니 앵커도 영영 안 바뀐다(실측: 정확히 50000µs에 정착).
  이제 같은 방향으로 `reanchor_after`(3)회 연속 클램프되면 앵커가 그 경계를 따라
  이동한다. 클램프가 풀리거나 방향이 바뀌면 streak은 리셋되므로, 이상 프레임 한
  장이 노출을 튀게 하지는 못한다.
- `auto_exposure_starcount.py`·`auto_exposure.py` — 제어 법칙의 모든 갈래가
  위로만 움직였다. 위 두 경계를 풀고 debug 로그로 다시 관측하니 닫힌 순환이었다:
  `1s → 밝은 하늘 가드(중앙 ROI 평균 251>240) → 앵커 400ms → 검출 0 → 복구 상승
  → 800ms → 6~8개(목표 20 미달) → 1s → 가드 …`. 두 갈래를 뒤집었다.
  (1) 밝은 하늘 가드가 앵커 복귀 대신 **노출을 절반으로** 내리고 그 지점을
  ceiling으로 기억한다. 이후 상승은 ceiling으로 막혀 방금 sky glow로 판명된
  노출로 되돌아가지 못한다. ceiling은 데드밴드 진입, 또는 확실히 어두운 프레임
  (평균 < `bright_clear_mean` 120)에서 해제된다 — 240에서 걸고 120에서 푸는
  간격이 히스테리시스이고, 가드 임계 바로 아래에서 풀면 순환이 되살아난다.
  (2) 검출 0 복구는 프레임이 sky glow 한계임을 아는 호출자에 한해 하강 사다리
  `[200, 100, 50, 25]ms`를 쓴다. prior는 활성화 시점에 한 번만 정해지고, 한
  바퀴 실패하면 반대편 rung으로 확장한다. 매치 수 컨트롤러는 프레임 밝기 신호가
  없어 기존 야간 사다리 그대로다.
- 테스트: `tests/test_auto_exposure.py`에 사다리 에스컬레이션·밝은 사다리 6종
  (+기존 wrap 테스트를 새 동작으로 갱신), `tests/test_auto_exposure_starcount.py`에
  재앵커링·ceiling 7종 추가. 전체 783 unit 통과.
- 실장비 검증(서울, imx462): `auto_star` 전환 후 복구 사다리가
  `400→800→1000→200 → [확장] → 100→50→25ms`로 실제 25000µs까지 하강하는 것을
  로그로 확인. 이전에는 400ms↔1s를 무한 왕복했다.

<a id="mf_change_history_ko--livecam-카메라-설정-확정-저장-2026-07-25"></a>
### LiveCam 카메라 설정 확정 저장 (2026-07-25)

LiveCam 페이지에서 설정을 바꾸고 다른 페이지를 보고 돌아오면 값이
원복되던 문제를 수정했다. 원인은 두 가지였고, 첫 번째가 근본 원인이다.
게인이 저장되지 않는 것은 의도된 동작이라 그대로 두었다(재시작 시 카메라
프로파일 기본값 복귀, 저장은 Exp Save 항목만). 나중에 결함으로 오인해
"고치는" 일이 없도록 `set_gain` 처리부에 의도를 주석으로 남겼다.

- `config.py` — 프로세스 간 config 덮어쓰기(근본 원인).
  `config.json`은 main/UI·카메라·웹 세 프로세스가 각자 시작 시점에 읽은
  `Config` 인스턴스로 공유한다. `set_option()`이 자기 메모리 사본을 그대로
  파일에 덮어써서, 한 프로세스가 값을 저장하면 그 사이 다른 프로세스가 바꾼
  키가 전부 되돌아갔다(카메라 프로세스가 `camera_exp`를 저장하면 웹이 방금
  쓴 LiveCam 설정이 원복). 이제 쓰기 직전에 파일을 다시 읽어 병합한
  뒤(`_refresh_from_disk()`) 저장하고, 임시 파일 + `os.replace()`로
  원자적으로 기록해 다른 프로세스가 쓰다 만 파일을 읽지 않게 했다.
  `reset_filters()`도 같은 병합을 거친다. 파일이 깨져 있으면 메모리
  사본을 유지해 한 번의 저장이 전체 초기화가 되지 않도록 했다.
- `camera_interface.py` — Auto 노출 모드가 저장되지 않던 문제.
  수동 노출만 `camera_exp`에 기록하고 `set_exp:auto`/`auto_star`는 기록하지
  않아서, 카메라는 auto로 돌아도 config·UI는 이전 수동값을 계속 보여주고
  재시작하면 auto 선택이 사라졌다. 이제 auto 모드도 저장한다
  (`set_exp:native`는 주간 정렬용 임시 모드이므로 종전대로 저장하지 않음).
- `config.py` — 저장된 값을 읽는 쪽도 갱신되지 않던 문제.
  LiveCam에서 Star를 선택하면 config와 카메라는 바뀌는데, main/UI 프로세스는
  시작 시 읽은 `Config`를 계속 써서 Camera Exp 메뉴 체크와 포커스 화면 서픽스가
  이전 노출을 그대로 보여줬다(누가 `load_config()`를 호출할 때까지). 이제
  `get_option()`이 파일의 `(mtime, size)` 변화를 보고 다시 읽는다. 재확인은
  `REFRESH_INTERVAL`(0.25초) 간격으로 제한해 draw 루프에서 매 호출 `stat`을
  하지 않는다(실측 1.64µs/호출). equipment/locations는 종전대로 메모리 객체를
  쓰며 명시적 `load_config()`에서만 재구성한다.
- `api_extensions.py` — 웹 Apply의 config 기록 시점이 LCD 메뉴와 달랐다.
  Camera Exp 메뉴는 선택 즉시 `config_option`을 쓰고(`ui/text_menu.py`)
  post_callback이 `set_exp`를 큐에 넣는데, 웹은 명령만 넣고 기록은 카메라
  프로세스가 큐를 비울 때까지 미뤄졌다. 유휴 상태(저전력 sleep)에서는 카메라가
  ~60루프에 한 번만 큐를 비우므로 그때까지 페이지·메뉴 모두 이전 노출을
  보여줬다. 이제 메뉴와 같은 순서로 노출을 먼저 기록하고 명령을 넣는다.
  게인은 Camera Gain 메뉴도 config에 쓰지 않으므로 그대로 기록하지 않는다.
- 테스트: 신규 `tests/test_config.py` 10종(교차 프로세스 병합·원자적 쓰기·
  손상 파일·읽기 갱신·재확인 간격), 신규 `tests/test_api_camera_controls.py`
  7종(Flask 테스트 클라이언트로 실제 엔드포인트 구동 — 노출 즉시 기록·큐잉,
  게인 미기록, 클램프값 기록, 잘못된 값은 무변경), 전체 771 unit 통과.
  실장비 검증: 서비스 재시작 후 `auto_star` 유지, 카메라 노출 저장 시 LiveCam
  `low_percentile` 유지, 장수명 `Config` 리더가 웹 변경 반영, Apply 직후
  카메라가 큐를 비우기 전에도 페이지·config가 새 노출을 보고함.

<a id="mf_change_history_ko--헤드리스-콘솔-부팅--wf-panel-pi-cpu-점유-제거-2026-07-30"></a>
### 헤드리스 콘솔 부팅 — wf-panel-pi CPU 점유 제거 (2026-07-30)

모니터 없이 운용하는 장비에서 데스크톱 세션의 Wayland 패널(`wf-panel-pi`)이
디스플레이 미부착 상태에서 렌더링 busy-loop에 빠져 코어 1개를 상시 점유했다
(실측 CPU 95%+, 부팅 5시간 동안 누적 290분). PiFinder는 데스크톱과 무관한
systemd 서비스로 동작하므로 데스크톱 부팅 자체를 끈다.

- `mf_pifinder_setup.sh`: "Disable unwanted services" 섹션에 콘솔 자동로그인
  전환 추가 — `raspi-config nonint do_boot_behaviour B2`(콘솔 자동로그인),
  `raspi-config`가 없으면 `sudo systemctl set-default multi-user.target` 폴백.
  재부팅 시점부터 적용된다.
- 실장비 적용(2026-07-30): 부팅 타겟 `multi-user.target` 전환 후
  `systemctl isolate multi-user.target`으로 데스크톱 세션 즉시 종료.
  load average 3.6 → 1.9, `pifinder`/`cedar_detect` 서비스 정상 유지 확인.
- 데스크톱이 다시 필요하면 `sudo raspi-config nonint do_boot_behaviour B4`
  (데스크톱 자동로그인)로 되돌린다. VNC 데스크톱을 쓰려는 경우에도 마찬가지.

<a id="mf_change_history_ko--wifi-복구-도구--bt-코엑스-펌웨어-웨지-대응-2026-08-05"></a>
### WiFi 복구 도구 — BT 코엑스 펌웨어 웨지 대응 (2026-08-05)

BT 조이스틱 페어링 중 STA가 죽고 재부팅 2회로만 복구된 사건(당일 실측
분석)의 대응책. CYW43455 단일 2.4GHz 라디오를 WiFi/BT가 공유하는 구조에서
BT 고밀도 국면(페어링·부팅 직후 재연결 폭풍)이 brcmfmac 펌웨어의 STA 상태
머신을 웨지시킬 수 있고, 이는 서비스 재시작으로 복구 불가(커널/펌웨어
계층)다.

- `scripts/mf_wifi_recover.sh`: 유닛 정지(monitor/hostapd/dnsmasq,
  NetworkManager) → uap0 삭제 → brcmfmac_wcc/brcmfmac/brcmutil 리로드
  (칩 펌웨어 리셋) → 부팅 순서로 복원(NM→prepare→AP 유닛) → 상태 보고.
  로그: `PiFinder_data/wifi_recover.log`. 실측: 정상 상태에서 전체 사이클
  11초, STA 즉시 재접속·AP 복구, SSH 세션 생존.
- LCD: Settings > Advanced > **WiFi Recover** (Confirm/Cancel, shutdown과
  동일 패턴). `callbacks.recover_wifi` → `sys_utils.recover_wifi()`
  (예외 격리, 실패 시 "WiFi still down" 표시). 실기기 화면 확인 완료.
- i18n: 신규 msgid 4건 5개 언어 번역(AI-TRANSLATED).
- 현장 수칙(사건 분석에서 도출): 페어링은 집에서, 조이스틱 켠 채 재부팅
  금지, 마운트(AP 2.4GHz 클라이언트)는 ESP32 계열이라 5GHz 이전 불가 —
  AP+STA 동일 채널 제약으로 STA도 2.4GHz 고정.

<a id="mf_change_history_ko--indi-메뉴링크를-mount-control에-연동-2026-08-10"></a>
### INDI 메뉴/링크를 Mount Control에 연동 (2026-08-10)

Mount Control이 꺼져 있으면 INDI 관련 항목을 LCD UI와 웹 UI 양쪽에서 감춘다.
기능 게이팅은 이미 있었다 — `main.py:706`이 mountcontrol 프로세스 기동을
막고 `callbacks._send_mount_control`이 명령마다 "Mount Control Off"를
띄운다. 즉 **동작하지 않는 항목이 화면에만 남아 있던 상태**였고, 이번에
표시를 맞췄다.

**LCD (`ui/menu_manager.py`, `ui/menu_structure.py`)**

`dyn_menu_equipment()` 선례를 따라 `dyn_menu_indi(cfg)`를 추가하고
`MenuManager.__init__`에서 **`preload_modules()` 앞에** 호출한다(꺼져 있으면
INDI UI 모듈을 아예 인스턴스화하지 않는다). 대상 2개에 label을 붙였다 —
`Start > INDI`(`indi_actions`, 13항목), `Settings > INDI Setting`
(`indi_settings`, 35항목).

- **`Settings > Mount Type`은 유지한다.** INDI 전용이 아니다 —
  `pos_server.py:787`(SkySafari)과 `telemetry.py`가 마운트 없이도 읽는다.
- **토글 위치는 `Tools > Test Mode > Experimental > Mount Control` 그대로
  둔다** (사용자 결정 2026-08-10, upstream 호환성). 즉 INDI가 감춰진
  상태에서 다시 켜려면 이 경로를 알아야 한다.
- **제거가 아니라 복원 가능한 pruning이다.** 메뉴 트리는 프로세스 전역
  상태라 `test_ui_modules.py`처럼 `MenuManager`를 여러 번 만드는 곳에서
  영구 삭제하면 이후 매니저가 INDI를 잃은 트리를 보게 된다. 꺼낸 항목을
  `_pruned_indi_entries`에 (부모 리스트, 인덱스, 항목)로 캐시해 두고
  켜지면 **원래 자리에** 되돌린다. 멱등하다.
- 실운영에서는 `mount_control_toggle`이 PiFinder를 재시작하므로 매니저당
  1회 실행으로 충분하다(실시간 메뉴 갱신 불필요).

**웹 (`server.py`, `views/base.html`)**

링크만 감춘다(사용자 결정) — `/indi/*` 라우트 19개는 그대로라 URL 직접
접근은 여전히 가능하다.

- **함정: 이 서버는 `render_template()`이 아니라
  `app.jinja_env.get_template().render()`로 그린다.** Flask의
  `@app.context_processor`가 **적용되지 않는다.** `jinja_env.globals`에
  등록해야 하고(216행 `_` 선례), 값이 아니라 **콜러블**로 넣어야 서버 시작
  시점 값으로 굳지 않는다.
- `base.html` 상단에서 `show_indi`를 한 번 정의하고 네비 2곳(데스크톱/
  모바일)에서 쓴다. **전역이 없으면 표시하는 쪽으로 기본값을 잡았다** —
  `test_web_catalogs.py`처럼 자체 Flask 앱을 만드는 곳은 이 전역을 등록하지
  않는다(실제로 처음 구현에서 웹 테스트 7건이 `UndefinedError`로 깨졌다).
  등록 누락 시 조용히 감춰지는 것보다 그냥 보이는 편이 낫다.

검증: `dyn_menu_indi` 숨김/복원/멱등성/원위치 복원과 Mount Type 잔존을
테스트 2건으로 고정(`test_menu_struct.py`). 템플릿은 전역 없음/True/False
3가지 상태에서 렌더 확인(2/2/0개). 전체 유닛·스모크 1147건 통과.

<a id="mf_change_history_ko--indi-위치시간-테스트-2건의-환경-의존-제거-2026-08-10"></a>
### INDI 위치/시간 테스트 2건의 환경 의존 제거 (2026-08-10)

`test_build_indi_location_time_properties_*` 2건이 이 기기에서 계속 실패하고
있었다. 원인은 코드가 아니라 **테스트가 실기기 상태를 읽는 것**이었다.

`build_indi_location_time_properties()`는 `device_name`을 생략하면
`resolve_indi_device_name()` → `get_indi_profile_device_name()`을 거쳐
**실제 INDI 프로파일 DB(`~/.indi/profiles.db`)** 에서 telescope 계열 드라이버
이름을 찾아 쓴다. 이 기기 프로파일에는 `Telescope Simulator`가 등록돼 있어
그 이름이 나오는데, 테스트는 `DEFAULT_ONSTEP_DEVICE_NAME`(=`LX200 OnStepX`)을
기대하고 있었다.

**동작 판정 (사용자 확인, 2026-08-10): `Telescope Simulator`가 기본이 맞고
OnStepX는 사용자가 설정하는 항목이다.** 즉 `DEFAULT_ONSTEP_DEVICE_NAME`은
프로파일이 아예 없을 때만 쓰이는 폴백이고, 프로파일이 있으면 그쪽이
이기는 현재 동작이 정상이다. 상수도 그대로 둔다.

두 테스트는 좌표 변환(서경 −118.25 → 241.75)과 오프셋 포맷(`9.00`/`-7.00`)을
보는 것이지 디바이스 이름 해석을 보는 게 아니므로, `device_name`을 명시해
격리했다. 왜 명시해야 하는지 주석으로 남겼다 — 안 그러면 "불필요한 인자"로
보고 되돌리기 쉽다.

이 함정의 성질: **프로파일이 없는 개발 머신에서는 통과하고, INDI를 설정한
실기기에서만 실패한다.** 실제로 `HOME`을 격리해 돌리면 수정 전에도 통과했다.
같은 의존을 가진 테스트는 이 2건뿐임을 확인했다.

검증: 이 기기(프로파일 있음)와 `HOME` 격리(프로파일 없음) 양쪽에서
`test_sys_utils.py` 54건 통과. **전체 유닛·스모크 1145건 통과, 실패 0건** —
장기간 남아 있던 실패 2건이 이로써 해소됐다.

<a id="mf_change_history_ko--wifi_statustxt-추적-해제--부재-폴백-2026-08-10"></a>
### `wifi_status.txt` 추적 해제 + 부재 폴백 (2026-08-10)

`wifi_status.txt`는 소스가 아니라 **런타임 상태**다. `switch-ap.sh`,
`switch-cli.sh`, `switch-apsta.sh`가 모드를 바꿀 때마다 덮어쓰고
(`echo -n`, 개행 없음), `pifinder_setup.sh:140`이 설치 시 `Client`로
씨앗을 심는다. 추적 대상이라 기기에서 모드를 바꿀 때마다 저장소가
dirty해졌고, `git pull`이 "로컬 변경을 덮어쓴다"며 막힐 수 있었다.

`git rm --cached` + `.gitignore` 등록으로 추적을 해제했다.

**단순 추적 해제만으로는 앱이 죽는다 (이래서 폴백을 함께 넣었다).**
읽는 곳이 5군데인데 전부 예외 처리 없는 맨 `open()`이었다 —
`splash.py`(부팅 스플래시), `ui/status.py`, `sys_utils.Network.__init__`,
`ui/callbacks.get_wifi_mode`, `ui/software.py`. 새 클론처럼 파일이 없으면
`FileNotFoundError`로 부팅이 실패한다.

`utils.read_wifi_mode(default="Client")` 헬퍼를 추가하고 5곳을 모두 여기로
보냈다. 기본값을 `Client`로 잡은 근거: 설치 스크립트가 쓰는 값과 같고,
`sys_utils`의 분기(2098/2324/2326/2624/2626/2663/2743/2745)가 전부
`WIFI_MODE_AP`/`WIFI_MODE_APSTA`를 조건으로 하므로 **AP를 띄우는 경로가
모두 건너뛰어진다** — 모를 때 틀려도 안전한 방향이다. `.strip()`을 추가했는데
모든 writer가 `echo -n`이라 실동작은 동일하고, 손으로 편집해 개행이 붙는
경우만 구제한다.

부수 정리: 이제 아무도 읽지 않는 `self.wifi_txt` 속성 2개
(`sys_utils.Network`, `ui/software.py`)를 제거했다. 모드 변경은
`go_wifi_*()` → 셸 스크립트 경로로만 일어난다.

`pifinder_post_update.sh`에 파일 부재 시 `Client`로 재생성하는 가드를 넣었다.
추적을 해제하는 이 업데이트를 받으면 git이 (수정하지 않은) 로컬 파일을
지우기 때문이다.

**주의: AP 또는 AP+STA로 쓰던 기기는 이 업데이트 후 기록된 모드가 Client로
초기화된다.** OS 네트워크 설정 자체(wpa_supplicant/NetworkManager/dhcpcd)는
그대로이고 이 기록 파일만 잃는 것이므로, 메뉴에서 모드를 다시 선택하면
된다. 이 기기는 마침 Client 상태였다.

검증: 파일을 치운 상태에서 `read_wifi_mode()` → `'Client'`, `splash` import
성공, `get_wifi_mode()` → `['Client']` 확인. ruff lint/format 통과, 유닛·스모크
1143건 통과(기존 실패 2건 외 신규 실패 없음).

<a id="mf_change_history_ko--문서-빌드를-개발-환경에-편입--nox--s-docs-2026-08-10"></a>
### 문서 빌드를 개발 환경에 편입 — `nox -s docs` (2026-08-10)

`docs/source/*.rst`를 고쳐도 로컬에서 검증할 방법이 없었다. Sphinx가 개발
환경에 포함돼 있지 않아 Read the Docs가 푸시 후 빌드할 때까지 깨진 참조를
알 수 없었고, 실제로 직전 동기화 라운드에서는 임시 파이썬 스크립트로
`:ref:`/치환자/이미지를 전수 검사해 대신했다. 그 방식은 문법 오류나 목차
구조 문제는 못 잡는다.

**MF 로컬 변경 (upstream에 없음 — 동기화 시 보존할 것):**

- `python/requirements_dev.txt`: 끝에 `-r ../docs/source/requirements.txt`
  한 줄 추가. 버전을 여기서 다시 고정하지 않고 **참조**만 한 이유는 Read
  the Docs가 설치하는 파일과 단일 출처를 유지하기 위해서다(로컬 빌드 결과가
  발행본과 어긋나지 않는다). 이 한 줄로 기존 개발 환경 구축 절차
  (`pip install -r requirements.txt -r requirements_dev.txt`)가 그대로
  Sphinx까지 설치한다 — CLAUDE.md와 Bookworm 설치 문서 양쪽이 이미 이
  명령을 안내하므로 별도 단계가 늘지 않는다.
- `python/noxfile.py`: `docs` 세션 추가.
  `python -m sphinx -n -W --keep-going -q -E ../docs/source ../docs/build/html`.
  `-n`은 누락된 참조를 보고하고 `-W`는 경고를 실패로 만든다 — "렌더는
  됐다"를 "맞다"로 오해하지 않기 위해서다. `--keep-going`으로 한 번에 전부
  보고한다. `nox.options.sessions` 기본 목록에는 **넣지 않았다**(문서를
  건드리지 않는 커밋에서 매번 돌 이유가 없음).
- CLAUDE.md의 nox 명령 목록, `mf_bookworm_install_ko/en.md`의 개발 환경
  절차에 반영.

빌드 산출물 `docs/build/`는 이미 루트 `.gitignore`의 `build/`에 걸린다.

검증: 이 기기(Bookworm, Python 3.11)에 설치 후 `nox -s docs` 실행 성공,
경고 0건. 설치된 것은 `docs/source/requirements.txt`의 고정 버전 —
Sphinx 7.2.6, sphinx-rtd-theme 1.3.0, sphinxcontrib-mermaid 0.9.2.

주의: `requirements_dev.txt`를 설치하는 nox 세션들(`type_hints`,
`unit_tests`, `smoke_tests`, `web_tests`, `ui_tests`, `babel`)의 venv에도
Sphinx가 함께 들어간다. `reuse_venv=True`라 최초 1회 비용이며, 대신 개발
환경 어디서든 문서 빌드가 가능해진다는 쪽을 택했다.

<a id="mf_change_history_ko--upstream-동기화--rev4-문서자산-수용-4a83d25b7eaf058c-2026-08-09"></a>
### upstream 동기화 — rev4 문서/자산 수용 (`4a83d25b..7eaf058c`, 2026-08-09)

upstream 신규 12건 중 **11건 적용, 1건 제외**. 재동기화 판단 기준과 커밋
단위 근거는 [mf_upstream_patch_reference_ko.md](maintenance.md#mf_upstream_patch_reference_ko)의
2026-08-09 라운드에 있고, 여기에는 **다음 업데이트 때 반드시 다시 확인해야
할 것**만 남긴다.

**정책 변경 (사용자 결정)**: rev4 하드웨어 관련 수용을 **허용**한다. 조건은
두 가지 — 현재 소스의 동작에 문제가 없어야 하고, 충돌 시 임의 병합하지 않고
사용자 결정을 받는다. 이전의 "rev4 전면 제외" 정책은 폐기됐다.

**런타임 코드 변경 0건.** `python/` 이하는 한 줄도 바뀌지 않았다(`.claude/`
스킬 스크립트 제외). 바뀐 영역은 `docs/source/`(rev4 매뉴얼), `docs/ax/`,
`case/rev4`·`gerbers/rev4`·`kicad/PiFinder_rev4`(약 19MB 설계 자산),
`.claude/skills/`, `CONTEXT-MAP.md`뿐이다. 실행 중인 앱의 동작은 동일하다.

**다음 동기화에서 되돌리면 안 되는 결정 3건:**

- **rev4 매뉴얼을 upstream 그대로 유지한다.** `user_guide.rst`에 배터리
  잔량 표시·충전·저전력 경고/자동 종료·사운드 절이 들어와 있는데, 이
  포크에는 해당 기능이 **없다**. "문서가 없는 기능을 설명한다"는 이유로
  되돌리지 말 것 — upstream diff를 최소로 유지하고 rev4 소프트웨어 이식
  시 자동으로 맞아떨어지게 하려는 의도적 선택이다.
- **`menu_map.rst`에서 Volume 항목만 제외했다.** menu_map은 실제 메뉴
  구조를 그리는 문서라 포크 메뉴와 일치시켰다(포크엔 `sound.py`도 Volume
  항목도 없음). 반면 `user_guide.rst`의 `Sounds` 절은 위 방침에 따라
  upstream 그대로 뒀다. **menu_map만 실물 기준, 산문은 upstream 기준이라는
  비대칭은 의도된 것**이며 불일치 버그가 아니다.
- **`troubleshooting.rst`**: upstream의 신규 "Align (Day)" 진단 산문을
  받으면서, 그것이 재작성한 Camera Type 불릿에 MF의 Mono/Color 안내
  문장을 복원해 넣었다. em-dash는 같은 라운드에 도입된 STE 하우스
  스타일(`7eaf058c`)에 맞춰 문장 분리로 바꿨다(의미 동일).

**미적용 1건**: `27ca9624`(#573, ADR 0020 배터리 프로파일링 + SOC_LUT).
수정 대상인 `battery_bq25895.py`와 `docs/adr/0020-soc-as-runtime-fraction.md`가
**둘 다 포크에 부재**해 단독 적용이 물리적으로 불가능하다. 배터리 이식을
결정하면 그때 함께 처리한다.

**발견: `0x6A`가 배터리와 디스플레이 감지에 이중으로 쓰인다 (중요).**
`hardware_detect.py:44`의 `detect_ssd1333_display()`가
`i2c_present(0x6A)`(BQ25895 충전칩 ACK)를 **SSD1333 패널 마커로 재사용**하고
있다. 한편 upstream은 `has_bq25895`와 `has_buzzer`를 같은 `0x6A` 프로브
하나에서 뽑는다. 이 기기 실측은 I2C 버스 1에 `0x28`(BNO055)만 응답하고
`0x6A`는 없으며, `config.json`에 `display_hardware` 키가 없어 자동감지
결과인 `ssd1351`(128×128)로 돌아가는 중이다. 따라서:

- 배터리를 쓰려고 **BQ25895 보드를 물리적으로 붙이면 디스플레이 감지가
  `ssd1333`(176×176)으로 전환돼 화면이 깨진다** — 패널은 그대로 SSD1351인데.
  rev4 하드웨어 착수 전에 이 커플링을 먼저 끊어야 한다(`config.json`에
  `display_hardware` 명시하거나 디스플레이 감지를 배터리 프로브에서 분리).
- PWM 충돌은 **없다**(확인함). `config.txt`의
  `dtoverlay=pwm-2chan,pin=12,...,pin2=13,...`이 두 채널을 모두 열고, 포크
  키패드 백라이트는 채널 1(GPIO13), upstream `sound.py`는 채널 0(GPIO12)을
  쓴다. 실측상 `pwmchip0`에 `pwm1`만 export돼 있어 채널 0은 비어 있다.

**알려진 부작용 2건 (동작 문제는 아님):**

- `pf_remote launch -fb`는 이 포크에서 실패한다 — `main.py`에
  `-fb/--fakebattery`가 없다(배터리 미이식).
- `pf_remote launch`의 새 기본값이 `--display headless_176`인데 **이 기기의
  실제 패널은 SSD1351 128×128**이다. 문서용 스크린샷을 찍을 때는
  `--display headless`를 명시할 것.

**검증**: `python/` 변경 0건 / `:ref:` 244개 라벨 dangling 0건 / 치환자
(`min_software`, `v3_docs`) 미정의 사용 0건 / `.. image::` 264건 누락 0건 /
잔존 충돌 마커 0건 / 스킬 스크립트 2건 py_compile 통과 /
`test_menu_struct`·`test_hardware_detect_display`·`test_obj_types_docs` 12건
통과. **(2026-08-10 보강) Sphinx를 설치하고 실제 빌드까지 확인했다 —
nitpicky 모드(`-n`) 경고 0건, `-W`(경고=실패)로도 성공.** Volume을 제외한
부분 적용이 문서를 깨뜨리지 않았음이 구조 검증이 아닌 실제 빌드로
확정됐다. 이 검증 절차는 `nox -s docs`로 상시화했다(아래 항목 참조).

**다음 라운드 백로그 (rev4 본체 이식)**: `#498`(hardware enablement),
`#541`·`#549`(배터리 UX), `#551`(keypad matrix), `#552`·`#556`(bringup),
`0edff3bb`(#539 rename). 정책 변경으로 "제외"가 아니라 **미결정 백로그**가
됐다. 문서는 이미 rev4를 설명하고 있으므로 이식하면 문서와 소프트웨어가
비로소 일치한다. 착수 시 `0edff3bb`를 먼저 처리해야
`product-knowledge-base.md` 류의 순서 충돌이 재발하지 않는다.

<a id="mf_change_history_ko--livecam-웹-프리뷰--fit-모드가-축소-전용이던-문제-수정-2026-08-09"></a>
### LiveCam 웹 프리뷰 — fit 모드가 축소 전용이던 문제 수정 (2026-08-09)

fit 모드가 CSS `max-width/height: 100%`(contain)에만 의존해 **셸보다 작은
프레임을 확대하지 못했다**. 컬러 변형의 디베이어 프리뷰는 해상도가
절반이라 셸보다 작아 1:1로 렌더되는데, 줌 라벨은 실제 fit 배율을
계산해 표시하므로(예: 136%) 라벨과 실물이 어긋났고, 수동 줌(명시적
픽셀 크기)을 만져야 제대로 보였다. fit 모드도 `fitScale()` 결과를
명시적 픽셀 크기로 적용하도록 수정(floor로 1px 스크롤바 방지, 셸 크기
미해결 시 기존 contain 폴백). 프레임 load/창 resize 재적용은 기존
리스너 그대로.

<a id="mf_change_history_ko--livecam-다운로드--컬러-변형은-실측-크로마-유지-2026-08-08"></a>
### LiveCam 다운로드 — 컬러 변형은 실측 크로마 유지 (2026-08-08)

`download_color_mode()`가 "이 포크의 센서는 실측 모노"라는 변형 선택
이전의 전제로 흑백을 하드코딩하고 있었다. 발행 프레임 info의 `mono`
플래그를 읽어 모노 프레임만 흑백으로 내리고, 선언된 컬러 변형
(imx462_color 등)은 실측 크로마를 유지하도록 변경 (frame info 부재 시
모노로 보수 폴백). 프리뷰가 흑백/단색으로 보이는 것 자체는 버그가 아니라
LiveCam 표시 모드 기본값이 `theme`(단색 틴트)이기 때문 — 컬러로 보려면
Color Mode를 `color`로 선택. 실기 확인: 컬러 imx462에서 color 모드 프리뷰
R/G/B 채널 분리(실제 크로마), 다운로드 RGB 유지.

<a id="mf_change_history_ko--pi-5-raw-스케일-정규화--pisp의-msb-정렬-16비트-대응-2026-08-08"></a>
### Pi 5 raw 스케일 정규화 — PiSP의 MSB 정렬 16비트 대응 (2026-08-08)

Pi 5/CM5(PiSP 프런트엔드)는 raw를 **16비트 MSB 정렬 샘플로만** 반환한다:
SRGGB12를 요청해도 SRGGB16(값 ×16)이 온다. Pi 4(Unicam)는 프로파일
비트수 그대로를 반환하므로, 12비트(최대 4095)를 가정하는 모든 하위 경로
(bias 238 차감, 8비트 스트레치, LiveCam `_linear_scale`, 웹 raw API,
포화 검사, SQM)가 Pi 5에서 ×16 값을 받아 전부 클리핑됐다 — 증상: 게인을
1로 낮춰도 Align(day)·LiveCam·`/api/camera/raw`가 순백(Focus의 주간
raw 렌더만 데이터 최대값 자동 스케일이라 정상으로 보임).

수정: `camera_pi.raw_downshift()`가 전달 포맷의 비트수와 프로파일
비트수의 차만큼 캡처 경계(3개 `make_array("raw")` 지점 공통 헬퍼
`_raw_array`)에서 우시프트해 전 소비자가 프로파일 단위를 유지한다.
실기(Pi 5 + 컬러 imx462) 검증: shift=4 감지, raw 평균 651(rpicam 직접
측정 658과 일치), `capture()` 프리뷰가 순백에서 정상 이미지로 복귀.
유닛 테스트 `test_camera_pi_raw.py` 추가.

<a id="mf_change_history_ko--카메라-monocolor-변형-선택-2026-08-08"></a>
### 카메라 mono/color 변형 선택 (2026-08-08)

설계 문서 [mf_camera_mono_color_plan_ko.md](camera.md#mf_camera_mono_color_plan_ko)
(plan → 구현됨, 후기 §8)의 P1–P4를 구현했다. CFA는 I2C로 읽을 수 없어
런타임 판별이 불가하므로, mono/color는 기기당 1회 설정으로 선언하고 파생
프로파일 이름(`imx462_color`/`imx296_color`)에 실어 전 프로세스에 전파한다.

- `sqm/camera_profiles.py`: `replace()` 파생 컬러 프로파일 2종 +
  `apply_variant()` 헬퍼. imx296_color 포맷은 커널 드라이버 소스로 확정한
  `SBGGR10`(mono=Y10; Bayer 순서는 실기 미검증 → non-SRGGB라 색 게이트가
  닫히는 보수 폴백).
- `camera_pi.py`: `CameraPI(exposure_time, cfg)`로 config 전달,
  `camera_variant` 적용. `capture_bias`의 카메라별 크롭 사다리를
  `profile.crop_and_rotate()`로 대체(등가 — 프로파일 상수와 일치 확인).
- `default_config.json`: `"camera_variant": "mono"` (기존 기기 비트 동일).
- Camera Type 메뉴 5항목(imx477, imx296/imx462 × Mono/Color) + 콜백 통합:
  센서(오버레이) 변경 시에만 재부팅, 변형만 변경 시 서비스 재시작, 무변경
  재선택은 no-op. `get_camera_type()`이 부트 오버레이 id에 변형을 합성.
  `sys_utils_fake.py`에 누락돼 있던 `switch_cam_imx462` 보강.
- 테스트: `test_camera_variant.py` 신규(프로파일 파생·apply_variant·
  합성 체크마크·재시작 정책·메뉴 value 정합), radiometer 출하 프로파일
  가드에 `imx462_color`(게이트 통과)/`imx296_color`(게이트 폐쇄) 편입.
  smoke 7건 + unit 1,131건 통과(실패 3건은 기기 상태 의존 기존 실패로
  변경 전 트리에서 동일 재현 확인).
- 실기 검증: 컬러 imx462 장착 기기에서 `camera_variant=color` 적용 후
  카메라 프로세스 `imx462_color` 기동(SRGGB12 스트림 정상), 웹 API
  `camera_type=imx462_color` 확인. SQM 상수는 mono 승계 미검증 상태
  유지(야간 실측 필요).

<a id="mf_change_history_ko--보류-업스트림-2건-이식--sqm-색보정560-focus-멀티스타531-2026-08-05"></a>
### 보류 업스트림 2건 이식 — SQM 색보정(#560), Focus 멀티스타(#531) (2026-08-05)

동기화 라운드에서 보류했던 마지막 2건을 "MF 수정 우선" 원칙으로 이식했다.
판단 근거·상세는 [mf_upstream_patch_reference_ko.md](maintenance.md#mf_upstream_patch_reference_ko)
2026-08-04 섹션의 해당 항목(적용 완료로 갱신됨) 참조.

- **#560 (`fde9beaa`)**: 하늘색 기반 radiometric zero point — 함정이었던
  모노 오검출을 `_mosaic_phase_is_rggb`의 `profile.mono` 선행 거부로 차단.
  imx462 SQM은 상수 zero point 유지(~+0.74 mag 왜곡 방지), MF 회귀 핀
  테스트로 고정. upstream 상수 재적합(15.25→15.159)으로 발행 SQM이
  −0.09 mag 이동하는 것은 수용(보정 개선).
- **#531 (`b7fa9e8a`)**: Focus 화면 4모드 재작성 수용 + MF 기능 3종
  (가이드 키, Gain 마킹메뉴, 주간 raw 렌더→Image 모드) 재구현.
  `positioning.py` 전체 채택이 MF 필드를 지우는 것을 테스트로 잡아 복원.
  문서는 post-#546 상태로 수렴(#546/#547 종결). 헤드리스 실기 검증:
  4모드 렌더, GAIN 마킹메뉴 진입, 디버그 카메라 솔빙 정상.
- 전체 스위트 1,105건 통과. 남은 미이식은 i18n 문자열 래핑 5곳(#562)뿐.

<a id="mf_change_history_ko--ssd1333-4축-밝기-이식-upstream-568570-부분-이식-2026-08-05"></a>
### SSD1333 4축 밝기 이식 (upstream #568+#570 부분 이식, 2026-08-05)

SSD1333(176×176) 채택 계획이 확정되어, 보류했던 upstream 밝기 재설계를
부분 이식했다. 커밋 `0cb8314e`(#568)+`31f0a5c5`(#570) — pre-charge 전압을
4번째 밝기 축으로 추가하고, by-eye 감마 대신 실측 응답 표면 기반 knee
커브·테이블 룩업으로 dimming 정책을 재적합한 것.

- 수용: `displays.py`/`ssd1333_device.py` 드라이버, 밝기 테스트 17건,
  모델 문서(ADR 0023 개정, `docs/ax/display/` CONTEXT+response).
- 제외: 측정 저널 44개, 러너 스크립트, 벤치 하네스
  (`panel_photometry`/`precharge_sweep`) ~6,250줄 — 광도계 리그가 있어야
  도는 단독 도구라 우리 패널 재특성화가 필요해질 때 upstream에서 가져온다
  (response 문서 상단 MF note로 안내).
- MF 우선 보존 확인: `display_spi()` Pi5 헬퍼, `__init__(bus_speed_hz)`
  (SSD1333 40MHz), MF `rotate=0`, `get_display(spi_speed_hz)`, 디스플레이
  자동감지 무접촉 — 병합 후 마커 전수 재확인.
- 부수 수리: `test_hardware_detect_display.py`가 7월 `get_i2c` 전환
  (cc7ae95e)을 안 따라가고 옛 `board` 속성을 패치한 채 방치돼 있었다
  (pytest 마커가 없어 `-m "smoke or unit"` 전체 실행에서 항상 제외 —
  그래서 안 보였음). `get_i2c` seam 기준으로 재작성하고 unit 마커 부여,
  프로브 예외 폴백 테스트 추가. 전체 1,047건 통과.
- 현 기기(SSD1351)에서는 동작 무변화. SSD1333 패널 연결 시: rev4 보드가
  아니면 BQ25895 마커가 없어 자동감지가 ssd1351로 남으므로, 서비스
  ExecStart에 `--display ssd1333`을 지정해야 한다.

<a id="mf_change_history_ko--릴리즈-체크를-포크-기준으로-전환-2026-08-05"></a>
### 릴리즈 체크를 포크 기준으로 전환 (2026-08-05)

Software 화면의 릴리즈 확인이 brickbots의 `release/version.txt`를 보고 있어서,
upstream이 2.6.1을 발행하면 포크 기기에 남의 릴리즈 기준 "Update Now"가 뜨는
상태였다 (2026-08-04 동기화 조사에서 미결로 기록). NixOS 마이그레이션 게이트
(`migration_gate.json`)도 같은 문제 — upstream이 `nixos_for_everyone`을 켜면
이 포크가 제외한 NixOS 마이그레이션이 원격으로 트리거될 수 있었다.

- `ui/software.py`: 두 URL 모두 `hjoungjoo/MF_PiFinder`의 release 브랜치로
  전환. 포크는 아직 release 브랜치가 없으므로 둘 다 404 (실측 확인).
- **"Unknown" 표시 분기 추가**: `update_needed()`는 파싱 불가 입력에
  의도적으로 True를 반환하므로(업스트림 테스트 고정), fetch 실패(네트워크
  다운 또는 release 미발행)가 곧장 "Update Now"로 이어졌다. 이제 릴리즈
  버전이 "Unknown"이면 "Release info / unavailable"을 표시하고 업데이트를
  권하지 않는다.
- i18n: 신규 msgid 2건(`Release info`, `unavailable`) 5개 언어 번역
  (AI-TRANSLATED 마커).
- 릴리즈를 낼 때는 release 브랜치에 `version.txt`만 있으면 체크가 그대로
  동작한다. `pifinder_update.sh`는 이미 origin(포크)의 release를 pull하므로
  수정 불요.
- **버전 체계 (같은 날 후속)**: upstream 버전과 구분하기 위해 `version.txt`를
  `m` 접두사 체계로 전환 (`2.6.0` → `m2.6.0`, 사용자 결정). 표시 경로
  (스플래시/웹/API)는 문자열 그대로라 무영향. `update_needed()`는
  `_semver_tuple()`로 분리하며 `m` 접두사를 벗기고 비교 — 안 벗기면
  `int("m2")` 예외가 오류 편향(True)으로 흘러 **업데이트 직후에도 영원히
  "Update Now"가 뜨는** 문제가 있었다. 접두사 케이스 테스트 4건 추가
  (동일 버전=False가 핵심). 마이그레이션 게이트는 버전 문자열이 아니라
  마커 파일 기준이라 무영향 확인.

<a id="mf_change_history_ko--설치-스크립트-이름-정리--pifinder_setupsh가-포크-설치본-2026-08-04"></a>
### 설치 스크립트 이름 정리 — `pifinder_setup.sh`가 포크 설치본 (2026-08-04)

포크 설치본이 `mf_pifinder_setup.sh`라는 별도 이름으로 있어서, 저장소를 받아
`pifinder_setup.sh`를 실행하면 upstream 릴리즈가 설치됐다. 대표 이름을 포크
설치본에 넘긴다.

- `mf_pifinder_setup.sh` → `pifinder_setup.sh`(포크 설치본이 기본).
- upstream 설치본은 `pifinder_setup.sh.bak`으로 보존 — upstream 재동기화 시
  비교 기준으로 쓴다.
- **클론 브랜치 수정**: `--branch mf_pifinder` → `--branch main`.
  `mf_pifinder` 브랜치는 origin(hjoungjoo/MF_PiFinder)에 더 이상 없어서,
  이 스크립트로 설치하면 clone 단계에서 실패하는 상태였다. 헤더의 설치 명령
  URL도 `main/pifinder_setup.sh`로 갱신.
- `python/tests/test_wifi_apsta_static.py`가 `pifinder_setup.sh`를 직접 읽는다 —
  새 내용에서도 6건 전부 통과(AP+STA 프로비저닝 동일).

<a id="mf_change_history_ko--문서-파일"></a>
### 문서 파일

<a id="mf_change_history_ko--docsmf_devmf_bookworm_install_komd"></a>
#### `docs/mf_dev/mf_bookworm_install_ko.md`

CM5 Bookworm 64-bit 설치 절차를 기준으로, `mf_pifinder` 브랜치의 Bookworm 설치
흐름을 한국어로 정리했다.

PiFinder 관련 포함 내용:

- PiFinder 저장소 위치와 branch
- PiFinder 의존성 설치
- PiFinder systemd 서비스 설치
- PiFinder 데이터 디렉터리 구성
- `pifinder`가 아닌 custom OS username/hostname 설치
- PiFinder 개발자 모드 테스트 명령
- PiFinder 주변기기 확인 명령
- CM5 Bookworm에서 PiFinder가 주의해야 할 boot config 경로

<a id="mf_change_history_ko--docsmf_devmf_bookworm_install_enmd"></a>
#### `docs/mf_dev/mf_bookworm_install_en.md`

`mf_bookworm_install_ko.md`의 영문판이다.

<a id="mf_change_history_ko--docsmf_devmf_change_history_komd"></a>
#### `docs/mf_dev/mf_change_history_ko.md`

현재 문서다. PiFinder 소스 수정 사항을 파일별로 상세 기록한다.

<a id="mf_change_history_ko--docsmf_devmf_change_history_enmd"></a>
#### `docs/mf_dev/mf_change_history_en.md`

소스 수정 히스토리의 영문판이다.

<a id="mf_change_history_ko--docsmf_devmf_pifinder_new_device_tasks_komd"></a>
#### `docs/mf_dev/mf_pifinder_new_device_tasks_ko.md`

새 Raspberry Pi 디바이스에서 `mf_pifinder` 브랜치를 설치하고 검증하기 위한
한국어 체크리스트다.

<a id="mf_change_history_ko--docsmf_devmf_pifinder_new_device_tasks_enmd"></a>
#### `docs/mf_dev/mf_pifinder_new_device_tasks_en.md`

`mf_pifinder_new_device_tasks_ko.md`의 영문판이다.

<a id="mf_change_history_ko--docsmf_devmf_pifinder_rpi4_pi5_compatibility_komd"></a>
#### `docs/mf_dev/mf_pifinder_rpi4_pi5_compatibility_ko.md`

Pi4/Pi5/CM5 보드 profile, 자동 설정값, 검증 절차를 한국어로 요약한 문서다.

<a id="mf_change_history_ko--docsmf_devmf_pifinder_rpi4_pi5_compatibility_enmd"></a>
#### `docs/mf_dev/mf_pifinder_rpi4_pi5_compatibility_en.md`

`mf_pifinder_rpi4_pi5_compatibility_ko.md`의 영문판이다.

<a id="mf_change_history_ko--최종-동작-기준"></a>
### 최종 동작 기준

현재 소스 기준으로 기대하는 PiFinder 동작은 다음과 같다.

- Bookworm에서는 PiFinder 코드가 `/boot/firmware/config.txt`를 우선 사용한다.
- Legacy 계열에서는 `/boot/config.txt` fallback이 유지된다.
- 설치/업데이트 스크립트는 현재 OS user의 `$HOME/PiFinder`, `$HOME/PiFinder_data`를 기준으로 동작한다.
- systemd와 Samba 설정은 설치 시 실제 OS user/home 경로로 렌더링된다.
- Raspberry Pi OS 설치 시 hostname을 장비별로 다르게 정하면 `<hostname>.local` mDNS 충돌을 줄일 수 있다.
- IMX462는 imx290으로 강제 변환하지 않고 직접 overlay로 다룰 수 있다.
- SSD1351 OLED 기본 SPI 속도는 `32MHz`다.
- SPI 장치가 `/dev/spidev10.0`으로 잡혀도 디스플레이 초기화가 가능하다.
- Pi camera 최초 gain은 원본처럼 카메라 프로파일의 `analog_gain`을 사용한다.
- `Camera Gain` 메뉴에서 runtime gain을 조정할 수 있고 `Profile`로 원본 기본 gain에 복귀할 수 있다.
- `GPS Settings > GPS Port`에서 gpsd serial device를 선택할 수 있다.
- 이 CM5 장비의 현재 GPS 포트는 `/dev/ttyAMA2`, baud는 `115200`이다.
- `Settings > Advanced > Keyboard`에서 Bluetooth 키보드 스캔/연결을 시도할 수 있다.
- USB 키보드와 Bluetooth 키보드는 기본 `keyboard_pi` libinput 경로로 PiFinder 입력에 매핑된다.
- USB/Bluetooth 키보드의 일반 알파벳은 검색/텍스트 입력 화면에서 실제 문자로 입력된다.
- USB/Bluetooth 키보드의 `Alt` 조합은 `ALT_*`로 처리된다.
- USB/Bluetooth 키보드의 `Left`, `Right`, `Enter/KP Enter`는 1초 이상 누르면 long key로 처리된다.
- USB/Bluetooth 키보드의 `Up`, `Down`은 1초 이상 누르면 일반 `UP/DOWN` 반복 입력으로 처리된다.
- USB/Bluetooth 키보드의 `Shift` 또는 `Ctrl` 조합 long key shortcut은 호환용으로 유지된다.
- paired/trusted Bluetooth 키보드는 PiFinder 서비스 시작 시 백그라운드에서 자동 재접속을 시도한다.
- `Settings > User Pref... > Language`에서 `한국어`를 선택할 수 있다.
- 한국어 UI는 Sarasa CJK 폰트를 사용하며, 언어 변경 직후 PiFinder를 재시작해 폰트를 다시 로드한다.
- 한국어 메뉴에서도 키보드 문자 입력은 현재 영문 알파벳 입력만 지원한다.
- 밝은 장면의 Focus 화면은 raw 기반 표시 fallback을 사용한다.
- 어두운 관측 장면의 Focus 화면은 기존 focus stretch 흐름을 유지한다.
- `scripts/camera_lcd_preview.py`로 PiFinder와 분리된 카메라-to-LCD 진단이 가능하다.

<a id="mf_change_history_ko--pi4-bookworm-호환성-후속-수정"></a>
### Pi4 Bookworm 호환성 후속 수정

Raspberry Pi 4 Bookworm 64-bit 실기 테스트에서 CM5용 GPS 포트 기본값이 Pi4와
맞지 않는 문제가 확인되어 보드별 자동 GPS 포트 선택을 추가했다.

- `default_config.json`의 `gps_port` 기본값을 `auto`로 변경했다.
- `python/PiFinder/board_config.py`를 추가해 `pi5_class`, `pi4`, `legacy` profile로
  보드별 UART overlay와 GPS 기본 포트를 정의했다.
- `sys_utils.get_default_gpsd_device()`는 `board_config` profile을 통해 CM5/Pi5는
  `/dev/ttyAMA2`, Pi4는 `/dev/ttyAMA3`, 그 외 보드는 `/dev/ttyAMA1`을 선택한다.
- `pifinder_paths.sh`도 같은 `pi5_class`/`pi4`/`legacy` profile helper를 사용해
  설치 시 UART overlay와 gpsd `DEVICES` 초기값을 정한다.
- `GPS Settings > GPS Port` 메뉴에 `Auto`와 `/dev/ttyAMA3` 항목을 추가했다.
- 설치 스크립트도 같은 보드 판별을 사용해 `/etc/default/gpsd`의 `DEVICES`를
  초기 설정한다.
- Pi4 테스트 장비에서는 `gpsd`가 `/dev/ttyAMA3`, 115200bps에서 u-blox 수신기를
  인식했다. 실내 테스트라 GPS fix는 아직 없고, 야외 안테나 테스트가 남아 있다.
- Bookworm BlueZ에서 `bluetoothctl paired-devices`가 동작하지 않아 Bluetooth
  장치 조회 명령을 `bluetoothctl devices Paired`로 변경했다.
- 테스트한 `K06 BLE Keyboard`는 paired/trusted/connected 상태에서도 기본 설정에서는
  `/dev/input/event*`가 생성되지 않았다.
- `/etc/bluetooth/input.conf`에서 `UserspaceHID=true`, `LEAutoSecurity=true`를
  활성화하고 Bluetooth 데몬을 재시작하자 `/dev/input/event4`가 생성됐고,
  `libinput debug-events`에서 방향키 입력을 확인했다.
- 설치 스크립트가 새 설치 시 같은 BlueZ input 설정을 적용하도록 반영했다.
- `docs/mf_dev/mf_pifinder_rpi4_pi5_compatibility_ko.md`를 추가해 Pi4/Pi5/CM5 보드별
  profile, 설치 시 적용값, 확인 절차를 한 문서에 정리했다.

<a id="mf_change_history_ko--검증한-항목"></a>
### 검증한 항목

소스 수준 검증:

```bash
bash -n \
  /home/pifinder/PiFinder/pifinder_paths.sh \
  /home/pifinder/PiFinder/pifinder_setup.sh \
  /home/pifinder/PiFinder/pifinder_update.sh \
  /home/pifinder/PiFinder/pifinder_post_update.sh \
  /home/pifinder/PiFinder/switch-ap.sh \
  /home/pifinder/PiFinder/switch-cli.sh \
  /home/pifinder/PiFinder/migration_source/v1.x.x.sh \
  /home/pifinder/PiFinder/migration_source/v2.1.0.sh \
  /home/pifinder/PiFinder/migration_source/v2.2.1.sh \
  /home/pifinder/PiFinder/migration_source/v2.2.2.sh \
  /home/pifinder/PiFinder/migration_source/v2.4.0.sh \
  /home/pifinder/PiFinder/migration_source/v2.6.0.sh

python3 -m py_compile \
  /home/pifinder/PiFinder/python/PiFinder/api_extensions.py \
  /home/pifinder/PiFinder/python/PiFinder/main.py \
  /home/pifinder/PiFinder/python/PiFinder/sys_utils.py \
  /home/pifinder/PiFinder/python/PiFinder/keyboard_interface.py \
  /home/pifinder/PiFinder/python/PiFinder/keyboard_pi.py \
  /home/pifinder/PiFinder/python/PiFinder/camera_interface.py \
  /home/pifinder/PiFinder/python/PiFinder/ui/base.py \
  /home/pifinder/PiFinder/python/PiFinder/ui/callbacks.py \
  /home/pifinder/PiFinder/python/PiFinder/ui/fonts.py \
  /home/pifinder/PiFinder/python/PiFinder/ui/bluetooth_keyboard.py \
  /home/pifinder/PiFinder/python/PiFinder/ui/menu_manager.py \
  /home/pifinder/PiFinder/python/PiFinder/ui/menu_structure.py \
  /home/pifinder/PiFinder/python/PiFinder/ui/textentry.py \
  /home/pifinder/PiFinder/python/PiFinder/ui/preview.py \
  /home/pifinder/PiFinder/python/PiFinder/displays.py \
  /home/pifinder/PiFinder/scripts/camera_lcd_preview.py
```

한국어 locale 검증:

```bash
pybabel compile -d python/locale -l ko
python3 - <<'PY'
import gettext
tr = gettext.translation('messages', 'python/locale', languages=['ko'])
_ = tr.gettext
for s in ['Start', 'Focus', 'Chart', 'Objects', 'GPS Port', 'Keyboard', 'Korean']:
    print(f'{s} -> {_(s)}')
PY
```

PiFinder 서비스 수준 확인:

```bash
systemctl status pifinder --no-pager --full
journalctl -u pifinder -n 80 --no-pager
```

화면/API 확인:

```bash
curl -fsS http://127.0.0.1/api/screen -o /tmp/pifinder_screen.png
curl -fsS http://127.0.0.1/api/camera/raw -o /tmp/pifinder_camera_raw.png
```

이 검증 명령들은 문서 기록용이며, 이 문서는 OS 설치나 하드웨어 조립 절차를 다루지 않는다.


---

<a id="mf_upstream_patch_reference_ko"></a>

## mf_upstream_patch_reference_ko.md

<a id="mf_upstream_patch_reference_ko--mf_pifinder-upstream-패치-기준-문서"></a>
## MF_PiFinder upstream 패치 기준 문서

> 아래 OS 언급은 당시 설계·전환 기준이다. 현재 MFNavis 설치는
> [Trixie 64-bit / Python 3.13 안내](setup.md#mf_trixie_install_ko)를 따른다.

작성일: 2026-07-03

이 문서는 `brickbots/PiFinder` 원본 소스가 변경되었을 때 `mf_pifinder`
브랜치(현재 개발 브랜치는 `main`)에 다시 적용하거나 유지해야 할 패치 내용을
빠르게 판단하기 위한 기준 문서이다.

목표:

- upstream 변경을 가져올 때 이미 적용한 패치와 의도적으로 제외한 패치를 구분한다.
- 충돌 가능성이 높은 파일과 기능 경계를 미리 확인한다.
- 다음 재동기화 작업에서 테스트와 검토 순서를 재사용한다.

<a id="mf_upstream_patch_reference_ko--현재-기준점"></a>
### 현재 기준점

로컬 기준 브랜치:

- `main` (과거 비교 기록의 브랜치명은 `mf_pifinder`)

비교 대상 upstream:

- `brickbots/PiFinder main`

<a id="mf_upstream_patch_reference_ko--2026-09-06-사용자-선택-912-선별-반영-68-제외"></a>
#### 2026-09-06: 사용자 선택 9~12 선별 반영, 6~8 제외

비교 기준은 앞선 1~5 작업과 동일한 MF `9dfd3a3f`, upstream/main `803d41eb`다.
사용자의 후속 선택에 따라 **6~8은 제외**, **9는 MF 충돌 분석 후 수동 이식**,
**10~12는 필요한 변경만 반영**했다. 아래 내용은 아직 커밋하지 않은 작업 트리다.

| 번호 | upstream | 처리 및 MF 보호 |
| --- | --- | --- |
| 6 | #625 렌즈 변경 시 solver 재시작 | 사용자 요청으로 제외. 기존 동작 유지. |
| 7 | #624 렌즈 설정 self-heal | 사용자 요청으로 제외. 기존 동작 유지. |
| 8 | #632 미확인 optical train의 FOV gate 비활성화 | 사용자 요청으로 제외. 기존 동작 유지. |
| 9 | #621 `ef7e7928` | Stellarium 초기화용 사이트·시각 명령과 응답 추가. MF TCP 버퍼, `MS` 기반 실제 GoTo, Align, 음수 0도 적위, 좌표 epoch, 실제 이동 상태·정지, 짧은 연결 가이드 동작 유지. [상세 분석](interfaces.md#mf_stellarium_push_port_analysis_ko). |
| 10 | #513 `ef4aab03`, #633 `3f94f65a` | Chart 목표 십자·주변 DSO·중앙 천체 읽기/상세 열기. 기존 MF 표시 방향·투영 수학·nearby 좌표 순서 보존. |
| 11 | #641 `803d41eb` | BOM의 BNO055 보드 경고만 적용. Adafruit 2472가 아닌 4646 필요. 실행 코드 변경 없음. |
| 12 | `81b4eae6` | `case/rev4/dovetail_bottom.stl` hardstop 수정 파일만 적용. Rev4 전원/보드 지원 패치는 가져오지 않음. |

<a id="mf_upstream_patch_reference_ko--9번-핵심-판단"></a>
##### 9번 핵심 판단

- upstream처럼 `Sd`에서 즉시 push/GoTo하면 MF의 Align 입력과 실제 마운트 제어에
  충돌한다. `Sr/Sd`는 좌표 보관, `MS`는 이동이라는 기존 MF 분리를 유지했다.
- `Q`는 응답만 보내는 함수가 아니라 기존 실제 정지 함수를 호출한다. 이동 상태
  `D`와 형식 `GW`도 기존 MF 정보를 반환하며 upstream의 고정 응답으로 바꾸지 않았다.
- 사이트·시각 초기화 명령은 GPS·시스템 시각·마운트 위치를 변경하지 않는다.
  접속 종료는 임시 좌표·사이트 echo만 지우고, 짧은 TCP 연결을 사용하는 기존
  가이드 이동은 중단하지 않는다. 기존 가이드 정지·시간 제한 경로는 유지했다.
- 모든 테스트는 소켓·설정·마운트 의존성을 격리했다. 실제 앱의 epoch 설정,
  연결 handshake와 물리적 이동은 현장 확인이 필요하다.

<a id="mf_upstream_patch_reference_ko--10번-중복충돌-검토"></a>
##### 10번 중복/충돌 검토

- `nearby.py`의 반경 검색과 #622 `[dec, ra]` 수정은 MF에 이미 있다. 파일을
  다시 적용하지 않았다. #513의 옛 좌표 순서를 가져오는 회귀도 피했다.
- `user_guide.rst`의 목표·주변 DSO 설명은 이미 있었으므로 중복 삽입하지 않고
  중앙 천체 기능 설명만 추가했다.
- 목표 십자는 DSO 밝기와 독립적이다. 관측 목록은 등급/개수 제한 없이 표시하며,
  주변 DSO만 시야별 등급 제한과 최대 20개 제한을 받는다. ID별로 중복을 제거한다.
- 중앙 천체는 화면에 표시한 마커 중에서 선택하며 선택 흔들림 방지와 이름 스크롤을
  사용한다. RIGHT로 해당 상세 화면과 거리순 목록을 연다. Chart 설정의
  `Center Object`(한국어 `중앙 천체`, 기본 On)로 표시를 끌 수 있다.
- 상세 화면/설정에서 복귀할 때 같은 solve 시각이어도 한 번 다시 그리도록 했다.
  세 화면 크기에서 설정 변경·목표 변경·무솔브·RA/Dec 표시 배치를 검사했다.
- `plot.py`는 기존 투영을 배열 계산으로 묶는 부분만 변경했다. 이전 MF scalar
  구현과 새 scalar/batch 결과가 RA 경계·고위도·회전에서 같은지 비교했다.

<a id="mf_upstream_patch_reference_ko--최종-검증과-적용-경계"></a>
##### 최종 검증과 적용 경계

- 전체 단위·스모크: **1,793 passed, 860 deselected**. 기존 tetra3 `np.math`
  DeprecationWarning 8건. 앞선 1~5 변경까지 포함해 재검증했다.
- Chart/상세/Align 관련 UI 통합 선택 실행: **7 passed, 2 skipped, 285 deselected**.
  두 skip은 실제 solve와 정렬별 순서를 요구하는 기존 UIAlign 키 순회 테스트다.
  Chart의 cold/warm 화면과 대상 추적 통합 테스트는 실행·통과했다.
- mypy: **192개 소스 오류 없음**. Ruff lint 및 변경 파일 포맷 검사 통과.
  전체 포맷 검사에서 지적하는 기존 `indi_goto_guide_service.py`는 수정하지 않았다.
- 한국어 메시지 컴파일 완료. BOM diff와 STL은 지정 upstream 변경만 반영했다.
  STL Git blob은 `d6eff844019b8c65683e49e0cfde66400d0095d4`로 원본과 일치한다.
- 실행 서비스 재시작, 실제 마운트/GPS/카메라 명령, 커밋·푸시는 하지 않았다.
  STL 출력물의 물리적 맞물림은 검사하지 않았다. 기존 `test_images/260903/` 유지.
- 아래 1~5 기록의 “6번 이후 미반영”은 해당 단계 종료 시점의 기록이다.
  현재 최종 선택 상태는 이 절을 우선한다.

<a id="mf_upstream_patch_reference_ko--2026-09-06-사용자-선택-15-선별-반영"></a>
#### 2026-09-06: 사용자 선택 1~5 선별 반영

비교 기준: MF `9dfd3a3f`, upstream/main `803d41eb`.
아래는 이번 작업 트리의 반영 내역이며 아직 커밋·푸시하지 않았다.
이전 문서의 마지막 기록(8/9) 이후 MF에서 별도로 수정된 소스까지 비교했다.
upstream 전체 병합이나 커밋 단위 일괄 cherry-pick은 하지 않았다.

| 번호 | upstream | 이번 반영 범위 / 기존 MF 보호 |
| --- | --- | --- |
| 1 | #571 `f5d70cf7` | 장비/GPS 폼 서버 검증, 소수 측정값, 오류 표시·입력 유지, 잘못된 장비 URL 인덱스 방어. MF INDI·LiveCam·위치 카탈로그·설정 원자적 저장 경로 유지. |
| 2 | #640 `97985713` | `python/tetra3` Git 추적 해제와 설치·업데이트·CI 링크 생성. MF의 기존 `set -e` 및 업데이트 실패 시 `False` 반환은 이미 반영되어 있으므로 재수정하지 않음. |
| 3 | #638 `e15662dc` | Update Now/Cancel 텍스트 두 곳만 기존 `msg_top/msg_bottom`에 맞춤. MF 릴리스 URL·m 버전 비교·업데이트 실패 처리 유지. |
| 4 | #614 `bcdc4981`, #620 `14d9ccaa` | Focus UP/DOWN 임시 노출 단계 조정과 하단 상태 표시. MF Auto Star·수동 Gain 복원을 위해 카메라 런타임 상태 보관 방식으로 조정. |
| 5 | #635 `bfeaeb0f` | STATUS의 GPS MSG, UBX 미지원/체크섬 오류 마커, 20 Hz 진단 이벤트 제한. MF 시간 유효성·동기화 경로와 위성 4개 값 유지. |

<a id="mf_upstream_patch_reference_ko--upstream-그대로-적용하지-않은-부분"></a>
##### upstream 그대로 적용하지 않은 부분

- **Focus 복원**: `set_exp:auto_star`를 다시 보내면 MF에서는 Gain이 센서
  프로파일로 초기화되고 수동 Gain 잠금이 풀린다. 따라서 카메라 프로세스가 진입
  직전 노출·Gain·자동노출 모드·Gain 선택을 보관하고 복원한다. 설정 파일은 쓰지
  않고 기존 solver 기반 제어기 객체도 교체하지 않는다. framewise Auto Star는
  복귀 시 제어 상태를 리셋하되 수동 Gain 잠금 여부를 유지한다.
- **Focus 수명주기**: 기존 메뉴는 새 화면을 처음 열 때 항상 `inactive()`를
  호출하지 않는다. Focus만 `covered()` 훅으로 해제하도록 하고 다른 화면의
  기존 수명주기는 유지했다. 최근 목록 바로가기로 스택을 줄이는 경우도 해제한다.
  각 방문에 토큰을 부여해 이전 화면의 지연 명령이 새 노출 선택을 덮지 못하게 했다.
  외부 노출/Gain/AE 명령이 들어오면 hold를 해제하고 기존 명령 처리가 우선한다.
- **Focus MF 기능**: Gain 퀵 메뉴, INDI Guide 종료 처리, 광각 원본 픽셀 경로,
  주간 포화 영상의 Bayer 평균·스트레치·회전을 유지했다. 주간 원본 영상도 새
  상태 표시줄 위에 전체 장면이 들어가도록 표시 크기만 조정했다.
- **tetra3 복구**: 공통 `scripts/ensure_tetra3_link.sh`를 사용한다. 이미 올바른
  상대 링크면 그대로 둔다. 기존 일반 파일·디렉터리·다른 링크는 삭제하지 않고
  `python/tetra3.backup.*/original`에 보존한다. submodule 대상이 없으면 기존
  경로를 건드리기 전에 실패한다. 과거 v2.1.0 마이그레이션이 상대 링크를 다시
  절대 링크로 바꾸던 한 줄은 제거했다.
- **GPS**: 위성 튜플 `(seen, used, in_view, top_cno)`, NAV-SAT 우선순위와
  NAV-SVINFO fallback, NAV-PVT 및 GPSD 시간 처리 분기를 보존했다. GPS MSG
  경과 시간은 main의 이벤트 수신 시점 기준이고 GPS의 시스템 시각 변경과 무관하다.
- **번역**: upstream locale 파일 전체를 덮지 않고 새 검증 문구의 한국어 번역만
  추가·컴파일했다. 기존 MF 번역은 유지했다.

<a id="mf_upstream_patch_reference_ko--반영검증-경계"></a>
##### 반영·검증 경계

- 실제 `python/tetra3` 링크는 유지되어 현재 import가 가능하다. Git index에는
  추적 해제에 필요한 삭제만 staged 상태이며 다른 변경은 unstaged 상태다.
- 실행 중 서비스 재시작, 실제 GPS 시각/위치 설정, 실제 카메라·마운트 명령,
  설치/업데이트 스크립트 실행은 하지 않았다. 장비 설정도 이 작업으로 저장하지 않았다.
- 기존 사용자 파일 `test_images/260903/`와 선택하지 않은 6번 이후 항목은 손대지 않았다.
- 새 테스트는 폼 요청을 Flask 테스트 클라이언트/격리 설정에서, 카메라 명령을
  가짜 백엔드에서, 링크 복구를 임시 디렉터리에서 검증한다.
- 실기기 확인은 별도로 필요하다: Focus 진입/UP·DOWN/복귀와 Auto Star·수동 Gain,
  176px 업데이트 화면, GPS 연결/단절 표시, 브라우저 장비 폼 입력.

최종 검증 결과 (2026-09-06):

- `cd python && .venv/bin/python -m pytest -q -m 'unit or smoke'`:
  **1,612 passed, 857 deselected**. 기존 tetra3의 `np.math` 사용에 따른
  DeprecationWarning 8건만 발생했다. 웹 브라우저/실기기 통합 테스트는 제외했다.
- `.nox/type_hints/bin/mypy PiFinder`: **191개 소스 오류 없음**.
- Ruff lint 전체 통과. 변경한 Python 파일의 포맷 검사 통과. 전체 포맷 검사는
  기존 HEAD와 동일한 `PiFinder/indi_goto_guide_service.py` 한 파일만 지적하며,
  요청 범위 밖인 해당 파일은 수정하지 않았다.
- 변경된 설치·업데이트·마이그레이션·링크 스크립트 `bash -n` 통과.
  실제 설치나 업데이트는 실행하지 않았다.
- 한국어 메시지 `pybabel compile -d locale -l ko` 통과.
- 실제 작업 트리에서 `import tetra3` 성공. 링크 복구 테스트는 새 링크·멱등성,
  기존 절대/끊어진 링크·파일·폴더 보존, submodule 미초기화 시 무변경을 확인했다.
- `git diff --check`와 staged diff 검사 통과.

2026-07-03 기준 최근 반영 상황:

- upstream selected commits applied:
  - NixOS PR build CI (이후 미사용으로 2026-09-28 워크플로 제거)
  - case/accessory STL changes
  - observing list CSV import improvements
  - UTC-aware datetime handling
  - Set Time/Date self-gate when no location lock exists
  - OBJ_TYPES single-source refactor
- local MF-only patch:
  - SSD1333 automatic display detection, separated from the larger Rev-4 hardware patch

2026-07-13 추가 반영:

- upstream selected commits applied:
  - Stellarium 2.0 observing list import (#527, `39412ac`)
  - catalog filter cache: skip re-filtering unchanged catalogs on list open (#526, `f704a26`)
  - UBlox GPS NAV-SVINFO/NAV-SAT 디코딩 수정 (#524, `9cb0060`) — `gps_ubx_parser.py`/
    테스트는 clean 적용, `gps_ubx.py`는 NAV-PVT 핸들러에서 MF 시간 처리와 upstream
    numSV used-count를 둘 다 유지하도록 수동 병합
- 검토 후 이번엔 제외:
  - NixOS 마이그레이션 3건 (#523 `e22ac48`, #521 `0621d15`, #517 `02e6b30`) — MF의
    NixOS 이관 지원 여부 미결정
  - state datetime tz 수정 (#508, `e64f0b6`) — timez.py 기준 이미 반영됨, 재적용 시
    제외한 Rev-4 state.py 변경이 딸려오므로 하지 않음
  - Rev-4 hardware enablement (#498, `e82b809`) — 정책상 제외 유지

2026-07-29 추가 반영 (upstream `534fc809..a132bc36`, 20 commits 검토):

- upstream selected commits applied (clean cherry-pick):
  - DeepskyLog eyepiece import AttributeError 수정 (#529, `f68de732`) —
    `server.py` 한 줄 수정 clean 적용. 동봉된 테스트의 FakeConfig에 MF server가
    읽는 `get_option()`을 보강 (`be252f29`)
  - Polar Alignment 가이드 field feedback 반영 (#518, `56d428f6`)
  - filtered list 갱신 유지 + 천체별 observed status 파생 (#528, `d2c566b6`) —
    catalogs/object_list clean 적용, 관련 테스트(cache/cursor/identity) 통과
  - cedar shmem RemoveIPC 복구 (#548, `1afbd3c2`) — **수동 이식으로 적용 완료
    (2026-07-29)**. SSH 로그아웃 시 logind `RemoveIPC=yes`가
    `/cedar_detect_image` shmem을 삭제해 이후 solve가 전부 실패하던 문제.
    이식 내용: `PFCedarDetectClient._del_shmem` 오버라이드(사라진 세그먼트를
    정상 해제로 처리), INTERNAL 폴백 시 1회 경고 로그, 인라인 폴백에
    `detect_hot_pixels` 유지, `pifinder_setup.sh`의 `RemoveIPC=no` drop-in.
    마이그레이션은 upstream `v2.6.1.sh` 대신 MF 규칙의 `mf_removeipc.sh`로
    이식(멱등이라 이후 upstream v2.6.1이 와도 무해). 테스트
    `test_solver_cedar_client.py`는 라이브 solver의 실제 세그먼트를 건드리지
    않도록 테스트 전용 shmem 이름을 쓰게 수정해서 가져옴. 개발 기기에는
    drop-in을 즉시 적용하고 마이그레이션 마커를 남김
  - 위치 입력 comma/period decimal (#536, `447aec8b`) — **수동 이식으로 적용
    완료 (2026-07-29)**. `parse_coordinate()` 서버 헬퍼, location 입력
    type=text inputmode=decimal 전환, JS `normalizeDecimal()` 정규화.
    MF location catalog 마크업과의 충돌만 수동 해소, 변경 내용 자체는 동일.
    두 스타일시트 모두 `input[type=text]`를 스타일링하므로 Red Night 테마
    영향 없음. `test_server_coordinates.py` 동봉
  - SSD1333 3축 밝기 (`a132bc36`) — **적용 완료 (2026-07-29)**. gray scale
    ceiling을 3번째 밝기 축으로 추가, dim floor 13400:1 범위. `displays.py`
    충돌 해소: import 병합 + MF의 `__init__(bus_speed_hz)` 시그니처(Pi5 SPI
    `display_spi()` 헬퍼) 유지. upstream ADR `0023-ssd1333-brightness`는 새
    번호 규칙(숫자=upstream)에 따라 그대로 수용. 밝기 매핑 단조성/레지스터
    범위는 fake device 시뮬레이션으로 확인, 실제 SSD1333 패널 실측은 미실시
  - SQM 스택 (#532 `b5b16883`, #544 `69fe28c2`, #542 `b36cb8c6`,
    #543 `5ef6a1b2`) — **수동 이식으로 적용 완료 (2026-07-30, 5단계)**.
    radiometer 우선 SQM(솔브 독립 1 Hz 발행), raw-green 측광, Gaia-G/B−V
    색보정, wing/cloud/black-level 추정기, raw 전용 보정 위저드,
    full-sensor 스윕. 상세 계획·리스크·커밋은
    [mf_sqm_stack_port_plan_ko.md](camera.md#mf_sqm_stack_port_plan_ko).
    #542가 revert한 cedar hunk는 적용하지 않았고(우리 hybrid+RemoveIPC
    유지), #543은 post-#544 최종 상태 기준 이식으로 자동 포함. rev4
    rename hunk는 #539와 함께 보류 유지. **잔여 완료 조건: bias 238 기준
    야간 재검증(웜맵/σ) + SQM 위저드 1회 실행**
- 충돌로 보류 (수동 병합 필요, 다음 라운드 대상):
  - Focus raw multi-star 뷰 (#531, `70e243b9`) — MF가 수정한 `ui/preview.py`와 충돌
  - quick start focus 문서 (#546, `e9cbfe52`) — #531의 새 focus 화면을 전제로 한
    문구라 #531과 함께 판단
  - keypad matrix 분리 (#551, `a90311e7`) — `keyboard_pi.py` 충돌, rev4 power
    button GPIO 처리가 딸려옴
- 정책상 제외 (rev4 battery/hardware 제외 정책 유지):
  - battery ADR/CONTEXT 문서 (`cb79a5bd`, `08da007d`) — `docs/ax/battery/` 자체가
    MF에 없음
  - low-battery UX (#541 `46e658b4`), warning latch (#549 `afcb80ad`) —
    `battery_bq25895.py` 미포함
  - bringup 벤치 검증 (#552 `81a522fe`, 문서 #550 `28f52a5a`) — `keypad`,
    `battery_bq25895`, `sound` 모듈 의존
  - rev4 rename (#539 `0edff3bb`) — rev4 enablement 미적용 상태에서 rename만
    가져오면 diff만 커짐

2026-08-04 추가 반영 (upstream `a132bc36..4a83d25b`, 2.6.1 릴리즈 포함 31 commits 검토):

- upstream selected commits applied (clean cherry-pick):
  - catalog_objects 인덱스 (#564, `8d357eb6`) — object 상세 진입 스톨 수정.
    이 Pi 실측 조회 36ms → 1.1ms. DB 블롭까지 수용(런타임 백필이 no-op이
    되고, git 추적 파일인 `astro_data/pifinder_objects.db`가 기기에서
    dirty해지는 문제 회피)
  - SQM 스윕 노출 정착 (#561, `351129a3`) — imx462가 노출 변경 후 3프레임
    stale인데 2프레임만 플러시하던 문제. **스윕 재촬영/위저드 실행 전에
    선행 적용 필수였음(이제 적용됨)**
  - focus 기법 문서 (#547, `3e23052b`) — 보류 중이던 #546의 release 브랜치
    백포트판. 현행(pre-#531) focus 화면 기준이라 clean 적용. #546 자체는
    제외로 종결
  - ADR 0020 3중 충돌 정리 (`0b76b3c7`) — upstream이
    `0020-sqm-raw-green-*`→`0024`, `0020-filter-freshness-*`→`0025`로 개명.
    MF 트리에도 0020이 두 개 공존하던 실결함이 해소됨. `m` 접두사 규칙과
    무충돌(m0024 ≠ 0024). plain 0020은 이 트리에서 미할당 상태로 남음
    (upstream SOC ADR 몫). `mf_sqm_stack_port_plan_ko.md`의 인용도 갱신
- 수동 병합으로 적용:
  - GPS NAV-SAT latch/floor (#563, `e87abe49`) — NAV-SAT 5초 신선도 창,
    `_publish_sats()` seen>=used floor(NAV-PVT 선착 시 "0/9" 표시 수정 —
    MF 수신기의 정상 기동 순서), 파서 uSat 품질 게이트 정합, timezone
    미해석 시 UTC 폴백(커밋 크래시 수정). MF의 4원소 sats(in_view,
    top_cno)와 `_gps_time_message()` 유지한 채 병합.
    **의도적 미수용: `ui/timeentry.py` 타임존 표시줄 복원 hunk** — MF가
    128px 화면 오버런 때문에 일부러 지운 줄이라 되살리지 않음(동봉 표시
    테스트도 미이식). 다음 동기화에서 재론 금지
- 검토 후 이번엔 제외/보류 (상세: 2026-08-04 조사):
  - SQM 색보정 zero point (#560, `b28f7d9d`) — **2026-08-05 mono 가드와
    함께 적용 완료** (보류 해제). `_mosaic_phase_is_rggb`가 `profile.mono`를
    먼저 거부 — 가드 없이는 실측 모노 imx462(R/G=1.000 고정)에 색보정이
    켜져 SQM이 조용히 ~+0.74 mag 이동했음(함정 확인 후 차단). imx462/
    imx290은 상수 zero point 유지(upstream 재적합값 15.159, 기존 15.25
    대비 −0.09), hq는 색보정 전체 수용. 테스트: shipped-profile 불변
    테스트를 모노 거부 기준으로 재작성, 샘플러 역학 테스트 4건은
    `replace(mono=False)`로 색경로 유지, MF 회귀 핀
    (`test_measured_mono_imx462_keeps_the_constant_zero_point`) 추가.
    오프라인 재적합 도구(`radiometric_fit.py`)도 수용 — 향후 모노 전용
    zero point 재적합에 필요
  - i18n 2.6.1 패스 (#562, `26e79dc3`) — `.po`/`.mo`는 절대 수용 금지
    (언어당 527 msgid 소실, 실번역 35~36건 파괴). `ui/software.py` 2곳 +
    `ui/telemetry_list.py` 3곳 문자열 래핑만 후보로 남김(ko 비용: 신규
    msgstr 3건)
  - SSD1333 4축 밝기 (#568 `03e2314d` + #570 `3b4a7974`) — **2026-08-05
    부분 이식으로 적용 완료** (SSD1333 채택 계획 확정에 따라 보류 해제).
    드라이버(displays.py, ssd1333_device.py)+테스트(17건)+모델 문서
    (ADR 0023, docs/ax/display/)만 수용. 측정 저널 44개·러너 스크립트·
    벤치 하네스(panel_photometry/precharge_sweep, ~6,250줄)는 제외 —
    재특성화가 필요하면 upstream 커밋에서 가져온다(ssd1333-response.md
    상단 MF note). CONTEXT-MAP 충돌은 Display 항목만 수용(Battery/Sound/
    NixOS/Bring-up은 제외 컨텍스트). MF displays.py 수정(display_spi,
    bus_speed_hz, rotate=0, get_display spi_speed_hz) 전부 보존 검증.
    부수 발견: MF 자동감지 테스트(test_hardware_detect_display)가
    cc7ae95e의 get_i2c 전환을 안 따라간 채 방치돼 있었음(마커 없어 전체
    실행에서 항상 제외) — get_i2c seam 기준으로 재작성+unit 마커 부여
  - 2.6.1 릴리즈 커밋 5건 (`2fbc5acc` 등) — 릴리즈 문서/버전. 내용 상당수가
    rev4 등 미포함 기능. version.txt는 m 접두사 체계로 전환(m2.6.0, 2026-08-05). **주의: upstream이
    2.6.1을 release 브랜치에 발행하면 `ui/software.py:164`의 릴리즈 체크가
    brickbots 기준 "Update Now"를 띄우게 됨 — 2026-08-05 해결: 릴리즈
    체크/마이그레이션 게이트 URL을 포크로 전환, "Unknown" 표시 분기 추가**
  - bringup 도구 (#556 `2c8f2606`, `ff57fb22`, `8c813f94`) — import 단계
    실패(`keypad`/`battery_bq25895`/`sound`/`types.hardware`/`types.sound`
    부재). #552 제외 결정의 재확인. `ff57fb22`는 기제외 `81a522fe`와
    바이트 동일
  - keypad matrix 분리 (#551) — **보류 사유 정정**: rev4 power GPIO가
    딸려오는 게 아니라(그건 base에 이미 있던 컨텍스트), 실제 장벽은
    MF 4열(20키) vs upstream 5열(25키) 매트릭스 상수 자체. 수용 시 키패드
    오배선이라 제외로 격상. 유일 소비자가 제외된 bringup 도구
  - Focus multi-star (#531, `70e243b9`) — **2026-08-05 적용 완료** (보류
    해제). 새 4모드 화면(stars/single/image/stats) 수용, MF 기능 3종을 새
    화면 위에 재구현: GuideKeyMixin 유지, camera_gain 마킹메뉴(right) 유지,
    주간/포화 프레임 raw 렌더 경로는 Image 모드로 이식(기존 stretch EMA
    대신 프레임 median≥220 기준 — 새 화면이 stretch 상태를 제거했기 때문).
    `types/positioning.py`는 upstream 실제 델타(독스트링 한 문장)만 수용 —
    전체 채택 시 MF 필드(SolveDiagnostics.Centroids/solve_path, ImuSample
    보정 텔레메트리)가 소실되는 것을 테스트 4건 실패로 확인 후 복원.
    문서(quick_start/troubleshooting)는 post-#546 상태로 수렴 — 새 화면
    채택으로 #547의 구화면용 문구가 대체되고, #531 전제로 제외했던
    #546(`e9cbfe52`)도 함께 종결. 헤드리스 실행으로 4모드 렌더·GAIN
    마킹메뉴·솔빙 정상 확인, 전체 1,105건 통과
  - NixOS/CI 8건, 이미 반영된 docs/case 커밋들 — 해당 없음 또는 기반영

2026-08-09 추가 반영 (upstream `4a83d25b..7eaf058c`, 12 commits 검토):

- **정책 변경 (2026-08-09, 사용자 결정)**: rev4 하드웨어 관련 변경의 수용을
  **허용**한다. 단 두 가지 조건이 붙는다 — (1) 현재 소스의 동작에 문제가
  없어야 하고, (2) 충돌이 발생하면 임의 병합하지 말고 사용자에게 보고해
  결정을 받는다. 이전의 "rev4 전면 제외" 정책은 이 항목으로 대체된다.
- upstream 브랜치 상태: `upstream/release`가 `upstream/main`에 수렴했다.
  release에만 있고 main에 없는 커밋은 0건이며, release는 main보다 `7eaf058c`
  하나 뒤에 있을 뿐이다. `v2.6.1` 태그 자체(`8c6ae841`, 08-02)는 이미
  2026-08-04 라운드에서 검토 완료였고, "2일 전 업데이트"의 실체는 태그가
  아니라 08-06~08-07에 release에 얹힌 문서/자산 커밋 11건이다.
- 이번 라운드의 성격: **런타임 파이썬 코드 변경 0건**. 전량 rev4 사용자
  매뉴얼 재작성, rev4 하드웨어 설계 자산, 문서 작성용 Claude 스킬 개선이다.
  적용 후 `git diff --name-only`로 `python/` 이하 변경이 없음을 확인했다.
- 적용 완료 (8건, clean cherry-pick):
  - `511b599d` (#572) rev4 문서 갱신 계획 + `pf_remote.py` `--display`/`-fb`
    플래그. **충돌 1건을 무손실로 해소**: `product-knowledge-base.md`는 포크가
    merge-base 이후 한 번도 수정한 적이 없어(diff 0) MF 저작 내용이 존재하지
    않는다. 충돌 원인은 MF 드리프트가 아니라 제외한 `0edff3bb`(rev4 rename)를
    건너뛴 순서 문제라, upstream의 `511b599d` 시점 버전을 그대로 채택했다.
    **주의: `pf_remote launch -fb`는 이 포크에서 실패한다** — `main.py`에
    `-fb/--fakebattery`가 없다(배터리 미이식). 기본 경로(`--display
    headless_176`)는 포크에 `DisplayHeadless176`이 실재하므로 정상 동작한다
  - `de285d96` (#574) 내부 브링업 레퍼런스 `docs/ax/bringup.md` + CONTEXT-MAP
  - `f71ff317` (#575) rev4 화면·조이스틱, "Which PiFinder do I have?" (WP3)
  - `746edad9` (#577) Power & Charging 전면 재작성 (WP1)
  - `b138894f` (#578) SD 카드 — rev4 외부 슬롯 우선, v3/v2.5 별도 절 + **신규
    v2.5 절차**(기존에 없던 정보)
  - `5460cc60` (#582) 누락 rev4 상호 링크 2건
  - `7eaf058c` (#585) 문서 스킬 Simplified Technical English 하우스 스타일.
    `.claude/skills/`는 포크가 merge-base 이후 무수정이라 드리프트 없음
  - `aac4a7fb` rev4 하드웨어 설계 자산(KiCad/거버/STL/f3z, 약 19MB).
    런타임 영향 0
- 충돌 3건 — **사용자 결정 후 수동 병합으로 적용 완료 (2026-08-09)**:
  - **문서 방침 결정 (사용자)**: rev4 문서는 **upstream 그대로 유지**한다.
    포크에 없는 기능(배터리 잔량 표시·충전·저전력 경고·자동 종료, 사운드)을
    설명하는 절이 생기지만, "미지원" note를 달지 않고 upstream diff를 최소로
    유지하는 쪽을 택했다. rev4 소프트웨어를 이식하면 문서가 자동으로 맞는다.
    **따라서 다음 동기화에서 "문서가 없는 기능을 설명한다"는 이유로 되돌리지
    말 것** — 의도된 상태다
  - `016e0282` (#576) rev4 사운드/Volume — `menu_map.rst` 충돌.
    **결정: MF의 IMU Settings 트리 유지 + upstream GPS Baud Rate 문구 채택 +
    Volume 항목은 제외.** menu_map은 실제 메뉴 구조를 그리는 문서라 포크
    메뉴와 일치시켰다(포크엔 `sound.py`도 Volume 메뉴 항목도 없음).
    `user_guide.rst`의 `Sounds` 절은 문서 방침 결정에 따라 upstream 그대로
    수용했다 — menu_map만 실물 기준, 산문은 upstream 기준이라는 비대칭이
    의도된 것임에 주의
  - `84a2fbaf` (#583) rev4 사진 배치 — `troubleshooting.rst` 충돌.
    **결정: upstream의 신규 "Align (Day)" 진단 산문을 받고, 그 Camera Type
    불릿에 MF의 Mono/Color 안내 문장을 복원.** 복원 시 em-dash를 문장 분리로
    바꿔 방금 도입한 STE 하우스 스타일(`7eaf058c`)에 맞췄다 — 의미는 동일
  - `43200f86` (#584) v3 매뉴얼 아카이브 링크(`conf.py`의 `|v3_docs|` 치환자)
    — 예상대로 **순수 cascade**였다. `84a2fbaf` 해소 후 clean 적용됨
- 이번 라운드 제외:
  - `27ca9624` (#573) ADR 0020 배터리 프로파일링 + SOC_LUT 주석 —
    `battery_bq25895.py`와 `docs/adr/0020-soc-as-runtime-fraction.md` **둘 다
    포크에 부재**. rev4가 허용으로 바뀌었어도 이 커밋만 단독 적용하는 것은
    불가능하다(존재하지 않는 파일에 대한 수정). 배터리 수용은 `#498`/`#541`/
    `#549` 일괄 이식 결정이 선행되어야 한다
  - `0edff3bb` (#539) rev4 rename — 이번 라운드에서 의도적으로 제외.
    `main.py`, `config.py`, `hardware_detect.py`, `splash.py`, `state.py`,
    `ui/menu_structure.py`, `camera_interface.py` 등 **MF가 수정한 런타임
    파일 다수**를 건드리고 PiFinder Type 식별자를 바꾼다. "현재 동작 무손상"
    조건상 문서 라운드와 섞으면 안 된다. rev4 본체 이식을 결정할 때 함께 다룬다
- 결과: 신규 12건 중 **11건 적용, 1건 제외**(`27ca9624` — 적용 대상 파일 부재)
- 검증 (2026-08-09, 충돌 해소 후 재실행):
  - `python/` 이하 변경 0건 — 런타임 회귀 가능성 구조적으로 없음
  - Sphinx가 미설치라 실제 빌드는 못 했고, 대신 구조 검증을 돌렸다:
    `:ref:` 타깃 전수 확인(244개 라벨, dangling 0건), `|치환자|` 정의
    `min_software`/`v3_docs` 2건에 미정의 사용 0건, `.. image::` 264건 전수
    확인(누락 0건 — `includes/` 상대경로는 포함 문서 기준으로 해석되는 정상
    케이스), 잔존 충돌 마커 0건
  - `pf_remote.py`/`screenshot_to_doc.py` py_compile 통과
  - `test_menu_struct.py`, `test_hardware_detect_display.py`,
    `test_obj_types_docs.py` 12건 통과
  - 커밋만 했고 push하지 않았다. 롤백 기준점: `5b49bc82`
- 다음 라운드로 넘긴 결정 (rev4 본체 이식):
  - `#498`(rev4 hardware enablement) / `#541`·`#549`(배터리 UX) /
    `#551`(keypad matrix) / `#552`·`#556`(bringup) / `0edff3bb`(#539 rename)
    — rev4 허용 정책으로 바뀌었으니 이제 "정책상 제외"가 아니라 **미결정
    백로그**다. 문서는 이미 rev4를 설명하고 있으므로, 이식하면 문서와
    소프트웨어가 비로소 일치한다. 착수 시 `0edff3bb`를 먼저 처리해야
    `product-knowledge-base.md` 류의 순서 충돌이 재발하지 않는다

ADR 번호 규칙 (2026-07-29 확정):

- upstream과 MF가 각자 ADR을 추가하면서 0020부터 번호가 갈라졌다 (upstream
  0020=SOC runtime fraction, 0021=blind-floor shutdown, 0023=SSD1333
  brightness vs MF의 star-count/auto-exposure/solve-hold/cedar+SEP hybrid).
- 그래서 번호 공간을 분리했다: **MF가 자체 작성하는 ADR은 `m` 접두사**를
  쓴다 (`docs/adr/mNNNN-*.md`). 기존 MF ADR 4건은 번호를 유지한 채
  `m0020`~`m0023`으로 개명했고, 새 MF ADR은 `m0024`부터 이어간다.
- **upstream ADR은 체리픽 시 번호를 그대로 유지**한다 — upstream 커밋
  메시지/문서가 인용하는 번호가 우리 트리에서도 유효해야 하기 때문.
  숫자만 있는 ADR = upstream 것, `m` 접두사 = MF 것으로 출처가 구분된다.
- 2026-07-29 이전의 커밋 메시지가 말하는 "ADR 0020~0023"은 문맥에 따라
  MF 것(현재 m0020~m0023)일 수 있다.

주의:

- 이 문서는 전체 변경 히스토리 문서가 아니다.
- 상세 기능 기록은 `docs/mf_dev/mf_change_history_ko.md`를 참고한다.
- 이 문서는 upstream 재동기화와 패치 재적용 기준에 집중한다.

<a id="mf_upstream_patch_reference_ko--upstream에서-이미-반영한-변경"></a>
### upstream에서 이미 반영한 변경

다음 upstream 변경은 `mf_pifinder`에 반영되어 있다.

| 영역 | 상태 | 비고 |
| --- | --- | --- |
| NixOS PR build CI | 워크플로 제거됨 | 최초 반영 후 미사용으로 2026-09-28 워크플로 제거. manifest script는 유지 |
| case/accessory files | 적용됨 | 코드 영향 없음. STL/JPG/README 변경 |
| Observing list CSV import | 적용됨 | `obslist_formats.py`, docs, tests 적용 |
| Observing list Stellarium 2.0 import | 적용됨 | #527 `39412ac`. `obslist_formats.py` Stellarium reader 확장 |
| catalog filter cache | 적용됨 | #526 `f704a26`. `catalog_base.py` 추가, 변경 없는 카탈로그 재필터 생략 |
| UBlox GPS NAV-SVINFO/NAV-SAT 디코딩 수정 | 적용됨 | #524 `9cb0060`. `gps_ubx_parser.py` 오프셋 수정, `gps_ubx.py` NAV-PVT 수동 병합 |
| UTC-aware datetime | 적용됨 | `timez.py` 추가, `state.py`, `server.py`, callback 시간 처리 변경 |
| Set Time/Date self-gate | 적용됨 | 위치 lock이 없으면 수동 시간/날짜 설정 UI가 inert 상태로 메시지 표시 |
| OBJ_TYPES single-source | 적용됨 | Type filter menu가 `OBJ_TYPES`에서 생성됨 |

이 변경들은 다음 upstream sync 때 중복 적용하지 않는다.

<a id="mf_upstream_patch_reference_ko--upstream에서-의도적으로-제외한-rev-4-하드웨어-변경"></a>
### upstream에서 의도적으로 제외한 Rev-4 하드웨어 변경

upstream의 Rev-4 hardware enablement 패치는 아직 전체 적용하지 않았다.

제외한 기능:

- BQ25895 battery telemetry
- BQ25895 fast-charge runtime configuration writes
- sound/earcon buzzer subsystem
- GPIO15 hardware power button
- GPIO14 gpio-poweroff latch
- battery titlebar icon
- Raspberry Pi red power LED shutdown

제외 이유:

- Rev-4 전용 GPIO/I2C/PWM 가정이 Pi4/Pi5/CM5 호환 경로에 영향을 줄 수 있다.
- GPIO14 poweroff latch는 하드웨어 배선이 맞지 않으면 위험할 수 있다.
- sound/earcon은 관측 환경에서 기본 OFF 정책이 필요하다.
- battery charger write 동작은 하드웨어 검증 후 별도 옵션으로 넣는 것이 안전하다.

부분 적용한 기능:

- SSD1333 display auto-detection only

현재 구현:

- `python/PiFinder/hardware_detect.py`
- `python/PiFinder/main.py`
- `python/PiFinder/splash.py`
- `python/tests/test_hardware_detect_display.py`

동작:

- BQ25895 I2C address `0x6A` ACK를 Rev-4/SSD1333 display marker로 사용한다.
- 감지 성공 시 기본 display hardware는 `ssd1333`이다.
- 감지 실패, Blinka import 실패, GPIO/I2C 접근 실패 시 기존 기본값 `ssd1351`로 fallback한다.
- `--display` 명령행 옵션이 있으면 자동 감지보다 우선한다.

다음에 Rev-4 변경을 추가로 가져올 때:

- battery/sound/power/latch를 한 번에 병합하지 않는다.
- `HardwareCapabilities` 같은 공통 타입을 추가하더라도 기존 `hardware_detect.py`의
  import-safe fallback을 유지한다.
- GPIO14 poweroff latch는 별도 설치 옵션과 명확한 문서가 필요하다.

<a id="mf_upstream_patch_reference_ko--mf-전용-주요-패치-영역"></a>
### MF 전용 주요 패치 영역

다음 영역은 upstream에 아직 없거나 MF 브랜치에서 다르게 동작한다.
upstream 변경 시 이 기능들이 깨지지 않는지 우선 확인한다.

<a id="mf_upstream_patch_reference_ko--platform--bookworm--pi4-pi5-cm5"></a>
#### Platform / Bookworm / Pi4-Pi5-CM5

주요 파일:

- `pifinder_paths.sh`
- `pifinder_setup.sh`
- `pifinder_update.sh`
- `pifinder_post_update.sh`
- `python/PiFinder/board_config.py`
- `python/PiFinder/boot_config.py`
- `python/PiFinder/sys_utils.py`
- `python/PiFinder/displays.py`
- `pi_config_files/*.service`

보존해야 할 정책:

- Bookworm boot config는 `/boot/firmware/config.txt` 우선, legacy는 `/boot/config.txt`.
- `PiFinder_data`와 systemd/Samba 경로는 현재 OS 사용자 기준으로 렌더링한다.
- Pi4/Pi5/CM5 보드 profile에 따라 GPS UART default가 달라진다.
- Pi5/CM5는 OLED CS 충돌을 피하기 위해 `uart2-pi5` 경로를 사용한다.
- SPI 장치는 `/dev/spidev0.0`과 `/dev/spidev10.0` 모두 지원한다.

<a id="mf_upstream_patch_reference_ko--camera--focus--gain"></a>
#### Camera / Focus / Gain

주요 파일:

- `python/PiFinder/camera_interface.py`
- `python/PiFinder/ui/preview.py`
- `python/PiFinder/ui/menu_structure.py`
- `python/PiFinder/ui/callbacks.py`
- `scripts/camera_lcd_preview.py`

보존해야 할 정책:

- focus preview와 camera gain runtime/profile 설정을 유지한다.
- LCD preview script는 하드웨어 디버깅용으로 유지한다.
- upstream camera 변경 시 exposure/gain menu callback 충돌을 확인한다.

<a id="mf_upstream_patch_reference_ko--korean-localization"></a>
#### Korean localization

주요 파일:

- `python/locale/ko/LC_MESSAGES/messages.po`
- `python/locale/ko/LC_MESSAGES/messages.mo`
- `python/PiFinder/ui/fonts.py`
- `python/PiFinder/ui/menu_structure.py`

보존해야 할 정책:

- 언어 메뉴에서 `ko`를 유지한다.
- CJK font와 restart 안내 흐름을 유지한다.
- upstream i18n 업데이트 후 Korean `.po` drift를 확인한다.

<a id="mf_upstream_patch_reference_ko--bluetooth--usb-hid-keyboard"></a>
#### Bluetooth / USB HID keyboard

주요 파일:

- `python/PiFinder/keyboard_interface.py`
- `python/PiFinder/keyboard_pi.py`
- `python/PiFinder/ui/bluetooth_keyboard.py`
- `python/PiFinder/ui/textentry.py`
- `python/PiFinder/ui/menu_structure.py`

보존해야 할 정책:

- libinput 기반 HID keyboard event mapping을 유지한다.
- Bluetooth scan/pair/connect UI를 유지한다.
- INDI guide 이동용 `qwe/asd/zxc` 추가 키맵을 유지한다 (Guide page와
  `GuideKeyMixin` 기반 passive 화면).
- key press/release가 필요한 guide motion은 release/timeout fail-safe를 유지한다.

<a id="mf_upstream_patch_reference_ko--integrated-time-sync"></a>
#### Integrated time sync

주요 파일:

- `python/PiFinder/gps_time_sync.py`
- `python/PiFinder/gps_time_sync_helper.py`
- `python/PiFinder/ui/gps_time_sync_status.py`
- `scripts/install_chrony_time_sync.sh`
- `scripts/install_gps_time_sync_helper.sh`
- `pi_config_files/pifinder_gps_time_sync.service`

보존해야 할 정책:

- 기본 시간 관리는 `chronyd` 중심이다.
- PiFinder time sync UI는 GPS/NTP/RTC 상태와 helper를 관리한다.
- 실제 시스템 시간 변경은 privileged helper/service 층에서 수행한다.
- INDI/OnStep으로 보낼 시간은 사용자가 입력한 값이 아니라 PiFinder가 사용하는 현재
  정확한 UTC 시간이어야 한다.

<a id="mf_upstream_patch_reference_ko--wi-fi-apsta"></a>
#### Wi-Fi AP+STA

주요 파일:

- `scripts/pifinder_apsta.sh`
- `scripts/import_initial_wifi_networks.py`
- `python/PiFinder/sys_utils.py`
- `python/PiFinder/server.py`
- `python/views/network.html`
- `pi_config_files/pifinder_apsta_prepare.service`
- `pi_config_files/pifinder_apsta_monitor.service`
- `pi_config_files/dhcpcd.conf.apsta`

보존해야 할 정책:

- Wi-Fi mode는 STA/AP/AP+STA를 지원한다.
- AP+STA에서는 STA channel을 기준으로 AP virtual interface를 재시작한다.
- AP IP는 설정 가능해야 한다.
- AP security/password 설정을 유지한다.
- AP+STA internet sharing은 option이며 default OFF이다.
- 설명 문구에는 부하와 속도 저하 가능성을 안내한다.
- OS 초기 설치 시 등록된 STA profile을 PiFinder 목록으로 가져온다.
- 새 STA 추가 시 주변 SSID scan 목록을 사용할 수 있어야 한다.
- STA band preference는 2.4G/5G 선택 정책을 유지한다.

<a id="mf_upstream_patch_reference_ko--locations-catalog"></a>
#### Locations catalog

주요 파일:

- `python/PiFinder/location_catalog.py`
- `python/PiFinder/data/location_catalog.json`
- `scripts/build_location_catalog.py`
- `python/views/locations.html`
- `python/views/location_form.html`

보존해야 할 정책:

- 국가/지역/군구/도시 선택으로 좌표와 고도를 자동 입력한다.
- 북한 데이터는 제외한다.
- 한국은 행정구역 데이터를 섞어 비교적 상세한 선택을 지원한다.
- 수동 위치 선택은 실내 GPS unlock 상태에서도 PiFinder location source로 사용 가능해야 한다.
- Red Night theme에서 form/select/action tooltip 색상이 하얗게 튀지 않아야 한다.

<a id="mf_upstream_patch_reference_ko--web-ui-theme--pwa"></a>
#### Web UI theme / PWA

주요 파일:

- `python/views/base.html`
- `python/views/css/style.css`
- `python/views/js/init.js`
- `python/views/manifest.webmanifest`
- `python/views/service-worker.js`
- `python/views/images/pwa-icon-192.png`
- `python/views/images/pwa-icon-512.png`

보존해야 할 정책:

- Red Night theme는 관측 중 암시야를 해치지 않는 적색 UI여야 한다.
- Logs page의 log content 색은 원래 의미 색을 유지한다.
- Android PWA 전체화면에서 theme color와 display mode를 유지한다.
- 메뉴 이동 후 fullscreen/PWA 상태가 불필요하게 깨지지 않도록 한다.
- Theme 선택은 navigation의 select로만 제공하고, 별도 bar는 제거 상태를 유지한다.

<a id="mf_upstream_patch_reference_ko--indi--onstepx"></a>
#### INDI / OnStepX

주요 파일:

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

보존해야 할 정책:

- INDI 기능은 optional이다. 기본 PiFinder 설치만으로 INDI가 강제 설치되면 안 된다.
- OnStepX는 커스텀 INDI driver 이름이며, 원본 LX200 OnStep driver를 직접 덮어쓰지 않는다.
- INDI profile에서 active driver name을 읽고, OnStepX일 때만 OnStepX 전용 화면/동작을 사용한다.
- OnStepX 위치/시간 sync는 driver readback 표시와 실제 OnStep 값이 일관되도록 유지한다.
- OnStep 위치/시간 설정 시 PiFinder 현재 UTC 시간을 사용한다.
- OnStepX `Backlash`는 OnStep 펌웨어와 맞춘 0..3600 arc-sec 범위를 유지한다.
- OnStepX `GUIDE_RATE`는 driver 호환성과 향후 guide-rate 제어를 위해
  writable/readback 동작을 유지하는 것이 좋다. 현재 Auto Backlash는 INDI
  GoTo를 사용하므로 `GUIDE_RATE`에 의존하지 않는다.
- OnStepX가 아닌 일반 INDI mount에서는 generic INDI path를 유지한다.
- INDI restart는 server/profile/driver를 모두 정지 후 다시 시작하고, 가능하면 자동 connect한다.

<a id="mf_upstream_patch_reference_ko--lcd-indi-ui"></a>
#### LCD INDI UI

주요 파일:

- `python/PiFinder/ui/indi.py`
- `python/PiFinder/ui/menu_structure.py`
- `python/PiFinder/ui/base.py`
- `python/PiFinder/keyboard_pi.py`

보존해야 할 정책:

- Start 메뉴 하단에 INDI 항목을 둔다.
- INIT/STATUS/GUIDE 페이지를 유지한다.
- Guide page는 숫자키 `2/4/6/8`(동서남북)과 `qwe/asd/zxc` 키맵을 사용하고,
  `9/3`은 slew rate 조절이다. 대각선 이동은 키보드 문자키에만 있다.
- 5키는 guide motion에 사용하지 않는다.
- motion은 press-to-move, release-to-stop 방식이다.
- freeze나 key release 누락 시 timeout/fail-safe stop을 유지한다.
- 상단 bar의 `I` indicator는 INDI 연결 정상/문제 상태를 표시한다.

<a id="mf_upstream_patch_reference_ko--skysafari--mount-mode-integration"></a>
#### SkySafari / mount mode integration

주요 파일:

- `python/PiFinder/pos_server.py`
- `python/PiFinder/pointing_coordinate_service.py`
- `python/PiFinder/mountcontrol_indi.py`
- `python/PiFinder/imu_pi.py`
- `python/PiFinder/imu_calibration.py`

보존해야 할 정책:

- SkySafari `:Sr/:Sd`(target 저장) → `:MS#`(GoTo) / `:CM#`(Sync/Align, 직전
  `Sr/Sd` 우선)의 forwarding 의미를 유지한다. 전체 흐름은
  [mf_goto_mount_source_structure_ko.md](mount.md#mf_goto_mount_source_structure_ko) 참조.
- GoTo forwarding이 켜져 있으면 Align/Sync도 INDI/OnStep에 전달할 수 있어야 한다.
- solve 전에는 IMU fallback/보정값을 사용할 수 있다.
- solve가 성공하면 IMU alignment correction은 초기화한다.
- Reset Pointing은 IMU alignment correction을 폐기하고, 솔빙이 없으면 raw
  (보정 미적용) IMU 좌표로 마운트를 재-sync한다 — 잘못된 target으로 정렬했을 때
  IMU 원좌표로 복구하는 유일한 수단이다.
- mount mode가 Alt/Az, EQ, 기타 INDI mount에서 동작할 수 있도록 OnStep 전용 코드는 driver
  capability/name으로 gate한다.

<a id="mf_upstream_patch_reference_ko--imu-compass--calibration"></a>
#### IMU compass / calibration

주요 파일:

- `python/PiFinder/imu_pi.py`
- `python/PiFinder/imu_calibration.py`
- `python/PiFinder/ui/menu_structure.py`
- `python/PiFinder/ui/callbacks.py`

보존해야 할 정책:

- magnetometer/compass fusion은 option이다.
- 기본 동작은 기존 IMU 안정성을 해치지 않아야 한다.
- calibration은 자동 저장/로드를 우선하고, 수동 save/load/clear 메뉴를 제공한다.
- calibration 상태 UI는 실제 BNO055 상태를 반영한다.

<a id="mf_upstream_patch_reference_ko--문서-빌드-툴체인-2026-08-10-추가"></a>
#### 문서 빌드 툴체인 (2026-08-10 추가)

주요 파일:

- `python/requirements_dev.txt`
- `python/noxfile.py`
- `CLAUDE.md`
- `docs/mf_dev/mf_bookworm_install_ko.md` / `_en.md`

보존해야 할 정책:

- `requirements_dev.txt` 마지막의 `-r ../docs/source/requirements.txt` 한 줄을
  유지한다. upstream에는 없는 MF 추가분이며, 이것 때문에 기존 개발 환경 구축
  명령만으로 Sphinx가 함께 설치된다.
- 버전을 `requirements_dev.txt`에 직접 고정하지 않는다. Read the Docs가 쓰는
  `docs/source/requirements.txt`를 참조해 단일 출처를 유지한다.
- `noxfile.py`의 `docs` 세션을 유지한다. `-n -W --keep-going`이 핵심이다 —
  경고를 실패로 만들지 않으면 부분 적용으로 끊긴 참조를 놓친다.
- `docs` 세션은 `nox.options.sessions` 기본 목록에 넣지 않는다.
- upstream이 자체 docs 세션이나 docs extra를 추가하면 중복 여부를 확인하고
  한쪽으로 정리한다.

<a id="mf_upstream_patch_reference_ko--충돌-가능성이-높은-파일"></a>
### 충돌 가능성이 높은 파일

upstream sync 때 먼저 확인할 파일:

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

특히 다음 파일은 기능 경계가 많이 겹친다.

- `main.py`: startup process, display selection, GPS/camera/keyboard selection, time sync queue
- `server.py`: web routes, network/location/INDI APIs, time/location push
- `sys_utils.py`: privileged system operations, Wi-Fi, chrony, INDI service helpers
- `keyboard_pi.py`: GPIO keypad, HID keyboard, guide fail-safe
- `ui/menu_structure.py`: upstream menu additions과 MF menu additions가 자주 충돌
- `ui/base.py`: titlebar/status indicators/theme-independent LCD UI helpers
- `pos_server.py`: SkySafari LX200 protocol, GoTo/Sync/Guide/IMU fallback

<a id="mf_upstream_patch_reference_ko--upstream-sync-권장-절차"></a>
### upstream sync 권장 절차

1. 현재 상태 확인:

```bash
git status --short --branch
git remote -v
git fetch upstream main
git rev-list --left-right --count upstream/main...HEAD
git log --oneline --left-right --cherry-pick upstream/main...HEAD --max-count=80
```

2. 변경 범위 확인:

```bash
git diff --stat HEAD...upstream/main
git diff --name-status HEAD...upstream/main
```

3. 충돌 dry-run:

```bash
git merge-tree --write-tree HEAD upstream/main
```

4. 적용 기준:

- 문서/CI/asset 같은 runtime 영향이 적은 변경부터 적용한다.
- Python runtime 변경은 기능 단위로 cherry-pick하거나 별도 sync branch에서 merge한다.
- Rev-4 hardware patch처럼 hardware side effect가 큰 변경은 쪼개서 적용한다.
- OnStepX/INDI/Network/Time sync 파일은 automatic resolution을 믿지 말고 diff를 읽는다.

5. 최소 검증:

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

6. 하드웨어 검증:

- Pi4 Bookworm 64-bit
- Pi5 또는 CM5 Bookworm 64-bit
- Camera preview/focus
- GPS lock/unlock and manual location load
- Bluetooth keyboard key press/release
- Web Red Night theme
- AP+STA and AP client list
- INDI Web UI and LCD INDI Guide stop fail-safe
- SkySafari GoTo/Align/Guide path

<a id="mf_upstream_patch_reference_ko--알려진-테스트-주의사항"></a>
### 알려진 테스트 주의사항

전체 `python -m pytest python/tests`는 현재 일부 기존 테스트가 환경/테스트 API 문제로
실패할 수 있다.

2026-07-03 확인된 대표 원인:

- `test_multiproclogging.py`: `pifinder_logconf.json` 경로 의존
- `test_radec_entry.py`: 테스트가 기대하는 생성자/API와 현재 코드 불일치
- `test_ui_modules.py`: `key_number_press(number)` 같은 인자 필요 key method를 무인자로
  sweep하는 테스트 구조

따라서 upstream sync 후에는 위의 최소 검증 목록을 우선 기준으로 삼고, 전체 테스트 실패는
첫 traceback을 기준으로 실제 회귀인지 기존 테스트 불일치인지 분리한다.

<a id="mf_upstream_patch_reference_ko--다음에-문서를-갱신해야-하는-경우"></a>
### 다음에 문서를 갱신해야 하는 경우

다음 변경이 발생하면 이 문서를 갱신한다.

- upstream main에서 `main.py`, `server.py`, `sys_utils.py`, `ui/menu_structure.py`,
  `pos_server.py`가 크게 바뀐 경우
- Rev-4 battery/sound/power 기능 중 일부를 추가 적용한 경우
- INDI generic path와 OnStepX-specific path를 다시 분리하거나 합친 경우
- SkySafari Align/GoTo/Guide 처리 정책이 바뀐 경우
- chronyd/time sync 정책이 바뀐 경우
- AP+STA 네트워크 정책이나 service 이름이 바뀐 경우
