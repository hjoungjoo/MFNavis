# SkySafari GoTo 무동작 장애 분석 및 복구 검증 (2026-07-18)

> 상태: **실측 검증 완료 — 복구 성공** (15:45 KST, GoTo 0.91′ 오차로 목표 도달)
> 관련 문서: [mf_mountcontrol_indi_flow_ko.md](../history/development/mount.md#mf_mountcontrol_indi_flow_ko),
> [mf_indi_goto_guide_plan_ko.md](../history/development/mount.md#mf_indi_goto_guide_plan_ko),
> [mf_goto_mount_source_structure_ko.md](../history/development/mount.md#mf_goto_mount_source_structure_ko)
>
> **개정 이력**: 초판(14:55)은 "재연결 시 `enable_tracking()` 레이스로 추적 OFF 방치"를
> 원인으로 지목했다. 이후 실측 테스트(15:09~15:45)에서 이 가설이 **불완전**함이 확인됐다
> — 추적을 켜는 어떤 경로도 듣지 않는 **OnStepX 컨트롤러 웨지(wedge) 상태**가 진짜
> 원인이었고, 컨트롤러 재부팅 + 재초기화로만 복구됐다. 5장·6장은 실측 기준으로 전면
> 개정되었다.

## 1. 증상 요약

- SkySafari GoTo가 세션 초반에는 정상 동작하다가, 특정 시점 이후 **GoTo만 동작하지
  않음**.
- **수동 조작(N/S/E/W 이동)은 정상** — 사용자 실기 확인. 연결·모터·INDI 경로 정상.
- GoTo를 보내면 마운트가 전혀 움직이지 않고, 180초 뒤 PiFinder가
  `assuming complete` 처리 후 `GoTo error did not improve`로 중단.

## 2. 시스템 구성 (장애 당시)

| 구성 요소 | 값 |
|---|---|
| 마운트 컨트롤러 | **OnStepX 10.28q** (커스텀 빌드, SWS "mfoozoo Website Plugin"), AltAz |
| 연결 | 네트워크 `10.10.10.12` (PiFinder AP `uap0` 대역, WiFi -28dBm) |
| 컨트롤러 포트 | 80(SWS 웹), **9996~9999(명령 채널)** — 9999는 INDI 드라이버 점유, **9998은 진단용으로 자유 사용 가능** |
| INDI | `indiserver -p 7624` + `indi_lx200_OnStepX` v1.27-mf1 (LX200_OnStep 상속 커스텀), Web Manager 프로파일 `OnstepX` |
| PiFinder 설정 | `onstep_connection_type=network`, `mount_control=true`, `indi_goto_method=pifinder` |
| SkySafari | LX200 프로토콜, 포트 4030 (`pos_server.py`) |
| 위치/시각 | 풍납동 (37.527N, 127.109E), KST(UTC+9) |

## 3. 타임라인 (KST, 2026-07-18)

### 장애 발생

| 시각 | 이벤트 | 근거 |
|---|---|---|
| 03:17 | `pifinder.service` 기동 | systemctl |
| (오전~오후) | SkySafari GoTo 수 회 정상 동작 | 사용자 확인 |
| **14:28:28** | indiserver 재시작 (트리거 미상) | `/tmp/indiserver.log` |
| 14:28:52~14:30:40 | 시간동기 실패, `TELESCOPE_TRACK_MODE/STATE` 속성 타임아웃, setprop 실패 다수 | pifinder.log |
| 14:33:38 | 시간 동기 성공 (마운트 시계 복원) | `indi_getprop` |
| 14:45:41 | SkySafari GoTo 시도 → 마운트 무반응 | 역산 |
| 14:48:45 | `assuming complete` (180s) → `GoTo error did not improve` | pifinder.log |

### 복구 테스트 (실측)

| 시각 | 조치 | 결과 |
|---|---|---|
| 15:09 | 사전 상태: `TRACK_OFF=On`, RA 드리프트 **0.251°/min = 항성시** 실측 | 추적 OFF 확정 |
| 15:11 | `indi_setprop TRACK_SIDEREAL` + `TRACK_ON` | MODE는 적용, **STATE는 무시됨** |
| 15:13 | 드라이버 DISCONNECT→CONNECT (PiFinder 재초기화 재실행) | **추적 여전히 OFF** |
| 15:18 | 드라이버 디버그 로깅 활성화, TRACK_ON 재시도 | `:Te#`→`1` ack 후에도 `:GU#`에 `n` 유지 |
| 15:22 | SkySafari 경로 GoTo 테스트 | `:CM#`→**E9**, `:MS#`→**9** (마운트 거부), 무동작 |
| 15:2x | 직접 채널(9998)에서 `:Te#`/`:Q#`/`:hR#` | `:Te#` ack만, `:hR#`→**0 거부**, `:Q#` 무효 |
| **15:29** | **`:ERESET#` 컨트롤러 재부팅** (~35초) | 부팅 후 At Home(`H`), **날짜 소실(01/02/00)** |
| 15:34 | 드라이버 DISCONNECT→CONNECT → PiFinder 재초기화(시간/위치 동기+unpark+추적) | **날짜 복원 + 추적 ON** (`:GU#`에서 `n` 소실) |
| 15:38 | SkySafari 경로 GoTo 최종 검증 (−2° 소규모) | sync 수락, **물리 슬루**, 반복 보정 후 **오차 0.91′ 도달, final sync 완료** |

## 4. 장애 상태의 관측 증거

### 4.1 웨지 상태 시그니처 (실측)

```
:GU# = "nNpAT180"          ← n(추적 안 돎) + T(추적 플래그?) 동시 존재 = 내부 모순
:Te#  → '1'  (ack)   그러나 :GU#에 'n' 유지   ← ack만 하고 실행 안 함
:CM#  → 'E9' (sync 거부)
:MS#  → '9'  (GoTo 거부, "Unspecified Error")
:hR#  → '0'  (홈 리셋도 거부)
:Q#   → 무효 (상태 변화 없음)
수동 이동(:Mn/:Ms/:Me/:Mw) → 정상 동작
날짜/시각/위치/last_err(None)/TMC(무결함)/WiFi(-28dBm) → 모두 정상
```

핵심 특징: **읽기와 수동 이동은 전부 정상인데 상태 변경 명령(추적/sync/goto/홈)만
전멸.** "부분적으로 잘 동작한다"는 사실이 진단을 오래 헷갈리게 하므로 주의.

### 4.2 물리적 결정 증거: RA readback의 항성시 드리프트

추적이 꺼진 AltAz 마운트는 경통이 멈춰 있으므로 RA readback이 하늘 흐름을 따라
드리프트한다. 실측: 25초 간격 두 샘플에서 **정확히 0.251°/min(항성시)**.
Dec은 불변. → "경통 정지 + 추적 OFF"의 확증이자 최고의 원격 진단 지표.

### 4.3 GoTo 명령 경로 검증 (드라이버 로그 실측)

```
CMD <:Sr17:31:02#> successful.       ← 좌표 전달은 성공
CMD <:Sd+52*16:49#> successful.
CMD <:CM#>  → RES <E9>               ← sync 거부
CMD <:MS#>  → RES <9>                ← GoTo 거부
ERROR: OnStep slew/syncError: Unspecified Error
```

- 좌표(`TARGET_EOD_COORD`)는 정상 수락 → PiFinder `_goto_target_accepted()` 통과
  → **slew 미시작을 아무도 감지 못 함** → 180초 fallback → "위장 실패".
- 목표 고도 +17°(지평선 위), 한계(-10°~80°) 이내 → 한계 거부 아님 (`FastAltAz` 검증).

## 5. 원인 분석 (개정판)

### 확정된 사실

1. **직접 원인: OnStepX 컨트롤러의 웨지 상태.** 4.1의 시그니처처럼 상태 변경
   명령이 전부 거부/무시되며, INDI·드라이버·PiFinder 어느 층의 문제도 아니다
   (직접 채널 9998로 마운트 단독 확인).
2. 이 상태에서 `:Te#`는 **ack('1')만 반환하고 실행하지 않는다** → "ack ≠ 적용".
   적용 여부는 반드시 `:GU#`의 `n` 소실로 검증해야 한다.
3. 소프트웨어 복구 수단(`indi_setprop`, 드라이버 재연결, `:Q#`, `:hR#`)은 웨지를
   풀지 못한다. **컨트롤러 재부팅만이 유효**했다.
4. 재부팅 후에도 날짜/시간이 소실되므로(01/02/00, RTC 없음) **재초기화(시간/위치
   동기 + unpark + 추적 인에이블)까지 해야 완전 복구**된다. 날짜/시간 미설정
   상태에서도 `:Te#`는 ack만 하고 추적을 켜지 않는다(부팅 직후 실측).

### 웨지 유발 원인 (미확정)

- 14:28 indiserver 재시작 전후 정황(시간동기 실패, 속성 타임아웃)은 웨지의
  **증상일 가능성**이 높다. indiserver 재시작 자체도 컨트롤러 이상의 여파일 수 있음.
- 웨지 이전 컨트롤러 로그가 없어 유발 원인은 미상. 후보: 커스텀 펌웨어(10.28q)
  버그, 고온(CPU 76~78°C, 한여름 주간), 명령 채널 다중 접속 경합.
- `:GU#`에 `n`+`T` 동시 표시라는 모순은 펌웨어 내부 상태 불일치를 시사 —
  사용자 커스텀 펌웨어이므로 소스에서 `:Te#` 처리 경로 확인 가능.

### 초판 분석과의 차이

초판은 "재연결 시 `enable_tracking()` 2초 타임아웃 레이스로 추적 OFF 방치"를
원인으로 지목했다. 실측 결과 **정상 조건의 재연결 재초기화(15:13)로도 추적이
켜지지 않았으므로**, 그 레이스는 부차적이다. 다만 `enable_tracking()`의 조용한
실패(아래 7.3)는 여전히 실재하는 취약점이고, 웨지가 아닌 단순 레이스 상황이라면
초판의 처방으로 충분했을 것이다.

## 6. 복구 방법 테스트 결과 (실측 매트릭스)

| # | 방법 | 결과 | 비고 |
|---|---|---|---|
| 1 | `indi_setprop TRACK_MODE/STATE` | ❌ | MODE만 적용, STATE 무시 (웨지) |
| 2 | 드라이버 DISCONNECT→CONNECT (PiFinder 재초기화) | ❌ | 웨지 상태에선 무효 |
| 3 | `:Q#` (전체 중지) | ❌ | 상태 불변 |
| 4 | `:hR#` (홈 리셋) | ❌ | `'0'` 거부됨 |
| 5 | **`:ERESET#` 컨트롤러 재부팅** | ⚠️ 부분 | 웨지는 풀리나 날짜/시간 소실 → 그것만으론 GoTo 불가 |
| 6 | **재부팅 후 드라이버 재연결 토글 (= 5+2 조합)** | ✅ **완전 복구** | PiFinder가 시간/위치/unpark/추적 재설정 |

검증: 복구 후 SkySafari 경로 GoTo가 sync 수락 → 물리 슬루 → 보정 1회 →
**최종 오차 0.91′** 도달, `pifinder final sync complete`.

## 7. 검증된 수동 복구 절차 (현장 표준)

증상: "수동 이동은 되는데 GoTo만 안 됨".

```bash
# ── 1) 진단: 웨지 여부 판정 (진단 채널 9998 — 드라이버 9999를 방해하지 않음)
python3 - <<'EOF'
import socket, time
s = socket.create_connection(("10.10.10.12", 9998), timeout=4); s.settimeout(2)
for cmd in (b":GU#", b":Te#", b":GU#"):
    s.sendall(cmd); time.sleep(0.5)
    print(cmd.decode(), "->", s.recv(64).decode())
s.close()
EOF
#  두 번째 :GU#에도 'n'이 남아 있으면(= :Te# ack만) → 웨지. 2)로.
#  'n'이 사라졌으면 → 웨지 아님. 추적만 꺼진 것 → 이대로 복구 완료.

# ── 2) 컨트롤러 재부팅 (축 정지 확인 후: :GU#에 'N' 존재 = GoTo 없음)
python3 - <<'EOF'
import socket
s = socket.create_connection(("10.10.10.12", 9998), timeout=4)
s.sendall(b":ERESET#"); s.close()
EOF
sleep 40   # 재부팅 ~35초. 대안: 마운트 전원 재투입

# ── 3) PiFinder 재초기화 트리거 (시간/위치/unpark/추적 재설정)
indi_setprop "LX200 OnStepX.CONNECTION.DISCONNECT=On"; sleep 3
indi_setprop "LX200 OnStepX.CONNECTION.CONNECT=On"; sleep 20
#  ※ indi_setprop이 타임아웃으로 실패하면 재시도 (이 장비에서 간헐 발생)

# ── 4) 확인: 날짜 복원 + 추적 ON
python3 - <<'EOF'
import socket, time
s = socket.create_connection(("10.10.10.12", 9998), timeout=4); s.settimeout(2)
for cmd in (b":GC#", b":GU#"):
    s.sendall(cmd); time.sleep(0.5)
    print(cmd.decode(), "->", s.recv(64).decode())
s.close()
EOF
#  :GC# = 오늘 날짜(01/02/00이면 실패), :GU#에 'n' 없어야 함
```

이후 SkySafari에서 GoTo 재시도. 재부팅으로 좌표계가 초기화(At Home)되므로
첫 GoTo에서 PiFinder가 자동 sync 후 슬루한다(pifinder 방식). 필요시 아는 별에
sync 한 번 더.

## 8. 자동 복구 기능 설계 제안 (개정)

### 8.1 GoTo pre-flight + 웨지 판정 (핵심)

`goto_target()` 진입 시:

1. `_read_tracking_enabled()` 확인. OFF면 `set_tracking(True)`.
2. **적용 검증**: set 후 `:GU#`(OnStep Status)에서 `n` 소실 확인. INDI ack나
   switch 상태만 믿지 말 것 — "ack ≠ 적용"이 이번 장애의 함정이었다.
3. 검증 실패 → **웨지 판정**: `goto_failed("mount wedged; tracking enable ignored")`
   로 **즉시** 실패 보고(180초 대기 금지) + 콘솔 경고 + 상태 파일에 `wedge_suspected`.

### 8.2 웨지 자동 복구 (옵션, 설정 게이트)

`indi_onstep_auto_reboot_on_wedge`(기본 off) 활성 시: 웨지 판정 →
축 정지 확인(`:GU#`에 `N`) → 직접 채널로 `:ERESET#` → 40초 대기 →
드라이버 CONNECTION 토글 → 검증(날짜+`n` 소실) → GoTo 재시도 1회.
실패 시 사용자에게 "마운트 전원 재투입 필요" 안내.

### 8.3 컨트롤러 재부팅 감지 (재발 대비 필수)

**컨트롤러 재부팅은 현재 스택에 보이지 않는다** — TCP가 조용히 재수립되어
`connected`가 유지되지만 마운트는 날짜/시간을 잃는다(실측). 감지 규칙:

- 상태 하트비트에서 주기적으로 `:GC#` 날짜 확인 → `01/xx/00`이면 재부팅 판정
  → 시간/위치 동기 + unpark + 추적 인에이블 재실행.
- 보조 신호: `:GU#`에 `H`(At Home) 재출현, 위치 readback 급변.

### 8.4 slew 미시작 조기 감지

`_arm_goto_motion` 후 5초 내 busy/OnStep goto-active가 한 번도 관측되지 않고
위치 변화도 없으면 `goto_failed("mount did not start slew")`로 조기 종료.
(기존 `indi_seen_busy`/`onstep_seen_goto_active` 플래그 재사용.
현재는 180초 후 "assuming complete"로 **위장 실패**한다.)

### 8.5 `enable_tracking()` 견고화 + 상태 노출

- 속성 미정의 시 백오프 재시도, 최종 실패 시 warnings 기록 (조용한 `return True` 제거).
- `mount_control_status.json`에 `tracking_enabled` 필드 추가 → GoTo/Guide 서비스와
  웹 UI가 감지/표시 가능.
- 180초 fallback 로그를 원인별로 구분
  (`"GoTo did not complete in 180s (never busy, target error 24.1 deg)"` 식).

## 9. 파생 발견 (테스트 중 확인된 사항)

1. **진단 채널**: OnStepX 명령 포트 9996~9999 중 9999는 INDI 점유 시 두 번째
   클라이언트에 무응답. **9998이 진단/복구용으로 안전** (실측).
2. **`indi_setprop`/`indi_getprop` 간헐 타임아웃**: 이 장비(속성 80개)에서 자주
   발생. 스크립트 복구/진단은 PyIndi가 신뢰성 높음.
3. **pos_server 버그**: `:Sr`/`:Sd` 파싱 실패(예: 공백 포함) 시 `'0'`을 돌려주지만
   전역 `sr_result`/`sd_result`에 **이전 GoTo의 좌표가 남아** 있어, 이어지는
   `:MS#`가 낡은 타깃으로 발사된다([pos_server.py:1081](../../python/PiFinder/pos_server.py#L1081)).
   파싱 실패 시 저장값을 무효화해야 함.
4. **`:GU#` 디코드** (INDI 드라이버 파서 기준): `n`=추적 안 돎, `N`=슬루 안 함,
   `p`=언파크, `H`=앳홈, `A`=AltAz. 말미 숫자들은 레이트/에러(마지막 0=무에러).
   웨지 시 `n`+`T` 동시 표시가 관측됨.
5. **SWS 웹 상태**: `http://10.10.10.12/index.txt` (ajax)에서 컨트롤러 온도·드라이버
   상태·last_err·WiFi 신호를 즉시 확인 가능.
6. UnPark의 실체는 `:hR#`이다(드라이버 `UnPark()`). 마운트가 "UnParked"를 보고하면
   PiFinder가 unpark를 건너뛰므로 `:hR#`가 발사되지 않는 경로가 존재.

## 10. 재발 시 체크리스트

1. RA readback이 **+0.251°/분** 드리프트? (상태 파일 2회 샘플) → 추적 OFF.
2. 9998로 `:Te#` → `:GU#`: ack 후에도 `n` 유지? → **웨지** → 7장 절차.
3. `:GC#` 날짜가 `01/xx/00`? → 컨트롤러가 재부팅됐는데 재초기화 안 된 상태
   → 드라이버 CONNECTION 토글.
4. `pifinder.log`에서 `GoTo error did not improve` / `assuming complete` /
   `Timeout waiting for property` 검색.
5. `/tmp/indiserver.log`의 `startup:`(UTC)으로 INDI 스택 재시작 여부 확인.
6. SWS `index.txt`로 컨트롤러 온도/에러 확인 (이번 사례 76~78°C).

## 11. 미해결 질문

- **웨지 유발 원인**: 재부팅 이전 컨트롤러 로그 부재로 미상. 커스텀 펌웨어
  10.28q의 `:Te#` 처리 경로(ack 후 미적용 조건)와 상태 플래그(`T`/`o`/`e`) 의미를
  펌웨어 소스에서 확인 권장. 재발 시 SWS/시리얼 로그 확보.
- 14:28 indiserver 재시작의 트리거 주체 (웹 UI 조작 vs 자동 복구 vs 웨지 여파).
- 고온(주간 76~78°C)과 웨지의 상관관계 — 방열 개선 후 재발 여부 관찰.
