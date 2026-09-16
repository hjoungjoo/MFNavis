# GOTO 이동 중 PUSH·SkySafari 표시 갱신 — 2026-09-17

## 증상과 범위

마운트 이동은 정상이나 PUSH의 남은 방향별 각도와 SkySafari 표시가 이동 도중
멈추고 다음 솔빙에서 갱신된다는 사용자 보고를 대상으로 한다. 실제 보고 구간의
IMU 로그를 재생한 결과는 아니므로 현장 정지 원인을 확정하지 않는다.

기존 integrator는 `imu.moving=False`이면 추정 좌표 갱신을 중단한다. PUSH는 이
좌표를 직접 읽고, 외부 좌표 서비스도 유효한 솔빙 기반 좌표를 우선 선택한다.
따라서 이동 감지가 꺼지는 저속 구간에서 표시가 정지할 수 있다.

## 변경

- `DisplayPointing`은 마지막 성공 솔빙의 카메라축·정렬축과 같은 노출의 IMU
  quaternion을 기준으로 표시 좌표만 예측한다.
- 5초 이내의 마운트 상태가 명령에 의한 이동을 보고하고 최신 IMU가 유효하면,
  `imu.moving`과 integrator의 각도 deadband에 관계없이 현재 자세를 반영한다.
- 정지·오래된 마운트 상태·IMU 이상에서는 새 예측을 중단한다. 마지막 표시
  위치는 유지하며, 더 새로운 integrator 추정이나 새 솔빙 결과로 갱신한다.
- 솔빙 기준, 정렬축 또는 화면 방향 변경과 좌표 서비스 Reset은 표시 캐시를
  초기화한다. 유효한 솔빙/IMU 기준이 없으면 기존 표시 경로를 사용한다.
- PUSH의 방향별 각도 계산에 표시용 solution을 전달한다. 마운트 명령에서 쓰는
  `_current_pointing_radec`와 shared solution은 변경하지 않는다.
- 좌표 서비스의 `display`는 별도 선택 필드다. SkySafari/LX200의 위치 응답만
  이 값을 선택하며 기존 equinox-of-date 변환을 유지한다. Stellarium은 기존
  catalog 좌표 규약을 유지한다.
- 상태 파일의 `current`·`solved` 및 서비스의 `radec()`는 기존 제어 좌표를
  유지한다. 진단용 `display` 필드만 추가한다. 가이드가 읽는 좌표를 표시
  예측으로 대체하지 않는다.

## 검증

관련 자동 테스트 **303개 통과**, 변경 Python 파일 Ruff 검사·포맷 검사 및
`git diff --check` 통과. 새 회귀 테스트는 14개다.

검증 범위: moving=False인 저속 이동, 정지·실패 솔빙 후 표시 유지, 새 솔빙
복귀, stale/invalid IMU 및 상태 차단, anchor 소실/Reset, EQ·Alt/Az의 PUSH와
외부 표시 좌표 일치, SkySafari/Stellarium 좌표 변환, 상태 파일의 제어 좌표 보존.

```bash
cd /home/pifinder/PiFinder/python
.venv/bin/python -m pytest -q \
  tests/test_display_pointing.py tests/test_pos_server.py \
  tests/test_pos_server_stellarium.py tests/test_pointing_coordinate_service.py \
  tests/test_calc_utils.py tests/test_alignment_tracking_flow.py \
  tests/test_integrator_drift.py tests/test_pointing_arrows.py
```

소스 수정과 자동 검증만 수행했다. 서비스 재시작과 실제 마운트 이동 검증은
수행하지 않았다. 실제 적용 후에는 GOTO 감속 구간의 PUSH 각도·SkySafari 이동,
정지 후 표시 유지 및 새 솔빙 복귀를 확인해야 한다.
