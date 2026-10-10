# INDI LX200 OnStepX Driver Test Checklist

> 상태: **완료된 1회성 검증 기록 (2026-07-01)** — INDI 드라이버 통합 가능성
> 판단을 위한 사전 테스트였고 결론은 완료됐다. 이력 참고용이며 유지보수
> 대상 아님. 운영/설치 절차는 [mf_indi_mount_install_ko.md](../history/development/mount.md#mf_indi_mount_install_ko) 참조.

이 문서는 OnStep 장비를 PiFinder에서 INDI로 사용하기 전에, 같은 기능을
직접 LX200 명령과 `LX200 OnStepX` INDI 드라이버로 비교하기 위한 체크리스트다.

## 기준 소스

- OnStep 소스: `hjoungjoo/OpenX_pio_E4`
- 확인 커밋: `7e216f4dee4071ba8cd3f200a2063b810e898571`
- 주요 참조 파일:
  - `src/telescope/mount/site/Site.command.cpp`
  - `src/telescope/mount/guide/Guide.command.cpp`
  - `src/telescope/mount/goto/Goto.command.cpp`
  - `src/telescope/mount/park/Park.command.cpp`
  - `src/telescope/mount/home/Home.command.cpp`
  - `src/telescope/mount/Mount.command.cpp`
  - `src/telescope/mount/status/Status.command.cpp`

## 테스트 격리

테스트 중에는 PiFinder 서비스와 INDI Web Manager를 멈춰서 포트 충돌과
자동 상태 갱신을 막는다.

- `pifinder` 서비스 정지
- `indiwebmanager.service` 정지
- 남아 있는 `indiserver` 프로세스 정지
- OnStep TCP 포트는 기본 `10.10.10.12:9999`로 테스트한다.
- INDI 서버는 수동으로 `indiserver -p 7624 indi_lx200_OnStep`만 실행한다.

## 직접 LX200 명령 체크리스트

| 항목 | 명령 | 기대 결과 | 결과 |
| --- | --- | --- | --- |
| TCP 접속 | `10.10.10.12:9999` 연결 | 연결 성공 | PASS |
| 제품/버전 조회 | `:GVP#`, `:GVN#` | 모델/버전 문자열 또는 지원 응답 | PASS: `On-Step`, `10.28q` |
| 상태 조회 | `:GU#`, `:GW#`, `:D#` | 추적/파크/고투/가이드 상태 확인 | PASS: 최종 `nNpAT250#`, `AN0#`, `#` |
| 현재 좌표 조회 | `:GRH#`, `:GDH#`, `:GAH#`, `:GZH#` | RA/Dec/Alt/Az 고정밀 응답 | PASS |
| 시간 조회 | `:GC#`, `:GL#`, `:GG#`, `:GX80#`, `:GX81#`, `:GX89#` | 로컬/UTC/오프셋/준비 상태 확인 | PASS: `:SG-09:00#`일 때 UTC 정상 |
| 위치 조회 | `:GtH#`, `:GgH#`, `:Gv#` | 위도/경도/고도 확인 | PASS: 최종 `+37*31:37`, `-127*06:34`, `30m` |
| 속도 설정 | `:R0#` ... `:R9#` | 각 rate 명령 수락 | PASS: 명령 수락 확인. 세부 rate 표시는 별도 해석 필요 |
| 수동 이동 East/West | `:Me#`, `:Mw#`, `:Qe#`, `:Qw#`, `:Q#` | 누르는 동안 이동, 정지 명령 후 정지 | PASS: `g` 상태 발생 후 정지 |
| 수동 이동 North/South | `:Mn#`, `:Ms#`, `:Qn#`, `:Qs#`, `:Q#` | 누르는 동안 이동, 정지 명령 후 정지 | PASS: `g` 상태 발생 후 정지 |
| Unpark | `:hR#` | 성공 응답 또는 이미 unpark 상태 | NOT RUN: 최종 상태는 UnParked |
| Park 상태 | `:h?#`, `:GU#` | 파크/홈 상태 문자열 확인 | PASS: `0,0,0#`, `nNp...` |
| Home/Return Home | `:hF#`, `:hC#` | 명령 수락 및 상태 변화 확인 | NOT RUN: 큰 동작이라 이번 비교 테스트에서 제외 |
| Target 설정 | `:Sr...#`, `:Sd...#`, `:GrH#`, `:GdH#` | 목표 RA/Dec 설정 및 조회 | PASS |
| Goto | `:MS#`, `:D#`, `:Q#` | 허용 좌표는 이동 시작, 정지 가능 | PASS: 현재 좌표 근처 작은 오프셋 Goto 수락 |

## INDI Driver 체크리스트

| 항목 | INDI 속성/동작 | 기대 결과 | 결과 |
| --- | --- | --- | --- |
| 드라이버 로드 | `LX200 OnStepX` 장치 생성 | `indi_getprop`에서 장치 확인 | PASS: custom driver `1.27-mf1`, process `indi_lx200_OnStepX` |
| TCP 설정 | `CONNECTION_MODE`, `DEVICE_ADDRESS` | `10.10.10.12:9999` 설정 가능 | PASS: 두 단계 설정 후 속성 생성 |
| Connect | `CONNECTION.CONNECT=On` | 연결 On, 오류 없음 | PASS: 첫 설정 직후 재시도 필요, 이후 연결 성공 |
| 상태 조회 | `CONNECTION`, `TELESCOPE_PARK`, `TELESCOPE_SLEW_RATE` | 직접 명령 상태와 일치 | PASS: UnParked/Error None |
| 현재 좌표 조회 | `EQUATORIAL_EOD_COORD`, `HORIZONTAL_COORD` | 직접 `:GRH#/:GDH#/:GAH#/:GZH#`와 비교 가능 | PASS: RA/Dec 조회 가능 |
| 시간/위치 설정 | `TIME_UTC`, `GEOGRAPHIC_COORD` | OnStep에 반영되고 직접 조회와 일치 | PASS after driver fix: PyIndi 전체 벡터 전송으로 위도/경도 초 단위, 고도, UTC time 적용 확인. `indi_setprop` CLI element 단위 전송은 사용 금지 |
| 수동 이동 East/West | `TELESCOPE_MOTION_WE` | 직접 명령과 같은 방향, Off 후 정지 | PASS: `g` 상태 발생 후 Off/Abort로 정지 |
| 수동 이동 North/South | `TELESCOPE_MOTION_NS` | 직접 명령과 같은 방향, Off 후 정지 | PASS: `g` 상태 발생 후 Off/Abort로 정지 |
| Slew Rate | `TELESCOPE_SLEW_RATE.0` ... `.9` | OnStep rate 0..9와 일치 | PASS/PARTIAL: INDI 선택 상태는 0..9 모두 전환됨. OnStep 내부 rate 의미 매핑은 추가 확인 필요 |
| Park/Unpark | `TELESCOPE_PARK` | 직접 명령 상태와 일치 | PARTIAL: UnParked readback 확인. Park 동작은 미실행 |
| Home/Return Home | `TELESCOPE_HOME`, `TELESCOPE_PARK_OPTION` | 지원 여부 확인 | NOT RUN |
| Goto | `ON_COORD_SET`, `EQUATORIAL_EOD_COORD` | 직접 `:MS#`와 같은 조건에서 이동 | PASS/PARTIAL: 작은 RA 오프셋에서 좌표 이동 확인. Goto 상태 플래그는 명확하지 않음 |
| Stop | Abort/stop 관련 속성 또는 `CONNECTION` 상태 | 이동 중 안전 정지 가능 | PASS: `TELESCOPE_ABORT_MOTION.ABORT=On` 후 직접 최종 정지 확인 |

## 판정 기준

- 직접 LX200 명령과 INDI 드라이버가 모두 성공: PiFinder 연동 구현 가능.
- 직접 LX200 명령은 성공하지만 INDI 드라이버만 실패: 드라이버 설정/구현 문제로 분류.
- 직접 LX200 명령도 실패: OnStep 설정, 펌웨어 상태, 네트워크, 파크/홈/제한 조건 문제로 분류.
- INDI 속성이 존재하지 않음: 현재 설치된 INDI 드라이버에서 미지원 기능으로 분류.

## 테스트 결과 요약

- 실행 일시: 2026-07-01 23:35-23:47 KST
- 테스트 장비: OpenX/OnStep TCP `10.10.10.12:9999`, firmware `10.28q`,
  INDI `indi_lx200_OnStepX` custom driver `1.27-mf1`
- 직접 LX200 결과: 연결, 조회, 시간/위치 설정, 수동 이동/정지, 작은 Goto 모두 정상.
- INDI 드라이버 결과: 연결, 상태 조회, 수동 이동/정지, 작은 Goto는 사용 가능.
- LX200 OnStepX 결과: PyIndi 전체 벡터 전송으로 시간/위치 설정도 정상 동작한다.
- 처리 가능한 작업:
  - PiFinder에서 INDI 드라이버를 통한 수동 가이드/정지
  - INDI 드라이버를 통한 제한적 Goto 전달
  - PiFinder Web UI와 LCD INIT에서 INDI 경유 위치/시간 동기화
  - INDI 연결 상태와 기본 상태 readback 표시
- 처리 불가능하거나 별도 확인이 필요한 작업:
  - `indi_setprop` CLI로 `GEOGRAPHIC_COORD`/`TIME_UTC` element를 따로 쓰는
    방식은 사용하지 않는다. 테스트 중 지정하지 않은 vector element가 0으로
    바뀌는 문제가 있었다.
  - OnStep 직접 명령에서 한국 시간 기준 올바른 `:SG#` 값은 `-09:00`이다.
    INDI 표준 `TIME_UTC.OFFSET`은 `+9.00`으로 표시되므로 두 값의 부호 관례가 다르다.

## 최종 안전 상태

- 테스트 종료 시 `:Q#` 전체 정지 명령을 전송했다.
- 최종 직접 상태:
  - `:D#` -> `#`
  - `:GU#` -> `nNpAT250#`
  - `:GtH#` -> `+37*31:37.000#`
  - `:GgH#` -> `-127*06:34.000#`
  - `:Gv#` -> `30.0#`
  - `:GG#` -> `-09:00#`
  - `:GX80#` -> 실제 UTC와 일치

## 코드 반영 정책

- LX200 OnStepX의 위치/시간 설정은 커스텀 INDI driver와 PyIndi 전체 벡터
  전송을 기본으로 사용한다.
- PiFinder Web UI와 LCD INIT의 `Send Location/Time`은
  `apply_indi_onstep_location_time(...)`를 사용한다.
- `sync_onstep_location_time_exclusive(...)`는 수정 드라이버를 사용할 수 없거나
  OnStep 전용 복구가 필요한 경우의 fallback으로 남긴다.
- fallback 직접 전송 명령:
  - `:St...#`: 위도
  - `:Sg...#`: 경도
  - `:Sv...#`: 고도
  - `:SG...#`: OnStep UTC offset
  - `:SL...#`: local time
  - `:SC...#`: local date
- 다른 기능은 체크리스트 결과를 기준으로 INDI driver 명령을 계속 사용한다.
  현재 수동 이동/정지, slew rate 선택, 제한적 Goto는 INDI 경로를 사용할 수 있다.
