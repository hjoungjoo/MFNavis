# MF PiFinder GPS Aiding Plan (u-blox 전용)

> 아래 OS 언급은 당시 설계·전환 기준이다. 현재 MFNavis 설치는
> [Trixie 64-bit / Python 3.13 안내](mf_trixie_install_ko.md)를 따른다.

작성일: 2026-07-14
상태: 설계 초안 (구현 전 검토용)

이 문서는 u-blox 수신기(GEP-M1025, M10 SPG 5.10)가 장시간 전원 차단 후
콜드스타트로 시작하는 문제를 완화하기 위해, Raspberry Pi가 가진 시각·위치·
보조 데이터를 **사용자의 주입 요청 시점에** 수신기에 주입(aiding)하는
기능의 설계와 동작 순서를 정리한다. 구현 전에 이 문서로 동작 순서와
정책을 확정한다.

## 배경

- GEP-M1025의 백업 전원은 배터리가 아니라 슈퍼커패시터다. 유지 시간이
  분~수 시간 수준이라, PiFinder를 하루 이상 꺼두면 시각·궤도력·알마낙이
  모두 소실되어 매번 완전 콜드스타트가 된다. (설정은 플래시에 있어 유지됨)
- 콜드/웜 스타트에서 이미 추적 중인 위성의 C/N0 자체는 같지만,
  **획득(acquisition) 감도와 TTFF는 크게 다르다**. 콜드는 전 위성을
  넓은 도플러×코드 공간에서 blind 탐색해야 하므로 획득 문턱이 높고
  (M10 기준 약 -148 dBm), 웜/핫은 좁은 창만 탐색해 재획득 감도
  (약 -160 dBm)에 가깝게 동작한다. 실효 차이는 10~15 dB에 달한다.
- 2026-07-14 진단에서 PiFinder 본체 EMI가 GPS 신호를 10~15 dB 깎는 것을
  확인했다(A-B-A 측정). aiding은 이 손실을 부분적으로 상쇄하는
  실질적인 우회책이기도 하다.

## 목표

- **사용자가 주입을 요청한 시점**(LCD/Web의 Inject Now)에 수신기를
  콜드 → 웜(가능하면 핫에 근접) 스타트로 전환한다. **부팅 시 자동 주입은
  하지 않는다** — 수신기에 쓰는 시점은 항상 사용자가 결정한다.
- **완전 오프라인으로 동작한다.** 인터넷, 외부 서비스 가입, 계정이 일절
  필요 없다.
- 사용자가 방식별로 켜고 끄고, 수동으로 주입/저장할 수 있어야 한다.
- 기존 GPS 흐름(gpsd, gps_gpsd/gps_ubx, time sync helper)을 흔들지 않는다.
- 실패해도 부팅과 GPS 수신 자체는 절대 방해하지 않는다 (best-effort).

## 범위와 전제

- **u-blox 전용**: 주입에 쓰는 UBX-MGA/UPD는 u-blox 프로토콜이다.
  게이트는 config가 아니라 **수신기 감지**로 한다 — gpsd `DEVICES` 응답의
  `driver == "u-blox"` (현재 기기: `SW ROM SPG 5.10, PROTVER=34.10`).
  gpsd/ublox 어느 백엔드를 쓰든 수신기가 u-blox이면 동작한다.
- **패키지 사용**: 전송 도구는 gpsd의 `ubxtool`을 쓴다. Bookworm에서
  `/usr/bin/ubxtool`은 이미 있으나 `python3-gps` 패키지가 필요하다
  (`pifinder_setup.sh`에 추가). gpsd가 `-b`(readonly)로 실행 중이면 기능을
  비활성화하고 상태에 사유를 남긴다.
- 수신(ACK 확인, DBD 캡처)은 리포에 이미 있는 `UBXParser`의 gpsd raw watch
  (`?WATCH raw:2`)를 재사용한다. 새 시리얼 접근은 만들지 않는다 —
  포트는 계속 gpsd가 소유한다.
- ROM 펌웨어(SPG 5.10)는 `UBX-UPD-SOS`(플래시 자동 저장/복원)를 지원하지
  않을 수 있으므로 계획에서 제외하고, 호스트(Pi) 저장 방식(② MGA-DBD)으로
  통일한다.

## 두 가지 방식

| # | 방식 | 데이터 | 효과 | 기본값 |
| --- | --- | --- | --- | --- |
| ① | MGA-INI 시각+위치 | Pi 시계(chrony/RTC), PiFinder 위치 | 콜드 → 웜. 탐색 공간 대폭 축소 | On |
| ② | MGA-DBD 백업/복원 | 수신기가 실제 수집한 nav DB(궤도력/알마낙) | 최근 사용 시 핫 근접, 이후 웜 | On |

- **두 방식 모두 사용자 선택 항목이다.** ①도 예외 없이 토글로 켜고 끈다
  (`gps_aiding_ini_enabled`). 어떤 방식도 사용자가 끄면 주입하지 않는다.
- ①이 활성화되어 있으면 항상 가장 먼저 주입한다 (시각이 있어야 뒤의
  데이터를 수신기가 검증할 수 있으므로).
- ②는 위치 정보와 함께 저장·관리한다. 장소가 바뀌면 즉시 반응한다
  (아래 "위치 변경 반응" 참고).
- 두 방식 모두 인터넷이 필요 없다.

### 제외한 방식: AssistNow (MGA-ANO)

u-blox AssistNow(구 Online/Offline, 신 Predictive Orbits)의 궤도 예측
데이터도 같은 주입 경로로 쓸 수 있으나, **외부 서비스 가입 절차가 필요해
이 계획에서 제외한다**:

- 구 Online/Offline은 2026-05-31부로 EOM/EOS, 신규 토큰 미발급.
- 후속 Predictive Orbits는 M10에 무료지만 Thingstream 계정 가입 +
  ZTP 기기 등록(수신기 `UBX-SEC-UNIQID` 기반 chipcode 발급) 절차가 필요.

PiFinder는 오프라인·무계정 동작을 원칙으로 하므로 채택하지 않는다.
데이터 포맷(UBX-MGA-ANO)과 접근 절차 조사 기록은 git 이력
(`fb86262` 이전 버전)에 남아 있어, 추후 필요 시 재검토할 수 있다.

## 아키텍처

```text
새 모듈: python/PiFinder/gps_aiding.py
데이터:   ~/PiFinder_data/gps_aiding/
            dbd/  snapshot_*.ubx   (② 스냅샷, 회전 보관)
            dbd/  index.json       (스냅샷 메타: 시각, 위치, 소스)
상태:     ~/PiFinder_data/gps_aiding_status.json
```

실행 주체:

- **주입은 전부 사용자 요청으로만**: server.py 라우트와 LCD 콜백이
  같은 모듈의 주입 함수를 직접 호출한다. 별도 큐는 만들지 않는다.
  부팅 시 자동 주입 경로는 없다.
- **백그라운드 워커는 ② 주기 DBD 백업 전용**: GPS 프로세스가 시작될 때
  `gps_aiding.start_worker()` 데몬 스레드를 띄우되, 이 워커는 수신기에
  aiding 데이터를 주입하지 않는다 — fix lock 상태에서 주기적으로
  DBD를 **읽어 저장**만 한다. gpsd 연결과 u-blox 감지가 끝난 뒤에만
  동작한다.
- **직렬화**: 수신기에 쓰는 모든 동작은 파일 lock
  (`gps_aiding.lock`, flock)으로 직렬화한다. 프로세스가 달라도 안전하다.
- 전송은 `ubxtool -P 34.10 -c CLASS,ID,<hex payload>` 서브프로세스,
  검증/캡처는 UBXParser raw watch. MGA ACK는 `CFG-NAVSPG-ACKAIDING`이
  켜져 있을 때만 오므로, ACK는 "확인되면 기록"하고 없어도 실패로
  간주하지 않는다(fire-and-forget 허용).

## 주입 요청 처리 순서도

주입은 사용자가 LCD/Web에서 `Inject Now`를 눌렀을 때만 실행된다.

```mermaid
flowchart TD
    A[사용자 Inject Now 요청<br/>LCD 또는 Web] --> B{gpsd ready and driver == u-blox?}
    B -->|no| Z1[aiding skip - status에 사유 기록]
    B -->|yes| C{gps_aiding_enabled?}
    C -->|no| Z1
    C -->|yes| C2{ini_enabled?}
    C2 -->|no| J
    C2 -->|yes| D{시각 신뢰 가능?<br/>chrony synced 또는 RTC valid}
    D -->|yes| E[MGA-INI-TIME_UTC 주입<br/>tAcc 정직하게 설정]
    D -->|no| F[시각 주입 생략]
    E --> G{위치 신뢰 가능?<br/>lock된 위치 또는 최근 fix}
    F --> G
    G -->|yes| H[MGA-INI-POS_LLH 주입<br/>posAcc = 위치 error 반영]
    G -->|no| I[위치 주입 생략]
    H --> J{dbd_enabled and 스냅샷 있음?}
    I --> J
    J -->|yes| K[DBD 스냅샷 선택 후 복원 주입]
    J -->|no| P[완료]
    K --> P
    P --> Q[gps_aiding_status.json 기록<br/>방식별 결과/시각/ACK]
```

주입 순서 원칙: **시각 → 위치 → DBD**. 시각이 있어야 수신기가
뒤따르는 궤도력 데이터의 유효성을 판정할 수 있다.

## ② MGA-DBD 저장/복원 순서도

저장 (백업):

```mermaid
flowchart TD
    A[저장 트리거] --> A1[주기: fix lock 상태에서 N분마다<br/>기본 15분]
    A --> A2[수동: Web/LCD 'DBD 저장']
    A --> A3[종료: PiFinder shutdown hook]
    A1 --> B{GPS fix lock?}
    A2 --> B
    A3 --> B
    B -->|no| Z[생략 - lock 없으면 DB 가치 낮음]
    B -->|yes| C[UBXParser raw watch 열기]
    C --> D[UBX-MGA-DBD poll 전송]
    D --> E[DBD 응답 프레임 수집<br/>timeout 내 전부]
    E --> F[snapshot_YYYYmmdd_HHMMSS.ubx 저장]
    F --> G[index.json 갱신:<br/>saved_at, lat, lon, source, 메시지 수]
    G --> H[오래된 스냅샷 회전 삭제<br/>max_snapshots 초과분]
```

복원 (주입 요청 시):

```mermaid
flowchart TD
    A[DBD 복원<br/>Inject Now 흐름의 한 단계] --> B{index.json에 스냅샷 있음?}
    B -->|no| Z[생략]
    B -->|yes| C[현재 의도 위치 결정<br/>PiFinder 선택 위치 또는 마지막 fix]
    C --> D{나이 < 4h 이고<br/>거리 < location_match_km 인 스냅샷?}
    D -->|yes| E[해당 스냅샷 선택<br/>궤도력까지 유효 - 핫 근접]
    D -->|no| F[가장 최신 스냅샷 선택<br/>알마낙 가치는 수 주 유지 - 웜]
    E --> G[스냅샷의 DBD 메시지 순차 주입]
    F --> G
    G --> H[이후 단계의 INI-POS가<br/>위치를 현재 값으로 보정]
    H --> I[status 기록: 선택 스냅샷,<br/>나이, 거리, 메시지 수]
```

- 궤도력은 ~4시간만 유효하므로 "나이 < 4h + 같은 장소"가 최상 케이스다.
  그 외에는 알마낙/이온층 보정 가치로 최신 스냅샷을 넣는다 (콜드보다
  항상 낫고, 해가 되지 않는다).
- 위치 태깅은 스냅샷 메타(index.json)에 저장한다. 장소별로 별도 보관할
  필요는 없다 — 궤도력·알마낙 자체는 위치 독립이고, 위치는 ①이 맡는다.
  매칭 판정은 "이 스냅샷의 궤도력을 핫스타트급으로 신뢰할지"의 기준이다.

## 위치 변경 반응

```mermaid
flowchart TD
    A[사용자가 위치 변경<br/>locations 선택/GPS lock/Web 입력] --> B{aiding + ini + position<br/>모두 enabled and u-blox?}
    B -->|no| Z[아무것도 안 함]
    B -->|yes| C[MGA-INI-POS_LLH 즉시 재주입<br/>새 위치 + posAcc]
    C --> D[status 기록: last_pos_inject]
```

- 관측지를 옮겨 다니는 사용 패턴에서, 위치가 바뀌는 순간 수신기 탐색
  가정도 바로 갱신되도록 한다. 훅 지점은 main.py의 `gps_msg == "fix"`
  중 source가 GPS가 아닌 경우(수동/저장 위치 적용)와 locations 콜백.
- 위치 변경도 사용자의 명시적 행위이므로 "사용자 요청 시점 주입" 원칙에
  부합한다. 부팅처럼 사용자 개입 없이 일어나는 자동 주입은 아니다.

## 사용자 제어 (UI)

LCD:

```text
Settings > Advanced > GPS Settings > GPS Aiding
  Aiding        Off / On          (gps_aiding_enabled)
  Use INI       Off / On          (gps_aiding_ini_enabled, ① 시각+위치)
  Use DBD       Off / On          (gps_aiding_dbd_enabled)
  Inject Now    [action]          (활성화된 방식 전체 재주입)
  Save DBD      [action]          (지금 DBD 백업)
```

Web (GPS 관련 카드 또는 Tools):

- 방식별 토글(①시각/위치 분리 토글 포함)
- 상태 표시: 방식별 마지막 주입 시각/결과,
  DBD 스냅샷 목록(시각·위치·나이)
- 버튼: `Inject Now`, `Save DBD Now`
- LCD보다 세부 설정(주기, 임계값)은 Web에만 노출

## 설정 키 (default_config.json)

```text
gps_aiding_enabled            true    기능 전체
gps_aiding_ini_enabled        true    ① (사용자 선택 토글, LCD/Web)
gps_aiding_time               true    ① 세부: 시각 주입 (Web 전용)
gps_aiding_position           true    ① 세부: 위치 주입 (Web 전용)
gps_aiding_dbd_enabled        true    ②
gps_aiding_dbd_interval_min   15      주기 백업 간격
gps_aiding_dbd_max_snapshots  5       회전 보관 수
gps_aiding_dbd_match_km       100     핫스타트급 신뢰 거리 임계
```

모든 키는 일반 설정처럼 저장된다 (LiveCam processing 같은 세션 전용
스위치는 없음 — aiding은 리소스를 상시 소비하지 않는다).

## 안전 규칙

- **UI와 GPS 수신을 절대 막지 않는다**: 주입은 사용자 요청 시에만
  실행되고, 모든 단계에 타임아웃(전송 수 초), 실패는 로그 + status
  기록 후 다음 단계로. 주입 실행 중에도 LCD/Web은 블로킹되지 않는다
  (백그라운드 실행 + 상태 표시).
- **거짓 데이터를 넣지 않는다**:
  - 시각: chrony synced 또는 time sync helper가 신뢰하는 상태에서만.
    `tAccS/Ns`를 실제 신뢰도로 설정 (NTP면 수백 ms~수 초, RTC면 크게).
  - 위치: lock된 저장 위치 또는 최근 GPS fix만. `posAcc`에 위치 error를
    반영하고 하한을 둔다. 불확실하면 생략 — 틀린 위치 주입은 무주입보다
    나쁘다.
- 수신기 쓰기는 flock으로 전 프로세스 직렬화. gpsd `-b` 감지 시 기능
  비활성 + status에 안내.
- ubxtool 부재/실패(패키지 미설치)면 기능 비활성 + status 안내.

## 메시지/도구 참고

```text
전송: ubxtool -P 34.10 -c <class,id,payload>
  MGA-INI-TIME_UTC   0x13 0x40 (type=0x10)  시각 + tAcc
  MGA-INI-POS_LLH    0x13 0x40 (type=0x01)  lat/lon/alt + posAcc
  MGA-DBD            0x13 0x80              poll(빈 payload) / 복원(덤프 재전송)
확인: UBXParser raw watch
  MGA-ACK            0x13 0x60              ACKAIDING 켜진 경우만 수신
  MGA-DBD 응답        0x13 0x80              백업 캡처 대상
```

- UBXParser에 MGA 클래스(0x13) raw 프레임 패스스루를 추가해야 한다
  (현재는 NAV 계열만 파싱). 파싱은 불필요 — 프레임 bytes 그대로 저장/재전송.

## 구현 단계

```text
Stage 1  gps_aiding.py 뼈대 + ① 시각/위치 주입 + Inject Now 진입점(Web)
         + status 파일 (u-blox 감지, flock, ubxtool 래퍼, 게이트 규칙)
Stage 2  설정 키 + LCD 메뉴 + Web 카드/버튼 (Inject Now)
Stage 3  ② DBD: UBXParser MGA 패스스루, 백업(주기/수동/종료), 복원,
         index.json, 위치 태깅/선택 규칙
Stage 4  위치 변경 훅, pifinder_setup.sh에 python3-gps 추가, 문서 갱신,
         실측 검증
```

각 Stage는 독립적으로 배포/검증 가능해야 한다. Stage 1만으로도
콜드 → 웜 효과가 나온다.

## 테스트 계획

- 실내: 주입 명령 성공/타임아웃, status 파일 필드, flock 경합,
  gpsd `-b`/ubxtool 부재 시 비활성 동작.
- 실외 A/B (scripts/gps_acquisition_diag.py 재사용):
  - cold (주입 안 함) vs ① vs ①+② 의 TTFF 비교
    (각 케이스 모두 부팅 후 사용자가 Inject Now를 누른 시점 기준)
  - 전원 수 시간 차단 → 재부팅 → Inject Now 시나리오
  - 관측지 이동 시나리오 (위치 변경 반응 확인)
- 회귀: 기존 GPS 흐름(fix/time/satellites 메시지, time sync helper)
  무영향 확인. aiding 전체 Off 시 현재와 완전 동일해야 한다.

## 미해결 질문 (구현 전 확정 필요)

1. 종료 시 DBD 백업 훅의 위치 — PiFinder 정상 종료 경로가 짧아서
   systemd `ExecStop` 스크립트가 더 안정적일 수 있음.
2. gpsd 3.22 ubxtool의 M10(PROTVER 34) 호환 — `-c` 원시 전송은 문제
   없을 것으로 보이나 Stage 1에서 실기기 확인이 첫 작업.
