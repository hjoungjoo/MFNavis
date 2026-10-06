# MF PiFinder mountcontrol_indi 동작 순서도

이 문서는 `python/PiFinder/mountcontrol_indi.py`의 현재 구현을 기준으로
INDI 마운트 제어 프로세스의 역할, 명령 처리 순서, 상태 발행 경로를 정리한다.

관련 문서:

- `docs/mf_dev/mf_coordinate_helper_plan_ko.md`: `PointingCoordinateService`와 SkySafari 좌표 응답 흐름
- `docs/mf_dev/mf_multipoint_align_flow_ko.md`: Multi Align의 사용자 흐름
- `docs/mf_dev/mf_backlash_measurement_flow_ko.md`: Backlash 측정 상태 machine과 계산식
- `docs/mf_dev/mf_goto_mount_source_structure_ko.md`: SkySafari GoTo/Push 구조와 소스 위치

## 전체 역할

`MountControlIndi`는 PiFinder 내부 명령을 INDI telescope driver 명령으로 변환하는
마운트 제어 프로세스이다. Web UI, LCD UI, SkySafari POS server 등이 직접 INDI에
접근하지 않고 queue 명령을 넣으면, 이 프로세스가 INDI server/driver와 통신한다.

```mermaid
flowchart LR
    Web[Web UI / Flask] --> Q[mountcontrol_queue]
    LCD[LCD UI] --> Q
    SS[SkySafari POS server] --> Q
    Q --> MC[MountControlIndi.run loop]
    MC --> INDI[INDI server / active telescope driver]
    INDI --> Mount[OnStepX or other INDI mount]
    MC --> Status[mount_control_status.json]
    MC --> Console[console_queue / LCD short messages]
    Status --> Web
    Status --> PCS[PointingCoordinateService]
    PCS --> PStatus[pointing_coordinate_status.json]
    PCS --> SS
```

## 주요 파일과 데이터

소스:

- `python/PiFinder/mountcontrol_indi.py`
- `python/PiFinder/pos_server.py`
- `python/PiFinder/server.py`
- `python/PiFinder/pointing_coordinate_service.py`
- `python/PiFinder/indi_multipoint_align.py`
- `python/PiFinder/indi_backlash_calibration.py`

상태 파일:

```text
/home/pifinder/PiFinder_data/mount_control_status.json
/home/pifinder/PiFinder_data/pointing_coordinate_status.json
```

`mount_control_status.json`은 mount-control의 최신 상태 snapshot이다.
Web UI와 `PointingCoordinateService`가 이 파일을 읽는다.

대표 필드:

```text
state
message
updated
slew_rate
ra
dec
home_state
park_state
driver_mount_status
raw_mount_status
manual_motion_direction
manual_motion_lease_remaining
mount_motion_active
mount_motion_type
mount_readback_priority
goto_motion_active
target_ra
target_dec
target_error_deg
guide_correction_enabled
backlash_ra
backlash_de
backlash_auto
multipoint_align
coordinate_sync
device
connection_health
serial_present
serial_path
serial_path_stable
recovery_reason
recovery_attempt
```

## 시간 상수

중요한 현재 값:

```text
POSITION_STATUS_MIN_INTERVAL = 0.5 sec
STATUS_HEARTBEAT_INTERVAL = 2.0 sec
AUTO_CONNECT_START_DELAY = 5.0 sec
AUTO_CONNECT_RETRY_INTERVAL = 10.0 sec
USB_SERIAL_MONITOR_INTERVAL_SECONDS = 1.0 sec
USB_SERIAL_RETURN_DEBOUNCE_SECONDS = 2.0 sec
USB_SERIAL_DISCONNECT_WAIT_SECONDS = 3.0 sec
USB_SERIAL_FRESH_TELEMETRY_WAIT_SECONDS = 12.0 sec

MANUAL_MOTION_LEASE_SECONDS = 1.2 sec
MANUAL_MOTION_MIN_LEASE_SECONDS = 0.3 sec
MANUAL_MOTION_MAX_LEASE_SECONDS = 5.0 sec
MANUAL_MOTION_MAX_CONTINUOUS_SECONDS = 10.0 sec
MANUAL_MOTION_POLL_SECONDS = 0.1 sec
MANUAL_MOTION_STOP_RETRY_SECONDS = 0.5 sec

SkySafari POS server guide bridge:
_GUIDE_LEASE_SECONDS = 1.2 sec
_GUIDE_KEEPALIVE_SECONDS = 0.4 sec
_GUIDE_RESTART_SECONDS = 8.0 sec
_GUIDE_MAX_HOLD_SECONDS = 60.0 sec

GOTO_COMPLETE_MIN_SECONDS = 1.0 sec
GOTO_COMPLETE_STABLE_SECONDS = 2.5 sec
GOTO_COMPLETE_POSITION_STABLE_DEG = 0.02 deg
GOTO_COMPLETE_TARGET_TOLERANCE_DEG = 0.5 deg
GOTO_COMPLETE_FALLBACK_SECONDS = 180.0 sec
```

## 프로세스 시작과 메인 루프

`run()`은 mount-control 프로세스의 중심 루프이다.

```mermaid
flowchart TD
    A[run 시작] --> B[state=idle 기록]
    B --> C[next_auto_connect_at 설정]
    C --> D[loop]
    D --> U[_check_usb_serial_reinsert]
    U --> E[_check_manual_motion_deadline]
    E --> F[_publish_manual_motion_progress]
    F --> G[_check_goto_motion]
    G --> H[_check_pending_goto_refine]
    H --> I[_check_guide_correction]
    I --> J{queue command 수신?}
    J -->|yes| K[handle_command]
    K --> L{shutdown?}
    L -->|yes| Z[disconnect 후 종료]
    L -->|no| D
    J -->|timeout| M{auto connect 시각?}
    M -->|yes, USB recovery 허용| N[connect announce=false]
    M -->|no| O[_write_status_heartbeat]
    N --> O
    O --> D
```

루프 특징:

- 명령이 없어도 주기적으로 수동 이동 deadline, GoTo 완료, refine, guide correction을 확인한다.
- 수동 이동 중이면 queue timeout이 짧아져 stop/deadman 처리가 빠르게 돈다.
- 서비스 시작 후 5초 뒤 자동 연결을 시도하고, 실패하면 10초 간격으로 재시도한다.
- 연결 후 heartbeat는 명령 처리가 비어 있을 때 nominal 2초 간격으로 상태 파일을
  갱신한다.
- OnStepX USB 설정에서는 configured serial path를 1초마다 확인한다. 분리 및
  재삽입 복구 중에는 일반 auto-connect를 억제한다.

## 상태 기록 흐름

상태 기록은 대부분 `_write_controller_status()`를 통해 이루어진다.

```mermaid
flowchart TD
    A[동작 함수] --> B[_write_controller_status]
    B --> C[_status_fields]
    C --> D[현재 내부 상태 병합]
    D --> E[_home_park_status_fields]
    E --> F[OnStep Status / Park / raw :GU# 조회]
    F --> G[_write_status]
    G --> H[mount_control_status.json atomic write]
```

중요한 점:

- `_status_fields()`는 `current_ra/current_dec`를 항상 `ra/dec`로 넣는다.
- `_mount_common_status_fields()`는 동작별 내부 상태를 공통 telemetry로 정규화한다.
- manual motion, GoTo, guide correction, backlash, multipoint align 상태가 있으면
  같은 payload에 같이 들어간다.
- `PointingCoordinateService`는 이 상태 파일의 `ra/dec`,
  `mount_readback_priority`, `mount_motion_active`, `coordinate_sync`,
  `multipoint_align` 등을 사용해 현재 좌표 후보를 판단한다.
- `goto_motion_active`, `manual_motion_direction`, `goto_refine_pending`,
  `state`는 계속 남아 있지만 좌표 선택의 1차 기준은 공통 telemetry이다.

공통 mount telemetry:

```text
mount_motion_active
  실제 또는 명령상 마운트가 움직이는 중이면 true.

mount_motion_type
  manual / goto / goto_refine_settle / guide_correction /
  align_goto / backlash_auto 등의 진단용 분류.

mount_readback_priority
  좌표 서비스가 IMU delta보다 mount readback을 우선해야 하면 true.
  GoTo settle/refine처럼 실제 motion은 아닐 수 있지만 readback이
  authoritative 해야 하는 구간도 포함한다.
```

## INDI 연결 순서

`connect()`는 명령 실행 전에 자주 호출된다. 이미 정상 연결이면 바로 성공한다.

```mermaid
flowchart TD
    A[connect] --> B{이미 connected?}
    B -->|yes, device connected| OK[return true]
    B -->|yes, stale| C[mark_disconnected]
    B -->|no| D{PyIndi 있음?}
    D -->|no| FAIL[missing_pyindi]
    D -->|yes| E{OnStep direct location/time sync?}
    E -->|yes| F[sync_location_time reconnect_after=false]
    E -->|no| G[기존 client disconnect]
    F --> G
    G --> H[PiFinderIndiClient 생성]
    H --> I[connectServer]
    I -->|fail| FAIL2[server_unavailable]
    I -->|ok| J[_wait_for_device]
    J -->|fail| FAIL3[no_telescope]
    J -->|ok| K[CONNECTION property 대기]
    K --> L{driver device connected?}
    L -->|no| M[CONNECTION.CONNECT set_switch]
    L -->|yes| N{INDI location/time sync?}
    M --> N
    N -->|필요| O[sync_location_time]
    N -->|skip| P[unpark_mount]
    O --> P
    P --> Q[enable_tracking]
    Q --> R[_wait_for_current_position]
    R -->|fail| FAIL4[device_connect_failed]
    R -->|ok| S[connected=true, state=connected]
```

주의:

- OnStepX direct sync 설정이 켜져 있으면 INDI 연결 전에 exclusive LX200
  location/time sync를 수행할 수 있다.
- 연결 성공 후 현재 구현은 `unpark_mount()`와 `enable_tracking()`을 호출한다.
- 연결 마지막에는 `EQUATORIAL_EOD_COORD` readback을 기다려 `current_ra/current_dec`를 채운다.

## INDI client event와 위치 갱신

`PiFinderIndiClient.updateProperty()`가 INDI 2.x의 단일 콜백으로,
`EQUATORIAL_EOD_COORD` number vector가 갱신될 때(드라이버 `POLLING_PERIOD`,
기본 1초 주기) 호출된다. 구버전 PyIndi 호환용 `newNumber()`도 남아 있지만,
현재 설치된 PyIndi(INDI 2.x)에서는 호출되지 않는다 — 과거에는 이 때문에
드라이버의 좌표 push가 전부 유실되어 위치가 5초 heartbeat로만 갱신됐다
(2026-07-17 수정).

```mermaid
flowchart TD
    A[INDI updateProperty EQUATORIAL_EOD_COORD] --> B[RA hours / DEC deg 추출]
    B --> C[set_current_position RA*15, DEC]
    C --> D[current_ra/current_dec 갱신]
    D --> E[_write_position_status]
    E --> F{0.5초 제한 통과?}
    F -->|yes| G[state=connected, ra/dec 기록]
    F -->|no| H[내부 값만 갱신]
```

이 이벤트 기반 갱신은 GoTo/추적을 포함한 일반 readback 변화를 ~1Hz로
공급하며, pointing coordinate service의 마운트 이동 감지가 이 주기에
의존한다. 수동 이동 중에는 INDI driver가 좌표를 즉시 발행하지 않거나
PiFinder 루프가 소비하지 못할 수 있어, 현재 구현은 수동 이동 중 별도
polling 발행도 수행한다.

## OnStepX USB 분리·재삽입 복구

USB transport의 effective 설정이 확정되면 mount-control은 설정된 serial path를
감시한다. `/dev/ttyUSB*` 번호 변경을 피하기 위해 Web에서 저장된
`/dev/serial/by-id/...` 경로를 사용하는 것이 기준이다.

```mermaid
flowchart TD
    A[healthy / configured path present] -->|path absent| B[usb_absent]
    B --> C[park tracking slew-rate track-frequency snapshot]
    C --> D[connected=false / 일반 auto-connect 억제]
    D -->|같은 path 재등장| E[return_debounce 2초]
    E -->|다시 소실| B
    E -->|2초 유지| F[CONNECTION.DISCONNECT 1회]
    F --> G[보존 모드 connect]
    G --> H{새 좌표 + 새 OnStep Status?}
    H -->|아니오| X[recovery_failed / 같은 주기 retry 금지]
    H -->|예| I[park 상태 불변 확인]
    I --> J[필요한 tracking slew frequency만 복원]
    J --> K[healthy / recovery_attempt=1]
```

보존 모드 `connect()`는 location/time sync, unpark, tracking-on을 실행하지 않는다.
cached `CONNECTION=On`이나 기존 좌표 property 존재만으로는 성공하지 않으며,
새 client generation 이후 좌표와 `OnStep Status` callback을 모두 확인한다.
park 상태가 달라졌으면 자동 park/unpark 이동을 하지 않고 실패로 남긴다.
tracking과 slew rate는 snapshot과 현재 상태가 명확하게 다를 때만 원래 값으로
복원한다. 수동 이동·GoTo·guide 명령은 저장하거나 재전송하지 않는다.

오래된 INDI client의 늦은 disconnect callback은 generation이 다르면 무시한다.
USB 분리 뒤 늦게 도착한 좌표 callback도 `connected=false`인 동안 최상위 상태를
`connected`로 덮어쓰지 않는다. 로그와 상태는 기존 tmpfs 경로만 사용하며 USB
복구 전용 SD 로그를 만들지 않는다.

## 명령 분배

`handle_command()`는 queue command의 `type`에 따라 실제 함수로 분기한다.

| command type | 처리 함수 | 의미 |
| --- | --- | --- |
| `shutdown` | return false | mount-control loop 종료 |
| `init` | `connect()` | INDI 연결 |
| `restart_driver` | `restart_driver()` | INDI Web Manager/server/driver 재시작 |
| `sync` | `sync_mount()` | mount 좌표를 지정 RA/Dec로 sync |
| `goto_target` | `goto_target()` | 지정 RA/Dec로 GoTo |
| `toggle_guide_correction` | `toggle_guide_correction()` | solve 기반 1회/반복 보정 토글 |
| `stop_movement` | `stop_mount()` | 이동 정지. `stop_tracking=true`(LCD 0키)이면 대기 보정도 취소하고 Tracking Off를 확인 |
| `manual_movement` | `manual_move()` | 방향키 수동 이동 시작/유지 |
| `manual_movement_keepalive` | `manual_motion_keepalive()` | 같은 방향 lease 연장 |
| `increase_slew_rate` | `change_slew_rate(1)` | slew rate 증가 |
| `reduce_slew_rate` | `change_slew_rate(-1)` | slew rate 감소 |
| `set_slew_rate` | `set_slew_rate()` | slew rate 직접 설정 |
| `refresh_slew_rate` | `refresh_slew_rate()` | driver slew rate 읽기 |
| `refresh_backlash` | `refresh_backlash()` | backlash readback |
| `set_backlash` | `set_backlash()` | backlash 값 저장 |
| `auto_backlash` | `auto_calculate_backlash()` | backlash motion test 시작 |
| `backlash_compass_continue` | `continue_backlash_compass_goto_loop()` | backlash test 다음 단계 |
| `backlash_compass_stop` | `stop_backlash_auto()` | backlash test 중지 |
| `multipoint_align_start` | `start_multipoint_align()` | Multi Align 시작 |
| `multipoint_align_select_star` | `select_multipoint_align_star()` | 별 선택 |
| `multipoint_align_goto_target` | `select_multipoint_align_target()` | SkySafari target으로 align target 설정/GoTo |
| `multipoint_align_confirm` | `confirm_multipoint_align()` | align point 확정 |
| `multipoint_align_clear_target` | `clear_multipoint_align_target()` | 현재 target만 지우고 세션 유지 |
| `multipoint_align_cancel` | `cancel_multipoint_align()` | Multi Align 취소 |
| `sync_location_time` | `sync_location_time()` | 위치/시간 동기화 |
| `park_action` | `park_action()` | park/unpark/home/set-park 동작 |

## 수동 이동 순서

수동 이동은 Web UI, LCD UI, Bluetooth/USB keyboard, SkySafari guide command가
공통으로 사용하는 핵심 경로이다.

SkySafari guide command 예:

```text
:Mn# -> north
:Ms# -> south
:Me# -> east
:Mw# -> west
:Q#  -> stop
```

`pos_server.py`는 guide move를 받으면 mount-control queue에 수동 이동 명령을
넣고, SkySafari가 짧은 TCP command connection을 반복해서 쓰는 경우에도 이동이
끊기지 않도록 내부 keepalive timer를 유지한다.

```text
{"type": "manual_movement", "direction": "...", "lease_seconds": ...}
{"type": "manual_movement_keepalive", "direction": "...", "lease_seconds": ...}
{"type": "stop_movement"}
```

순서:

```mermaid
flowchart TD
    S[SkySafari :Mn/:Ms/:Me/:Mw] --> T[pos_server guide timer 시작]
    T --> A[manual_movement command]
    T --> KA[0.4초마다 manual_movement_keepalive]
    T --> KR[8초마다 manual_movement 재전송]
    S2[SkySafari :Q/:Qn/:Qs/:Qe/:Qw] --> STOPCMD[stop_movement]
    A --> B[manual_move direction]
    B --> C{direction 유효?}
    C -->|no| FAIL[return false]
    C -->|yes| D[INDI motion property 선택]
    D --> E[_apply_indi_properties]
    E -->|fail| FAIL2[state=manual_failed]
    E -->|ok| F[_arm_manual_motion_deadline]
    F --> G[_publish_manual_motion_progress force=true]
    G --> H[state=manual_motion, ra/dec 기록]
    H --> I[run loop]
    I --> J[_publish_manual_motion_progress]
    J --> K[0.5초 간격으로 cached readback 발행]
    I --> L[_check_manual_motion_deadline]
    L --> M{lease 만료?}
    M -->|no| I
    M -->|yes| N[stop_mount]
    N --> O[TELESCOPE_ABORT_MOTION.ABORT]
    KA --> I
    KR --> B
    STOPCMD --> N
```

방향 매핑:

```text
north     -> TELESCOPE_MOTION_NS.MOTION_NORTH
south     -> TELESCOPE_MOTION_NS.MOTION_SOUTH
east      -> TELESCOPE_MOTION_WE.MOTION_WEST
west      -> TELESCOPE_MOTION_WE.MOTION_EAST
northeast -> north + west
northwest -> north + east
southeast -> south + west
southwest -> south + east
```

east/west가 반대로 매핑되는 이유:

- 현재 UI/사용자 기준 방향과 OnStep guide axis 방향을 맞추기 위한 보정이다.
- 이 보정은 테스트로 고정되어 있다.

deadman/lease 동작:

- `manual_move()`가 시작되면 기본 1.2초 lease가 잡힌다.
- 같은 방향 keepalive가 들어오면 mount-control deadline이 연장된다.
- mount-control 단일 `manual_movement`의 최대 연속 시간은 10초이다.
- SkySafari POS server는 누르고 있는 동안 0.4초 간격 keepalive를 보내고,
  8초마다 새 `manual_movement`를 보내 mount-control의 10초 연속 제한을
  넘지 않게 한다.
- SkySafari guide bridge의 전체 안전 제한은 60초이다.
- stop command 또는 lease 만료 시 `TELESCOPE_ABORT_MOTION.ABORT`를 보낸다.
- TCP command connection이 닫힌 것만으로는 stop을 보내지 않는다.
  SkySafari가 짧은 연결로 `:Mn#`과 `:Qn#`을 따로 보낼 수 있기 때문이다.
  실제 정지는 `:Q...#` 명령 또는 60초 안전 제한으로 처리한다.

좌표 발행:

- 수동 이동 시작 직후 `manual_motion` 상태와 현재 `ra/dec`를 강제로 발행한다.
- 이후 run loop에서 0.5초 간격으로 `ra/dec`를 갱신 발행한다.
- 이때 공통 telemetry는 `mount_motion_active=true`,
  `mount_motion_type=manual`, `mount_readback_priority=true`가 된다.
- `PointingCoordinateService`는 세부 동작 이름이 아니라
  `mount_readback_priority=true`를 보고 IMU delta를 보류하고 mount readback을 우선한다.

## GoTo 순서

`goto_target()`은 INDI 표준 `ON_COORD_SET=SLEW`와 `EQUATORIAL_EOD_COORD`를 사용한다.

```mermaid
flowchart TD
    A[goto_target ra dec] --> B[connect]
    B -->|fail| FAIL[return false]
    B -->|ok| C[ON_COORD_SET.SLEW]
    C --> D[EQUATORIAL_EOD_COORD RA=deg/15 DEC=deg]
    D --> E[_goto_target_accepted]
    E -->|fail, retry 가능| C
    E -->|fail, retry 초과| F[state=goto_failed]
    E -->|ok| G[_last_goto_target 저장]
    G --> H[_arm_goto_motion]
    H --> I[state=slewing, target_ra/target_dec 기록]
    I --> J[run loop _check_goto_motion]
```

GoTo target acceptance는 다음 중 하나면 성공으로 본다.

- `TARGET_EOD_COORD` readback이 target과 3 arcmin 이내
- INDI mount busy 상태가 true
- OnStep raw status가 GoTo active로 보임
- 현재 좌표가 target과 3 arcmin 이내
- timeout 전 위 조건 중 하나를 만족

## GoTo 진행/완료 판정

GoTo가 시작되면 `_goto_motion` dict가 만들어진다.

```text
target_ra
target_dec
started_at
complete_ready_since
indi_seen_busy
onstep_seen_goto_active
last_complete_position
target_error_deg
position_change_deg
```

진행 중 루프:

```mermaid
flowchart TD
    A[_check_goto_motion] --> B{_goto_motion 있음?}
    B -->|no| END[return]
    B -->|yes| C{refine 대기 중?}
    C -->|yes| END
    C -->|no| D{manual motion 중?}
    D -->|yes| END
    D -->|no| E{시작 후 1초 지남?}
    E -->|no| END
    E -->|yes| F[_indi_mount_is_busy]
    F --> G[_read_goto_progress_position]
    G --> H[_write_goto_progress_status]
    H --> I[_goto_completion_ready]
    I -->|ready| J[_complete_goto_motion]
    I -->|not ready| K{180초 초과?}
    K -->|yes| L[timeout complete 처리]
    K -->|no| END
```

완료 판정 조건:

1. INDI busy가 true이면 완료 아님.
2. OnStep raw `:GU# return`에 GoTo active가 보이면 완료 아님.
3. OnStep complete가 true라도 busy/active를 한 번도 못 봤고 시작 후 3초 미만이면 관찰 대기.
4. INDI busy가 명확히 false가 아니면 완료 아님.
5. 현재 위치가 target과 0.5도보다 멀면 완료 아님.
6. 현재 위치가 직전 완료 후보 위치에서 0.02도보다 많이 움직였으면 완료 아님.
7. 위 조건을 통과한 상태가 4초 이상 유지되면 완료.

GoTo 진행 상태 발행:

```text
state = slewing
message = GoTo in progress
mount_motion_active = true
mount_motion_type = goto
mount_readback_priority = true
ra
dec
target_ra
target_dec
target_error_deg
indi_busy
goto_wait_seconds
goto_motion_active = true
```

이 값이 SkySafari 좌표 안정성에 중요하다. GoTo 중에는 mount readback을 계속 발행하고,
`PointingCoordinateService`는 `mount_readback_priority=true`를 보고 이를 우선 사용한다.

## GoTo refine와 guide correction

참고(2026-07-19): `indi_goto_refine_once` 옵션이 제거되어 이제
`refine_after_goto=true`를 보내는 호출자가 없다. GoTo 후 정밀 보정은
GoTo/Guide 서비스(`indi_goto_method = pifinder`)가 담당하며, 아래 refine 로직은
mount-control에 남아 있지만 휴면 상태다.

GoTo refine:

```mermaid
flowchart TD
    A[goto_target refine_after_goto=true] --> B[_arm_goto_refine]
    B --> C[state=refine_wait]
    C --> D[8초 대기]
    D --> E[_current_plate_solve]
    E -->|fresh solve 없음| F[계속 대기 또는 timeout]
    E -->|fresh solve 있음| G[solve 좌표와 target 오차 계산]
    G -->|accuracy 이내| H[state=refine_complete]
    G -->|accuracy 초과| I[sync_mount solve 좌표]
    I --> J[goto_target target 다시 전송]
    J --> K[state=refine_sent]
```

Guide correction:

GoTo 완료 허용 오차(`indi_goto_refine_accuracy_arcmin`)는 2026-10-03 요청에 따라
기본값과 현재 저장 설정 모두 **1분각**으로 변경했다. GoTo 정지 후 새 솔빙의
오차가 1분각 이하이면 완료하며, 이를 초과하면 기존 미세 보정·재시도 절차를
따른다. 추적 유지도 같은 `indi_goto_refine_accuracy_arcmin` 값을 사용한다.
후속 요청으로 두 기준을 통합했으며, 설정 화면의 “GoTo 완료·추적 유지 허용 오차”를
변경하면 둘 다 함께 바뀐다. 이전 `indi_tracking_guide_threshold_arcmin` 키는
구버전 프로세스 호환용으로만 같은 값을 저장하며 새 판정에서는 사용하지 않는다.

```mermaid
flowchart TD
    A[toggle_guide_correction on] --> B[target 결정]
    B --> C[interval마다 fresh solve 확인]
    C --> D[target과 solve 오차 계산]
    D -->|accuracy 이내| E[추가 펄스 없이 다음 새 솔빙 대기]
    D -->|accuracy 초과| F[확인된 가이드 속도로 timed pulse]
    F -->|timed pulse 미지원| G[manual_move direction, 짧은 lease]
```

2026-10-03 사용자 요청에 따라 **기존 반복 솔빙·보정에서 학습하던 예측 보정은 제거했다.**
추적 유지 명령은 `predictive_tracking=false`를 전달하며, 오래된 명령의 true도
호환성 인자로만 받고 무시한다. 기존 가이드는 새 솔빙에서 확인한 오차가
허용 범위를 벗어날 때만 위치 펄스를 보낸다. 솔빙 사이의 0.2초 예측 루프,
100ms 예측 펄스, 작은 예측량 누적 및 `GuideDrift` 학습 연결은 사용하지 않는다.
상태 호환 필드 `guide_predictive_tracking`은 false,
`guide_drift_arcsec_per_sec`는 0이다.

새 **부드러운 영상 보정 엔진**의 RAW 기반 위치 보정·드리프트 추정·예측과
검증된 짧은 한도 내 예측 유지는 그대로 유지한다. 이 기능은 별도 설정과
검증된 프로필을 사용하며 기존 보정과 명령 소유권을 공유하지 않는다.

복귀 GoTo가 끝난 뒤에는 최초 정지 확인 시각을 기록하고, 그 시각 이후에 촬영한
최근의 고품질 카메라 solve를 확인해야 추적 보정을 다시 활성화한다.
`observation_after_wall`로 같은 시각을 mount-control에도 전달해 독립적으로 읽은
이전 solve를 소비하지 않게 한다. 새 solve가 없으면 복귀 대기 상태를 유지한다.
2026-10-02 M31 증상 조사에서, 기존 경로가 도착 전 좌표를 재사용해 2500ms
추가 펄스를 보내는 경우를 모의 재현했다. 오래된 오차가 작은 경우의 펄스와
큰 경우의 반복 GoTo를 모두 회귀 테스트로 차단했다. 당시 상세 RAM 로그는
남아 있지 않아 첫 이탈의 실제 원인은 확정하지 못했다.

아래는 제거 전 기존 예측 펄스에 관한 2026-10-02 조사 기록이다.
당시 0.2초는 애플리케이션의 전송 주기이며 물리적인 보정 주기를 보장하지 않았다.
공개 [OnStepX Mount.cpp](https://github.com/hjd1964/OnStepX/blob/main/src/telescope/mount/Mount.cpp)의
Alt/Az 경로는 1초마다 `poll()`에서 가이드 영향을 추적 속도로 변환한다.
[Guide.cpp](https://github.com/hjd1964/OnStepX/blob/main/src/telescope/mount/guide/Guide.cpp)의
펄스 시작·종료는 `update()`를 호출하지만 이 Alt/Az 변환을 다시 계산하지 않는다.
따라서 짧은 펄스가 poll 사이에서 사라지거나, poll에서 반영된 속도가 다음 poll까지
남을 가능성이 있다. 동일한 100ms 요청을 200ms마다 보내는 단순 모델에서도
poll과의 시차에 따라 효과가 달라졌다. 기존 단위 테스트는 명령 길이만큼 정확히
움직이는 모델을 사용하므로 이 펌웨어 응답 차이를 검증하지 못한다.

2026-10-02 실내에서 설치된 OnStepX 10.28x를 직접 시험했다. 추적 중 100ms
북쪽 펄스의 Dec 좌표 변화는 거의 0 또는 약 9각초였고, 100ms 펄스 10개를
목표 200ms 간격으로 보낸 세 시험은 각각 약 9·18·0각초였다. 실제 명령 평균
간격은 약 200~204ms였다. 2500ms 펄스도 약 3초간 속도에 반영됐다.
이 결과는 짧은 펄스의 효과가 시작 시점에 따라 달라진다는 문제를 장비에서도
확인한 것이다. 예측기의 명령 기반 이동량 추정이 실제 응답과 일치하지 않는다.
이는 모터 카운터와 펌웨어 좌표의 측정이며, 독립 엔코더나 별 영상 검증은 아니다.
시험 고도는 펌웨어 좌표 기준 약 -0.52도로 M15/M31 관측 조건을 재현하지 않았다.
M15의 최초 증상은 예측 기능 추가 전에도 있었다는 사용자 설명이 있으므로,
짧은 예측 펄스만으로 당시 첫 이탈의 원인을 확정할 수 없다.

같은 시험에서 INDI가 추적 정지와 오래된 좌표를 보고하면서 실제 펌웨어는
추적 중인 상태도 확인했다. INDI 드라이버 재시작 후 추적 상태 보고가 복구됐고,
INDI 경유 시험에서도 100ms 북쪽 펄스에 약 9각초가 반영되는 경우를 확인했다.
INDI 좌표는 변경 시에만 통지되며 표준 좌표 정밀도가 낮으므로, 세부 시간/이동량
판단에는 위 직접 통신의 고정밀 좌표와 모터 카운터 기록을 사용한다.
관측 당시에도 이 상태였는지는 확인되지 않았다. 현장 관측 DB와 상세 펄스/솔빙
기록은 남아 있지 않았으며, journal의 GoTo 기록만으로 원래 오차를 재생할 수 없다.
시험 원자료와 요약은 데이터 디렉터리의
`telemetry/20261002_indoor_tracking/`에 저장했다.

2026-10-02 야외 재관측에서 솔빙 중단 후 복구 경로가 도착 오차에 관계없이
새 Sync+GoTo를 시작하고, 보정 횟수와 미세 보정 실패 판단을 초기화하는 것을
확인했다. 이제 이 경로도 일반 GoTo 도착과 같은 `_evaluate_goto_arrival()`로
진입한다. 정지 후의 새 solve 오차가 정확도 이내이면 완료하고, 근접 범위이면
미세 보정하며, 범위 밖일 때만 GoTo를 보낸다. 기존 횟수와 미세 보정 실패
판단은 유지하므로 솔빙 복구만으로 재시도 배치의 대기를 우회하지 않는다.
반복 솔빙 중단, 중앙 도착, 근접/원거리 도착, 배치 한계와 실패 판단 유지를
포함한 관련 테스트 357개를 통과했다.

같은 날 23:18경에는 이동 명령 없이 약 12초간 마운트 카운터와 카메라 solve를
동시에 기록했다. 고도 카운터는 약 +11.15각초/초, 13개 카메라 solve에서 추정한
고도 변화는 약 +149.83각초/초였다. 이 구간은 양쪽 모두 상승 방향이며 속도
차이가 크다. 방위각은 각각 약 -7.71, -9.29각초/초였다. 카메라 값은 J2000
좌표를 GMST로 근사 변환한 결과이므로 정밀 축 배율 보정값으로 사용하지 않는다.
미정렬 상태의 마운트 절대 좌표 차이 자체를 오류 근거로 삼지 않으며, 특정 천체나
고도에서 방향이 반전되는지는 아직 확인하지 못했다. 추적/GoTo 마이크로스텝은
설정값으로 64/4이지만 실제 드라이버 레지스터는 읽지 못했으므로 전환 실패도
확정하지 않았다. 실제 과속을 확인한 뒤 자동 보정과 기본 추적을 정지했다.
원자료와 동시 비교 결과는 `telemetry/20261002_225845_M31_user_goto/`의
`simultaneous_native_direction.jsonl`, `simultaneous_direction_analysis.json`,
카메라 기록은 `captures/solver_sessions/a218aae1a067409cb1fc6a97d1ceff52/`에 있다.

## Sync 순서

`sync_mount(ra, dec)`는 INDI 표준 sync 경로를 사용한다.

```mermaid
flowchart TD
    A[sync_mount ra dec] --> B[connect]
    B --> C[ON_COORD_SET.SYNC]
    C --> D[EQUATORIAL_EOD_COORD RA=deg/15 DEC=deg]
    D --> E[state=connected, mount synced]
    E --> F[set_current_position ra dec]
```

Multi Align과 SkySafari align/sync 동작에서 이 경로가 중요하다.

## Location/Time sync

`sync_location_time()`은 설정에 따라 두 경로 중 하나를 사용한다.

```mermaid
flowchart TD
    A[sync_location_time] --> B[_shared_location_time_values]
    B --> C{direct OnStep LX200 sync?}
    C -->|yes| D[_sync_location_time_direct_onstep]
    C -->|no| E[apply_indi_onstep_location_time]
    D --> F[필요 시 INDI reconnect]
    E --> G[write_onstep_location_cache]
```

OnStep direct sync:

- INDI driver와 같은 TCP/serial port를 공유하면 충돌할 수 있으므로 exclusive 방식으로 처리한다.
- INDI를 멈추거나 driver 연결을 정리한 뒤 LX200 command를 직접 보내고 다시 연결한다.

INDI sync:

- PyIndi/INDI property를 사용해 latitude, longitude, elevation, UTC time을 보낸다.

시계 신뢰 게이트(A4): 미신뢰 시계도 전송을 막지 않고 현재 PiFinder 시간을
잠정(provisional)으로 보낸다 — 상세 규약과 근거는
[mf_time_sync_ko.md](mf_time_sync_ko.md)(정규 소유자) 참조. Multi-Point
Align 시작만 하드 게이트를 유지한다(`_sync_multipoint_location_time`).

## Park/Home/Tracking/Slew

Park/Home:

```text
park        -> TELESCOPE_PARK.PARK
unpark      -> TELESCOPE_PARK.UNPARK
set_home    -> TELESCOPE_HOME.SET
return_home -> TELESCOPE_HOME.GO
set_park    -> TELESCOPE_PARK_OPTION.PARK_CURRENT
```

Tracking:

- `_read_tracking_enabled()`는 driver property와 OnStep Status text를 함께 확인한다.
- `set_tracking(enabled)`는 tracking switch를 적용하고 confirm한다.

Slew rate:

- `set_slew_rate(rate)`는 `TELESCOPE_SLEW_RATE.<0..9>`를 적용한다.
- `refresh_slew_rate()`는 현재 driver switch 상태를 읽어 `self.slew_rate`를 갱신한다.

Guide rate:

- `set_guide_rate(rate)`는 driver의 guide rate number vector를 적용한다.
- OnStepX 드라이버는 이 쓰기를 펌웨어 공유 레이트 선택자 `:R<n>#`로 보내
  수동 이동 속도까지 오염시킨다 — 가이드 사이클마다 펄스 창 종료 후 사용자
  slew rate를 재적용하고, 사용자 `manual_move` 직전에도 오염 시 즉시
  재적용한다(상세: [mf_indi_goto_guide_plan_ko.md](mf_indi_goto_guide_plan_ko.md)
  복귀 속도 전환 절).
- 현재 backlash 테스트는 pulse guide 방식이 아니라 GoTo loop 방식으로 정리되어 있다.

## Backlash 관련 흐름 요약

Backlash의 수동 저장, 자동 측정 상태 machine, GoTo 측정 loop, solved 좌표 기록,
필터링, 추천값 계산은 `python/PiFinder/indi_backlash_calibration.py`의
`BacklashCalibrationMixin`에서 관리한다. `MountControlIndi`는 이 mixin을
상속하고, INDI 연결/GoTo/Sync/Tracking/status 발행 같은 공통 마운트 동작을
제공한다.

자동 Backlash 계산 좌표는 `PointingCoordinateService.solved`에서 가져오며,
plate solve가 유효한 상태에서만 동작한다. `PointingCoordinateService.current`
는 fallback이 섞일 수 있으므로 계산에는 사용하지 않는다.

Backlash UI 명령은 다음으로 들어온다.

```text
refresh_backlash
set_backlash
auto_backlash
backlash_compass_continue
backlash_compass_stop
```

`set_backlash()`:

```mermaid
flowchart TD
    A[set_backlash ra de] --> B[value 0..3600 validate]
    B --> C[_apply_backlash_values]
    C --> D[_apply_indi_backlash]
    D --> E[state=connected, backlash_ra/backlash_de 갱신]
```

Auto backlash:

- 현재 주 모드는 `compass_goto_loop`이다.
- `PointingCoordinateService.solved`가 유효한지 확인한다.
- 안전 위치/마운트 모델/AltAz 또는 RA/Dec frame을 고려한다.
- 이동 기록은 상세 CSV/records 형태로 분석한다.
- 계산 결과를 UI에 표시하지만, 최종 적용은 사용자가 입력/저장하는 방식이다.

자세한 절차는 `docs/mf_dev/mf_backlash_measurement_flow_ko.md`와 실제 UI 상태를
함께 봐야 한다.

## Multi-Point Align 흐름 요약

명령:

```text
multipoint_align_start
multipoint_align_select_star
multipoint_align_goto_target
multipoint_align_confirm
multipoint_align_clear_target
multipoint_align_cancel
```

시작 순서:

```mermaid
flowchart TD
    A[start_multipoint_align] --> B[controller.start]
    B --> C[sync location/time]
    C --> D[stale OnStep native alignment reset]
    D --> E[PiFinder pointing 읽기]
    E --> F[sync_mount PiFinder coordinate]
    F --> G[verify mount sync]
    G --> H[native alignment start는 defer]
    H --> I{mode auto?}
    I -->|yes| J[auto star 선택]
    I -->|no| K[manual star 대기]
    J --> L[_align_goto_current_star]
```

중요 규칙:

- Multi Align 시작 시 mount 좌표를 PiFinder 좌표에 먼저 sync한다.
- PiFinder 좌표는 solve/estimate가 있으면 그것을 우선하고, 없으면 IMU fallback을 사용한다.
- OnStep native alignment start는 현재 구현에서 즉시 시작하지 않고 defer한다.
  이유는 OnStep native align start가 home frame을 reset할 수 있어 star-selection/GoTo
  이전 PiFinder sync를 깨뜨릴 수 있기 때문이다.
- 별을 선택하면 target sent 여부를 기록한다.
- confirm은 가장 최근 GoTo/선택된 target 좌표를 기준으로 처리한다.
- native alignment session이 시작된 경우 `NewAlignStar.1`을 보내고,
  그렇지 않으면 `sync_mount()`로 현재 별 좌표에 sync한다.

자세한 순서도는 `docs/mf_dev/mf_multipoint_align_flow_ko.md`를 기준으로 본다.

## SkySafari와의 관계

SkySafari는 PiFinder에 좌표를 push 받지 않는다. LX200 명령으로 계속 요청한다.

```text
:GR# -> current RA 요청
:GD# -> current Dec 요청
```

PiFinder 쪽 흐름:

```mermaid
flowchart LR
    MC[MountControlIndi] --> MCS[mount_control_status.json]
    MCS --> PCS[PointingCoordinateService background loop]
    PCS --> Current[latest CoordinateState.current]
    SS[SkySafari :GR#/:GD#] --> POS[pos_server]
    POS --> Current
    POS --> Reply[LX200 RA/Dec response]
```

따라서 mount-control이 GoTo/수동 이동 중 `ra/dec`를 계속 발행해야 SkySafari 위치가
움직이는 중에도 자연스럽게 변한다.

## 디버깅 포인트

서비스 상태:

```bash
systemctl status pifinder.service --no-pager -l
```

mount-control 상태:

```bash
jq . /home/pifinder/PiFinder_data/mount_control_status.json
```

coordinate service 상태:

```bash
jq . /home/pifinder/PiFinder_data/pointing_coordinate_status.json
```

수동 이동 중 확인할 값:

```text
mount_control_status.json:
  state == "manual_motion"
  mount_motion_active == true
  mount_motion_type == "manual"
  mount_readback_priority == true
  manual_motion_direction != null  # 호환/진단용
  ra / dec가 0.5초 간격으로 변함

pointing_coordinate_status.json:
  current.source가 mount 또는 mount_delta 계열로 유지
  health warning에 mount motion/settle active가 보일 수 있음
```

GoTo 중 확인할 값:

```text
mount_control_status.json:
  state == "slewing"
  mount_motion_active == true
  mount_motion_type == "goto"
  mount_readback_priority == true
  goto_motion_active == true  # 호환/진단용
  target_ra / target_dec
  target_error_deg
  ra / dec가 이동 중 변함

pointing_coordinate_status.json:
  GoTo 중 IMU delta보다 mount readback 우선
```

문제가 생겼을 때 우선순위:

1. `mount_control_status.json`의 `ra/dec`가 실제로 갱신되는지 본다.
2. 갱신된다면 `pointing_coordinate_status.json`에서 어떤 source가 선택되는지 본다.
3. 둘 다 정상인데 SkySafari만 다르면 POS server의 `:GR#/:GD#` 응답 경로를 본다.
4. `mount_control_status.json`이 멈춰 있으면 INDI driver readback 또는 mount-control loop를 본다.

## 현재 수동 이동 좌표 갱신의 핵심

현재 수동 이동 좌표 갱신은 다음 세 함수가 담당한다.

```text
_read_manual_motion_progress_position()
_write_manual_motion_progress_status()
_publish_manual_motion_progress()
```

호출 위치:

```text
manual_move()
  -> 시작 직후 force publish

run()
  -> 매 loop 시작부
  -> queue timeout 후 empty branch
```

이 구조의 목적:

- SkySafari가 좌표를 요청할 때 최신 수동 이동 좌표를 받을 수 있게 한다.
- GoTo와 동일하게 움직이는 동안 mount readback을 우선하게 한다.
- IMU 흔들림이 수동 이동 중 좌표 오차로 섞이지 않게 한다.
