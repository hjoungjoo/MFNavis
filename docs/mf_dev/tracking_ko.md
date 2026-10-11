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

솔빙 실패 프레임의 별 대응으로 상대 이동을 측정하고 기본 추적 보정에 연결하는
후속 설계는 [별 영상 기반 상대 추적](solver_ko.md#솔빙-실패-시-별-영상-기반-상대-추적-개발-설계)을 따른다.
이 통합 설계는 미구현이며 현재 visual shadow의 운영 제어권을 변경하지 않는다.

## Smooth와 상대 영상 추적의 통합 계획

2026-10-11 사용자 요구 반영. **기본 GoTo와 추적 보정 수정이 끝난 뒤 진행할
후속 작업**이다. 현재는 요구사항만 기록한다. 운영 코드 통합, INDI 화면 이동,
설정 변경은 아직 수행하지 않으며 추가 테스트·검증은 사용자가 요청할 때 진행한다.
기본 작업이 끝났다는 추정만으로 통합이나 장비 시험을 자동 시작하지 않는다.

기존 Smooth에는 실제 보정 실행 경로가 있다. 이번에 작성한
`benchmark_visual_fallback.py`와 `benchmark_weak_star_fallback.py`는 오프라인
시험 코드다. 같은 목적의 경로를 별도 제품 기능으로 늘리지 않고, 기본 GoTo/Guide의
완료된 수명주기에 기존 Smooth의 영상 측정·실행 경로와 필요한 시험 결과를 통합한다.

### 통합 범위

- 기존 Smooth의 장비 응답, 관측 시각·품질 검사, 보정 실행과 제어권 관리를
  재사용한다. 진행 중인 기본 GoTo/Guide 수정 결과를 먼저 확인해 중복 상태기계,
  이중 보정, 잘못된 기준점 전환을 정리한다.
- 무솔빙 GoTo 대기 중 Align을 받으면 사용자 도착 확인으로 처리하고,
  이동 종료·정착 이후 현재 영상 위치를 기준으로 보정한다. 첫 유효 솔빙이
  복구되면 그 실제 좌표를 한 번만 추적 타겟으로 채택한다. 자세한 계약은
  [솔빙 실패 상대 추적 설계](solver_ko.md#무솔빙-goto-대기-중-정렬-처리)를 따른다.
- 별이 적고 희미한 환경을 주 사용 조건으로 삼는다. 시험한 로컬 ROI 탐색,
  별 분포·모양 검사와 짧은 영상 누적을 통합 후보로 삼되, 시험용 전체 영상
  복사나 최소 별 수·SNR 값을 그대로 운영 경로에 옮기지 않는다. 기존 ROI 전달과
  검출 결과를 재사용하고 누적 관측의 실제 시각을 보존한다.
- 불필요하거나 목적과 충돌하는 설정·동작은 정리한다. 영상이 불충분하면
  보정을 보류하며, Stop·새 GoTo·반복 Align과 솔빙 복구의 처리 소유자는 하나로 한다.
  달·행성 등 기존 지원 기능은 공통 타겟 처리와의 호환성을 확인한다.

### INDI 화면과 최소 설정

통합 시 현재 **Smooth optical tracking 영역을 INDI 페이지의 마지막 기능 영역으로
이동**한다. 기본 GoTo와 추적 조작 흐름을 먼저 배치한다.

일반 화면에는 영상 추적 보정의 사용/해제 설정과 현재 상태·대기 이유를 중심으로
남긴다. 타겟 좌표·천체 종류·정렬은 기존 GoTo/Align 정보를 재사용하고 같은 값을
다시 입력하게 하지 않는다. 시작·중지는 기존 추적 조작과 연결해 중복 버튼을 정리한다.
사용 설정 자체가 새 GoTo나 캘리브레이션 이동을 시작해서는 안 된다.

현재의 Off/Shadow/Active 선택, 별도 타겟 통합 체크박스, RA·Dec 재입력,
장비 프로필 JSON 업로드·다운로드, 캘리브레이션은 일반 사용 화면에서 요구하지 않는
방향으로 정리한다. 필요한 개발·장비 설정은 별도 진단 경로로 분리한다.
장비 응답과 광학 정보의 유효성 검사는 유지하고, 준비되지 않았으면 필요한 조치를
상태로 표시한다. 설정 단순화를 위해 미검증 값을 자동 승인하지 않는다.

표시 상태는 솔빙 기반 보정, 영상 기반 보정, 영상 부족 대기, 사용자 중지를
구분한다. 세부 별 수·오차·거부 원인은 진단 정보로 제공한다.
이 절은 후속 화면 설계이며 현재 웹 UI가 이미 바뀌었다는 뜻은 아니다.

## 구현과 회귀

- [Smooth runtime](../../python/MFNavis/smooth_tracking_runtime.py), [허가 계약](../../python/MFNavis/tracking_contracts.py).
- [Visual shadow](../../python/MFNavis/visual_tracking_runtime.py), [영상 측정](../../python/MFNavis/visual_tracking_images.py).
- [Smooth runtime 검사](../../python/tests/test_smooth_tracking_runtime.py), [제어권 전환](../../python/tests/test_smooth_tracking_handover.py).
- [타겟 통합](../../python/tests/test_tracking_target_integration.py), [Visual 환경 검사](../../python/tests/test_visual_tracking_runtime.py).

과거 현장 프로파일과 측정 결과는 [실측 보고서](../mf_report/README.md)를 따른다.
특정 장비의 프로파일을 다른 장비의 응답 보증으로 사용하지 않는다.
