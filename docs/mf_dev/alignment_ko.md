# 정렬·Sync·백레시 측정

기준: 2026-10-10 작업 트리. 일반 광학 정렬, 다중 정렬과 백레시 측정을 구분한다.
GoTo 중 솔빙이 없는 사용자의 도착 확인은 [마운트 제어](mount_control_ko.md)의
`arrived_waiting_solve` 전이를 따른다.

## 일반 정렬과 솔빙 없는 도착 확인

정렬은 사용자가 선택한 기준과 광학 target pixel을 연결하는 작업이다.
IMU/마운트 추정 좌표를 새 광학 관측으로 바꾸지 않는다.
진행 중인 GoTo에서 솔빙이 없을 때 LCD Align 또는 SkySafari Align을 받으면,
수동으로 도착했다는 의도를 저장하고 마운트 추적으로 기다린다.
정렬 확인과 이동 종료 이후의 첫 유효 solve로 실제 추적 타겟을 고정한다.

## 다중 정렬

`MultiPointAlignController`는 선택한 별, 이동 여부, 확인한 포인트와 세션 상태를
공통으로 관리한다. LCD와 웹은 이 컨트롤러를 사용하며, 세션 중 SkySafari Sync는
다중 정렬 확인 명령으로 라우팅한다. 별 이동은 GoTo, 중심 맞추기는 사용자 조그,
포인트 확정은 별도 확인 명령이다. 실제 정렬 모델 기록은 OnStep/INDI 실행 경로가 담당한다.

신뢰 가능한 관측지·시각과 mount Sync 결과를 확인한 뒤 정렬을 시작한다.
멀티 포인트 정렬은 일반 site/time 초기화보다 시각 신뢰 조건이 엄격하다.
별 선택 고도 범위는 관측 편의 조건이며 드라이버의 물리 이동 한계와 별개다.
정렬 세션 취소, GoTo 취소, 축 Stop의 의미를 서로 바꾸지 않는다.

## 백레시 자동 측정

`BacklashCalibrationMixin`은 RA/DE 설정 조회·저장과 왕복 이동 측정을 담당한다.
내부 호환 모드 이름은 `compass_goto_loop`지만 측정 기준은 최근의 실제 solved 좌표다.
IMU 또는 mount fallback 좌표로 백레시 값을 확정하지 않는다.

시작 기준 solve → 허용된 축 목표 생성 → INDI GoTo → 이동 완료 후 새 solve 대기 →
왕복 기록 → 방향별 분석 순서로 진행한다. solve가 오래됐거나 없으면 측정 대기/실패로
처리한다. Auto Backlash는 `GUIDE_RATE` 변경이나 timed guide 펄스로 측정하지 않는다.
사용자 취소와 한계 정지는 다음 이동보다 먼저 처리한다. 기록과 추천값을 확인한 뒤
장치 설정에 반영하며, 하드웨어가 다른 경우 이전 장비의 측정값을 복사하지 않는다.

LCD Backlash 화면은 `+` RA 선택, `-` DE 선택, 숫자 입력, `0` 입력 지우기,
Right 자동 측정, Square 저장이다. 공통 마운트 키맵과 별도의 입력 화면이다.

## 소스와 검증 근거

- [다중 정렬 세션](../../python/MFNavis/indi_multipoint_align.py), [마운트 실행기](../../python/MFNavis/mountcontrol_indi.py).
- [백레시 측정](../../python/MFNavis/indi_backlash_calibration.py), [INDI 화면](../../python/MFNavis/ui/indi.py).
- [정렬·추적 회귀](../../python/tests/test_alignment_tracking_flow.py), [마운트 회귀](../../python/tests/test_mountcontrol_indi.py).

이전 단계별 순서도·장비별 측정 기록은 [마운트 이력](../history/development/mount.md)에 보관했다.
새 기능 변경 시 실제 장치의 모델 기록과 축 이동을 별도로 검증한다.
