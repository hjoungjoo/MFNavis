# 검증·현장 수집 — 이전 설계와 조사 기록

> 2026-10-10 통합 보관. 아래 본문의 “현재/현행”, 기본값, 완료 상태와 명령은 원문 작성 당시 기준이다.
> 오늘의 동작은 [개발 기준 문서](../../mf_dev/README.md)를 따른다. 이력에 적힌 절차를 현재 설치 절차로 사용하지 않는다.

- [mf_feature_review_checklist_ko.md](#mf_feature_review_checklist_ko)
- [mf_solver_goto_field_sheet_20260908_ko.md](#mf_solver_goto_field_sheet_20260908_ko)
- [mf_solver_goto_observation_workplan_20260908_ko.md](#mf_solver_goto_observation_workplan_20260908_ko)
- [mf_solver_performance_capture_workplan_20260907_ko.md](#mf_solver_performance_capture_workplan_20260907_ko)


---

<a id="mf_feature_review_checklist_ko"></a>

## mf_feature_review_checklist_ko.md

<a id="mf_feature_review_checklist_ko--mf_pifinder-기능-검토-및-테스트-체크리스트"></a>
## MF_PiFinder 기능 검토 및 테스트 체크리스트

플랫폼 항목은 2026-09-27 Trixie/Python 3.13 기준으로 갱신했다.
나머지 upstream 비교는 당시 검토 기준을 보존한다. 현재 설치·실테스트 범위는
[Trixie 안내](setup.md#mf_trixie_install_ko)를 참고하며, 아래 미체크 항목은
검증 완료를 의미하지 않는다.

작성일: 2026-07-03 / 전면 갱신: 2026-08-05

이 문서는 `brickbots/PiFinder` `main` 브랜치와 현재 `main` 브랜치를 비교해,
MF_PiFinder에 추가되었거나 원본과 다르게 수정된 기능을 검토/테스트 항목으로 정리한
목록이다.

기준:

- 비교 대상: `upstream/main` (`https://github.com/brickbots/PiFinder/tree/main`,
  `4a83d25b`, 2.6.1 릴리즈 병합 포함)
- 현재 소스: `main` (`f13fde43`)
- 비교 시점: 2026-08-05 (diff 규모: 420파일, +117,825/−9,085)
- 명령 기준:
  - `git fetch upstream main`
  - `git rev-list --left-right --count upstream/main...HEAD`
  - `git diff --stat upstream/main...HEAD`
  - `git diff --name-status upstream/main...HEAD`

비교 요약:

- upstream에는 있지만 MF에 전체 적용하지 않은 주요 변경 (§16):
  - Rev-4 battery/sound/power hardware enablement 전체 패치
  - bring-up 벤치 도구, keypad matrix 분리, NixOS 릴리즈 CI
- MF에 추가/수정된 주요 영역 (§1–§15 = 7/3 기준, §17–§25 = 이후 추가):
  - Trixie/RPi4/RPi5/CM5 설치 및 보드 profile
  - AP+STA Wi-Fi / Bluetooth·USB HID keyboard / 조이스틱
  - Red Night/PWA Web UI / 웹 카탈로그·통합검색 / Locations catalog
  - chronyd 중심 시간 관리
  - INDI/OnStepX/SkySafari mount integration + LCD INDI UI +
    PointingCoordinateService(mount+IMU 융합)
  - IMU compass/calibration
  - **cedar+SEP 하이브리드 솔빙 + cedar 풀프레임 1차 경로** (광해 대응 핵심)
  - 자동 노출 별 수 컨트롤러
  - SQM 라디오미터 스택 + 모노 색보정 가드
  - LiveCam RAW 프리뷰/라이브 스택 + 웹 카메라 컨트롤
  - SSD1333 자동감지 + 4축 밝기(업스트림 포트, 드라이버만)
  - Focus 4모드 화면(업스트림 #531) 위의 MF 기능 3종 재구현
  - 소프트웨어 업데이트 채널 포크 분리 (m-버전 체계)
  - 한국어 UI

관련 문서:

- `docs/mf_dev/mf_upstream_patch_reference_ko.md`: upstream 재동기화와 패치 재적용 기준
- `docs/mf_dev/mf_change_history_ko.md`: 전체 변경 히스토리
- `docs/mf_dev/mf_pifinder_rpi4_pi5_compatibility_ko.md`: Pi4/Pi5/CM5 Trixie 호환성 요약
- `docs/mf_dev/mf_indi_mount_install_ko.md`: INDI 설치/운영
- `docs/mf_dev/mf_wifi_apsta_ko.md`: AP+STA Wi-Fi
- `docs/mf_dev/mf_time_sync_ko.md`: 시간 동기화
- `docs/mf_dev/mf_keyboard_mapping_ko.md`: 키보드 매핑

<a id="mf_feature_review_checklist_ko--테스트-우선순위"></a>
### 테스트 우선순위

| 우선순위 | 의미 |
| --- | --- |
| P0 | 장치 부팅/설치/기본 관측 기능에 직접 영향. 반드시 테스트 |
| P1 | 주요 기능. 실제 장비나 네트워크 환경에서 테스트 권장 |
| P2 | 보조 기능 또는 문서/개발 편의. 회귀 확인 위주 |

<a id="mf_feature_review_checklist_ko--1-platform--trixie--raspberry-pi-4-5-cm5-호환성"></a>
### 1. Platform / Trixie / Raspberry Pi 4, 5, CM5 호환성

우선순위: P0

주요 변경:

- Trixie 64-bit 기본 설치 경로 지원
- `/boot/firmware/config.txt` 우선, legacy `/boot/config.txt` fallback
- 현재 OS 사용자 기준으로 `MFNavis_data`, systemd, Samba 경로 처리
- Pi4/Pi5/CM5 보드별 GPS UART profile
- Pi5/CM5에서 OLED CS 충돌을 피하기 위한 `uart2-pi5` 사용
- `/dev/spidev0.0`, `/dev/spidev10.0` 양쪽 SPI 지원
- SSD1333 display auto-detection 추가

주요 파일:

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

검토 포인트:

- [ ] 새 OS 설치 후 `mfnavis_setup.sh`가 일반 사용자로 끝까지 실행되는가
- [ ] Pi4에서 `gps_port=auto`가 `/dev/ttyAMA3`로 해석되는가
- [ ] Pi5/CM5에서 `gps_port=auto`가 `/dev/ttyAMA2`로 해석되는가
- [ ] boot config가 실제 사용 중인 경로에 적용되는가
- [ ] `uart3`와 OLED CE0/GPIO8 충돌이 Pi5/CM5에서 발생하지 않는가
- [ ] `spidev0.0`만 있는 장비와 `spidev10.0`만 있는 장비 모두 동작하는가
- [ ] SSD1333 marker 감지 실패 시 기존 SSD1351 기본 동작으로 fallback 되는가
- [ ] splash와 main UI가 같은 display selection을 사용하는가

테스트 항목:

- [ ] Pi4 Trixie 64-bit fresh install
- [ ] Pi5 또는 CM5 Trixie 64-bit fresh install
- [ ] `systemctl status mfnavis mfnavis_splash indiwebmanager`
- [ ] `ls /dev/spidev* /dev/ttyAMA*`
- [ ] Web UI 접속
- [ ] LCD/OLED splash 표시
- [ ] LCD/OLED main UI 표시
- [ ] GPS 포트 자동 선택 확인
- [ ] camera preview 확인

<a id="mf_feature_review_checklist_ko--2-camera-focus-화면--gain-2026-08-05-갱신--upstream-531-4모드-화면-기준"></a>
### 2. Camera Focus 화면 / Gain (2026-08-05 갱신 — upstream #531 4모드 화면 기준)

우선순위: P1

주요 변경:

- upstream #531 Focus 재작성 수용: stars(별 4타일)/single/image/stats 4모드,
  raw 무보간 크롭, HFD 히스토리
- MF 재구현 3종: GuideKeyMixin(카메라 화면 마운트 조그), Gain 마킹메뉴(right),
  주간/포화 프레임 raw 렌더 경로(Image 모드, median≥220 시 12-bit 원본을
  베이어 쿼드 평균+퍼센타일 스트레치로 표시 — 주간 정렬용)
- camera gain profile/runtime 선택
- LCD camera preview debug script

주요 파일:

- `python/PiFinder/ui/preview.py`
- `python/PiFinder/focus.py`
- `python/PiFinder/camera_interface.py`
- `python/PiFinder/ui/callbacks.py`
- `scripts/camera_lcd_preview.py`

검토 포인트:

- [ ] SQUARE로 4모드 순환이 되는가
- [ ] 마킹메뉴에 EXPOSURE/GAIN이 있고 GAIN 점프가 동작하는가
- [ ] 주간(밝은 배경)에 Image 모드가 검게 뭉개지지 않고 장면을 보여주는가
- [ ] mount_control on일 때 카메라 화면에서 가이드 키가 동작하는가
- [ ] runtime gain 변경이 실제 camera metadata와 일치하는가

테스트 항목:

- [ ] Stars 모드에서 +/−로 확대 배율 변경
- [ ] Single 모드 HFD 판독 표시
- [ ] Stats 모드에 별 수/FWHM/노출/게인 표시
- [ ] 주간 실외에서 Image 모드 장면 확인 (주간 정렬 경로)
- [ ] 관련 테스트: `test_focus_preview.py`, `test_focus.py`, `test_ui_guide_keys.py`

<a id="mf_feature_review_checklist_ko--3-korean-ui-localization"></a>
### 3. Korean UI Localization

우선순위: P1

주요 변경:

- 한국어 locale 추가
- 언어 메뉴에 `ko` 추가
- CJK font 처리
- 언어 변경 후 restart 안내

주요 파일:

- `python/locale/ko/LC_MESSAGES/messages.po`
- `python/locale/ko/LC_MESSAGES/messages.mo`
- `python/PiFinder/ui/fonts.py`
- `python/PiFinder/ui/menu_structure.py`

검토 포인트:

- [ ] 언어 메뉴에서 Korean 선택 가능
- [ ] LCD에서 한글이 깨지지 않는가
- [ ] Web UI에서 한글이 정상 표시되는가
- [ ] upstream i18n 변경 후 Korean `.po`가 누락되지 않았는가

테스트 항목:

- [ ] 언어를 Korean으로 변경
- [ ] 재시작 후 LCD menu 확인
- [ ] Web UI navigation/title/button 확인
- [ ] 로그/에러 메시지 표시 확인

<a id="mf_feature_review_checklist_ko--4-bluetooth--usb-hid-keyboard"></a>
### 4. Bluetooth / USB HID Keyboard

우선순위: P0

주요 변경:

- libinput 기반 HID keyboard event 처리
- Bluetooth keyboard scan/pair/connect UI
- USB keyboard 입력 지원
- 텍스트 입력용 키코드 확장
- `qwe/asd/zxc` 방향 키맵 (INDI Guide page 및 mount 제어가 켜진 메뉴/상태 화면 공통, `GuideKeyMixin`)
- Guide motion release/fail-safe stop 보완

주요 파일:

- `python/PiFinder/keyboard_interface.py`
- `python/PiFinder/keyboard_pi.py`
- `python/PiFinder/ui/bluetooth_keyboard.py`
- `python/PiFinder/ui/textentry.py`
- `python/PiFinder/ui/indi.py`
- `python/PiFinder/ui/menu_structure.py`

검토 포인트:

- [ ] Bluetooth keyboard가 paired/connected 상태에서 `/dev/input/event*`로 잡히는가
- [ ] key press와 release가 모두 들어오는가
- [ ] 일반 메뉴 입력과 guide 방향 키맵(`GuideKeyMixin`)이 충돌하지 않는가
- [ ] 장시간 key hold 중 freeze/SSH 지연이 있어도 mount motion이 멈추는가
- [ ] AP+STA/Wi-Fi 변경 후 Bluetooth keyboard reconnect가 유지되는가

테스트 항목:

- [ ] Bluetooth keyboard pair
- [ ] Bluetooth keyboard reconnect after reboot
- [ ] USB keyboard 연결
- [ ] LCD menu navigation
- [ ] Text entry
- [ ] INDI Guide 방향키 press/release
- [ ] Guide motion 중 Bluetooth 연결 해제
- [ ] Guide motion timeout stop

<a id="mf_feature_review_checklist_ko--5-web-ui-red-night-theme--pwa"></a>
### 5. Web UI Red Night Theme / PWA

우선순위: P1

주요 변경:

- Red Night theme 추가
- browser별 theme 저장
- PWA manifest/service worker/icon 추가
- Android PWA fullscreen/theme-color 대응
- navigation theme selector 통합
- Locations/tooltip/select/form 색상 보정

주요 파일:

- `python/views/base.html`
- `python/views/css/style.css`
- `python/views/js/init.js`
- `python/views/manifest.webmanifest`
- `python/views/service-worker.js`
- `python/views/images/pwa-icon-192.png`
- `python/views/images/pwa-icon-512.png`
- `python/views/locations.html`
- `python/views/location_form.html`

검토 포인트:

- [ ] Red Night에서 흰색/밝은 색 UI가 남지 않는가
- [ ] Logs page의 log semantic color는 유지되는가
- [ ] PWA 설치 후 전체화면 진입이 되는가
- [ ] Android navigation/status bar가 theme color를 따르는가
- [ ] 메뉴 이동 후 PWA/전체화면 상태가 불필요하게 깨지지 않는가
- [ ] theme selector가 navigation에만 보이는가

테스트 항목:

- [ ] Chrome desktop theme 변경
- [ ] Android Chrome theme 변경
- [ ] Android PWA 설치
- [ ] PWA fullscreen navigation
- [ ] Logs page color 확인
- [ ] Locations add/edit form 확인
- [ ] Tooltips/action buttons 색상 확인

<a id="mf_feature_review_checklist_ko--6-wi-fi-ap--sta--apsta"></a>
### 6. Wi-Fi AP / STA / AP+STA

우선순위: P0

주요 변경:

- STA/AP/AP+STA mode 지원
- `uap0` virtual AP interface 생성
- STA channel 기반 AP channel 재시작
- AP IP 설정
- AP WPA2 security/password 설정
- AP+STA internet sharing option, default OFF
- OS 초기 Wi-Fi profile import
- 주변 SSID scan 후 STA profile 추가
- STA band preference
- AP connected device list 표시

주요 파일:

- `scripts/pifinder_apsta.sh`
- `scripts/import_initial_wifi_networks.py`
- `python/PiFinder/sys_utils.py`
- `python/PiFinder/server.py`
- `python/views/network.html`
- `pi_config_files/pifinder_apsta_prepare.service`
- `pi_config_files/pifinder_apsta_monitor.service`
- `pi_config_files/dhcpcd.conf.apsta`
- `switch-apsta.sh`

검토 포인트:

- [ ] STA only mode 정상
- [ ] AP only mode 정상
- [ ] AP+STA mode 정상
- [ ] AP+STA에서 AP client가 PiFinder Web UI에 접속 가능한가
- [ ] AP+STA internet sharing ON/OFF가 동작하는가
- [ ] STA channel 변경 시 AP channel 재설정이 되는가
- [ ] AP IP 변경 후 dnsmasq/dhcp lease가 정상인가
- [ ] STA band preference가 NetworkManager profile과 일치하는가
- [ ] STA망에서 PiFinder Web 접속이 안 되는 경우 client isolation 여부를 구분할 수 있는가

테스트 항목:

- [ ] AP mode에서 `10.10.10.1` 접속
- [ ] AP+STA에서 STA 인터넷 연결
- [ ] AP client 인터넷 공유 ON
- [ ] AP client 인터넷 공유 OFF
- [ ] OnStep device AP 접속 및 통신
- [ ] AP connected device list 표시
- [ ] STA SSID scan/add
- [ ] 기존 OS Wi-Fi profile import
- [ ] 2.4G/5G band preference 변경
- [ ] STA router client isolation 환경 확인

<a id="mf_feature_review_checklist_ko--7-locations-catalog"></a>
### 7. Locations Catalog

우선순위: P1

주요 변경:

- offline location catalog 추가
- country/state/district/city lookup
- 좌표/고도/source 자동 입력
- 한국 상세 행정구역 보강
- 북한 제외
- manual loaded location을 실내 GPS unlock 상태에서도 사용 가능하게 처리

주요 파일:

- `python/PiFinder/location_catalog.py`
- `python/PiFinder/data/location_catalog.json`
- `scripts/build_location_catalog.py`
- `python/views/locations.html`
- `python/views/location_form.html`
- `python/PiFinder/server.py`

검토 포인트:

- [ ] Country 선택 후 다음 select 목록이 정상 필터링되는가
- [ ] 한국 주소가 충분히 상세한가
- [ ] location name 자동 입력/변경이 자연스러운가
- [ ] Save Location이 정상 저장되는가
- [ ] default location 지정이 정상인가
- [ ] GPS unlock 상태에서도 수동 location이 PiFinder/INDI에 반영되는가
- [ ] Red Night theme에서 form/select 색상이 적절한가

테스트 항목:

- [ ] 서울/송파/풍납동 선택 후 저장
- [ ] 다른 한국 지역 저장
- [ ] 해외 주요 도시 저장
- [ ] default location 변경
- [ ] location reload
- [ ] INDI page PiFinder Location 업데이트
- [ ] OnStep Send Location and Time 확인

<a id="mf_feature_review_checklist_ko--8-integrated-time-sync--chronyd"></a>
### 8. Integrated Time Sync / chronyd

우선순위: P0

주요 변경:

- GPS/NTP/RTC/software PPS 통합 시간 관리
- chronyd 중심 정책으로 정리
- privileged helper service 분리
- GPS/NTP/RTC 상태 UI
- custom NTP server 설정
- Set Time/Date는 location lock이 없으면 self-gate
- PiFinder UTC-aware datetime handling 적용

주요 파일:

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

검토 포인트:

- [ ] 기본 clock manager가 chronyd 중심으로 동작하는가
- [ ] GPS 신호가 약하거나 unlock 상태에서 graceful degradation 되는가
- [ ] NTP network unavailable 상태에서 timeout/오류 처리가 안정적인가
- [ ] custom NTP server가 저장/적용되는가
- [ ] Pi5 RTC 경로가 문제를 만들지 않는가
- [ ] Set Time/Date는 location lock이 없으면 실행되지 않는가
- [ ] INDI/OnStep에 보낼 시간은 PiFinder current UTC time인가

테스트 항목:

- [ ] 실내 GPS unlock
- [ ] 실외 GPS lock
- [ ] NTP available
- [ ] NTP unavailable
- [ ] custom NTP server 입력
- [ ] chronyc sources/tracking 확인
- [ ] Time Sync LCD status
- [ ] Web status/API 확인
- [ ] OnStep time sync 후 OnStep Web UI 시간 확인

<a id="mf_feature_review_checklist_ko--9-indi-mount--onstepx"></a>
### 9. INDI Mount / OnStepX

우선순위: P0

주요 변경:

- optional INDI mount process
- INDI install scripts
- INDI archive package/install scripts
- OnStepX custom INDI driver patch flow
- INDI Web UI menu/page
- LX200 OnStep/OnStepX network/serial setup UI
- OnStep location/time sync 개선
- INDI restart
- active driver name/profile 기반 동작 분리
- generic INDI mount path 유지

주요 파일:

- `python/PiFinder/mountcontrol_indi.py`
- `python/PiFinder/pos_server.py`
- `python/PiFinder/ui/indi.py`
- `python/views/indi_mount.html`
- `python/views/tools.html`
- `scripts/install_indi_mount_OnstepX.sh`
- `scripts/install_indi_mount_archive.sh`
- `scripts/package_indi_mount_archive.sh`
- `scripts/patches/indi-v2.2.3.1-onstepx.patch`

검토 포인트:

- [ ] 기본 PiFinder 설치만으로 INDI가 강제 설치되지 않는가
- [ ] INDI 설치 script가 Pi4/Pi5 모두에서 동작하는가
- [ ] OnStepX driver가 원본 LX200 OnStep driver를 덮어쓰지 않는가
- [ ] active driver가 OnStepX일 때만 OnStepX 전용 UI가 보이는가
- [ ] USB serial 목록이 표시되는가
- [ ] network host/port 목록과 manual entry가 정상 동작하는가
- [ ] INDI restart가 server/profile/driver를 모두 정리하고 재시작하는가
- [ ] Home 상태, Park 상태, 원시 `:GU#` 상태가 분리 표시되는가
- [ ] 수동 Backlash가 마운트 이동 없이 `Backlash.Backlash RA/DEC`를 읽고 쓰는가
- [ ] Auto Backlash가 fresh plate-solved `PointingCoordinateService.solved` 좌표를 요구하고 IMU Compass/MAG calibration은 확인하지 않는가
- [ ] Auto Backlash가 시작 전 mount 좌표를 solved RA/Dec 기준으로 sync하고 tracking을 끄는가
- [ ] Auto Backlash가 측정 이동에 timed pulse guide가 아니라 INDI GoTo를 사용하는가
- [ ] Auto Backlash가 GoTo 후 mount/solved 샘플 기록 전에 stable INDI idle과 OnStep `:GU#`의 `N`(`No goto`) 상태를 기다리는가
- [ ] Auto Backlash가 각 GoTo leg 후 tracking을 다시 Off로 만드는가
- [ ] Alt/Az mount에서는 `AZ`/`ALT`, EQ mount에서는 `RA`/`DEC`를 한 축씩 고정 GoTo 시작/오프셋 점으로 반복 이동하는가
- [ ] Auto Backlash가 각 GoTo leg의 시작 mount 좌표, 종료 mount 좌표, 시작/종료 PiFinder solved 좌표를 기록하는가
- [ ] mount delta와 solved-coordinate delta 차이가 1도 이상인 leg는 제외하고, 남은 값의 상하 30%를 버린 middle 40% 평균을 표시하는가
- [ ] Auto Backlash가 Alt/Az에서는 `AZ+/-`, `ALT+/-`, EQ에서는 `RA+/-`, `DEC+/-`처럼 실제 이동 방향별 추천값을 분리 표시하는가
- [ ] Auto Backlash 결과는 계산값 표시만 하고, 입력칸 변경이나 `Save Backlash` 전 적용을 하지 않는가
- [ ] driver 통신 불량 시 기본 PiFinder 기능이 멈추지 않는가

테스트 항목:

- [ ] INDI 미설치 상태에서 기본 PiFinder 동작
- [ ] 기본 경로인 `install_indi_mount_archive.sh` 아카이브 설치
- [ ] 소스/패치 수정이 필요할 때만 `install_indi_mount_OnstepX.sh` 전체 빌드 설치
- [ ] INDI Web Manager 접속
- [ ] OnStepX profile start/connect
- [ ] LX200 OnStepX network TCP setup
- [ ] LX200 OnStepX USB serial setup
- [ ] Restart INDI
- [ ] OnStep Web UI, 직접 LX200 `:GU#`, PiFinder INDI Home/Park 상태 비교
- [ ] 현재 Backlash RA/DEC 읽기
- [ ] UI에서 Backlash RA/DEC를 수동 저장하고 driver 값이 변경되는지 확인
- [ ] Auto Backlash가 fresh plate-solved 좌표를 요구하고 Compass/NDOF나 MAG calibration은 요구하지 않는지 확인
- [ ] Auto Backlash가 motion test 중 tracking을 끄고 정상 완료 후에만 원래 tracking 상태를 복구하는지 확인
- [ ] Auto Backlash가 Backlash RA/DEC를 0으로 초기화하거나 적용/원복하지 않고,
      계산 후보값만 사용자 검토용으로 표시하는지 확인
- [ ] solved GoTo loop가 신뢰 가능한 mount/solved 이동 기록을 만들 수 없는 경우,
      값을 적용하지 않고 실패 메시지를 표시하는지 확인
- [ ] INDI server stop 상태에서 PiFinder UI 동작
- [ ] OnStep device offline 상태에서 PiFinder 동작

<a id="mf_feature_review_checklist_ko--10-lcd-indi-ui"></a>
### 10. LCD INDI UI

우선순위: P0

주요 변경:

- LCD Start menu 하단 INDI 항목
- INIT / STATUS / GUIDE 페이지
- INIT actions: connect/init, send location/time, reset pointing, park/unpark, set home, return home, set-park, restart
- STATUS periodic update
- GUIDE keypad overlay
- `2/4/6/8` cardinal 방향 + `q/e/z/c` 대각선, `9/3` 속도 조절 layout
- key press-to-move, release-to-stop
- `qwe/asd/zxc` keyboard mapping (Guide page 및 mount 제어가 가능한 다른 화면 공통)
- `I` top-bar indicator

주요 파일:

- `python/PiFinder/ui/indi.py`
- `python/PiFinder/ui/menu_structure.py`
- `python/PiFinder/ui/base.py`
- `python/PiFinder/keyboard_pi.py`

검토 포인트:

- [ ] Start menu 하단에 INDI가 보이는가
- [ ] INIT menu 항목이 화면을 넘지 않는가
- [ ] Restart action이 INIT에서 보이는가
- [ ] STATUS가 주기적으로 갱신되는가
- [ ] Guide overlay 안내(`2/4/6/8` 이동, `9/3` 속도, `0` Guide)가 실제 동작과 일치하는가
- [ ] 5키는 guide motion에 사용되지 않는가
- [ ] motion 중 key release 누락 시 timeout stop이 동작하는가
- [ ] Bluetooth keyboard로 start/stop 모두 동작하는가
- [ ] 상단 `I` 표시가 연결 상태에 따라 정상/점멸하는가

테스트 항목:

- [ ] LCD INIT connect/init
- [ ] LCD send location/time
- [ ] LCD park/unpark
- [ ] LCD set home/return home
- [ ] LCD restart INDI
- [ ] LCD Guide 방향 motion (키패드 `2/4/6/8`, 키보드 `q/e/z/c` 대각선)
- [ ] LCD Guide release stop
- [ ] Bluetooth keyboard Guide motion
- [ ] Web UI로 stop recovery

<a id="mf_feature_review_checklist_ko--11-skysafari--lx200--mount-mode-integration"></a>
### 11. SkySafari / LX200 / Mount Mode Integration

우선순위: P0

주요 변경:

- SkySafari LX200 `:Sr/:Sd/:MS#/:CM#` 처리 보강
- solve 전 IMU fallback pointing
- SkySafari GoTo를 INDI mount로 forwarding option
- SkySafari Guide를 INDI guide motion으로 bridge
- SkySafari Align/Sync를 PiFinder/IMU/INDI로 처리
- mount mode compatibility audit
- GoTo 완료/이동 상태 처리 보완
- Alt/Az/EQ 등 다양한 mount mode를 고려한 분리

주요 파일:

- `python/PiFinder/pos_server.py`
- `python/PiFinder/mountcontrol_indi.py`
- `python/PiFinder/imu_pi.py`
- `python/PiFinder/imu_calibration.py`
- `docs/mf_dev/mf_mount_mode_compatibility_ko.md`

검토 포인트:

- [ ] `:Sr/:Sd`는 target 좌표 저장만 하는가
- [ ] `:MS#`는 GoTo로 처리되는가
- [ ] `:CM#`는 Sync/Align으로 처리되는가
- [ ] `:CM#`는 직전 parsed `Sr/Sd` target을 우선 사용하는가
- [ ] GoTo forwarding ON이면 Align/Sync도 INDI/OnStep에 전달되는가
- [ ] solve 전 IMU correction이 적용되는가
- [ ] solve 후 IMU correction이 초기화되는가
- [ ] Alt/Az와 EQ mount mode에서 horizon/coordinate 상태가 잘못 표시되지 않는가
- [ ] SkySafari에서 GoTo 완료 상태가 정상 종료되는가
- [ ] target이 지평선 아래라고 잘못 판단되는 상황이 없는가

테스트 항목:

- [ ] SkySafari Push-To mode
- [ ] SkySafari GoTo mode
- [ ] SkySafari guide buttons
- [ ] SkySafari Align
- [ ] solve 전 IMU fallback
- [ ] solve 후 normal pointing
- [ ] INDI GoTo forwarding OFF
- [ ] INDI GoTo forwarding ON
- [ ] Alt/Az mount
- [ ] EQ mount

<a id="mf_feature_review_checklist_ko--12-imu-compass--calibration"></a>
### 12. IMU Compass / Calibration

우선순위: P1

주요 변경:

- optional BNO055 magnetometer/compass fusion
- IMU sensitivity 설정 유지
- auto calibration save/load
- manual calibration save/load/clear
- compass/calibration UI menu

주요 파일:

- `python/PiFinder/imu_pi.py`
- `python/PiFinder/imu_calibration.py`
- `python/PiFinder/ui/menu_structure.py`
- `python/PiFinder/ui/callbacks.py`
- `docs/mf_dev/mf_imu_compass_calibration_ko.md`

검토 포인트:

- [ ] 기본 OFF 상태에서 기존 IMU 동작이 안정적인가
- [ ] compass ON 시 heading 개선이 있는가
- [ ] 실내 자기장 간섭에서 오동작이 큰가
- [ ] calibration status가 실제 BNO055 상태와 맞는가
- [ ] auto save/load가 reboot 후 적용되는가
- [ ] manual save/load/clear가 동작하는가
- [ ] solve 성공 후 IMU correction 초기화와 충돌하지 않는가

테스트 항목:

- [ ] Compass OFF
- [ ] Compass ON
- [ ] Calibration auto save
- [ ] Calibration load after reboot
- [ ] Manual save/load/clear
- [ ] SkySafari no-solve pointing
- [ ] Plate solve 후 correction reset

<a id="mf_feature_review_checklist_ko--13-observing-list-csv-import"></a>
### 13. Observing List CSV Import

우선순위: P2

주요 변경:

- upstream CSV import 개선 반영
- lenient headers
- 다양한 coordinate format 지원
- docs examples 추가
- object type code drift guard와 연계

주요 파일:

- `python/PiFinder/obslist.py`
- `python/PiFinder/obslist_formats.py`
- `docs/ax/catalog/obslist-formats/README.md`
- `docs/ax/catalog/obslist-formats/examples/*`
- `python/tests/test_obslist_formats.py`
- `python/tests/test_obslist_resolve.py`

검토 포인트:

- [ ] 기존 `.pifinder` list import가 깨지지 않는가
- [ ] third-party CSV import가 동작하는가
- [ ] RA hour/degree/sexagesimal/colon format이 처리되는가
- [ ] object type filter와 OBJ_TYPES가 일치하는가

테스트 항목:

- [ ] example CSV import
- [ ] 잘못된 header 처리
- [ ] mixed coordinate format 처리
- [ ] object type filter 적용

<a id="mf_feature_review_checklist_ko--14-obj_types-single-source"></a>
### 14. OBJ_TYPES Single Source

우선순위: P2

주요 변경:

- object type code set을 `OBJ_TYPES`로 단일화
- Type filter menu를 `OBJ_TYPES.items()`에서 생성
- docs/default_config drift guard test 추가

주요 파일:

- `python/PiFinder/obj_types.py`
- `python/PiFinder/ui/menu_structure.py`
- `python/tests/test_obj_types_docs.py`
- `default_config.json`

검토 포인트:

- [ ] Type filter menu 순서가 적절한가
- [ ] 표시명이 LCD 폭에 너무 길지 않은가
- [ ] Korean translation에서 object type label이 자연스러운가
- [ ] `default_config.json`의 `filter.object_types`가 모든 type을 포함하는가

테스트 항목:

- [ ] Type filter menu 표시
- [ ] Type filter 선택/해제
- [ ] catalog filtering
- [ ] `test_obj_types_docs.py`

<a id="mf_feature_review_checklist_ko--15-documentation--test--ci--assets"></a>
### 15. Documentation / Test / CI / Assets

우선순위: P2

주요 변경:

- MF docs 추가
- upstream patch reference 문서 추가
- feature별 install/test docs 추가
- Nox 코드 품질·테스트·Trixie 문서 빌드 CI
- case/accessory assets 반영
- test coverage 추가

주요 파일:

- `docs/mf_dev/*.md`, `docs/mf_report/*.md`
- `.github/workflows/nox.yml`
- `.github/scripts/*`
- `case/accessories/*`
- `python/tests/test_*.py`

검토 포인트:

- [ ] 문서 이름/언어 쌍이 맞는가
- [ ] 한국어 문서에 대응 영문 문서가 있는가
- [ ] setup/install 문서가 현재 script 이름과 일치하는가
- [ ] GitHub Actions가 fork에서 의도대로 동작하는가
- [ ] asset 변경이 불필요한 PR noise를 만들지 않는가

테스트 항목:

- [ ] 문서 링크 확인
- [ ] install script 이름 확인
- [ ] CI workflow syntax 확인
- [ ] docs/source menu map 확인

<a id="mf_feature_review_checklist_ko--16-upstream-rev-4-hardware-patch-미적용부분-적용-항목"></a>
### 16. Upstream Rev-4 Hardware Patch: 미적용/부분 적용 항목

우선순위: 검토 전용

현재 상태:

- SSD1333 display auto-detection만 MF 방식으로 부분 적용
- battery/sound/power/latch는 전체 미적용

미적용 항목:

- BQ25895 battery telemetry
- BQ25895 fast-charge configuration writes
- sound/earcon buzzer subsystem
- GPIO15 hardware power button
- GPIO14 gpio-poweroff latch
- battery titlebar icon
- Raspberry Pi red power LED control
- bring-up 벤치 도구 (#552/#556 — `keypad`/`battery_bq25895`/`sound` 의존,
  import 불가)
- keypad matrix 분리 (#551 — MF 4열 vs upstream 5열, 수용 시 오배선)
- NixOS 릴리즈 CI 일체 (SD 이미지/마이그레이션 tarball/매니페스트)
- i18n `.po`/`.mo` 파일 (수용 금지 — 언어당 527개 MF msgid 소실;
  #562의 문자열 래핑 5곳만 후보로 남음)

검토 포인트:

- [ ] Rev-4 하드웨어가 실제 대상인지 확인
- [ ] GPIO14 poweroff latch 배선이 있는 장비에서만 적용할지 결정
- [ ] sound/earcon default OFF 정책 필요 여부 결정
- [ ] battery charger write 동작을 read-only와 분리할지 결정
- [ ] `HardwareCapabilities` 타입을 가져올 경우 기존 `hardware_detect.py` fallback 유지

<a id="mf_feature_review_checklist_ko--17-cedarsep-하이브리드-솔빙--cedar-풀프레임-1차-경로"></a>
### 17. cedar+SEP 하이브리드 솔빙 / cedar 풀프레임 1차 경로

우선순위: P0 — 이 포크의 존재 이유(광해 하늘 정확 솔빙)

주요 변경:

- 검출기 2종 병렬(cedar 풀프레임 σ8 + SEP σ4) + 좌표 4단 캐스케이드
  (cedar 중앙→cedar 전체→SEP 중앙→SEP 전체), `solver_cedar_fullframe` 플래그
- 품질 게이트 6종(엣지·포화·웜픽셀·클러스터 등) + 선택형 IMU 지평선 마스크
- 웜픽셀 맵(`sep_warm_map.py`), 섀도 CSV 계측(`sep_shadow.py`),
  `solver_frame_map`(네이티브 FOV→512 의미 통일), `solve_path` 진단 필드
- 정본 설계: `mf_cedar_sep_hybrid_design_ko.md`, ADR m0023

주요 파일:

- `python/PiFinder/solver.py`, `sep_detect.py`, `sep_warm_map.py`,
  `sep_shadow.py`, `solver_frame_map.py`, `horizon_mask.py`

검토 포인트:

- [ ] `/api/status`의 `solve_path`가 조건에 맞게 나오는가
      (중앙: `cedar_center`/`sep_center`, 중앙 실패 후 전체:
      `cedar_full`/`sep_full`)
- [ ] 웜픽셀 맵이 최신인가 (bias 238 기준 재검증 — SQM 포트 잔여 조건)
- [ ] 게이트가 지상 점광원(건물 불빛)을 걸러내는가

테스트 항목:

- [ ] 광해 하늘 라이브 솔브율 (기준: 8/1 실측 88–90%)
- [ ] 솔브 RMSE 및 매치 수 확인 (`/api/status`)
- [ ] `test_solver_cedar_fullframe.py`, `test_sep_detect.py`,
      `test_sep_fullframe_solve.py`

<a id="mf_feature_review_checklist_ko--18-자동-노출--검출-별-수-컨트롤러"></a>
### 18. 자동 노출 — 검출 별 수 컨트롤러

우선순위: P1

주요 변경:

- Camera Exp 메뉴 "Star"(`camera_exp=auto_star`)로 선택하는 별 수 서보,
  솔브 성공 홀드(ADR m0022), 앵커 클램프. ADR m0020/m0021/m0022.

주요 파일: `python/PiFinder/auto_exposure_starcount.py`, `auto_exposure.py`,
`camera_interface.py`

검토 포인트 / 테스트 항목:

- [ ] Star 모드 선택/해제와 기존 자동 노출 모드 무회귀
- [ ] `test_auto_exposure_starcount.py`

<a id="mf_feature_review_checklist_ko--19-sqm-라디오미터-스택--모노-색보정-가드"></a>
### 19. SQM 라디오미터 스택 + 모노 색보정 가드

우선순위: P1

주요 변경:

- upstream SQM 스택(#532/#542/#543/#544) 이식: 라디오미터 우선 발행,
  raw-green 측광, Gaia 색보정, 위저드, 스윕
- 스윕 노출 정착(#561), 하늘색 zero point(#560)를 **mono 가드와 함께** 이식 —
  실측 모노 imx462에 색보정이 켜지면 ~+0.74 mag 왜곡
  (`mf_report/mf_mono_sqm_colour_guard_20260805_*.md`)

주요 파일: `python/PiFinder/sqm/*`, `python/PiFinder/ui/sqm*.py`

검토 포인트:

- [ ] imx462 SQM이 상수 zero point를 유지하는가 (색 필드 없음)
- [ ] 잔여 완료 조건: bias 238 야간 재검증 + SQM 위저드 1회 실행

테스트 항목: `test_sqm.py`, `test_radiometer.py`, `test_radiometric_fit.py`,
`test_sweep_frame_record.py`

<a id="mf_feature_review_checklist_ko--20-livecam-raw-프리뷰--라이브-스택--웹-카메라-컨트롤"></a>
### 20. LiveCam RAW 프리뷰 / 라이브 스택 / 웹 카메라 컨트롤

우선순위: P1

주요 변경:

- RAW 프리뷰·롤링 스택, SEP 오버레이, `/api/camera/controls` 노출/게인,
  TIFF 16-bit 다운로드
- 라이브 뷰는 항상 JPEG, 포맷 설정은 다운로드 전용(UI 라벨 "Download Format")
- 다운로드는 그레이스케일(모노 센서 — 디베이어 크로마는 인공물)

주요 파일: `python/PiFinder/raw_live_stack.py`, `livecam_config.py`,
`api_extensions.py`, `python/views/livecam.html`

검토 포인트 / 테스트 항목:

- [ ] PNG 설정에서도 라이브 갱신 속도 유지(JPEG 스트림)
- [ ] 다운로드가 선택 포맷 그대로인가 (webp 포함)
- [ ] `test_raw_live_stack.py`, `test_api_camera_controls.py`

<a id="mf_feature_review_checklist_ko--21-웹-카탈로그--통합검색--관측-목록"></a>
### 21. 웹 카탈로그 / 통합검색 / 관측 목록

우선순위: P1

주요 변경: 기기 웹 카탈로그 페이지(라우트·필터·push·지정번호 정렬),
WDS lazy load 설계(미구현), Stellarium/CSV import(upstream 반영분)

주요 파일: `python/PiFinder/web_catalogs.py`, `python/views/catalogs*.html`

검토 포인트 / 테스트 항목:

- [ ] 통합검색 결과 정렬(지정번호 우선)과 push-to 동작
- [ ] `test_web_catalogs.py` (있는 경우) / 웹 UI 수동 확인

<a id="mf_feature_review_checklist_ko--22-조이스틱게임패드-입력"></a>
### 22. 조이스틱/게임패드 입력

우선순위: P2

주요 변경: evdev 직접 읽기(`joystick_input.py`), Settings > Advanced >
Joystick 바인딩 UI, 마운트 조그 연동. `python3-evdev`는 setup 스크립트가 설치.

검토 포인트 / 테스트 항목:

- [ ] 버튼 캡처/바인딩/Clear All, `test_joystick_input.py`

<a id="mf_feature_review_checklist_ko--23-소프트웨어-업데이트-채널--포크-릴리즈--m-버전"></a>
### 23. 소프트웨어 업데이트 채널 — 포크 릴리즈 / m-버전

우선순위: P1

주요 변경:

- 릴리즈 체크·NixOS 마이그레이션 게이트 URL을 `hjoungjoo/MF_PiFinder`
  release 브랜치로 전환 (brickbots 감시 금지 — 테스트로 핀)
- `version.txt` m 접두사 체계(`m2.6.0`), `_semver_tuple()`이 접두사 파싱
- 릴리즈 정보 미확보("Unknown") 시 "Update Now" 대신 안내 표시

주요 파일: `python/PiFinder/ui/software.py`, `version.txt`

검토 포인트 / 테스트 항목:

- [ ] release 브랜치 컷 후: 버전 비교/Update Now/`pifinder_update.sh` 흐름
- [ ] `test_software.py` (m-버전 4건 + Unknown 분기 + URL 핀 2건)

<a id="mf_feature_review_checklist_ko--24-디스플레이--ssd1333-자동감지--4축-밝기"></a>
### 24. 디스플레이 — SSD1333 자동감지 + 4축 밝기

우선순위: P2 (SSD1333 패널 채택 시 P1)

주요 변경:

- MF 자동감지: BQ25895(0x6A) ACK → ssd1333, 실패 시 ssd1351 폴백
  (`hardware_detect.py`)
- upstream #568+#570 4축 밝기 부분 이식(드라이버+테스트+모델 문서만;
  측정 하네스/저널 제외 — `docs/ax/display/ssd1333-response.md` MF note)
- Pi5 SPI 헬퍼(`display_spi`), `bus_speed_hz` 시그니처, MF `rotate=0` 유지

검토 포인트:

- [ ] **비-rev4 보드에 SSD1333 연결 시 `--display ssd1333` 지정 필요**
      (자동감지는 rev4 마커 기준)
- [ ] 밝기 전 구간에서 타이틀바 최암부 계조가 살아 있는가 (실패널 실측 미실시)

테스트 항목: `test_ssd1333_brightness.py`(17), `test_hardware_detect_display.py`(4)

<a id="mf_feature_review_checklist_ko--25-설치-스크립트--마이그레이션"></a>
### 25. 설치 스크립트 / 마이그레이션

우선순위: P0

주요 변경:

- `pifinder_setup.sh` = 포크 설치본(main 클론), upstream 원본은
  `pifinder_setup.sh.bak` 보존
- SD 마모 저감(tmpfs /tmp, indiserver logrotate, journald 캡),
  python3-evdev 설치, 콘솔 자동로그인(B2)
- MF 마이그레이션: `mf_apsta_wifi`, `mf_wifi_settings`, `mf_removeipc`
  (마커 파일 게이트 — 버전 문자열 아님)

검토 포인트 / 테스트 항목:

- [ ] 새 OS에서 `pifinder_setup.sh` 일반 사용자 실행 완주
- [ ] upstream 머지 시 이 파일 충돌 → `.bak`과 비교해 선별 반영
- [ ] `test_wifi_apsta_static.py` (setup 스크립트를 경로로 직접 읽음)

<a id="mf_feature_review_checklist_ko--최소-회귀-테스트-명령"></a>
### 최소 회귀 테스트 명령

전체 스위트가 1분 안에 끝나므로(2026-08-05 기준 1,114건/약 55초, Pi4 venv)
개별 파일 나열 대신 전체를 돌린다:

```bash
cd python/ && source .venv/bin/activate
python -m pytest -m "smoke or unit" -q
nox -s lint && nox -s format
```

주의: venv 미활성 시 시스템 파이썬에 selenium이 없어 `tests/website`
수집 오류로 중단된다 — venv부터 확인할 것.

<a id="mf_feature_review_checklist_ko--실제-장비-통합-테스트-순서"></a>
### 실제 장비 통합 테스트 순서

권장 순서:

1. PiFinder 서비스 부팅
2. Web UI 접속
3. LCD/OLED UI 확인
4. Camera preview/focus
5. GPS unlock 상태 확인
6. 저장된 location load
7. Time sync 상태 확인
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
19. Plate solve 후 correction reset
20. Reboot 후 설정 유지 확인
21. 야간: 하이브리드 솔빙 solve_path/솔브율 확인 (§17)
22. 야간: SQM 라디오미터 값 상식 검증 + (미완이면) 위저드 실행 (§19)
23. LiveCam 프리뷰 갱신 속도와 TIFF/포맷 다운로드 (§20)
24. Software 화면: 릴리즈 체크가 포크를 보는지, m-버전 표시 (§23)

<a id="mf_feature_review_checklist_ko--결과-기록-양식"></a>
### 결과 기록 양식

테스트할 때 아래 형식으로 기록하면 다음 패치 판단에 도움이 된다.

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


---

<a id="mf_solver_goto_field_sheet_20260908_ko"></a>

## mf_solver_goto_field_sheet_20260908_ko.md

<a id="mf_solver_goto_field_sheet_20260908_ko--솔빙goto-현장-기록표"></a>
## 솔빙·GoTo 현장 기록표

[통합 작업서](validation.md#mf_solver_goto_observation_workplan_20260908_ko)를 기준으로 관측 날짜별 사본을 만들어 작성한다.
**전처리 실행 간격 유지 / 한 번에 한 변경 / A→B→A / 정밀도·성공률 우선**.

<a id="mf_solver_goto_field_sheet_20260908_ko--1-관측-기준"></a>
### 1. 관측 기준

| 항목 | 기록 |
| --- | --- |
| 날짜·시간대·장소 | |
| 카메라·렌즈·초점 | |
| 왜곡 profile / k1 / target pixel | |
| 코드 HEAD / 실제 실행 소스 식별 / 미커밋 변경 | |
| 기준 config·소스·DB·warm map 보관 위치 | |
| 원복 묶음 이름·위치 | |
| 마운트·펌웨어·모드 | |
| guide rate / NS·WE 반전 / 도착 허용 오차 | |
| 노출 방식 / 실제 노출·게인 | |
| 독립 중심 오차 측정 방법·측정 불확실성 | |
| A/B 정밀도 허용 차이(시험 전 결정) | |
| R0 연결 계측 준비 / 수집 부하 점검 | |

<a id="mf_solver_goto_field_sheet_20260908_ko--2-시작종료-확인"></a>
### 2. 시작·종료 확인

- [ ] 현재 구성의 정렬·추적·GoTo 정상 동작 확인.
- [ ] 고정·추적 ON/OFF를 각 구간에 명시.
- [ ] RAW 기록은 광해 선택→시작, 기본 60초/120시도/512MiB 제한 확인.
- [ ] 긴 GoTo는 별도 telemetry 기록과 제어 로그로 전체 동작 포함 확인.
- [ ] 단계 태그는 분류용이며 메모에 변경 ID와 A/B를 기입.
- [ ] 종료 후 solver/integrator complete/error, 종료 이유·누락 확인.
- [ ] 원복 뒤 기준 동작 재확인, 원본과 제어 로그 보존.

<a id="mf_solver_goto_field_sheet_20260908_ko--3-구간-목록"></a>
### 3. 구간 목록

| 시험 ID | 시각 | F단계 / 변경 ID / A·B | 광해·광원·고도 | 고정/추적 | 출발→목표 / 이동각 | session ID / GoTo ID | 조건 변화·메모 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 01 | | | | | | | |
| 02 | | | | | | | |
| 03 | | | | | | | |
| 04 | | | | | | | |
| 05 | | | | | | | |
| 06 | | | | | | | |

<a id="mf_solver_goto_field_sheet_20260908_ko--4-goto-1회-상세--필요한-만큼-복사"></a>
### 4. GoTo 1회 상세 — 필요한 만큼 복사

| 항목 | 기록 |
| --- | --- |
| 시험 ID / GoTo ID / session ID | |
| 변경한 한 가지 항목 / 기준 A와 차이 | |
| 명령 시각 | |
| 마운트 이동 종료 / 검증된 안정 시각 | |
| 첫 정지 후 유효 솔빙 촬영 / 게시 시각 | |
| 첫 보정 / 마지막 보정 / 완료 시각 | |
| 총 시간 / 결과(성공·실패·중지) / 실패 이유 | |
| 재Sync·GoTo 횟수 / 펄스 횟수 | |
| 최종 실제 중심 오차 / 측정 방법 | |
| 추적 유지 중 변화 / 불필요한 움직임 | |
| fallback·타임아웃 / 기타 대기 | |
| RAW·게시·제어 기록 누락 / 불완전 구간 | |

<a id="mf_solver_goto_field_sheet_20260908_ko--5-반전지연-사건--필요한-만큼-복사"></a>
### 5. 반전·지연 사건 — 필요한 만큼 복사

| 항목 | 기록 |
| --- | --- |
| 사건 시각 / 전후 15초 자료 위치 | |
| 관측 방향(화면/경통/NS·WE 구분)·지속 시간 | |
| 명령 방향·길이·guide rate / 실제 움직임 | |
| 사용 frame ID / 노출 시작·종료 / 소비 시각 | |
| 이전 펄스 시작·종료와 노출의 관계 | |
| 단일 해 / 평균 해 / 실제 target 오차 | |
| 실제 오버슈트에 대한 필요한 복귀인가 | |
| 원인 분류 / 확인 근거 / 미확인 부분 | |
| 중지·원복 여부 | |

<a id="mf_solver_goto_field_sheet_20260908_ko--6-ab-결과와-후속-작업"></a>
### 6. A/B 결과와 후속 작업

| 항목 | A 기준 | B 변경 | A 복귀 |
| --- | --- | --- | --- |
| 전체 시도 / 성공·실패·타임아웃 | | | |
| 승인율 / 연속 실패·보류 | | | |
| 게시 지연 p50 / p95 / 최대 공백 | | | |
| GoTo 총 시간(개별값 또는 충분한 표본의 분포) | | | |
| 펄스·재GoTo 횟수 / 설명되지 않은 반전 | | | |
| 실제 최종 중심 오차 / 추적 안정성 | | | |
| 수집 부하·누락 / 비교 방해 조건 | | | |

판정: **채택 / 원복 / 추가 검증** 중 선택하고 이유를 적는다.

- 개선한 시간 구간과 증거:
- 정밀도·정상 성공 사례 보존 근거:
- 원인 확정된 문제 / 아직 가설인 문제:
- 비교에서 제외한 구간과 이유(원본은 보존):
- 다음 변경 한 가지와 필요한 시험:
- 자료 묶음·분석 문서 위치:


---

<a id="mf_solver_goto_observation_workplan_20260908_ko"></a>

## mf_solver_goto_observation_workplan_20260908_ko.md

<a id="mf_solver_goto_observation_workplan_20260908_ko--솔빙-안정성정밀도-유지와-goto-지연-개선-통합-관측-작업서"></a>
## 솔빙 안정성·정밀도 유지와 GoTo 지연 개선: 통합 관측 작업서

작성일: 2026-09-08. 상태: **검토·시험 계획 작성 완료, 아래 개선안은 구현·현장 검증 전**.
검토 당시 HEAD: `5d59a442`. 로컬 미커밋 변경이 있으므로 HEAD만으로 실행 코드를 식별하지 않는다.

이 문서는 다음 실제 관측에서 기준 측정, 원인 분리, 변경안 시험, 채택 판단에 사용할 주 작업서다.
2026-09-08 저녁의 1차 실행 결과와 C2/C4 일부 적용 상태는
[토성 추적 실측 보고서](../../mf_report/mf_solver_goto_field_test_20260908_ko.md)에 기록했다.
이어 적용한 전처리 중복 계산 제거, 펄스 관측 나이 보호와 전송 로그는
[속도 후속 개선 보고서](../../mf_report/mf_solver_speed_followup_20260908_ko.md)에 기록했다.
아래 본문은 최초 계획이며 모든 후보가 적용됐다는 뜻은 아니다.
현장에서는 [현장 기록표](validation.md#mf_solver_goto_field_sheet_20260908_ko)를 복사해 사용한다.
기존 [자료 수집 작업서](validation.md#mf_solver_performance_capture_workplan_20260907_ko)는 수집 기능·파일 형식 참고용으로 유지한다.

<a id="mf_solver_goto_observation_workplan_20260908_ko--1-목표와-변경-원칙"></a>
### 1. 목표와 변경 원칙

사용자는 마지막 실측에서 정확한 추적과 GoTo가 가능함을 확인했다. 해결하려는 증상은 다음과 같다.

- 광해가 있거나 솔빙이 지연되면 GoTo 도착과 미세 보정에 시간이 오래 걸린다.
- 보정 중 간혹 약하게 반대 방향으로 움직인다.
- 정상적인 솔빙, 실제 중심 정밀도, 추적 안정성을 유지하면서 위 지연과 불필요한 움직임을 줄이고 싶다.

우선순위는 **정상 솔빙·정밀도 보존 → 불필요한 보정 감소 → 유효 좌표 공급 및 GoTo 완료 시간 단축**이다.
왜곡 계수의 RMSE 최소화나 초당 시도 횟수 증가 자체를 성공으로 삼지 않는다.

고정 조건:

1. **전처리 실행 간격은 변경하지 않는다.** 파일 저장 간격과 제어 펄스 간격은 다른 항목이며 혼동하지 않는다.
2. 솔빙 품질·연속성 기준, 최종 도착 허용 오차를 느슨하게 해서 속도를 얻지 않는다.
3. 한 번에 한 가지 변경을 시험하고, 기준 A → 변경 B → 기준 A 복귀로 비교한다.
4. 광학·왜곡·정렬·노출·가이드 속도 변경을 같은 A/B에 섞지 않는다. Auto Star 사용 시 실제 노출·게인을 기록한다.
5. 이번 문서 작성에서는 운영 코드·설정·서비스를 변경하지 않았다. 아래의 ‘후보’는 이미 적용된 기능을 뜻하지 않는다.

<a id="mf_solver_goto_observation_workplan_20260908_ko--2-현재까지-확인한-사실과-한계"></a>
### 2. 현재까지 확인한 사실과 한계

<a id="mf_solver_goto_observation_workplan_20260908_ko--21-동일-코드의-두-방향-고정-시험"></a>
#### 2.1 동일 코드의 두 방향 고정 시험

| 항목 | 광해 심한 방향 | 직접 조명 적은 방향 |
| --- | --- | --- |
| 세션 | `e93cc8242a534e9eb0a1188af32236bc` | `ef8d72f2a6064f4499e4c7fb850adb51` |
| 승인/시도 | 64/77, 83.1% | 109/112, 97.3% |
| 입력 확보→게시 지연 p95 | 1.728초 | 0.245초 |
| 유효 게시 간격 p95 / 최대 | 3.089 / 3.291초 | 0.645 / 1.155초 |
| 실행 | sync 25 / async 52 | async 112 |
| 실제 노출 | 436948µs | 537140µs |
| 일주운동 근사 제거 후 target 분포 p95 | 71.29″ | 71.61″ |

광해 방향 sync 25회의 RAW 경로 시간 중앙값은 약 100.89ms, 전처리·검출 작업은 1376.23ms였다.
두 단계의 중앙값 합은 전체 처리 시간 중앙값과 같지 않다. 비동기 전처리 작업 시간은 전경 지연에 더하지 않는다.

이 자료는 고정·무추적 시험이며 사용자가 보고한 GoTo 역방향 움직임 당시의 제어 기록이 아니다.
두 방향은 별 분포와 자동 노출이 달라 광해만의 효과를 분리하지 못한다.
좌표 분포는 실제 기준 천체 대비 절대 중심 오차가 아니다.

<a id="mf_solver_goto_observation_workplan_20260908_ko--22-재현된-보정-일관성-문제"></a>
#### 2.2 재현된 보정 일관성 문제

대응 full RAW가 없을 때 이미 준비된 RAW/전처리 간 편향 보정이 512 해에 적용되지 않는 경로가 확인됐다.
9월 7일 `e53df91c…` 21번은 해당 후보가 승인됐다. 저장된 보정을 적용한 오프라인 계산에서 인접 target 변화가
약 137″/127″에서 40″/45″로 줄었다. 9월 8일 광해 세션 18번에서도 재현됐지만 이때는 연속성 검사에서 보류됐다.
이는 처리 일관성 개선 근거이며 절대 정확도나 수정 후 현장 성능 검증은 아니다.

<a id="mf_solver_goto_observation_workplan_20260908_ko--23-서로-다른-제어-판단과-시간-검사"></a>
#### 2.3 서로 다른 제어 판단과 시간 검사

| 현재 동작 | 개선 검토 이유 |
| --- | --- |
| 펄스는 최소 3초 간격, 최대 길이 2.5초 | 짧은 펄스에서는 남는 대기를 줄일 여지가 있지만 긴 펄스는 겹치면 안 됨 |
| 다음 펄스는 직전에 사용한 솔빙보다 새로운 timestamp를 요구 | 이전 펄스 종료 후 촬영했는지와 실제 좌표 나이는 해당 경로에서 직접 검사하지 않음 |
| GoTo 완료 판단은 조건에 따라 5개 솔빙 평균, 펄스는 단일 `pointing.aligned.solve` 사용 | 오차 판단 기준과 시간 범위가 서로 달라질 수 있음 |
| 평균 좌표는 최신 표본 timestamp를 사용 | 구성 표본 모두가 정지·펄스 종료 후 관측이라는 뜻은 아님 |
| 하위 GoTo 안정 확인 2.5초, 상위 추가 1초 및 1초 heartbeat | 정지 판정과 유효 영상 대기가 누적될 수 있음. 일부 주석의 4초는 현재 상수와 다름 |
| 상위 idle 인지 시각 이후 솔빙을 요구 | 실제 정지 후 촬영했어도 상위 idle 인지 전이면 배제될 수 있음 |
| 새 정지 후 high-quality solve 대기 12초 후 현재 좌표로 계속 판단하는 fallback | 오래된 관측·다른 품질의 좌표가 재-SYNC/GoTo로 연결됐는지 확인 필요 |
| RAW 실패 시 동기 복구, 3연속 패턴 성공 시 비동기 전환 | 복귀 시 누적 초기화와 실행 중 백그라운드 작업의 경합 검토 필요 |

상위 상태 파일이 최근에 갱신됐다는 사실은 영상이 최근 촬영됐다는 뜻이 아니다.
펄스 역전의 가능한 설명은 지연된 관측, 단일 해의 흔들림, 실제 오버슈트, 백래시/축 응답 등이다.
어느 것도 현재 기록만으로 원인으로 확정하지 않는다. 정상적인 초과 이동을 되돌리는 반전은 필요한 동작일 수 있다.

<a id="mf_solver_goto_observation_workplan_20260908_ko--24-왜곡-비교의-위치"></a>
#### 2.4 왜곡 비교의 위치

실제 변경된 k1은 **−0.08 → −0.11**이었다. 중앙값은 통계값이지 중앙부 왜곡률을 뜻하지 않는다.
저장 RAW 60장으로 생성한 전처리 입력 12개에서 −0.11은 기존보다 일관되게 개선되지 않았다.
−0.10은 고정 Brown 모델의 공통 별 교차검증에서 12개 모두 가장 좋은 후보였으나 운영 최적값으로 확정되지 않았다.

보정 저장값의 재검증 누락, 서로 다른 프레임 집합의 RMSE 개선율 비교,
`distortion=0`이어도 Tetra3가 후속 왜곡을 다시 적합하는 점을 확인했다.
반면 Brown 역변환 반복 8→100회의 차이는 이번 공통 별 비교 순위를 설명하지 못했다.
왜곡 재보정은 별도 시험으로 남기며, GoTo 지연 A/B 전에 임의로 변경하지 않는다.

<a id="mf_solver_goto_observation_workplan_20260908_ko--3-개선-후보와-의존-순서"></a>
### 3. 개선 후보와 의존 순서

| ID / 우선순위 | 변경 후보 | 기대 효과 | 주요 검증 / 원복 조건 |
| --- | --- | --- | --- |
| R0 / 필수 준비 | 솔빙–게시–제어–펄스–마운트 상태 연결 기록 | 반전·대기 원인을 구간별로 분리 | 기록 부하, 누락, 시계/ID 연결 확인. 성능 영향 시 기록량 축소 후 별도 비교 |
| C1 / 먼저 | 동일 RAW 전달 및 편향 적용을 RAW 확보 여부와 분리 | 좌표 불연속·전환 보류 감소 | 유효 context에서 정확히 1회 적용. 중복/과거 보정 사용 시 원복 |
| C2 / 먼저 | 펄스 후 노출·좌표 나이·명령 세대 검사 | 오래된 오차를 다시 보정하는 상황 방지 | 펄스 전/중 촬영 영상의 지연 도착, target 변경, 시각 불연속 시험 |
| C3 / 다음 | 완료 판단과 펄스가 사용하는 제어 좌표·표본 범위 일치 | 판단 충돌·불필요한 반전 감소 | 평균 지연과 작은 부호 반전 확인 조건 평가. 실제 이동 반응 악화 시 원복 |
| C4 / 다음 | 검증된 정지 시각 공유 및 이미 확보한 정지 후 영상 활용 | 도착 후 중복 대기 감소 | 정지 전/중간 일시 정지 영상을 채택하지 않을 것. 12초 fallback 별도 확인 |
| P1 / 저위험부터 | 불가능한 후보 탐색 제외, 동일 RAW 재사용, 불필요한 SEP 대기 절감 | 계산량·실패 탐색 시간 감소 | 경로별 승인 조건 보존, overlay/backoff/후보 통계 유지 |
| P2 / 구조 변경 | 전처리 복구와 새 RAW 처리의 대기 분리 | 광해에서 긴 좌표 공백 감소 | Tetra3/Cedar 자원 독립 소유, 누적 시각, generation, CPU 경합 검증 |
| P3 / C2·C3 후 | 펄스 종료·안정·새 관측 조건에 따른 다음 보정 시점 | 짧은 펄스 뒤 불필요한 3초 대기 감소 | 펄스 중첩 금지. 솔빙이 늦으면 효과 제한. 과보정 증가 시 원복 |
| Q1 / 별도 분기 | 모드 전환·편향 학습 안정성 및 광학 보정 평가 개선 | 좌표 품질과 전환 안정성 개선 | 동일 입력·공통 별·최종 저장값 검증, 독립 기준 오차 확인 |

P1의 후보 수 사전 검사는 native Cedar/SEP의 실제 최종 최소 조건에 맞춘다. RAW 512에 일괄 적용하지 않는다.
P2는 단순히 모든 처리를 비동기로 바꾸는 변경이 아니다. 과거 결과의 timestamp를 새 프레임으로 바꾸지 않는다.
실행 중 작업은 `clear_pending()`으로 취소되지 않는다. 누적 상태 공유도 이동·광학·정렬 context가 동일함을 입증해야 한다.
Q1의 모드 전환은 패턴 성공 횟수 외에 실제 승인 이력·경로·동일 프레임 일치도·bias 준비 상태를 비교한다.

<a id="mf_solver_goto_observation_workplan_20260908_ko--4-다음-관측-전에-준비할-것"></a>
### 4. 다음 관측 전에 준비할 것

<a id="mf_solver_goto_observation_workplan_20260908_ko--41-기준-보존"></a>
#### 4.1 기준 보존

- 장치·카메라·렌즈·초점·왜곡 profile/k1·target pixel·마운트 모드·guide rate/반전 설정을 기록한다.
- 정상 동작 기준의 config, 미커밋 변경 포함 소스, 별 DB, warm-pixel map, 광학 profile을 보관한다.
- 변경을 실제 실행 프로세스가 로드했는지 확인한다. 기록 시점 디스크 소스 해시만으로 실행 코드를 보증하지 않는다.
- 복귀할 코드와 설정 묶음의 이름을 현장 기록표에 적는다. 관련 없는 로컬 변경을 덮어쓰는 일괄 reset은 사용하지 않는다.
- 첫 기준 측정은 현재 검증된 구성으로 한다. 단지 분석 후보라는 이유로 −0.10을 적용하거나 왜곡 보정을 다시 하지 않는다.

<a id="mf_solver_goto_observation_workplan_20260908_ko--42-추가-계측-r0--아직-구현-전"></a>
#### 4.2 추가 계측 R0 — 아직 구현 전

기존 수집은 solver/integrator 기록이다. 다음 항목이 이미 자동 저장된다고 가정하지 않는다.
역방향 원인을 확정하고 C2~C4/P3을 검증하려면 연결 계측을 먼저 구현·확인해야 한다.

| 연결 구간 | 추가로 필요한 기록 |
| --- | --- |
| 입력 | boot/session/frame ID, 노출 시작·종료·기간 및 시각 정의, 누적 입력 목록·관측 범위 |
| 승인·소비 | 처리 완료·게시·제어 소비 시각, 원래 좌표·제어 좌표, 품질·보류 이유, 실제 bias 적용 여부/세대/전후 좌표 |
| 평균·세대 | 평균에 포함된 frame ID·최초/최종 시각, target/정렬/광학/이동 세대 |
| 명령 | GoTo/Sync/펄스 ID, 판단 오차, 축·방향·길이·guide rate·반전 설정, 요청/송신/응답 시각 |
| 실제 동작 | INDI 위치·운동·추적 상태, 가능한 실제 펄스 종료, 예상 종료와 확인 종료의 구분, 안정 판정 시각 |
| 완료 | GoTo 상태 전환, 대기 이유, fallback, 타임아웃, 최종 오차·좌표 출처 |

시각 차이는 같은 boot의 monotonic 기준으로 계산한다. 센서 wall-clock 시각과 연결할 때는 대응 관계와 시간 보정 이벤트를 보존한다.
INDI 명령 응답은 모터가 실제로 그만큼 움직였다는 증거가 아니다. 프레임 반응·위치 telemetry·관측 확인을 같이 쓴다.
짧은 펄스는 1초 단순 polling으로 놓칠 수 있어 명령 발생 지점의 이벤트 기록을 우선한다.
수집기는 제한된 큐로 비동기 저장하고 누락을 명시한다. 기록 기능의 성능 영향도 시험한다.

<a id="mf_solver_goto_observation_workplan_20260908_ko--43-코드상-모의-검증"></a>
#### 4.3 코드상 모의 검증

C2~C4/P3 구현 전후에는 다음 순서를 제어기에 재생하는 의미 있는 테스트가 필요하다.

- 이전 판단보다 새로운 영상이지만 이전 펄스 시작 전 촬영되어 늦게 게시되는 경우.
- 노출이 펄스와 겹친 경우, 펄스 종료 후 정상 영상, 장시간 새 솔빙 없음.
- 작은 오차의 부호만 흔들리는 경우와 실제로 목표를 넘어선 경우.
- 평균 창에 펄스 이전 표본이 남은 경우, 새 timestamp에 오래된 평균이 붙는 경우.
- 이동·정렬·target 변경·시계 보정·재시작 직전 작업이 뒤늦게 완료되는 경우.
- RAW 누락/복구와 bias reset 전후, 비동기↔동기 전환, 누적 워밍업 실패.

합격: 중복·이전 세대 펄스 없음, 검증되지 않은 완료 없음, 현재 정상 성공 사례 보존,
정상 새 관측이 도착하면 대기가 풀릴 것. 시간 검사 강화가 무한 대기나 항상 실패를 만들지 않아야 한다.

<a id="mf_solver_goto_observation_workplan_20260908_ko--5-현장-수집-방법"></a>
### 5. 현장 수집 방법

<a id="mf_solver_goto_observation_workplan_20260908_ko--51-짧은-raw-기준-기록--현재-사용-가능"></a>
#### 5.1 짧은 RAW 기준 기록 — 현재 사용 가능

1. 기존 PiFinder 웹 주소의 `/solver-capture`를 연다.
2. **광해 정도 선택 → 기록 시작**. 기본 RAW 포함, 최대 60초/120시도/기록 프로세스별 512MiB다.
3. solver와 integrator가 해당 session ID로 수집 중인지 확인한다.
4. 종료 후 두 작업의 complete/error, 종료 이유, RAW 수, 누락 수를 확인한다. draining이면 저장 완료를 기다린다.
5. session ID와 고정/추적 상태를 기록표에 적는다.

시작 버튼을 눌렀다고 정확히 60초 전체가 보장되지는 않는다. 시간·건수·용량 중 먼저 도달한 제한이 적용된다.
솔버가 사용한 RAW만 저장하므로 카메라 전체 연속 스트림이나 운영 누적 이력이 모두 복원되는 것은 아니다.

<a id="mf_solver_goto_observation_workplan_20260908_ko--52-긴-goto-기록"></a>
#### 5.2 긴 GoTo 기록

긴 동작 전체를 기본 RAW 60초 기록 하나로 덮었다고 판단하지 않는다.
세부 시험 설정에서 **결과·시간만 / 300초 / 최대 2000시도 / 512MiB**를 시작용 설정으로 사용할 수 있다.
이 값은 시험 수집 설정이며 운영 솔빙 기본값 변경이 아니다. 실제 종료 이유와 전체 동작 포함 여부를 확인한다.
대표 방향의 RAW 60초는 별도로 수집한다. 동시에 두 recorder 세션을 시작하지 않는다.

R0 제어 이벤트 기록이 준비됐다면 같은 GoTo ID로 함께 연결한다.
준비되지 않았다면 GoTo 시작/도착/반전 시각과 축·화면 오차를 수동으로 메모하고 결과를 **예비 관측**으로 분류한다.
수동 메모만으로 펄스 원인을 확정하거나 제어 변경을 검증 완료로 처리하지 않는다.

기존 UI의 ‘테스트 단계’는 자료 분류용이며 기능 활성화 스위치가 아니다.
C1/C2 등 이 문서의 ID는 새로운 UI 선택 항목이 아니다. `validation` 등 기존 태그와 메모 `C2-B-01`을 조합한다.
‘현재 구간 표시’는 다음 처리 프레임부터 적용되므로 정확한 명령 발생 시각의 대체물이 아니다.

<a id="mf_solver_goto_observation_workplan_20260908_ko--6-현장-시험-순서"></a>
### 6. 현장 시험 순서

| 단계 | 실행 | 최소 수집과 비교 | 다음 단계로 진행 조건 |
| --- | --- | --- | --- |
| F0 기준 확인 | 현재 정상 구성으로 정렬·추적·짧은 GoTo 확인 | 설정/코드 식별, 기준 천체, 실제 중심 위치, 계측 정상 여부 | 정상 구성 재확인. 이상이면 변경 시험을 시작하지 않고 원인 기록 |
| F1 정지 비교 | 광해 적음·심함에서 고정 시험, 추적 ON/OFF 구분 | 방향별 RAW 60초 각 3회 권장. 동일 조건 telemetry 구간으로 수집 부하 비교 | 입력·게시 연결과 누락 해석 가능, 기준 좌표 품질 확보 |
| F2 추적 유지 | 같은 기준 천체에서 추적 ON으로 유지 | 방향별 3~5분, 실제 중심 오차·드리프트·펄스·좌표 나이 기록 | 무추적 일주운동과 추적 오차를 혼동하지 않음 |
| F3 GoTo 기준 | 각 방향에서 넓은 이동과 근거리 재보정 시험 | 각 유형 3회 예비 반복, 출발/목표/이동각을 기록 | 총 시간과 각 대기·펄스를 연결. 증상 발생 시 세션 보존 |
| F4 단일 변경 | 준비·모의 검증된 후보 하나만 적용 | 동일 목표/유사 출발점에서 A→B→A, 같은 유형 최소 3쌍 예비 비교 | 정밀도·성공률 보존, 시간 개선 반복 확인, 원복 정상 |
| F5 환경 전환 | 별이 잘 보이는 방향↔광해 방향 이동 후 복구 | 이동 완료→첫 유효 솔빙, 모드 전환·bias·긴 공백 | 이전 자세 결과가 재사용되지 않고 정상 복구 |
| F6 최종 조합 | 단독 합격한 변경만 조합 | 15~30분 관측 및 양방향 GoTo 반복을 목표로 기록 분할 | 조합에서 회귀 없음. 기록 종료로 생긴 공백과 솔빙 공백 구분 |

반복 수와 시간은 현장 시작안이다. 3회만으로 희귀 오동작이나 p95 개선을 입증할 수는 없다.
구름·바람·초점·별 영역 변화가 큰 쌍은 제외 사유를 남기고 다시 비교한다. 실패 기록 자체는 삭제하지 않는다.
시간이 부족하면 **F0~F3 기준 자료 확보가 우선**이다. 미구현 후보를 급히 동시에 적용하지 않는다.

F1의 고정·무추적 자료는 좌표 변동 분석에, F2의 추적 자료는 추적 유지에,
F3/F4는 실제 GoTo 시간 검증에 사용한다. 어느 한 종류의 결과로 나머지를 대체하지 않는다.
광해 방향은 사용자가 실제 사용하는 별이 보이는 시야를 선택하고 고도·국소 광원의 화면 위치를 함께 남긴다.

<a id="mf_solver_goto_observation_workplan_20260908_ko--7-반대-방향-움직임-발생-시-판별-절차"></a>
### 7. 반대 방향 움직임 발생 시 판별 절차

1. 관측 시각, GoTo ID, 축(NS/WE 또는 화면 방향), 실제 별 이동 방향, 지속 시간, 당시 오차를 기록한다.
2. 해당 시점 전후 최소 15초의 원본과 제어 이벤트를 연결한다. 전후 맥락이 없으면 불완전 사례로 보존한다.
3. 명령 반전이 있었는지 확인한다. 화면의 별 이동 방향은 경통 방향과 같지 않을 수 있어 축 정의를 맞춘다.
4. 명령이 반전됐다면 사용한 영상이 이전 펄스 전/중/후인지, 단일 해와 평균 해가 서로 달랐는지 확인한다.
5. 실제 오차가 이미 부호를 바꿨다면 필요한 복귀 펄스인지 평가한다. 실제 오차가 그대로인데 좌표만 바뀌었다면 솔빙·시간·보정 경로를 우선 검토한다.
6. 명령은 같은 방향인데 실제 반응이 다르면 축 반전 설정·guide rate 적용·백래시·마운트 응답을 별도 시험한다.

진동·오차 증가가 반복되거나 의도하지 않은 이동이 지속되면 현장 중지 기능으로 동작을 멈추고 자료를 보존한다.
실측 반응을 확인하지 않고 두 축 반전 설정을 바꾸거나 펄스 강도를 올려 맞추지 않는다.

<a id="mf_solver_goto_observation_workplan_20260908_ko--8-지표와-채택-기준"></a>
### 8. 지표와 채택 기준

| 종류 | 필수 지표 | 해석 |
| --- | --- | --- |
| 솔빙 | 승인율, 연속 실패/보류, 경로별 성공·시간 | 빠른 실패 증가를 속도 향상으로 계산하지 않음 |
| 공급 | 입력 확보→게시 p50/p95, 최대 유효 좌표 공백, 제어 소비 시 영상 나이 | 처리 시간과 관측 시각을 분리. 긴 자료일 때만 p99 해석 |
| GoTo | 명령→이동 종료→첫 정지 후 승인→첫 보정→최종 확인 시간 | 총 시간 외에 어느 구간이 줄었는지 제시 |
| 제어 | Sync/재GoTo/펄스 횟수, 방향·길이, 반전 이유, 대기/fallback 횟수 | 필요한 반전과 잘못된 관측에 의한 반전 구분 |
| 정밀도 | 독립 기준 대비 target 중심 오차, 최종 오차, 추적 드리프트, 고정 산포 | RMSE·매칭 수는 보조. 화면에서 잘 맞았다는 확인과 정량 측정 구분 |
| 자원·수집 | CPU/가능한 온도·throttling, 기록 모드, 큐 누락, RAW 대응 누락, 해시 오류 | RAW 미확보와 저장 큐 누락을 별개로 집계 |

절대 오차는 기준 천체와 중심 pixel/스케일 또는 별도 영상 해를 통해 측정하고, 좌표계·epoch·관측 시각을 맞춘다.
PiFinder 좌표를 받아 움직이는 마운트/SkySafari의 표시가 PiFinder와 같다는 사실만으로 독립 검증이 되지는 않는다.
정량 기준이 없다면 ‘육안 중심 확인’으로 남기고 절대 정밀도 개선을 선언하지 않는다.

채택 조건:

- 프레임 오결합, 중복/과거 bias, 오래된 관측의 추가 펄스, 잘못된 완료가 재현 시험에서 없어야 한다.
- 동일 RAW에서 기준이 정상 승인한 해를 이유 없이 잃지 않고, 실제 중심 오차와 추적 안정성이 유지돼야 한다.
- 기준의 도착 허용 오차를 그대로 사용한다. 시험 시작 전 허용 차이를 측정 오차와 기존 산포를 보고 기록하고 사후 변경하지 않는다.
- p95·최대 좌표 공백 또는 반복 GoTo 총 시간이 줄어야 한다. 평균만 좋아지고 긴 대기·실패가 늘면 채택하지 않는다.
- 표본이 적거나 독립 정밀도 측정이 없으면 ‘유망/추가 검증’으로 남긴다. 새 기본값으로 확정하지 않는다.
- 실패·타임아웃도 전체 시도 수에 포함하고 성공한 GoTo만의 평균으로 비교하지 않는다.

원복 조건: 실제 오차·진동·실패 증가, 새 좌표가 있어도 진행되지 않는 대기, 누적/세대 오류,
마운트 명령 중첩, 기준 성공 사례 손실, 측정 불가능할 정도의 기록 누락이나 부하.
원복 후 동일 기준 시험을 1회 이상 반복해 정상 복귀를 확인한다. 이동 종료 후 필요한 재시작을 수행한다.

<a id="mf_solver_goto_observation_workplan_20260908_ko--9-관측-종료-후-분석보존"></a>
### 9. 관측 종료 후 분석·보존

1. 수집 종료·저장 완료를 확인하고 세션 폴더를 통째로 보존한다. 불완전 세션도 삭제하지 않는다.
2. 기존 `solver_capture report`로 무결성·완료 상태를 확인한다. 세션 경계의 게시 짝 누락을 실제 게시 실패로 단정하지 않는다.
3. 현장 기록표와 A/B 설정·실행 소스·R0 제어 로그·기준 영상·분석 스크립트를 연결한다.
4. 변경별로 ‘채택 / 원복 / 추가 검증’을 적고, 개선한 시간 구간과 정밀도 근거를 함께 기록한다.
5. 검증된 변경만 후속 기본값·배포 후보로 제안한다. 이번 문서 작성에 적용·커밋·서버 푸시는 포함하지 않았다.

<a id="mf_solver_goto_observation_workplan_20260908_ko--10-근거-자료"></a>
### 10. 근거 자료

- 9월 7일 안정성 분석 — 원본 장비의 기록 경로 `/home/pifinder/PiFinder_data/captures/analysis/20260907_stability/REPORT_ko.md`
- 9월 8일 두 방향 고정 시험 — 원본 장비의 기록 경로 `/home/pifinder/PiFinder_data/captures/analysis/20260908_live/REPORT_ko.md`
- 왜곡 계산·보정 평가 검토 — 원본 장비의 기록 경로 `/home/pifinder/PiFinder_data/captures/analysis/20260908_distortion_review/REPORT_ko.md`
- 동일 RAW 왜곡 계수 비교 — 원본 장비의 기록 경로 `/home/pifinder/PiFinder_data/captures/analysis/20260908_k1_comparison/REPORT_ko.md`
- GoTo 지연 코드 검토 — 원본 장비의 기록 경로 `/home/pifinder/PiFinder_data/captures/analysis/20260908_k1_comparison/GOTO_LATENCY_REVIEW_ko.md`
- [기존 동기·비동기 전환 설명](solver.md#mf_adaptive_solver_scheduling_ko)

원본 위치: `/home/pifinder/PiFinder_data/captures/solver_sessions/`.
장치 로컬 자료 링크는 다른 PC에서 자동으로 열리지 않는다. 문서와 관련 분석·세션 폴더를 함께 복사한다.
소스 근거: `solver.py`, `solver_scheduling.py`, `preprocess_bias.py`, `solve_acceptance.py`,
`sep_shadow.py`, `latest_frame_worker.py`, `integrator.py`, `pointing_coordinate_service.py`,
`mountcontrol_indi.py`, `indi_goto_guide_service.py`, `solver_capture.py`.


---

<a id="mf_solver_performance_capture_workplan_20260907_ko"></a>

## mf_solver_performance_capture_workplan_20260907_ko.md

<a id="mf_solver_performance_capture_workplan_20260907_ko--광해별-솔빙-속도정확도-검토-및-단계별-시험-작업서"></a>
## 광해별 솔빙 속도·정확도 검토 및 단계별 시험 작업서

작성: 2026-09-07. 기준 코드: `5d59a442` 이후 자료 수집 기능 추가 작업.

2026-09-08 후속: 다음 실제 관측의 개선 우선순위·GoTo/펄스 검증·채택 기준은
[솔빙·GoTo 통합 관측 작업서](validation.md#mf_solver_goto_observation_workplan_20260908_ko)를 먼저 사용한다.
현장 작성용 [기록표](validation.md#mf_solver_goto_field_sheet_20260908_ko)를 함께 제공한다.
이 문서는 기존 수집 기능의 사용법과 저장 형식 참고 자료로 유지한다.

<a id="mf_solver_performance_capture_workplan_20260907_ko--1-이번-작업-범위"></a>
### 1. 이번 작업 범위

구현한 것은 **시험 자료 수집 기능**이다. 아래 성능 개선안은 아직 적용하지 않았다.
전처리 실행 간격, RAW/전처리 선택 정책, 노출·게인, 품질·연속성 임계값,
마운트 제어는 변경하지 않는다. 수집은 기본 OFF이며 명시적으로 시작해야 한다.
단계 선택은 실험 이름표일 뿐 해당 최적화를 활성화하는 기능이 아니다.

목표는 광해가 강하거나 약할 때 **승인된 새 좌표를 빠르고 꾸준하게 공급하면서
실제 정렬 지점의 오차를 악화시키지 않는 것**이다. 실내 기능 점검은 별이 있는
하늘의 성능 검증을 대신하지 않는다.

<a id="mf_solver_performance_capture_workplan_20260907_ko--2-최종-코드-검토"></a>
### 2. 최종 코드 검토

| 항목 | 확인된 사실 | 제안 및 주의점 |
| --- | --- | --- |
| 불가능한 탐색 | native Cedar는 최종 최소 6매치, SEP는 7매치를 요구하지만 더 적은 후보로 시작하는 호출이 있음 | 경로별 최종 기준보다 후보가 적으면 사전 제외. RAW 512의 기존 정책에 일괄 적용하지 않음 |
| SEP 검출 잔류 | 전처리 우선 상태에서 RAW 대체 솔빙을 생략해도 SEP 검출 호출은 남음 | 별 표시·후보 통계·backoff 용도를 분리한 뒤 필요한 시점에 검출 |
| RAW 재조회 | 메인은 대응 RAW를 확보하지만 SEP는 공유 상태에서 최신 RAW를 다시 읽음 | 이미 확보한 동일 RAW를 직접 전달. 프레임 ID 검사를 없애지 않음 |
| 전환 조건 | raw_solved는 전처리 이전 대체 경로도 포함. 3회 패턴 성공과 bias 준비 조건이 분리됨 | 실제 경로·승인률·시간·잔차·보정 준비 상태를 함께 평가 |
| 비동기 범위 | 백그라운드는 전처리/SEP 검출, 후속 Cedar 검출·좌표 계산은 메인에서 실행 | 완전 분리는 후순위. Tetra3 캐시와 Cedar 공유 메모리를 독립 소유해야 함 |
| 전환 부하 | clear_pending은 실행 중 작업을 중단하지 않음. 동기 복귀는 누적 창을 초기화 | 실행 중 작업과 새 동기 작업의 CPU 경합, 재워밍업 공백 측정 |
| 시간 누적 | 최대 5프레임이며 실제 누적 시간 길이는 일정하지 않음 | 프레임 건너뛰기·별 이동과 합성 영상 centroid 편향 확인 |
| 메모리 | np.stack/float32 변환과 중간 배열이 반복됨 | 버퍼 재사용 후보. 연산 순서 변경 시 픽셀·centroid 동등성 검증 |
| 지표 | 기존 processing_ms는 큐 전달·integrator 반영까지 포함하지 않음 | 입력 확보→실제 공유 좌표 반영의 monotonic 지연을 별도 평가 |
| 정확도 | RMSE는 별 매칭 잔차이며 절대 지향 오차가 아님 | RA_target/Dec_target, 기준 좌표 오차, 정지 산포, 모드 전환 차이를 함께 평가 |

근거 소스: `solver.py`, `sep_shadow.py`, `solver_scheduling.py`,
`preprocess_bias.py`, `solve_acceptance.py`, `mf_star_only_preprocess.py`,
`latest_frame_worker.py`, `tetra3/cedar_detect_client.py`.

9월 3일 광해 A/B 기록은 원본 품질 솔브 0/30, 전처리 28/29, 전처리 연속성 승인
27/29였다. 당시 원본 실패 탐색 중앙값 약 611ms, 전처리 약 2124ms, 전처리 후
탐색 약 10ms였다. **과거 설정과 CPU 경합 조건의 결과이며 현재 속도 기준은 아니다.**

<a id="mf_solver_performance_capture_workplan_20260907_ko--3-현장-수집-사용법"></a>
### 3. 현장 수집 사용법

이 코드가 반영된 PiFinder 애플리케이션을 재시작한 뒤 사용한다. 수집 기능 추가만으로
서비스를 재시작하거나 실제 수집을 시작하지 않는다. 실제 관측 중 재시작은 이동을
종료한 뒤 수행한다. 웹 주소는 기존 PiFinder 주소 뒤에 `/solver-capture`를 붙인다.

예: `http://pifinder.local/solver-capture` (별도 웹 포트를 쓰면 그 주소를 유지).

1. **광해 정도만 선택하고 기록 시작**을 누른다. RAW·솔빙 결과·시간·설정·소스가
   자동 저장된다. 기본은 `baseline`, RAW 포함, 최대 60초/120시도/프로세스별 512MiB다.
2. 일반 수집에는 다른 설정이 필요 없다. 세부 비교 시험에서는 접힌 **세부 시험 설정**을
   열어 단계·메모·수집 내용을 바꿀 수 있다. 저장 부하 비교가 필요하면 **결과·시간만**
   60초와 같은 조건의 **RAW와 결과** 60초를 별도 수집한다.
3. 시작 요청 뒤 solver와 integrator 상태가 해당 session_id의 `recording`인지 확인한다.
   요청만 보이고 상태가 없으면 프로세스가 새 코드를 로드했는지 확인한다.
4. 선택 사항: 광원 방향·이동 시작/종료 등은 세부 시험 설정에 메모를 쓰고
   **현재 구간 표시**를 누른다. 구름·이동·실내 scene의 명시적 분류는 CLI로 가능하다.
   이미 시작한 솔빙은 이전 표시를 유지하고 다음 처리 프레임부터 새 표시를 사용한다.
   약 0.5초의 제어 확인 지연이 있으며, 프레임이 없으면 구간 이벤트도 기록되지 않는다.
5. 자동 종료 또는 **기록 종료** 후 두 기록 프로세스의 `complete` 또는 `error`를 확인한다.
   종료 전에 시작한 프레임/대기 저장분은 포함될 수 있다. `draining` 중에는 기다린다.
6. `directory`, `reason`, `dropped_records`, `raw_frames`를 확인해 원본 폴더를 보존한다.

CLI도 같은 요청을 사용한다. 웹과 CLI를 동시에 시작하면 중복 세션은 거부된다.

```bash
cd /home/pifinder/PiFinder/python

# 수집 부하가 작은 기준 구간
.venv/bin/python -m PiFinder.solver_capture start --scene light_pollution --stage baseline --mode telemetry --duration 60 --note '광해 방향, 고정 경통'
.venv/bin/python -m PiFinder.solver_capture status
.venv/bin/python -m PiFinder.solver_capture stop

# 앞 구간 저장 종료를 확인한 뒤 원본 수집
.venv/bin/python -m PiFinder.solver_capture start --scene light_pollution --stage baseline --mode raw --duration 60 --max-frames 120 --max-mib 512
.venv/bin/python -m PiFinder.solver_capture mark --scene transition --note '고도 상승 시작'
.venv/bin/python -m PiFinder.solver_capture mark --scene dark_sky --note '이동 종료, 별이 보이는 방향'
.venv/bin/python -m PiFinder.solver_capture stop
```

기본값은 최대 60초/120시도/기록 프로세스별 512MiB이며 먼저 도달한 제한에서
그 기록 작업자가 종료한다. 남은 디스크 공간이 약 128MiB 이하가 되면 종료한다.
용량 제한은 기록·영상 본문에 적용하며 초기 소스 사본·manifest·상태 파일은 별도다.
RAW 수집 기본은 솔버가 사용한 모든 시도를 대상으로 한다. 필요하면 `--raw-every 1`
등으로 **파일 저장만** 간격을 둘 수 있지만, 시간 누적 재생의 연속성이 줄어든다.
이는 전처리 실행 간격을 조절하지 않는다. 기록 작업자가 제한으로 종료해도 요청의
유효 시간이 남을 수 있으므로, 새 수집 전 `stop`과 종료 상태를 확인한다.

<a id="mf_solver_performance_capture_workplan_20260907_ko--4-저장-형식과-보존"></a>
### 4. 저장 형식과 보존

위치: `~/PiFinder_data/captures/solver_sessions/<session_id>/`

| 파일 | 내용 |
| --- | --- |
| manifest.json | 스키마 버전, 요청 조건, 관련 설정, Git HEAD, 주요 소스 SHA-256, Python/OS/boot ID |
| source/ | 수집 시작 시 주요 처리 모듈의 소스 사본. 로컬 미커밋 변경도 보존 |
| solver.jsonl | 시도별 프레임/시각/IMU 메타데이터, 구간, 승인·보류, 후보 좌표/매칭, 처리 경로·시간·후보 수, 편향/스케줄링/광학 정보 |
| solver_NNNNNN.npz | 같은 frame_id의 원본 센서 방향 RAW와 실제 512 솔버 입력. 숫자 배열만, 무손실·무압축 |
| integrator.jsonl | 솔브 메시지별 공유 상태 게시 여부와 게시 직후 monotonic 시각, 실제 pointing/진단 정보 |
| solver_summary.json / integrator_summary.json | 종료 이유, 저장 건수·바이트·큐 누락 건수 |

각 RAW 파일의 파일명·SHA-256·바이트 수는 대응 solver.jsonl 레코드에 있다.
파일을 임시 이름으로 쓰고 이름 변경을 완료한 다음 JSONL에 연결한다. 갑작스러운
전원 차단 시 `.part`나 마지막 불완전 JSONL 줄이 남을 수 있다. 요약 없는 폴더도
삭제하지 말고 불완전 세션으로 보존한다. 자동으로 기존 관측 자료를 지우지 않는다.

RAW는 **카메라 전체 프레임이 아니라 솔버가 실제 사용한 프레임**이다. 카메라의
중간 프레임 건너뛰기와 저장 큐 누락은 다른 현상이다. 카메라 frame_sequence/
frame_id/촬영 시각과 recorder sequence/dropped_records를 함께 확인한다.
필요한 전체 센서 연속 스트림 수집 기능은 이번 범위에 포함하지 않는다.
누적 창에 들어갔지만 솔버 기록 큐에서 누락된 프레임은 복원할 수 없다. 또한 전체
별 데이터베이스와 외부 warm-pixel map은 자동 복사하지 않는다. 정확한 재생 시험 전
사용한 데이터베이스·보정 파일을 별도로 보관하고, 누적 초기화 이후 연속 구간을 확보한다.

저장은 별도 스레드에서 한다. solver 큐는 2개, integrator 큐는 32개로 제한한다.
저장이 밀리면 새 기록을 버리고 누락 수를 늘린다. 원본 복사와 JSON 변환 비용,
CPU·메모리·SD 경합은 0이 아니므로 telemetry/RAW 기준 구간 비교가 필요하다.
RAW와 처리 후 이미지는 서로 대체하지 않는다. 전처리 영상은 이번 기능에서 별도
저장하지 않으며 원본으로 재생한다. 자료는 시험 담당 PC로 폴더째 복사할 수 있다.

```bash
# 예: 상태에 나온 실제 session_id로 대체
.venv/bin/python -m PiFinder.solver_capture report /home/pifinder/PiFinder_data/captures/solver_sessions/SESSION_ID
```

report는 읽기 전용이며 RAW·소스 사본 SHA-256, 불완전 파일, 단계/환경별 건수와 지연 p95를
출력한다. 무결성 오류는 종료 코드 2다. `complete=false`, `state=error`, 큐 누락과
게시 짝 누락도 별도로 확인한다. ZIP/NPZ를 읽을 때는 `np.load(path, allow_pickle=False)`를
사용한다. 자동 보고서는 절대 지향 오차나 오솔브 진실값을 만들어내지 않는다.

<a id="mf_solver_performance_capture_workplan_20260907_ko--5-시간좌표-해석-계약"></a>
### 5. 시간·좌표 해석 계약

- solver의 `input_ready_monotonic_ns`: 대응 입력을 확보한 직후. 노출 자체와
  그 이전의 카메라 처리·IPC 읽기 시간은 포함하지 않는다.
- `queue_put_return_monotonic_ns`: 솔빙 결과 큐 전달 호출 직후.
- integrator의 `published_monotonic_ns`: shared_state.set_solution 반환 직후.
- report의 `input_ready_to_publication_ms`: 같은 session/frame_id/exposure_end이고
  솔버 승인이 있으며 실제 게시된 두 기록만 연결한다. 서로 다른 boot의 monotonic
  시각을 빼거나, 게시 누락에 이전 좌표를 대입하지 않는다.
- 이 지연에는 기록 기능의 일부 부하가 포함된다. `capture_prepare_ms`는 기록
  준비 자체의 복사·직렬화 시간이며 디스크 작업 시간은 아니다.
- `raw_cascade_ms`는 전처리 이전 경로 전체, `raw_extract_ms`는 1차 검출이다.
  `raw_sep_wait_ms`는 SEP 준비·검출 대기 구간이며 백그라운드 SEP의 순수 CPU 시간과
  같지 않다. `stages`에는 실행된 중앙/전체 대체 경로의 경과 시간과 품질 솔브 여부가 있다.
- `preprocess_detect_ms`는 비동기에서는 과거 프레임의 worker 처리 시간이다.
  `preprocess_frame_id`, `generation`, `preprocess_background`를 함께 읽고
  현재 RAW의 처리 시간에 단순 합산하지 않는다. 비활성/워밍업의 0은 빠른 성공이 아니다.
- `candidate`는 연속성 검사 전 후보다. accepted=false이면 게시 좌표가 아니다.
  후보가 빈 경우는 품질 거부 또는 무패턴 등을 포함하며 세부 사유가 모두 분리되지는 않는다.
- frame_id와 exposure_end는 반드시 함께 사용한다. 재시작 뒤 frame_id가 재사용될 수 있다.
  manifest의 소스는 **기록 시작 시 디스크 파일**이므로 변경 뒤 프로세스 재시작 없이
  측정하면 실제 로드 코드와 다를 수 있다.
- 현재 수집 자료로는 API/LX200 송신 지연을 자동 측정하지 않는다. 외부 앱 체감 지연을
  평가할 때는 별도 클라이언트 관측 시각이 필요하다.

<a id="mf_solver_performance_capture_workplan_20260907_ko--6-단계별-실험-및-통과-기준"></a>
### 6. 단계별 실험 및 통과 기준

한 번에 하나의 변경만 적용한다. 각 단계는 기준→변경→기준 복귀 순서로 반복하고
광해 적음/강함/국소 광원/구름/이동 후 정착을 각각 수집한다. 정지 비교 중 수동 노출과
Auto Star 자료를 섞지 않는다. Auto Star 비교는 별도 그룹으로 분리한다.

| 단계 태그 | 구현·시험할 항목 | 필수 검증 |
| --- | --- | --- |
| baseline | 수정 전 telemetry와 RAW 각각 기록 | 수집 부하, 저장 누락, 승인률, 프레임 대응 확인 |
| candidate_gate | 최종 최소 매칭 수를 만족할 수 없는 탐색 제외 | 제외된 후보가 현행 경로에서 승인될 수 없음을 확인. RAW 512 정책 보존 |
| frame_reuse | 메인에서 확보한 대응 RAW를 SEP에 전달 | 카메라가 다음 프레임을 게시하는 경쟁 조건, frame_id/배열 동일성, 복구율 |
| lazy_sep | 필요 시점에 RAW SEP 검출 | LiveCam overlay, 후보 통계, backoff 상태 보존. 이미 필요한 전처리 간격 불변 |
| path_budget | 경로별 승인률/시간에 따른 탐색 순서·예산 | 광해 변화 시 재시도 회복, 어려운 정상 패턴 누락 여부, 실패 시간 감소 |
| mode_policy | 실제 성공 경로·품질·bias 준비를 함께 판단 | 경계선 성공 반복, 3회 성공 후 즉시 실패, RAW/전처리 좌표 차이 |
| async_worker | 후속 검출·좌표 계산까지 분리 | 독립 Tetra3/Cedar 메모리, generation 폐기, 오래된 좌표 역게시 금지, CPU 경합 |
| temporal_state | 작업자/누적 상태 수명·버퍼 최적화 | 이동/광학/정렬 초기화, 실제 누적 시간, centroid 편향, 수치 출력 비교 |
| validation | 선택한 개선 조합을 긴 구간에서 재검증 | p50/p95/최대 무갱신 시간, 정확도, 설정 변화·종료·재시작 |

모든 단계의 공통 통과 조건:

- 같은 RAW에서 기준이 정확하게 승인한 해를 이유 없이 잃지 않을 것.
- 매칭·잔차·연속성 기준을 느슨하게 해서 얻은 속도 향상을 개선으로 세지 않을 것.
- 기준 천체/독립 해로 검증한 RA_target/Dec_target 오차와 p95 산포가 악화되지 않을 것.
  기준 자체를 진실값으로 간주하지 않는다. 시간 추세 제거는 산포용이며 지연 편향을
  숨길 수 있으므로 원시 좌표와 시간 지연도 함께 평가한다.
- 프레임 오결합, 과거 좌표 역게시, NaN, 새로운 오솔브가 없을 것. 관측 표본에서 0회는
  모든 환경에서의 오솔브 확률 0을 증명하지 않는다.
- 실제 승인 좌표의 갱신 간격과 입력 확보→게시 지연이 개선될 것. 성공 프레임의
  평균 T_solve만 짧아진 결과는 불충분하다.
- 저장 누락이 많은 구간, 두 프로세스의 세션이 다른 구간, 불완전 원본은 성능 승인
  자료에서 분리한다. 변경 효과가 측정 흔들림보다 작으면 보류하고 반복한다.

<a id="mf_solver_performance_capture_workplan_20260907_ko--7-실내-재생-자료와-남은-작업"></a>
### 7. 실내 재생 자료와 남은 작업

기존 자료: `PiFinder_data/captures/mf_replay/20260903_light_pollution_ab`,
`20260903_cloud_coordinate_jitter`, `20260904_exposure_saturation_sweep` 및
8월의 달/건물광·구름 자료. RAW의 표시 회전을 되돌리는 규칙은 각 README를 따른다.

`python/scripts/replay_star_preprocess_ab.py`는 과거 비교 도구다. 현재 운영 코드와
노출·게인 fingerprint, 병렬 작업 수, 초기 RAW 경로, 타임아웃, 실제 시각과
적응형 스케줄러 재현이 다르므로 **그대로 실행한 수치를 현행 성능으로 채택하지 않는다.**

이번 NPZ/JSONL 수집과 무결성·지연 보고 기능은 구현했다. 현행 운영 경로를 그대로
구동하는 NPZ 재생 엔진, 실제 도착 시각에 따른 가상 스케줄러, 단계별 최적화,
독립 기준 좌표를 이용한 정확도 자동 판정은 후속 작업이다. 수집 자료는 그 작업에
필요한 원본/입력/메타데이터/설정/결과를 보존한다. 성공한 프레임만 추려 저장하지 않는다.

<a id="mf_solver_performance_capture_workplan_20260907_ko--8-구현-검증-기록"></a>
### 8. 구현 검증 기록

임시 디렉터리와 합성 배열로 OFF 무동작, 요청 검증, RAW 무손실·프레임 대응,
실패 기록, 구간 고정, 저장 샘플링, 시간/건수/용량 제한, 큐 누락, 디스크 오류,
두 프로세스 결과 연결, 원본·소스 체크섬 훼손, 웹 제어·인증, 기존 탐색 순서 보존을 검사했다.

2026-09-07 검증 결과:

- 기존 작업 변경을 제외한 HEAD 기반 검증 사본에 이번 코드만 적용:
  `pytest -m 'unit or smoke' -q` **1607 passed**, 857 deselected.
- 실제 작업 디렉터리의 수집·솔버·좌표 반영·API 관련 검사: **115 passed**.
- 검증 사본 전체 Ruff 검사 및 342개 Python 파일 포맷 검사 통과.
- 변경한 4개 모듈 mypy 검사 통과. 프로젝트 설정상 untyped 함수 본문 검사는 제한적이다.
- 기존 Tetra3의 `np.math` 사용 중단 예정 경고 8건. 테스트 실패는 없다.

브라우저 화면 조작, 실제 카메라 수집·마운트 이동·자동 노출 변경은 실행하지 않았다.
웹 경로·제어·인증은 Flask 테스트 클라이언트로 확인했다.
현장에서 첫 수집 후 프로세스별 complete와 무결성 보고를 반드시 확인한다.

<a id="mf_solver_performance_capture_workplan_20260907_ko--9-현장-시험-결과-작성-양식"></a>
### 9. 현장 시험 결과 작성 양식

각 단계마다 아래 표를 복사해 채운다. 자동 보고에 없는 항목은 별도 분석으로
계산하고, 측정하지 않은 정확도는 통과로 표시하지 않는다.

| 항목 | 기준 구간 | 변경 구간 |
| --- | --- | --- |
| session_id / 단계 / scene | | |
| 소스 버전·변경 내용 | | |
| 기준 천체·시각·고도·주변 광원·구름 | | |
| 고정/이동 및 구간 메모 | | |
| RAW/telemetry, 저장·누락 건수, 무결성 | | |
| 시도 수 / 승인 수 / 실제 게시 짝 수 | | |
| 입력 확보→게시 p50 / p95 | | |
| 승인 좌표 갱신 간격 p50 / p95 / 최대 공백 | | |
| 독립 기준 대비 지향 오차 / 정지 산포 | | |
| 모드 전환 전후 좌표 차이 / 첫 승인까지 시간 | | |
| 오솔브·오결합·역게시 및 특이사항 | | |

판정: 통과 / 보류 / 실패. 근거, 반복 횟수, 다음 시험 조건을 남긴다.
