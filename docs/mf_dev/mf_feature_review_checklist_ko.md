# MF_PiFinder 기능 검토 및 테스트 체크리스트

플랫폼 항목은 2026-09-27 Trixie/Python 3.13 기준으로 갱신했다.
나머지 upstream 비교는 당시 검토 기준을 보존한다. 현재 설치·실테스트 범위는
[Trixie 안내](mf_trixie_install_ko.md)를 참고하며, 아래 미체크 항목은
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

## 테스트 우선순위

| 우선순위 | 의미 |
| --- | --- |
| P0 | 장치 부팅/설치/기본 관측 기능에 직접 영향. 반드시 테스트 |
| P1 | 주요 기능. 실제 장비나 네트워크 환경에서 테스트 권장 |
| P2 | 보조 기능 또는 문서/개발 편의. 회귀 확인 위주 |

## 1. Platform / Trixie / Raspberry Pi 4, 5, CM5 호환성

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

## 2. Camera Focus 화면 / Gain (2026-08-05 갱신 — upstream #531 4모드 화면 기준)

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

## 3. Korean UI Localization

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

## 4. Bluetooth / USB HID Keyboard

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

## 5. Web UI Red Night Theme / PWA

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

## 6. Wi-Fi AP / STA / AP+STA

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

## 7. Locations Catalog

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

## 8. Integrated Time Sync / chronyd

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

## 9. INDI Mount / OnStepX

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

## 10. LCD INDI UI

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

## 11. SkySafari / LX200 / Mount Mode Integration

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

## 12. IMU Compass / Calibration

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

## 13. Observing List CSV Import

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

## 14. OBJ_TYPES Single Source

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

## 15. Documentation / Test / CI / Assets

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

## 16. Upstream Rev-4 Hardware Patch: 미적용/부분 적용 항목

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

## 17. cedar+SEP 하이브리드 솔빙 / cedar 풀프레임 1차 경로

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

## 18. 자동 노출 — 검출 별 수 컨트롤러

우선순위: P1

주요 변경:

- Camera Exp 메뉴 "Star"(`camera_exp=auto_star`)로 선택하는 별 수 서보,
  솔브 성공 홀드(ADR m0022), 앵커 클램프. ADR m0020/m0021/m0022.

주요 파일: `python/PiFinder/auto_exposure_starcount.py`, `auto_exposure.py`,
`camera_interface.py`

검토 포인트 / 테스트 항목:

- [ ] Star 모드 선택/해제와 기존 자동 노출 모드 무회귀
- [ ] `test_auto_exposure_starcount.py`

## 19. SQM 라디오미터 스택 + 모노 색보정 가드

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

## 20. LiveCam RAW 프리뷰 / 라이브 스택 / 웹 카메라 컨트롤

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

## 21. 웹 카탈로그 / 통합검색 / 관측 목록

우선순위: P1

주요 변경: 기기 웹 카탈로그 페이지(라우트·필터·push·지정번호 정렬),
WDS lazy load 설계(미구현), Stellarium/CSV import(upstream 반영분)

주요 파일: `python/PiFinder/web_catalogs.py`, `python/views/catalogs*.html`

검토 포인트 / 테스트 항목:

- [ ] 통합검색 결과 정렬(지정번호 우선)과 push-to 동작
- [ ] `test_web_catalogs.py` (있는 경우) / 웹 UI 수동 확인

## 22. 조이스틱/게임패드 입력

우선순위: P2

주요 변경: evdev 직접 읽기(`joystick_input.py`), Settings > Advanced >
Joystick 바인딩 UI, 마운트 조그 연동. `python3-evdev`는 setup 스크립트가 설치.

검토 포인트 / 테스트 항목:

- [ ] 버튼 캡처/바인딩/Clear All, `test_joystick_input.py`

## 23. 소프트웨어 업데이트 채널 — 포크 릴리즈 / m-버전

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

## 24. 디스플레이 — SSD1333 자동감지 + 4축 밝기

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

## 25. 설치 스크립트 / 마이그레이션

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

## 최소 회귀 테스트 명령

전체 스위트가 1분 안에 끝나므로(2026-08-05 기준 1,114건/약 55초, Pi4 venv)
개별 파일 나열 대신 전체를 돌린다:

```bash
cd python/ && source .venv/bin/activate
python -m pytest -m "smoke or unit" -q
nox -s lint && nox -s format
```

주의: venv 미활성 시 시스템 파이썬에 selenium이 없어 `tests/website`
수집 오류로 중단된다 — venv부터 확인할 것.

## 실제 장비 통합 테스트 순서

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

## 결과 기록 양식

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
