# Trixie 실내 OnStepX 시리얼 Auto 적용 복구 — 2026-09-27

## 조건과 원인

Raspberry Pi 5 / Debian Trixie / Python 3.13.5에서 실내 마운트 시리얼 연결을
시험했다. 사용자는 전원이 켜진 OnStepX의 제어 포트 연결을 확인했다.
시리얼 장치는 `/dev/ttyUSB0`, 안정 경로는
`/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0`이다.

앞선 마운트 미연결 시험에서 `mount_control=false`로 설정했다. 메인 프로세스는
이 설정과 무관하게 명령 큐를 생성하지만, OFF일 때 이를 소비하는 프로세스는
시작하지 않는다. 웹의 Auto 적용은 큐 존재만 확인하고 검색 명령을 넣어
"시작됨"을 표시했으므로 실제 검색은 진행되지 않았다.
INDI Web Manager도 실행 중이었지만 INDI 서버와 드라이버는 정지 상태였다.

또한 시리얼 속도를 순회하면 컨트롤러의 LX200 명령 파서에 불완전한 명령이
남을 수 있었다. 호스트의 입력 버퍼 초기화만으로 이를 없앨 수 없었고,
115200 baud에서도 제품명 대신 `0`을 수신했다. `#`로 명령 경계를 정리한 뒤
동일 포트에서 `:GVP#`와 `:GVN#`에 각각 `On-Step#`, `10.28x#`가 응답했다.

## 수정

- 제품명 조회 전에 명령 경계를 정리하고 잔여 응답을 버린다. DTR/RTS를
  조작하지 않는 기존 포트 열기와 제품·버전 검증, 중복 포트 제거, GPS 제외는 유지한다.
- 마운트 제어 OFF 또는 정지된 드라이버에서는 검색 명령을 넣지 않는다.
  원인과 복구 방법을 한국어·영어로 표시하고 잘못된 적용에는 HTTP 400을 반환한다.
- 드라이버 시작 직후 페이지 캐시가 비어 있어도 잘못 거부하지 않도록,
  Auto 적용의 준비 확인은 INDI 드라이버를 직접 읽는다.
- 연결 자체가 주차 해제·추적 시작을 요청하지 않도록 상태 보존을 기본으로 한다.
  자동 연결에서는 위치·시각 동기화를 별도로 취급한다.
- 추가로, 초기 위치·시각 자동 동기화에서 원래 OFF인 추적이 ON으로 바뀌는
  현상을 재시작 두 번에서 관측했다. 즉시 OFF로 복구했다. 시각 동기화 함수가
  기존 OFF 상태를 보존하고 부분 적용 실패 때에도 복구하도록 수정했다.

## 실물 검증과 운영 반영

기존 `OnstepX` 프로필로 INDI 서버·드라이버를 시작했다. 설정 원본은 원자료
디렉터리에 0600 권한으로 백업했고, 이번 연결 시험에 맞춰 마운트 제어를 켰다.
가이딩은 계속 비활성 상태다.

운영 가상환경에서 실제 `/indi/driver` 처리 함수를 Flask test client로 호출하고,
그 큐 명령을 동일한 `MountControlIndi` 검색 구현으로 처리했다. 실행 중인 웹
프로세스에 인증된 브라우저 요청을 보낸 검사는 아니다. 실제 INDI 드라이버·
시리얼 마운트와 통신하고 다음 결과를 읽었다.

| 항목 | 결과 |
| --- | --- |
| Auto 웹 처리 | HTTP 200, 검색 명령 1개 |
| 시리얼 검색 | 후보 1개, 검증된 장치 1개, success |
| 제품·펌웨어 | On-Step / 10.28x |
| 발견 속도 | 115200 baud |
| 연결 | `CONNECTION.CONNECT=On`, `CONNECTION_SERIAL=On` |
| 저장 | 안정 포트 경로·115200·usb를 INDI와 MFNavis 설정에 반영 |
| 추적 | 검색·연결 검증 후 OFF |

실제 시각 동기화 수정 검증도 성공했고, 전후 모두 추적 OFF로 읽혔다.
최종 서비스 시작은 00:47:41 KST다. 재시작 후 18개 표본 모두 연결 ON·추적 OFF였고,
자동 복구 명령을 추가로 보낼 필요가 없었다. 이후 상태도 `connected`,
`connection_health=healthy`, `serial_present=true`, `tracking_enabled=false`다.
서비스는 active/running, `NRestarts=0`, 수집 journal의 ERROR·Traceback은 0건이다.
수동 이동·GoTo·좌표 Sync·
가이딩 명령은 보내지 않았다. 수정 전 자동 동기화에서 추적 ON이 관측되었으므로
전체 검사 동안 물리적 움직임이 전혀 없었다고 보증하지 않는다.

## 회귀 검사

- 관련 회귀: **344 passed**, 실패 0개.
- 불완전 명령 파서 복구, Auto 준비 조건·중복 검색·캐시 초기 상태,
  기본 연결의 상태 보존, 시각 동기화 성공·부분 실패의 추적 보존을 검사했다.
- Ruff lint, format 406개 파일, `git diff --check` 통과.
- 전체 비-Selenium 회귀(IMU 파일 제외): **3549 passed, 3 skipped**, 실패 0개,
  212.68초, 프로세스 **exit code 0**. Selenium 브라우저 검사는 제외했다.
  IMU 전용 파일은 앞선 별도 모의 검사 3개 통과 기록을 유지하며 이번에는 재실행하지 않았다.

다음 Auto 적용에도 마운트 제어 ON과 실행 중인 OnStepX 드라이버가 필요하다.
이번 장비에서는 두 조건을 복구했다. Auto는 발견한 구체적인 포트·속도를 검증한
뒤 저장하므로 성공 후 화면에는 USB 시리얼 경로와 115200 baud가 표시된다.

## 원자료

`/home/mfnavis/trixie-fixed-cloudy-20260926/fixes/`에 보존한다.
설정 원본·상세 로그는 Git에 추가하지 않는다.

- `config-before-indoor-serial.json`
- `indoor-serial-discovery-after.json`
- `indoor-serial-apply.log`, `indoor-serial-apply-summary.json`
- `indoor-serial-runtime-after.json`, `indoor-serial-restart-state.json`
- `indoor-serial-time-state-after.json`, `indoor-serial-final-restart-state.json`
- `indoor-serial-targeted-final.log`
- `indoor-serial-verified-final-tests.log`, `indoor-serial-verified-final.xml`
