# 추적 제어의 종류와 소유권

기준: 2026-10-10 작업 트리. 아래 세 경로의 구현 상태를 구분해서 읽는다.

| 경로 | 구현과 시작 조건 | 솔빙/영상 소실 시 정책 |
|---|---|---|
| 기본 Tracking Guide | MFNavis GoTo/Guide 상태기계, 사용자 설정에 따라 활성 | 광학 도착 후 `GuideHoldover`; 기본 동작은 [GoTo 문서](mount_control_ko.md) |
| smooth tracking | `shadow`와 `active` 구현, MFNavis 모드·검증된 프로파일 등 조건 확인 | 관측 품질·허가 lease·검증된 coast 조건에 따라 별도 판정 |
| visual tracking 시험 | 확인된 환경의 `shadow`만 허용 | 별도 세션의 예측·재획득을 기록; 운영 마운트 보정 연결 없음 |

## 기본 추적 보정

네이티브 마운트 추적과 MFNavis의 추가 보정은 별개다. 기본 경로의 솔빙 실패 두 경우,
수동 이동과 사용자 정렬, 무기한 대기, 마지막 잔량과 표류 보정, 솔빙 복구는
[마운트 제어 기준 문서](mount_control_ko.md)에 하나의 상태기계로 정의했다.
별도 추적 방식의 품질 조건을 이 기본 경로의 실패 타이머로 사용하지 않는다.

## Smooth tracking

`smooth_tracking_runtime.start_session()`이 세션·타겟·광학 identity·연결 epoch·
제어 epoch·장비 응답 프로파일을 고정한다. `active` 시작은 검증된 응답/시각 프로파일을
요구하며, 명시적 펄스 캘리브레이션은 별도의 equipment/timing/Stop 검증 조건을 따른다.
`shadow`는 관측과 제안값을 비교하는 경로다. 기본 설정은 `mode=active`이지만
프로파일 기본값은 빈 객체여서 설정 문자열만으로 실장 보정이 승인되지 않는다.

`tick_policy()`는 관측·fault·신선한 mount 상태·Tracking On·비주차·비이동·
같은 연결 epoch를 확인한 뒤 짧은 `TrackingPermission`을 부여한다.
실행기는 각 패킷에서도 광학 나이와 드라이버 상태를 재확인한다.
active 세션이 제어권을 가지는 동안 기존 guide가 동시에 보정하지 않는다.
제어 epoch 변경은 사용자 명령으로 세션을 중지하고, 예전 허가를 재사용하지 않는다.

타겟 통합은 `smooth_tracking_target_integration_enabled=false`가 기본이다.
통합을 켜면 기존 천체 identity/에페메리스를 사용하고 RA·Dec 시간 변화를 반영한다.
통합 세션의 axis/GoTo recovery는 꺼지며 임의의 회복 슬루를 보내지 않는다.
coast는 확인된 프로파일과 허용된 관측 소실 사유가 있는 경우에만 승인한다.
모든 smooth timed pulse에도 공통 이동 한계 인터록이 적용된다.

## Visual tracking 시험과 후속 설계

`visual_tracking_runtime.read_manifest()`는 `schema=1`, `mode=shadow`,
장비 확인, Alt/Az 또는 EQ, camera/lens/calibration identity, RAW 크기와
roll 확인, 만료 시각, 최대 프레임 수, 별도 절대 출력 경로를 검사한다.
달 직접 측정은 독립적으로 확인한 원반 반지름이 필요하다. 같은 프레임의 RAW와
검출·메타데이터를 pairing하며, 환경 파일만으로 실장 검증 완료를 선언하지 않는다.
[환경 예제](visual_tracking_environment.example.json)는 실제 장비 값으로 확인해야 한다.

달 근접 stage GoTo 제안, 라이브 스택 안정화 조사, 과거 visual 전체 설계의
미완료 단계는 일반 GoTo에 이미 구현된 기능으로 설명하지 않는다.
미구현안의 세부와 trial/demo/replay 절차는 [마운트 이력](../history/development/mount.md)을 참조한다.

## 구현과 회귀

- [Smooth runtime](../../python/MFNavis/smooth_tracking_runtime.py), [허가 계약](../../python/MFNavis/tracking_contracts.py).
- [Visual shadow](../../python/MFNavis/visual_tracking_runtime.py), [영상 측정](../../python/MFNavis/visual_tracking_images.py).
- [Smooth runtime 검사](../../python/tests/test_smooth_tracking_runtime.py), [제어권 전환](../../python/tests/test_smooth_tracking_handover.py).
- [타겟 통합](../../python/tests/test_tracking_target_integration.py), [Visual 환경 검사](../../python/tests/test_visual_tracking_runtime.py).

과거 현장 프로파일과 측정 결과는 [실측 보고서](../mf_report/README.md)를 따른다.
특정 장비의 프로파일을 다른 장비의 응답 보증으로 사용하지 않는다.
