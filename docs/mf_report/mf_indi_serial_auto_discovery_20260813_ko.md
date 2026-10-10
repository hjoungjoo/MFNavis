# INDI OnStep 시리얼 포트·통신속도 자동찾기 구현 리포트

작성일: 2026-08-13  
상태: **구현 완료 / 자동·실장 검증 통과**

관련 설계:

- [`mf_indi_serial_auto_discovery_design_ko.md`](../history/development/connectivity.md#mf_indi_serial_auto_discovery_design_ko)
- [`mf_indi_serial_reconnect_design_ko.md`](../history/development/connectivity.md#mf_indi_serial_reconnect_design_ko)
- [`mf_indi_serial_port_dedup_20260813_ko.md`](mf_indi_serial_port_dedup_20260813_ko.md)

## ESP32 DTR/RTS 안전 보완

소스 감사에서 INDI Linux serial layer는 hardware/software flow control과 `HUPCL`을
끄고 DTR/RTS를 직접 조작하지 않는 것을 확인했다. 반면 자동탐색과 직접 위치·시간
동기화에서 사용한 pySerial 3.5는 `rtscts=False`, `dsrdtr=False`여도 open할 때
DTR/RTS 기본 active 상태를 각각 적용했다.

이를 다음과 같이 보완했다.

- PiFinder 전용 pySerial subclass에서 `_update_dtr_state()`와
  `_update_rts_state()`를 no-op 처리
- termios의 `CRTSCTS`, `IXON`, `IXOFF`, `IXANY`, `HUPCL` 해제
- `CLOCAL` 설정
- 자동 port/baud probe와 위치·시간 직접 serial 명령 경로에 동일 클래스 적용
- fake serial을 이용해 DTR/RTS hook 미호출과 termios flag를 자동 검증

이 보완은 PiFinder가 modem-control ioctl을 발생시키는 문제를 제거한다. USB-UART
kernel driver가 최초 `open()` 순간 자체적으로 만드는 신호까지 userspace에서
보장하지는 않으므로 ESP32 실장 최종 시험에서는 MCU reset reason 또는 계측기
파형 확인을 별도 항목으로 유지한다.

보완 적용 후 집중 회귀 시험 결과:

```text
test_sys_utils.py + test_sys_utils_fake.py + test_config.py
+ test_mountcontrol_indi.py + test_web_theme_static.py: 201 passed
ruff format/check: passed
compileall: passed
git diff --check: passed
pifinder.service restart: active
indiwebmanager.service: active
local Web HTTP 응답: 정상
```

실장 포트의 Auto probe는 INDI 연결을 일시 중단하는 동작이므로 이번 적용 과정에서
임의 실행하지 않았다. 다음 사용자 실행 시 새 DTR/RTS 억제 경로가 사용된다.

## 구현 범위

Web UI의 다음 선택을 1회 자동탐색 명령으로 구현했다.

```text
Connection Type: USB Serial
USB Serial Port: Auto (Find connected OnStep)
Communication Speed: Auto (Detect with port)
Apply to INDI
```

`__auto__` sentinel은 Web 요청과 mount-control queue 사이에서만 사용한다. INDI
XML이나 PiFinder config에는 저장하지 않으며, 성공하면 검증된 concrete port와
실제 baud만 저장한다.

## 탐색 순서

```text
사용자 Auto + Apply
→ local INDI / OnStep driver / mount idle precheck
→ by-id·by-path·ttyUSB·ttyACM 후보 realpath 중복 제거
→ configured GPS와 같은 실제 tty 제외
→ 기존 transport와 park/tracking/slew-rate snapshot
→ INDI device disconnect
→ 마지막 검증 baud → 9600 → 나머지 baud pass
→ 각 조합에 :GVP#와 :GVN# 읽기 명령만 1회 전송
→ verified OnStep이 정확히 1개인지 확인
→ concrete stable port/baud 적용, 아직 CONFIG_SAVE 금지
→ fresh position + OnStep status 및 mount 상태 보존 확인
→ CONFIG_SAVE
→ PiFinder mirror atomic write
```

verified가 0개이거나 2개 이상, timeout, 적용 실패, fresh telemetry 실패,
mount 상태 불일치 또는 CONFIG_SAVE 실패이면 기존 live transport를 되돌리고 기존
PiFinder mirror를 유지한다.

## 안전 경계

- 페이지 load, USB Serial 선택, boot, USB 재삽입만으로 자동찾기를 실행하지 않는다.
- `:GVP#`와 `:GVN#` 외 이동·Sync·park·tracking·설정 명령을 probe에 사용하지 않는다.
- 수동 이동, GoTo/refine, guide correction, backlash 시험, multi-point alignment,
  parking 또는 USB 재삽입 복구 중에는 시작 전에 거부한다.
- remote INDI host에서는 PiFinder local `/dev`를 검색하지 않는다.
- product 응답만 맞고 version이 유효하지 않은 후보는 probable로만 분류해 적용하지
  않는다.
- 여러 OnStep이 응답하면 임의로 첫 장치를 선택하지 않는다.
- 상세 상태와 제한된 probe 결과는 기존 tmpfs
  `/dev/shm/pifinder/mount_control_status.json`을 사용하며 SD 진단 로그를 만들지
  않는다.

## 변경 파일

| 파일 | 내용 |
|---|---|
| `python/PiFinder/sys_utils.py` | 후보/GPS 제외, baud 순서, bounded serial probe, baud-pass discovery, 저장 지연 옵션 |
| `python/PiFinder/mountcontrol_indi.py` | precheck, snapshot, scan, 적용, fresh telemetry, 저장과 rollback transaction |
| `python/PiFinder/server.py` | Auto sentinel 검증과 비동기 queue 요청 |
| `python/views/indi_mount.html` | Auto port/baud 선택, 진행 상태 polling과 성공값 표시 |
| `python/PiFinder/sys_utils_fake.py` | off-device 호환 API |
| `python/requirements.txt` | 직접 사용하는 `pyserial==3.5` 명시 |

## 자동 검증

최종 집중 시험:

```text
test_sys_utils.py + test_sys_utils_fake.py + test_config.py
+ test_mountcontrol_indi.py + test_web_theme_static.py
200 passed
ruff format/check: passed
compileall: passed
git diff --check: passed
```

고정한 주요 조건:

- by-id/by-path/tty alias 중 stable by-id 하나만 후보로 유지
- configured GPS realpath 제외
- `On-Step#`과 유효 version 응답만 verified
- product-only 응답은 probable이며 자동 적용 금지
- 마지막 검증 baud를 첫 pass로 사용하고 verified port는 재검사하지 않음
- verified 복수 후보는 ambiguous이며 적용·저장 금지
- unique 후보도 fresh telemetry와 mount 상태 복원 전에는 CONFIG_SAVE 금지
- 수동 이동 중에는 port 열거 전에 탐색 거부
- PyIndi callback이 누락돼도 CONNECT·transport·좌표·OnStep Status live readback을
  모두 확인해야 검증 통과

전체 suite는 `1764 passed, 177 skipped, 11 failed`였다. 11개 실패는 이번 변경
파일과 무관한 기존 test/API 불일치다.

- `test_multiproclogging.py` 4개: 문자열 log path에 `.parent` 접근
- `test_radec_entry.py` 6개: 현재 constructor와 예전 test argument 불일치
- `test_ui_modules.py` 1개: 기존 `DummyGuideScreen` smoke coverage 누락

## 실장 검증

현재 연결된 CH340/OnStepX 장비에서 Web 요청과 동일한 `Auto + Apply`를 실행했다.

```text
candidate_count: 1
verified_count: 1
product: On-Step
firmware version: 10.28v
selected port: /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0
selected baud: 115200
serial_discovery_state: success
connection_health: healthy
CONNECTION.CONNECT: On
park_state: Unparked
slew_rate: 9
mount_motion_active: false
```

탐색 전후 stable by-id, Unparked, slew rate 9, guide correction off와 무이동 상태가
유지됐다. USB monitor도 같은 concrete stable path로 복귀했다.

저장 결과:

```text
INDI live DEVICE_PORT: /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0
INDI live baud: 115200 On
INDI CONFIG_SAVE XML port: 같은 stable by-id
INDI CONFIG_SAVE XML baud: 115200 On
PiFinder mirror port: 같은 stable by-id
PiFinder mirror baud: 115200
__auto__ in XML/config: 없음
```

## 실장 시험 중 발견한 경계 조건

초기 구현은 candidate 적용 뒤 새 PyIndi client를 만들어 position과 OnStep Status
callback generation을 기다렸다. OnStepX driver가 reconnect 직후 일부 동적
property를 정의하기 전에 첫 vector를 보내면서 새 client가 event를 버렸고, 장비와
driver는 정상인데도 fresh telemetry timeout으로 잘못 판정됐다.

수정 후에는 기존에 property를 알고 있던 mount-control INDI client를 유지한다.
callback generation이 확인되면 그것을 사용하고, driver 경계로 callback이 누락되면
동일 새 session에서 다음 조건을 모두 live readback해 검증한다.

```text
CONNECTION.CONNECT = On
live port/baud = 발견한 concrete 값
EQUATORIAL_EOD_COORD RA/DEC = 유효 숫자
OnStep Status :GU# return = 비어 있지 않음
```

실패 주입 과정에서는 persistent 설정이 저장되지 않았고 기존 concrete 설정으로
원복됐다. 최종 보조 검증 적용 후 같은 실장 시험이 `success`로 완료됐다.
