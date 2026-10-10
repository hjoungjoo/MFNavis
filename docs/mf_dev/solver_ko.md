# 현재 솔빙·MFDS·전처리 설계

기준: 2026-10-10 작업 트리. 별 검출과 패턴 솔빙, 관측 승인과 포인팅 갱신을 구분한다.
검출 후보가 충분하거나 Tetra3 패턴이 일치해도 좌표를 즉시 제어에 사용할 수 있는 것은 아니다.

## 검출기와 실행 방식

현재 주 검출기는 MFDS 고정 바이너리 릴리즈다. `python/MFDS`와
`deployment/mfds.lock.json`을 통해 배포하며 MFDS 소스는 별도 저장소에서 관리한다.
기본 transport는 상주 native worker 프로세스와 전용 memfd 메모리다.
Cedar 서버나 Cedar systemd unit을 설치·기동하는 옛 설계는 현재 경로가 아니다.
`MF_DETECT_TRANSPORT=ctypes`는 명시적인 비교 모드이고 프로세스 오류 시 자동 전환하지 않는다.
[패키지 관리](../MFDS_BINARY_DISTRIBUTION_ko.md), [검출기 통합](../DETECTOR_INTEGRATION_ko.md)을 참조한다.

## 프레임 처리와 마지막 SEP 복구

카메라 RAW와 메타데이터 → MFDS 검출 → 중앙/전체 후보의 Tetra3 패턴 탐색 →
필요한 동일 관측 전처리 복구 → 광학 품질·좌표 연속성 승인 → `SuccessfulSolve` 게시 순서다.
센서 전체 공간과 표시 크롭 공간은 `solver_frame_map.py`로 변환한다.
RAW·전처리·검출 좌표·관측 시각의 대응을 유지한다.

MFDS 패키지의 검출 수준 보조 정책과 MFNavis의 **최종 SEP 솔빙 복구**는 별개다.
현재 `_solve_sep_emergency()`는 MFDS 주요 솔빙 경로 실패 뒤 동일 frame ID의
신선한 RAW에 한해 마지막 복구를 시도한다. 승인 대기 중인 MFDS 후보는 실패로
취급하지 않는다. 이동 중이거나 주요 경로가 완료되지 않은 경우 복구를 승인하지 않는다.
SEP 전처리/RAW 재시도는 추가 탐색 예산 1초를 공유하고 반복 실패는 backoff한다.
SEP 결과도 일반 광학 품질·연속성 검사를 통과해야 하며 임의의 좌표 점프를 게시하지 않는다.

## 동기·비동기 전처리

`solver_preprocess_mode=auto`가 기본, `sync`는 고정 동기 모드다.
시작과 RAW 실패 복구는 동기로 처리한다. RAW가 3프레임 연속 성공하면 비동기로 전환하고,
RAW 패턴은 풀려도 좌표 게시가 2회 연속 보류되면 다음 프레임을 동기 복구한다.
이동·광학·target pixel 변경과 정렬/캘리브레이션은 해당 이력과 generation을 초기화한다.

`LatestFrameWorker`는 실행 1개와 최신 대기 1개를 유지해 오래된 입력의 큐 누적을 막는다.
오래된 비동기 결과는 현재 프레임의 새 solve로 게시하지 않는다.
원본/전처리의 bias 보정은 대응 관측으로 학습하고 불일치나 기준 변경 시 초기화한다.

## 품질과 광학

이동 프레임 판정, false-solve 방어, `SolveContinuityGate`, optics/FOV 검증은
패턴 성공 이후의 승인 조건이다. 중앙/전체 프레임 솔빙과 centroid 왜곡 보정은 유지한다.
예전 Wide tiles·Edit exclusions UI/API·타일 복구 솔빙은 제거된 기능이며,
남아 있는 도우미 파일만으로 현재 서비스 경로에 연결됐다고 설명하지 않는다.
렌즈 측정과 활성 왜곡 프로파일은 [카메라·광학](camera_ko.md)을 따른다.

## 진단과 회귀

`utils.runtime_dir/solver_scheduling_status.json`에서 설정/실행 모드, 전환 이유,
frame ID·generation·처리 시간을 확인한다. 노출 시간, 계산 지연, 성공 관측 갱신 간격은
서로 다른 지표다. 전체 성능 비교에는 검출기 버전과 실제 실행 바이너리의 provenance를 포함한다.

- [솔버](../../python/MFNavis/solver.py), [스케줄러](../../python/MFNavis/solver_scheduling.py), [SEP 복구](../../python/MFNavis/sep_shadow.py).
- [스케줄링 검사](../../python/tests/test_solver_scheduling.py), [프레임 pairing](../../python/tests/test_solver_frame_pairing.py).
- [관측 승인](../../python/tests/test_solve_acceptance.py), [전처리 후보](../../python/tests/test_solver_preprocessed_candidates.py), [FOV 조건](../../python/tests/test_solver_optics_gate.py).

Cedar/SEP 조사·광각 타일 설계·전처리 초기 실험은 [솔빙 이력](../history/development/solver.md)에서
작성 당시의 근거로 읽는다. 현재 솔빙 실패의 마운트 동작은 [마운트 제어](mount_control_ko.md)를 따른다.
