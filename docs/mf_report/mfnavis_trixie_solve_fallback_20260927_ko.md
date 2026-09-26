# 2026-09-27 Trixie 실내 GoTo: 솔빙 실패 시 IMU·마운트 전환

## 환경과 요청

Raspberry Pi 5 / Debian 13.7 Trixie / Python 3.13.5에서 OnStepX 제어 포트를
USB 시리얼 115200 baud로 연결한 실내 테스트다. 실내에서 별이 보이지 않아
솔빙 실패는 정상이다. 사용자는 솔빙 실패 시 IMU로 마운트를 정렬하고
마운트 자체 GoTo·추적을 계속하며, 솔빙 복구 시 기존 GoTo·미세보정으로
복귀하도록 요청했다. 추적 중 실패·복구가 반복되어도 동일하게 동작해야 한다.

기존 동작은 최초 GoTo에 최근 솔빙을 필수로 요구했고, 이동 후에는 솔빙을
계속 기다렸다. 실제 상태는 `pifinder_goto_blocked`였다. IMU 샘플은 유효했지만
IMUPLUS / `uses_magnetometer=false` / 수동 정렬 없음이므로 좌표 서비스는
절대 방위로 채택하지 않았다. 사용자는 **현재 IMU 표시 좌표를 실내 테스트의
임시 기준으로 사용**하도록 명시적으로 선택했다.

## 변경 동작

- MFNavis 모드에서 최초 솔빙이 없으면 신선한 IMU 좌표로 검증된
  `sync_and_goto`를 요청한다. 기존 INDI 동기화 확인 절차를 통과해야 실제
  GoTo가 전송된다. 동기화 실패는 자동 재시도의 근거가 되지 않는다.
- IMU 좌표는 솔빙에 연결된 추정 좌표, 자기센서 또는 수동 정렬 기준 좌표를
  우선 사용한다. 정렬 전 상대 방위는 새 설정
  `indi_goto_allow_unaligned_imu=true`에서만 허용하며,
  동기화 이력의 `pointing_source=imu_provisional`로 구분한다.
- 이미 진행 중인 GoTo에서 솔빙이 실패하면 같은 마운트 이동을 이어간다.
  미세보정 중 실패하면 보정을 해제하고 IMU 또는 이미 정렬된 마운트 좌표를
  기준으로 마운트 GoTo를 진행한다. 두 좌표 모두 사용할 수 없으면
  추가 이동을 보내지 않고 좌표 복구를 기다린다.
- 목표 도착 후에는 마운트 자체 추적을 유지한다. 솔빙 실패만으로 반복적인
  Sync·GoTo·추적 토글 명령을 보내지 않는다.
- 새 솔빙이 복구되면 마운트 정지 이후에 얻은 결과인지 확인하고 동일 목표로
  정상 Sync+GoTo → 도착 오차 측정 → 미세보정 → 최종 Sync를 다시 진행한다.
  이전 솔빙, 이동 중 솔빙, 단순 IMU 갱신은 복귀를 허용하지 않는다.
- `last_solve_attempt` / `last_solve_success`를 좌표 메타데이터에 전달해
  정상 솔빙 사이의 IMU 갱신과 실제 솔빙 실패를 구별한다. 성공 시각이
  12초 이상 갱신되지 않는 경우도 솔빙 사용 불가로 판단한다.
- 이 전환은 승인된 MFNavis GoTo의 수명 동안 동작하며, 지속적인 펄스 보정용
  Tracking Guide 체크박스를 꺼도 유지된다. INDI Mount / Off 모드에서는
  이 자동 복귀를 시작하지 않는다.
- Stop, 목표 해제·교체, 수동 이동, 주차, 추적 Off, 모드 변경, 마운트 제어 Off는
  이전 목표의 자동 복귀를 취소한다. 복구 GoTo에는 기존 목표 고도 제한을 적용한다.
- 웹 INDI GoTo / Guide 설정에 임시 IMU 기준 옵션과 한국어 설명을 추가했다.
  기본값은 Off다. 실내 테스트가 끝나면 해제해야 한다. 임시 기준은 실제 천체
  위치를 보장하지 않으며, 일반 좌표 서비스의 절대 방위 판단은 바꾸지 않는다.

## 검증 범위

모의 큐·마운트 상태·솔빙 시각으로 최초 실내 GoTo, 검증 응답 대기/실패,
GoTo·미세보정·추적 중 솔빙 상실, 반복 복구, 정지 후 새 솔빙 요구,
오래된/미래/비정상 좌표 차단, 수동 제어 우선, 설정 저장을 검사했다.
실제 장비에 에이전트가 추가 이동 명령을 보내지 않았다.
실제 별을 이용한 복구 및 도입 정확도 검증은 실내에서 수행할 수 없다.

전체 회귀 테스트와 실제 서비스 적용 결과는 아래에 기록한다.

### 자동 검증 결과

- 전체: **3,595 passed / 3 skipped**, 20 warnings, 224.46초, 종료 코드 0.
- 마지막 취소 동작 보완 후 GoTo/솔빙 전환 테스트: **128 passed**.
  이 중 솔빙 전환 전용 파일은 47개 시나리오(매개변수 조합 포함)다.
- 좌표 서비스·웹 설정·마운트 실행기·LCD 관련 묶음: **402 passed**.
- Ruff 검사 및 포맷 검사: 통과, 407개 파일. 한국어 `.mo` 재컴파일 완료.
- Graft 로컬 인덱스 갱신 완료.
- 전체 실행에서는 Selenium 웹 테스트 및 하드웨어 import가 필요한
  `test_imu_runtime.py`를 제외했다. IMU 드라이버 자체는 이번 변경 대상이 아니다.

전체 실행 명령(`python/`에서):

```sh
../.venv-dev-trixie/bin/python -m pytest tests \
  --ignore=tests/website --ignore=tests/test_imu_runtime.py -q --tb=short \
  --junitxml=/home/mfnavis/trixie-fixed-cloudy-20260926/fixes/solve-fallback-final.xml
```

전체 실행 후 추가한 추적 Off/취소 경계 사례 4개와 최종 변경은 관련 테스트
128개를 다시 실행해 검증했다. 로그/XML 및 설정 백업은 장비 로컬
`/home/mfnavis/trixie-fixed-cloudy-20260926/fixes/`에 보관하며 저장소에는 넣지 않는다.

### 실제 상태를 이용한 비동작 검증

실제 `/dev/shm/mfnavis/`의 최신 IMU·마운트 상태를 읽되, 실행기가 연결되지
않은 로컬 큐로만 GoTo 처리를 호출했다. 결과는 `phase=native_goto`,
`source=imu_provisional`, `type=sync_and_goto`, `origin=imu_goto_fallback`이었다.
이 검증에서 마운트로 전송한 이동 명령은 없다.

### 서비스 적용

2026-09-27 **01:19:18 KST**에 기존 허용 명령
`sudo -n /usr/bin/systemctl --no-block restart mfnavis.service`로 적용했다.
서비스는 active/running, PID 152957, NRestarts 0이었다.

- 사용자 선택에 따라 실제 설정의 `indi_goto_allow_unaligned_imu=true` 적용.
- MFNavis GoTo 모드 유지. Tracking Guide는 기존 Off 설정 유지.
- OnStepX 연결 정상, 이동 없음, 추적 Off, 펄스 보정 Off 유지 확인.
- 새 서비스는 `idle`, 자동 복귀 미설정 상태로 시작했다. 이전에 거절된
  GoTo를 재기동 후 자동 실행하지 않는다. 웹 새로고침 후 사용자가 다시
  GoTo를 누르면 새 전환 절차로 시작한다.

재기동 로그에는 초기 INDI 속성 조회 시 `Could not find property` 메시지
11건이 있었고 마지막 발생은 01:19:28 KST였다. 이후 확인 시 연결 상태는
정상이었고 Python 예외/ERROR 로그는 없었다. 이는 실제 GoTo 전송 성공이나
실외 솔빙 복구를 검증한 것으로 해석하지 않는다.
