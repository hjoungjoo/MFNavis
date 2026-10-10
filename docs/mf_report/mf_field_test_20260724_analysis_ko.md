# 2026-07-24 현장 테스트 장애 분석 및 수정 계획

> 상태: **분석 완료 — 수정 진행 중** (체크리스트로 항목별 진행)
> 관련 문서: [mf_indi_goto_guide_plan_ko.md](../history/development/mount.md#mf_indi_goto_guide_plan_ko),
> [mf_goto_mount_source_structure_ko.md](../history/development/mount.md#mf_goto_mount_source_structure_ko),
> [mf_mountcontrol_indi_flow_ko.md](../history/development/mount.md#mf_mountcontrol_indi_flow_ko),
> [mf_time_sync_ko.md](../history/development/connectivity.md#mf_time_sync_ko),
> [mf_goto_tracking_recovery_analysis_ko.md](mf_goto_tracking_recovery_analysis_ko.md)
>
> 작성: 2026-07-25. 근거 로그: `~/PiFinder_data/pifinder.log`(WARNING 레벨),
> systemd journal(현재 부팅), `/dev/shm/pifinder/*.json`(실내 검증 세션 스냅샷),
> `/etc/fake-hwclock.data`.

## 1. 증상 요약 (사용자 보고)

관측: 2026-07-24 21:00~23:00 KST, OnStepX Alt/Az + INDI. 23:10 귀가 후 전원
재부팅, 이후 로그/상태는 실내 검증 테스트의 것이다.

1. LCD GUI로 얼라인을 진행한 뒤 SkySafari와 카탈로그로 GoTo했을 때, 갑자기
   얼라인이 이상한 곳으로 정렬된 것처럼 보였다. 정상 사용 불가.
2. 이를 피하려고 INDI 마운트 전용으로 동작시키려 했으나 PiFinder 모드처럼
   동작하는 것으로 보였고, 실내에서 같은 설정으로 재현하면 손으로 망원경을
   움직일 때 IMU에 따라 재정렬이 진행됐다.

## 2. 운용 원칙 (용어 확정)

이 문서와 이후 작업에서 용어를 다음처럼 구분한다.

- **정렬** = INDI mount sync (`ON_COORD_SET.SYNC`). 마운트의 좌표 프레임을
  맞추는 동작.
- **얼라인** = PiFinder 내부 정렬 (plate-solve 기반 target_pixel/aligned 축).
  LCD 화면에서 사용자가 수행하는 동작.

사용자 원칙 — **GoTo Type(`indi_goto_method`) 모드별 정책으로 확정
(2026-07-25 개정)**:

| 입력/동작 | GoTo Type = **INDI Mount** | GoTo Type = **PiFinder** |
| --- | --- | --- |
| SkySafari 정렬(`:CM#`) | **INDI 마운트 정렬만** 전송. PiFinder 얼라인은 건드리지 않음 | **PiFinder 얼라인(LCD Start > Align과 동일) + INDI 마운트 정렬 둘 다** 수행 |
| 자동 정렬(PiFinder가 스스로 보내는 sync) | **금지** — 자동 sync를 전송하지 않음 | **허용** — 융합좌표를 소스(솔브/IMU) 구분 없이 전송하는 의도된 폴백 (솔빙이 느리거나 실패해도, GPS가 불안해도 호핑 가능한 이동 유지) |
| 추적 가이드(펄스 미세 보정 + 외란 복구) | **전체 미동작** — 펄스 보정도, 외란 복구도 하지 않음(상태 표시만) | 허용 (Tracking Guide 설정에 따라 펄스 보정 + disturbance recovery) |
| PiFinder 얼라인 변경 경로 | LCD 메뉴(Start > Align)로만 | LCD 메뉴 + SkySafari 정렬 |

단서 조항: SkySafari발 PiFinder 얼라인 자동 수행에 구현상 문제가 발견되면
그 부분은 제외하고, PiFinder 얼라인은 **수동 LCD 메뉴로만** 수행한다
(INDI 정렬 전송은 유지).

초판 원칙 1~3("정렬은 INDI로만 / 얼라인은 LCD로만 / IMU 자동 정렬 금지")은
위 모드별 정책으로 대체되었다 — INDI Mount 모드에서는 초판 원칙이 그대로
성립하고, PiFinder 모드에서는 얼라인 동시 수행과 IMU 폴백 자동 정렬이
의도된 동작이다.

## 3. 타임라인 재구성

`pifinder.log`에 2026-07-24 부팅이 4회 기록되어 있다 (`Flask app created`
마커, 파일 라인 순서 기준):

| 부팅 | 로그 타임스탬프 | 실제 시각(추정) | 의미 |
| --- | --- | --- | --- |
| 1 | 18:19 → 19:21 | 18:19–19:21 (정상) | 집, 준비. 정상 종료 → fake-hwclock에 ~19:21 저장 |
| 2 | **19:21:41.074** → 20:06+ | **~20:50 → ~21:40** | 현장 전반부. **시계 ~1.5h 지연** |
| 3 | **19:21:41.194** → 19:52+ | **~21:50 → ~22:45** | 현장 후반부(세션 중 재부팅). **시계 ~2.5h 지연** |
| 4 | 23:11 → | 23:10 → (정상) | 집, 실내 검증. NTP로 부팅 직후 시계 복구 |

근거:

- 이 장비에는 RTC가 없다 (`timedatectl`: `RTC time: n/a`). 부팅 시
  fake-hwclock이 마지막 저장값을 복원한다.
- 부팅 2·3·4가 전부 **동일하게 19:21:4x 타임스탬프로 시작**한다. 부팅 1이
  19:21에 정상 종료하며 남긴 저장값을 셋 다 복원한 것이다. (fake-hwclock은
  정상 종료 시와 매시 :17 cron에서 저장한다. 부팅 2·3은 전원 차단으로 끝났고
  타임스탬프 기준 20:17을 넘기지 못해 저장이 갱신되지 않았다.)
- 현장에는 인터넷이 없어(PiFinder AP) chronyd의 NTP 소스가 없었고, GPS
  refclock(`gps1`)은 시간을 공급하지 못했다(7.A에서 원인 검증). PiFinder의
  시간 동기 관찰 프레임워크는 기본값 Off라
  (`gps_time_status.json`: `time_sync_enabled=false`) 경고조차 표시되지
  않았다. 결과적으로 시계를 고칠 수단이 없었다.
- 현재 부팅(4)의 journal에서 시계가 `19:21:23`(systemd 서비스 시작 스탬프) →
  `23:10:58`(NTP 동기)로 점프한 기록이 확인된다. `uptime -s` = 23:10:25.
- 관측 창(21:00~23:00) 스탬프의 로그 라인이 하나도 없다는 사실 자체가 현장
  세션이 틀린 시계로 돌았음을 뒷받침한다.

## 4. 문제 1 분석: 현장 세션이 1.5~2.5시간 틀린 시계로 운용됨

시계 오차 1.5~2.5시간 = **항성시(LST) 오차 22°~38°**.

- **plate solve와 LCD 얼라인은 시계와 무관**하다 (카메라 영상 vs 항성 DB).
  그래서 얼라인 직후에는 정상으로 보였다.
- 그러나 마운트 연결 시 PiFinder는 `sync_location_time()`으로 **틀린 시간을
  OnStepX에 전송**했다 (부팅 직후 1차 시도는 `Could not set INDI TIME_UTC`로
  실패 로그가 남았고, 자동 재연결 경로에서 이후 전송된다). Alt/Az 마운트는
  RA/Dec↔물리 방향 변환에 이 시간(LST)을 쓴다.
- 정렬(sync)한 별 근처에서는 sync가 오차를 국소적으로 흡수하므로 맞아 보이지만,
  **하늘에서 멀리 떨어진 대상을 GoTo하면 수십 도 단위로 어긋난다.**
  "갑자기 얼라인이 이상한 곳으로 정렬된 것처럼 보임"과 일치한다.
- 세션 중 재부팅(부팅 3)은 시계를 다시 19:21로 복원시켜 오차를 오히려 키웠다.

증폭 요인 (당시 활성):

- **GoTo Type = PiFinder 모드**가 켜져 있었다. 이 모드는 GoTo마다
  "현재 융합좌표로 mount 정렬 → GoTo"를 반복하는데, 틀린 프레임 위에서
  수렴하지 못했다. 로그(부팅 2, 스탬프 19:25:10 = 실제 ~20:55):
  `PiFinder GoTo stopped: GoTo error did not improve`.
- 스탬프 19:48:19(실제 ~21:18): `Could not read INDI GoTo busy state after
  180.6s; assuming complete` — GoTo 완료 판정 불가 180초. 이 "무동작 GoTo →
  180초 → error did not improve" 패턴은
  [mf_goto_tracking_recovery_analysis_ko.md](mf_goto_tracking_recovery_analysis_ko.md)의
  **OnStepX 웨지(wedge) 증상**과 같은 서명이므로, 당시 컨트롤러 웨지가
  겹쳤을 가능성도 있다 (현장 증거만으로는 확정 불가).
- 추적 가이드 외란 복구(아래 5장)도 틀린 프레임 위에서 sync를 반복했다.

## 5. 문제 2 분석: 추적 가이드 외란 복구가 IMU 좌표로 마운트를 정렬함

실내 검증(부팅 4, 시계 정상)으로 확정:

- `indi_goto_method = indi_mount`는 **정상 적용**되어 있었다
  (`indi_goto_guide_status.json`: `goto_method=indi_mount`,
  `phase=indi_mount_goto`). "PiFinder 모드처럼 보인" 것은 GoTo Type이 아니라
  **추적 가이드(Tracking Guide)의 외란 복구**다. 이 기능은 GoTo Type과
  무관하게 동작한다.
- 복구 시퀀스: 물리적 이동 감지(disturbed) → 정착(settle) → 오차 >
  `indi_tracking_guide_goto_threshold_deg`(0.5°)이면 **"현재 융합좌표로 mount
  정렬(sync) → 원래 타깃으로 GoTo"** —
  `indi_goto_guide_service.py::_begin_tracking_recovery_goto()`.
  이때 좌표 소스(solve/IMU)를 **구분하지 않는다.**
- 실내(솔브 없음)에서는 융합좌표가 IMU 기반이므로, 손으로 움직이면 IMU 좌표로
  마운트가 재정렬된다. 증거 (00:12:39 KST, 실내):

```text
mount_control_status.json
  coordinate_sync = {ra: 250.643, dec: -30.732, source: sync_mount,
                     synced_at: 00:12:39}
pointing_coordinate_status.json (동시점)
  solved.reason = "no solved pointing"
  selected_source = "mount_imu_delta"
  imu_mount_separation_degrees = 165.8
indi_goto_guide_status.json
  tracking_guide_recovery_count = 1
```

- 추가로 `tracking_guide_state = enabled`로 실내에서도 pulse guide 보정이
  계속 전송되고 있었다 (오차 4.1′ 기준).

**결론 재정리 (2026-07-25, 2장 모드별 정책 반영)**: 융합좌표(무솔브 시
IMU) 기반 자동 정렬 자체는 결함이 아니라 의도된 폴백이다 — 단, 그 폴백은
**GoTo Type = PiFinder 모드의 동작**이어야 한다. 당시 설정은
`indi_goto_method = indi_mount`였으므로, 이 sync는 모드별 정책 기준으로
**나가지 말았어야 할 자동 정렬**이다. 문제 2에서 남는 개선점:
(1) **B4 모드 게이트** — INDI Mount 모드에서는 자동 sync 전송 금지(핵심
수정), (2) 어떤 좌표로 정렬됐는지가 상태에 남지 않아 진단이 어려웠다 →
B5(소스 기록)/B8(표시)로 보강, (3) 보조 수단으로 Tracking Guide / GoTo
Recovery Off 설정 문서화(7.B 서두).

## 6. 모드별 정책(2장) 대비 현재 코드 상태

| # | 경로 | 위치 | 현재 상태 | 정책 대비 판정 |
| --- | --- | --- | --- | --- |
| 1 | SkySafari `:CM#` → PiFinder 얼라인(target_pixel) 교체 | `pos_server.py::_align_pifinder_if_enabled()` | `skysafari_pifinder_align` 기본 **true**, 모드 무관 동작 | PiFinder 모드: **의도된 동작**(얼라인+정렬 동시). INDI Mount 모드: 정책 위반 → **B6 모드 게이트** |
| 2 | SkySafari `:CM#` → 무솔브 IMU 얼라인 보정 | `pos_server.py::_set_imu_alignment_from_target_if_no_solve()` | 옵션 없이 항상 켜짐 (마운트 전송·target_pixel 변경 없음, IMU 폴백 좌표만 보정) | **의도된 동작으로 확정**(B7 종결) — 무솔브 호핑 정확도의 핵심 메커니즘, 두 모드 모두 정합 |
| 3 | 추적 가이드 외란 복구 → 융합좌표(IMU 포함)로 mount 정렬 | `indi_goto_guide_service.py::_begin_tracking_recovery_goto()` | 좌표 소스/GoTo Type 구분 없음 | PiFinder 모드: **의도된 폴백**(소스 무관). INDI Mount 모드: 자동 정렬 금지 위반 → **B4 모드 게이트** |
| 4 | PiFinder GoTo 모드 반복 정렬 / final sync, pointing reset 시 IMU 정렬 | `indi_goto_guide_service.py::_send_sync_and_goto()`, `_send_final_sync_once()`, `pos_server.py::_align_mount_to_imu_on_reset()` | 무솔브 시 IMU 좌표로 sync | PiFinder 모드 전용 경로 — **의도된 폴백**, 위반 아님 |

## 7. 수정 계획 체크리스트

우선순위 순. 항목별로 완료 시 체크하고 검증 내용을 기록한다.

### A. 시간 신뢰성 (문제 1 근본 대책)

설계 원칙 (2026-07-25 사용자 결정,
[mf_time_sync_ko.md](../history/development/connectivity.md#mf_time_sync_ko) 기반 재정리):

- **현장(무네트워크): GPS가 위치와 시간을 모두 동기**해야 한다.
- **네트워크가 있으면: GPS와 NTP 중 더 정확한 쪽을 자동 선택**한다.
- system clock의 유일한 관리자는 **chronyd**로 유지한다. chronyd는 이미
  NTP pool + gpsd SHM refclock(`refclock SHM 0 refid gps1`) 구성이라 소스
  자동 선택(더 정확한 쪽)이 기본 동작이다. 기존 시간 동기 기능 중 이
  구조와 겹치거나 clock을 이중으로 쓰는 부가 기능은 제거하고 핵심만 남긴다.

현재 확인된 상태 (2026-07-25 실사):

```text
chronyd active — pool 2.debian.pool.ntp.org + refclock SHM 0 (gps1)
gpsd active — /dev/ttyAMA3 @115200 단독 소유 (포트 경합 없음)
PiFinder GPS = gps_ubx.py, gpsd TCP 2947 경유 UBX 수신 (경합 없음)
chrony gps1 = Reach 0 (실내라 fix 없음 — 현장 fix 시 공급 여부 미검증)
chrony makestep = "1 3" (부팅 초기 3회 업데이트에만 스텝 허용)
time_sync_enabled = false (기본값 Off → 관찰/경고 전부 꺼짐)
```

- [x] **A1. GPS→gpsd→SHM→chrony 시간 공급 체인 실증** — 2026-07-25 새벽
  실외 검증으로 **원인 확정: gpsd 서비스 옵션에 `-n`이 없었다.**
  - 증상: GPS 2D fix + TPV 시간 공급 상태에서도 NTP0 SHM 세그먼트가
    전혀 쓰이지 않음(count=0, valid=0) → chrony `gps1` Reach 0.
  - 진단: gpsd를 포그라운드 `-N -n -D4`로 실행하자 즉시 `ntpshm_put`이
    매초 기록됨. 서비스 모드(클라이언트 워치 기반 활성화, PiFinder는
    `raw:2` 워치)에서는 SHM 공급이 되지 않았다. gpsd 문서대로 시각 동기
    용도에는 `-n`(클라이언트 없이 즉시 폴링)이 필수.
  - 조치: `/etc/default/gpsd`의 `GPSD_OPTIONS`를 `"-n -s 115200"`으로 변경
    (백업: `gpsd.bak-20260725`) 후 `gps1` Reach 3→7, offset +51ms 수신 확인.
  - 검증: 홈 네트워크(NTP 활성)에서 chrony가 NTP를 선택하고 gps1은 후보로
    유지 — "더 정확한 쪽 자동 선택" 동작 확인. GPS 직렬 시간 오차
    ~50ms = LST 오차 ~0.8″로 GoTo에 충분.
  - 남은 확인: 현장(무NTP) 조건에서 gps1 단독 선택 + 큰 오프셋 스텝
    리허설(다음 실외 관측 시). GPS fix 자체가 느린 문제는
    [mf_gps_aiding_plan_ko.md](../history/development/connectivity.md#mf_gps_aiding_plan_ko)와 연계.
- [x] **A2. chrony 큰 오프셋 스텝 보장** — `makestep 1 3` → `makestep 1 -1`
  적용(2026-07-25, 백업: `chrony.conf.bak-20260725`). RTC 없는 보드에서 부팅
  한참 뒤 GPS fix가 와도 즉시 스텝한다. 관측 중 큰 스텝은 A5 재동기 훅이
  뒤처리한다.
- [x] **A2b. 시스템 시간 설정의 설치 스크립트 반영** — 2026-07-25 구현.
  `install_chrony_time_sync.sh`에 `configure` 명령을 추가해 다음을 멱등
  관리한다(`install`도 수행): `/etc/default/gpsd`의 `-n` 옵션,
  `/etc/chrony/chrony.conf`의 `refclock SHM 0 poll 3 refid gps1`과
  `makestep 1 -1`. 기 적용된 기기에서 no-op 확인.
  - [ ] 후속: gps1 상수 오프셋(+50ms대 관찰) `offset` 보정값 검토
  - [ ] 후속(선택): 커널 PPS 활용 — `/dev/pps0` 살아 있음(KPPS 감지 확인).
    3D fix 후 PPS 유효성 확인되면 `refclock PPS /dev/pps0 lock gps1`로
    μs급 정밀도 가능. 필수는 아님(50ms로 충분).
- [x] **A3. 시간 동기 기능 축소(핵심만)** — 2026-07-25 구현. chronyd 단일
  클럭 관리자 원칙에 맞춰 정리:
  - 제거: PiFinder 자체 SNTP client, Software PPS,
    `Clock Manager = PiFinder`(직접 system clock 쓰기), `Best/GPS/NTP` 소스
    모드와 관련 config 키/LCD 메뉴/상태 필드 (`gps_time_sync.py` 1703→약
    1000줄).
  - 유지: chrony 상태 관찰/표시, GPS 후보 관찰(진단), RTC 헬퍼 요청 경로
    (RTC 도입 A6까지 기본 Off; helper의 system clock 경로 정리는 A6에서).
  - 기본값 변경: `time_sync_enabled` 기본 **On** (관찰 전용).
  - `selected`는 chronyd 동기 상태일 때의 Chrony 후보만 사용 — A4 게이트의
    판단 근거가 된다.
  - 문서 갱신: [mf_time_sync_ko.md](../history/development/connectivity.md#mf_time_sync_ko) /
    [mf_time_sync_en.md](../history/development/connectivity.md#mf_time_sync_ko) 재작성. 단위 테스트 26개 통과.
- [x] **A4. "시계 미신뢰" 게이트** — 2026-07-25 구현.
  - 신뢰 판정: chronyd가 이번 부팅에서 한 번이라도 동기(`stable`)되면 tmpfs
    마커 `/dev/shm/pifinder/clock_trusted.json`(boot_id 포함)을 기록.
    재부팅(fake-hwclock 복원)이면 마커가 사라지거나 boot_id 불일치로 무효.
    시간 동기 모니터가 마커를 쓰고, `gps_time_sync.clock_is_trusted()`는
    마커 우선 + 필요 시 `chronyc tracking` 직접 확인(성공 시 마커 기록)으로
    모니터 비활성 상태에서도 동작한다.
  - **마운트 location/time sync 게이트**: `sync_location_time()` 진입부에서
    미신뢰면 전송을 보류하고 상태 메시지("Mount time sync deferred...")를
    남긴다. Multi Align 시작은 위치/시간 sync 실패로 세션이 명확한 메시지와
    함께 실패한다.
    - **2026-08-08 완화**: 보류가 현장 세션을 통째로 묶는 문제(시간 없는
      마운트는 슬루 전면 거부 → 솔빙 가능한 하늘로 이동 불가)가 실측되어,
      일반 sync는 잠정(provisional) 시간 전송으로 변경. Multi Align만 하드
      게이트 유지. 현행 규약은 [mf_time_sync_ko.md](../history/development/connectivity.md#mf_time_sync_ko).
  - **LCD 경고**: 타이틀바 우측에 미신뢰 동안 "T"가 점멸(INDI 문제 표시와
    같은 규칙). **웹 경고**: `/indi` 페이지 상단 빨간 배너
    (`/indi/current_values`의 `clock_trusted`).
  - **수동 시간 우선(2026-07-25 추가)**: 사용자가 LCD Set Time/Date로 시간을
    수동 설정하면(`shared_state.datetime_is_manual()`) 신뢰 게이트보다
    우선한다 — 마운트로 전송되는 값이 바로 그 수동 시간
    (`shared_state.datetime()`)이기 때문. 수동 설정 즉시 마운트 site/time을
    재전송하고 추적 타깃을 해제한다. 수동 플래그는 공유 상태에만 살아 있어
    서비스 재시작/재부팅 시 초기화된다(요구사항: 재부팅 시 초기화).
- [x] **A5. 시간 점프 시 재동기** — 2026-07-25 구현. location 변경 자동
  재동기와 같은 좌표 서비스 루프(`pos_server`)에서 wall clock과 monotonic의
  괴리(임계 2초)로 점프를 감지 → `sync_location_time` 재전송 +
  `clear_tracking_target`. 점프 없이 미신뢰→신뢰로 전이한 경우(오프셋이
  스텝 임계 미만)에도 마운트가 이번 세션에 신뢰 시간을 받은 적이 없으므로
  site/time을 재전송한다.
- [x] **A6. RTC 미도입 결정** — 2026-07-25 사용자 결정: 현장은 GPS, 그 외에는
  NTP가 항상 있는 시스템이므로 RTC 하드웨어를 추가하지 않고 **시스템 기본
  (fake-hwclock + chronyd + A2 makestep + A4 게이트)에 따른다.**
  `rtc_sync` 옵션과 root helper는 기본 Off인 레거시로 남기며, 향후 정리
  대상이다.

### B. 자동 정렬(sync) 정책 (문제 2 + 원칙 반영)

여기서 "자동 정렬 전송"이란: PiFinder가 사용자 명령 없이 스스로
**PiFinder → INDI 마운트 방향**으로 sync 명령을 보내는 것을 말한다.

```text
indi_goto_guide_service ──{"type":"sync", ra, dec}──> mountcontrol_queue
  ──> MountControlIndi.sync_mount() ──> INDI ON_COORD_SET.SYNC ──> 마운트
```

이 sync는 마운트에게 "네가 지금 물리적으로 가리키는 방향의 좌표는
(ra, dec)다"라고 알려 **마운트의 내부 좌표 프레임을 통째로 다시 맞추는**
동작이다. 이때 보내는 (ra, dec)는 `PointingCoordinateService`의 현재
융합좌표이며, 솔브가 없으면 IMU 추측항법/mount+IMU 델타 좌표로도 전송된다.

**정책 확정 (2026-07-25, 사용자 결정, 2장 모드별 정책 표 참조)**:

1. **자동 정렬의 허용 여부는 GoTo Type이 결정한다.**
   - `indi_goto_method = pifinder`: 자동 정렬 허용. 좌표 소스(솔브/IMU)를
     구분하지 않고 전송하는 것은 의도된 설계다 — 실외에서도 plate solve가
     느리거나 실패하는 경우가 있고, GPS가 불안한 환경에서도 오차는 있더라도
     호핑이 가능한 수준의 이동을 유지해야 하기 때문. 솔브 소스 게이트로
     차단하지 않는다.
   - `indi_goto_method = indi_mount`: **자동 정렬 금지.** PiFinder가 스스로
     sync를 전송하면 안 된다(→ B4). 사용자 명령 sync는 모드와 무관하게 허용.
2. 실내 검증에서 관찰된 "손으로 움직이면 IMU 좌표로 재정렬"(문제 2의 증상)은
   PiFinder 폴백이 설계대로 동작한 것이나, 당시 `indi_goto_method =
   indi_mount`였으므로 **B4 기준으로는 나가지 말았어야 할 sync**다.
3. 보조 제어 수단: `Tracking Guide = Off` / `GoTo Recovery = Off`(C9)로
   추적 가이드 개입 자체를 끌 수 있다.

- [x] **B4. 추적 가이드/자동 정렬 모드 게이트** — 2026-07-25 구현.
  `_tick_tracking_guide_states()` 진입부 게이트: `indi_goto_method`가
  `pifinder`가 아니면 추적 가이드 상태를 `off`로 두고(사유
  "tracking guide inactive: <mode> mode") 아무 마운트 명령도 내지 않는다.
  켜져 있던 guide correction은 1회 off로 정리하고, armed 타깃은 제거해
  이후 모드 전환 시 잔재가 되살아나지 않게 했다. indi_mount GoTo는 더
  이상 tracking target을 arm하지 않는다. 단위 테스트 2종 추가, 전체
  smoke+unit 738 통과. 원 계획:
  `indi_goto_method = indi_mount`이면 **추적 가이드 전체가 동작하지
  않는다**:
  - 자동 sync 전송 금지.
  - 외란 복구(sync + 원래 타깃 복귀 GoTo) 미실행.
  - **펄스 미세 보정(guide correction)도 미동작** — INDI Mount 모드에서
    마운트를 움직이는 것은 사용자가 시킨 GoTo/수동이동/명시적 sync 전달과
    마운트 자체 추적뿐이다.
  - 상태에는 미동작 사유를 표시(`tracking guide inactive: indi_mount
    mode` 등, B8 연계). Tracking Guide 설정(On/Off)은 PiFinder 모드에서만
    효력을 가진다.
  - PiFinder GoTo 반복 sync/final sync는 PiFinder 모드에서만 실행되는
    경로라 자연히 해당 없음.
  - 대상: `indi_goto_guide_service.py` — `_tick_tracking_guide()` 진입부에
    모드 게이트(펄스/복구/타깃 arm 전부 포함) + 기타 자동 sync 경로 전수
    확인. mountcontrol의 `toggle_guide_correction`이 켜져 있으면 끄기.
- [x] **B5. 자동 정렬 가시성(소스 기록)** — 2026-07-25 구현. 모든 sync
  명령(자동 3경로 + SkySafari `:CM#` + LCD Guide 수동 + Multi Align +
  pointing reset)이 `origin`(누가 요청)과 `pointing_source`(좌표 출처:
  solved/mount_imu_delta/imu_fallback/타깃), 유효 솔브 나이를 실어 보내고,
  mountcontrol이 `mount_control_status.json`의 `coordinate_sync`에 기록한다.
  원 계획: 소스 게이트는 도입하지 않는 대신,
  어떤 좌표로 정렬됐는지를 추적할 수 있게 한다: 자동 sync 전송 시 사용한
  좌표 소스(`solved` / `mount_imu_delta` / `imu_fallback`)와 솔브 나이를
  함께 기록한다.
  - 기록 위치: `mount_control_status.json`의 `coordinate_sync`(현재
    ra/dec/source만 있음)에 `pointing_source`, `solve_age_seconds` 추가.
  - 자동 sync 3경로 (`indi_goto_guide_service.py`)가 명령에 소스 정보를
    실어 보낸다: `_begin_tracking_recovery_goto()`(외란 복구),
    `_send_sync_and_goto()`(PiFinder GoTo 반복), `_send_final_sync_once()`
    (최종 sync).
  - 사용자 명령 sync(LCD Guide 수동 sync, Multi Align confirm, SkySafari
    `:CM#`, 웹 sync 버튼)도 같은 필드로 소스를 남기면 현장 사후 분석이
    쉬워진다.
- [x] **B6. SkySafari 정렬(`:CM#`)의 모드별 라우팅** — 2026-07-25 구현.
  `pos_server.handle_sync_command()`가 `indi_goto_method`를 확인해
  PiFinder 모드에서만 PiFinder 얼라인을 수행하고, INDI Mount 모드에서는
  INDI 정렬 전송만 한다. `skysafari_pifinder_align` 키는 **PiFinder 모드
  내 추가 토글로 유지**(기본 true; 단서 조항 발동 시 이 키로 자동 얼라인만
  끌 수 있음, UI 노출은 하지 않음). 단위 테스트 2종 추가, 전체 smoke+unit
  740 통과. 원 계획:
  - `indi_goto_method = pifinder`: **PiFinder 얼라인 + INDI 마운트 정렬 둘
    다** 수행 (현재의 `skysafari_pifinder_align` 동작을 PiFinder 모드
    전용으로 유지).
  - `indi_goto_method = indi_mount`: **INDI 마운트 정렬만** 전송. PiFinder
    얼라인(target_pixel)은 건드리지 않는다.
  - 단서 조항: SkySafari발 얼라인 자동 수행에 구현상 문제가 확인되면
    PiFinder 모드에서도 얼라인 부분은 제외하고(INDI 정렬 전송은 유지)
    수동 LCD 메뉴(Start > Align)로만 수행한다.
  - `skysafari_pifinder_align` config 키는 모드 게이트로 흡수한다(키 제거
    또는 PiFinder 모드 내 추가 토글로 유지 — 구현 시 결정).
  - 대상: `pos_server.py::handle_sync_command()` (+ 필요시
    `default_config.json`, `server.py`, `views/indi_mount.html`)
- [x] **B7. 무솔브 IMU 얼라인 — 재분석 후 유지 확정(2026-07-25 사용자
  승인, 종결)**. 동작은 항상 켜짐 그대로 유지하고(코드 변경 없음), 잔재
  config 키 `skysafari_imu_align_without_solve`를 사용자 config에서
  제거했다(default_config/코드에는 원래 없음).

  동작 상세: 솔브가 없을 때 SkySafari `:CM#`(Align)을 받으면, "타깃의
  Alt/Az vs 현재 IMU가 가리키는 Alt/Az"의 차이를 **PiFinder 내부의 IMU
  보정 오프셋**(alt/az offset)으로 저장한다. 이 오프셋은:
  - **마운트로는 아무것도 전송하지 않는다** (INDI sync 아님).
  - **PiFinder 얼라인(target_pixel)도 건드리지 않는다** (LCD Start > Align과
    무관).
  - 적용 대상은 **IMU 폴백 좌표뿐**: SkySafari에 응답하는 현재 위치 표시,
    그리고 `PointingCoordinateService`의 IMU 폴백 샘플에 반영된다.
  - 이후 plate solve가 성공하면 오프셋은 자동 초기화되고 솔브 기반
    좌표로 전환된다.

  모드 정책과의 정합성 검토:
  - **PiFinder 모드**: 이 보정 덕분에 무솔브 상태에서도 IMU 폴백 좌표가
    사용자 Align 기준으로 정확해진다 — "솔빙이 느리거나 실패해도, GPS가
    불안해도 호핑 가능한 이동"이라는 폴백 철학을 실현하는 **핵심
    메커니즘**이다. 자동 정렬 폴백이 쓰는 융합좌표의 품질도 이것으로
    좋아진다. → 정합, 항상 켜져 있는 것이 맞다.
  - **INDI Mount 모드**: B4로 자동 sync가 없으므로 이 보정은 SkySafari
    위치 표시 개선에만 쓰인다. 마운트로 전송되는 것이 없어 "정렬은
    INDI로만" 정책과 충돌하지 않는다. → 정합, 위반 아님.

  **권고**: 초판의 "기본 off 옵션화" 계획은 구 원칙("얼라인은 LCD로만")
  기준의 과잉 조치였다. 개정된 모드 정책 하에서는 **항상 켜짐 유지**가
  맞다. 남는 정리 거리는 config의 잔재 키
  `skysafari_imu_align_without_solve`(코드가 읽지 않음) 제거/문서화뿐.
  사용자 확인 후 종결한다.
- [x] **B8. 자동 정렬 소스 상태 표시** — 2026-07-25 구현. 웹 `/indi`
  페이지의 마운트 상태 카드에 "Last Sync" 행 추가: `origin /
  pointing_source (solve Ns), Ns ago` 형식으로 ~1초 폴링 갱신. 현장에서
  "방금 정렬이 누구 요청이었고 솔브 기반이었는지 IMU 폴백이었는지"를 바로
  확인할 수 있다.

### C. 다음 관측 전 임시 설정 — 전체 대체됨 (2026-07-25 종결)

A·B절 구현으로 임시 설정이 모두 불필요해졌다. 적용하지 않는다.

- [x] ~~**C9.** GoTo Recovery / Tracking Guide Off~~ → **B4가 대체**:
  GoTo Type = INDI Mount이면 추적 가이드 전체(펄스/복구/자동 정렬)가
  코드에서 비활성. 별도 설정 불필요.
- [x] ~~**C10.** `"skysafari_pifinder_align": false` 추가~~ → **B6가 대체**:
  `:CM#`이 모드별로 라우팅되어 INDI Mount 모드에서는 얼라인을 건드리지
  않는다. 지금 이 키를 false로 하면 오히려 PiFinder 모드의 의도된
  동작(얼라인+정렬 동시)이 꺼진다 — 기본 true 유지. 단서 조항 발동 시에만
  false로 쓰는 비상 스위치로 남긴다.
- [x] ~~**C11.** 핫스팟 NTP 1회 동기~~ → **A절이 대체**: gpsd `-n` +
  chrony `makestep 1 -1` + 신뢰 게이트(A4) + 점프 재동기(A5)로 현장에서
  GPS만으로 시계가 복구되고, 미신뢰 동안 마운트 time sync가 보류된다.

### D. 진단성

- [x] **D12. 로그 tmpfs 이전 + 기본 INFO 로깅** — 2026-07-25 구현
  (사용자 결정: 로그성 데이터는 tmpfs 우선, 필요할 때만 SD 저장).
  - 로그 파일이 `~/PiFinder_data/pifinder.log`(SD)에서
    `/dev/shm/pifinder/logs/pifinder.log`(tmpfs)로 이동. 회전 20MB × 3으로
    축소(구 50MB × 5). 웹 Logs 페이지의 스트림/다운로드도 새 경로 사용.
  - SD 마모가 사라졌으므로 기본 프로파일에서 INDI 로거
    (MountControl/IndiGotoGuideService/PointingCoordinateService) +
    PosServer + GPS.TimeSync + main을 **INFO**로 상향 — 현장 타임라인
    재구성이 기본으로 가능해짐.
  - **주의: tmpfs 로그는 재부팅/전원 차단 시 사라진다.** 보존이 필요한
    세션은 웹 Logs 페이지의 **"SD로 저장"** 버튼으로
    `~/PiFinder_data/logs/saved_<시각>/`에 스냅숏을 남긴다(부록 참조).
- [ ] **D13. Moon 추적 주파수 잔존 점검** — 실내 검증 중
  `track_freq_label=Moon`(58.59Hz)이 고정 좌표 타깃 추적 중에도 남아 있었다.
  recent 목록의 달 대상(고정 좌표) GoTo로 lunar feed-forward가 걸린 뒤 정적
  대상 GoTo에서 sidereal 복원이 동작했는지 추적 주파수 정책
  (`track_freq_policy.py`) 경로 점검. recent/PUSH 행성 좌표가 저장 시점에
  고정되는 문제도 함께 확인.

## 8. 부록: 진단 명령

```bash
# 부팅/시계
uptime -s
timedatectl
cat /etc/fake-hwclock.data          # 마지막 저장 (UTC)
sudo journalctl --list-boots

# 상태 파일 (tmpfs, 재부팅 시 소실 — 문제 발생 시 즉시 복사해 둘 것)
python3 -m json.tool /dev/shm/pifinder/mount_control_status.json
python3 -m json.tool /dev/shm/pifinder/indi_goto_guide_status.json
python3 -m json.tool /dev/shm/pifinder/pointing_coordinate_status.json
python3 -m json.tool /dev/shm/pifinder/gps_time_status.json

# 정렬(sync)이 언제/어떤 좌표로 갔는지
#   mount_control_status.json .coordinate_sync {ra, dec, source, synced_at}
# 추적 가이드 복구 횟수
#   indi_goto_guide_status.json .tracking_guide_recovery_count
```

현장에서 문제 재발 시: **전원을 끄기 전에** ① 웹 Logs 페이지의 "SD로 저장"
버튼으로 tmpfs 로그를 `~/PiFinder_data/logs/saved_<시각>/`에 남기고
(D12 이후 로그는 tmpfs라 재부팅 시 사라진다), ② 위 상태 파일 4개를
`~/PiFinder_data/`로 복사해 두면 재부팅 후에도 분석할 수 있다.
