# 정지 상태 IMU GoTo 차단 수정 — 2026-09-29

## 확인된 원인

운영 로그에서 `MFNavis GoTo requires a recent plate solve`와 12초 대기 후
취소가 반복됐다. 같은 세션에서 실제 이동 직후에는
`Native GoTo fallback started (source=pifinder_imu_estimate)`가 기록됐다.

정지 상태에서는 IMUPLUS 드리프트 억제를 위해 추정 좌표와 `estimate_time`을
유지한다. IMU 센서 샘플은 계속 갱신되지만 GoTo는 좌표의 오래된 시각만
검사해 기존 솔빙 기준 IMU 좌표를 거절했다. 운영 설정에서 첫 솔빙 전 임시
IMU 사용도 꺼져 있어 최근 솔빙이 없으면 두 경로 모두 막혔다.

## 변경

- integrator가 기존 솔빙 기준 추정 좌표를 확인한 IMU 샘플 시각을
  `imu_observed_time`으로 별도 기록한다. 정지 중에는 최대 초당 한 번 게시한다.
- 좌표, `estimate_time`, 카메라 솔빙 성공 시각은 유지한다. 원시 IMU 수신이나
  좌표 서비스 상태 파일 갱신만으로 오래된 좌표를 유효하게 만들지 않는다.
- GoTo는 최근 integrator 확인 시각이 있는 기존 솔빙 기준 좌표를 IMU
  fallback으로 사용한다. 이를 새 솔빙으로 취급하거나 광학 복귀에 사용하지 않는다.
- 최초 GoTo 대기 중 IMU가 회복되면 같은 요청에서 다시 판단한다.
  기존 만료·수동 취소·마운트 이동·주차 조건은 유지한다.
- 사용자가 첫 솔빙 전 임시 IMU 사용을 선택해 운영 설정의
  `indi_goto_allow_unaligned_imu=true`를 저장했다. 기본 설정은 변경하지 않았다.

## 검증

관련 테스트 **469 passed**, Ruff 검사·포맷 검사 통과.
integrator의 실제 루프에서 솔빙 실패·정지 IMU·센서 오류를 재생하고 게시된
시각이 좌표 서비스와 GoTo fallback까지 전달되는지 확인했다.
오래된/미래/비정상 확인 시각 차단, 센서 갱신 중단, 카메라 복구와 구별,
대기 중 IMU 회복, 기존 마운트 실행기·추적·표시·텔레메트리 회귀도 포함한다.

```sh
source scripts/activate_dev_trixie.sh
python -m pytest tests/test_indi_solve_fallback.py \
  tests/test_indi_goto_guide_service.py tests/test_integrator_drift.py \
  tests/test_pointing_coordinate_service.py tests/test_telemetry.py \
  tests/test_display_pointing.py tests/test_mountcontrol_indi.py -q --tb=short
```

실제 마운트 이동과 천체 도입 정확도는 자동 테스트의 검증 범위에 포함되지 않는다.

## 운영 적용

이동 없음·활성 목표 없음 확인 후 `mfnavis.service`를 재시작했다.
확인 상태는 active/running, PID 20623, NRestarts 0, OnStepX connected였다.
첫 솔빙 전 임시 IMU 옵션의 런타임 반영도 확인했다.

재시작 후 실제 상태 파일을 읽고 마운트와 연결되지 않은 로컬 큐에만
GoTo를 모의 실행했다. `phase=native_goto`, `type=sync_and_goto`,
`origin=imu_goto_fallback`, `pointing_source=imu_provisional`을 확인했다.
이 검증에서 실제 마운트 이동 명령은 전송하지 않았다. 사용자가 새 GoTo를
요청하면 적용된 경로를 사용한다.
