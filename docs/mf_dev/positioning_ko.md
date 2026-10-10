# 포인팅 좌표·IMU·외부 좌표 계약

기준: 2026-10-10 작업 트리. 용어는 [Positioning CONTEXT](../ax/positioning/CONTEXT.md)를 따른다.
`PointingCoordinateService`는 solve, IMU, mount 샘플의 유효성·시각·정렬 상태를
평가해 `CoordinateState`를 만든다. 표시 좌표와 제어에 쓸 광학 관측을 구분한다.

## 좌표 선택 순서

1. 유효한 solved 샘플이 있으면 우선한다.
2. 정렬된 유효 mount 샘플이 있으면 mount readback을 사용한다. 정지 상태에서
   허용된 IMU delta가 있으면 mount+IMU 융합을 시도한다.
3. 유효한 IMU만 있으면 provisional 포인팅으로 표시할 수 있다. 자력계 기준이나
   세션 정렬이 없는 startup heading은 절대 제어 앵커로 승인하지 않는다.
4. 정렬되지 않은 mount readback만 있거나 모든 후보가 무효면 명확한 이유를 남긴다.

GoTo·수동 이동·펄스·정착 중에는 mount readback이 우선하며 마운트 자신이 만든
움직임을 IMU 외란으로 다시 누적하지 않는다. 이미 누적된 외란 오프셋은 유지하면서
그 구간의 추가 누적만 중지한다. 장소·광학·정렬 기준 변경은 관련 앵커와 이력을
정책에 따라 초기화한다.

## 관측과 추정

`pointing.aligned.solve`는 실제 광학 관측, `pointing.aligned.estimate`는
IMU 진행을 포함하는 포인팅이다. 화면이나 카탈로그의 “현재 위치”가 유효하더라도
정지 이후의 새 solve가 있다는 뜻은 아니다. GoTo 도착·백레시 측정·광학 Sync는
각 작업의 신선도·품질·이동 종료 조건을 별도로 확인한다.

RAW, centroid, 메타데이터는 같은 frame ID를 사용하고 노출 종료 시각으로 평가한다.
비동기 전처리 결과를 게시할 때도 같은 관측의 현재 조건과 generation을 검증한다.
새로운 솔빙 성공 시각을 예측이나 외부 Sync로 갱신하지 않는다.

## IMU와 정렬

IMU는 이동 감지와 dead reckoning을 담당한다. BNO055의 세션 heading과
자력계 사용 여부, 캘리브레이션, 실제 센서 timestamp를 함께 평가한다.
자력계 사용으로 생길 수 있는 국부 자기장 영향을 광학 관측으로 가려내야 한다.
현재 구현의 자세 처리와 자기 드리프트 개선 검토는 [포인팅 이력](../history/development/positioning.md)에 보관했다.
이력에 있는 특정 장비의 유효 설정을 제품 기본값으로 복사하지 않는다.

## 외부 좌표와 상태

`pos_server.py`의 좌표 서비스 루프는 reset 요청, 장소 변경, 시간 점프 및
신뢰 전이를 처리하고 상태를 갱신한다. SkySafari/LX200와 Stellarium은 각 프로토콜의
좌표 frame을 유지한다. 내부 RA/Dec 도수와 프로토콜 표현 단위를 섞지 않는다.
카탈로그 “근처” 탐색은 명시적으로 표시된 IMU fallback을 쓸 수 있지만
그 좌표를 mount Sync의 유효 solve로 바꾸지 않는다.

선택한 `utils.runtime_dir/pointing_coordinate_status.json`의 `current`, `solved`,
`imu`, `mount`, `selected_source`, `health`, `updated`를 함께 확인한다.
GoTo/Guide 서비스는 파일 신선도와 샘플 신선도를 각각 확인한다.

## 소스와 검증

- [좌표 서비스](../../python/MFNavis/pointing_coordinate_service.py), [Integrator](../../python/MFNavis/integrator.py), [외부 프로토콜](../../python/MFNavis/pos_server.py).
- [좌표 선택 검사](../../python/tests/test_pointing_coordinate_service.py), [드리프트 검사](../../python/tests/test_integrator_drift.py).
- [LX200 검사](../../python/tests/test_pos_server.py), [Stellarium 검사](../../python/tests/test_pos_server_stellarium.py).

도착 이후 실제 추적 타겟 고정과 솔빙 소실 처리의 기준은 [마운트 제어](mount_control_ko.md)다.
