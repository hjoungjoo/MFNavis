# 광각 렌즈 솔빙 — 단계별 구현 및 병합 계획

> **2026-09-22 기능 제거:** Wide tiles·Edit exclusions UI, 관련 API·설정 및 타일
> 복구 솔빙을 제거했다. 아래 내용은 이전 설계·운영 기록이다. 일반 중앙/전체 프레임
> 솔빙, 렌즈 왜곡 보정과 저장된 검증 데이터는 유지한다.

> 상태: **P6 야간 실측 진행 중**. P1(렌즈/수동 초점거리), P2의 TV 기본
> profile 영속 저장과 centroid-space Brown--Conrady 보정, P3의 순수 512² tile
> planner, P4의 LiveCam tile 표시·타일 단위 제외 저장, P5의 중앙→주변 타일
> 실행·광학중심 좌표 환산·합의까지 구현됐다. 다각형 마스크와 자동 실측 계수의
> 2026-08-25 첫 6mm 실측으로 타일 변을 640px로 확정했으며, 주변 합의와 왜곡 계수의
> 최종 승격은 추가 야간 실측/디버깅 단계(P6)에서 확정한다. 상세 구조의 정본은
> [광각 렌즈 다중 구역 솔빙 및 왜곡 보정 설계](mf_wide_angle_solver_design_ko.md)다.
> 이 문서는 구현 순서·커밋 경계·승인 조건만 소유한다.

## 1. 범위와 비범위

범위는 4/6/8/10 mm 렌즈 선언, 실측 왜곡 보정, 16 mm 등가 원본 크롭 타일,
중앙 포화 때의 다중 타일 합의, LiveCam 제외 영역의 영속 저장이다.

이번 프로젝트에서 하지 않는 일은 다음과 같다.

- 기존 16 mm solver, 정렬, SQM 보정값을 광각 구현과 함께 재조정하는 일
- 일반 관측 중 렌즈/FOV/왜곡 계수의 자동 추정·자동 config 덮어쓰기
- 단일 주변부 타일 해로 포인팅·정렬을 갱신하는 일
- 전체 광각 RAW를 축소하여 한 번에 솔브하는 일

## 2. 구현 단계

| 단계 | 산출물 | 기본 동작 영향 | 완료/다음 단계 진입 조건 |
| --- | --- | --- | --- |
| P0 | 이 설계·계획 문서, 기존 테스트/좌표계 인벤토리 | 없음 | 사용자 승인 |
| P1 | `4/6/8/10mm` Lens 선언, UI 메뉴, provisional 상태 표시·단위 시험 | 없음; 새 렌즈를 골라도 기존 solver | 기존 optics/UI/SQM 회귀 통과 |
| P2 | `mf_wide_calibration.py`, TV distortion 수동 입력/작은 센서 반경 환산, 영속 profile store/fingerprint 검증, native centroid-space Brown--Conrady 보정, REST 설정/상태 API | `wide_solver_enabled=false`일 때 없음 | 수동 TV profile 재부팅 복원·실측 자료로 자동 revision/검증된 0 보정 profile 확정 |
| P3 | rectified canvas·`TilePlanner`·최소 512² 원본 정사각 크롭/좌표 map, shadow 진단 | `wide_solver_enabled=false` | synthetic WCS와 tile 좌표 왕복 시험 |
| P4 | LiveCam tile 레이어·타일 단위 제외 UI/API/config 영속(다각형 편집은 후속) | solver 선택에는 아직 미반영 | 재부팅 복원, invalid tile/API 회귀 |
| P5 | 타일 Cedar→SEP 실행, 중앙 포화 판단, consensus 모듈 | opt-in 시 기존 `SuccessfulSolve` 하나로 어댑트 | 타일별 timeout 격리·인접 2-타일 엄격 일치·3개 이상 outlier 제거 자동 시험 |
| P6 | 야간 shadow 관측, 수치 확정, 선택 렌즈의 opt-in activation | 활성 렌즈만 변경 | 3개 독립 밤·중앙/달/마스크 시나리오 통과 |
| P7 | 문서·사용자 가이드·릴리스 노트, 필요 시 default 정책 검토 | 명시적 승인 전 기본 off | 롤백·운영 절차 검토 완료 |

P1–P5는 각각 독립 커밋/PR 단위로 유지한다. P6의 야간 실측 결과와 feature flag
전환은 코드 구현 커밋과 섞지 않는다. 문제가 나면 해당 단계만 revert하거나
`wide_solver_enabled=false`로 즉시 런타임을 차단할 수 있어야 한다.

## 3. 파일별 예상 변경

| 위치 | P1 | P2–P3 | P4 | P5 |
| --- | --- | --- | --- | --- |
| `python/PiFinder/optics.py` | 렌즈·상태 메타데이터 | calibrated focal FOV 해석 | - | policy 조회만 |
| `python/PiFinder/lens_calibration.py` | - | 신규: 모델/profile/remap/fingerprint | - | 좌표 변환 제공 |
| `python/PiFinder/mf_wide_tiles.py` | - | 신규: 512² tile plan·crop map | tile plan 직렬화 | solver 입력 |
| `python/PiFinder/mf_wide_consensus.py` | - | - | - | 신규: 후보 합의 |
| `python/PiFinder/mf_livecam_tiles.py` | - | LiveCam용 논리 셀/overlap payload | tile 제외 profile 직렬화 | solver가 제외 정보 소비 |
| `python/PiFinder/solver.py` | flag/config 읽기만 | shadow geometry | 상태 진단 게시 | 중앙→주변 상태기계 |
| `python/PiFinder/state.py` | - | tile diagnostics 저장소 | mask revision/overlay | consensus 진단 |
| `python/PiFinder/livecam_config.py` | - | - | mask schema/normalizer | - |
| `api_extensions.py`, `raw_live_stack.py`, `views/livecam.html` | - | - | 편집·오버레이 | tile 결과 색상 |
| `python/tests/` | lens/UI | calibration/tile | API/LiveCam | solver/consensus/integration |

기존 `solver_frame_map.py`의 512↔풀프레임 계약은 수정하지 않는다. 광각 타일의
새 변환은 별도 `TileCoordinateMap`으로 작성해, 현행 full-frame 경로와의 회귀
위험을 격리한다.

## 4. 사전 자료 수집

P2 전에 렌즈별로 다음을 기록한다.

- 렌즈 제조사/모델/배럴 표기, 조리개, IR-cut 유무, 실제 장착 방향
- 데이터시트 TV distortion(%), barrel/pincushion 방향, 기준 image height와 그 정의
- camera type·raw size·crop·bit depth·노출·gain·camera rotation
- 주간 ChArUco/체스보드 원본 20–40장과 보드 치수
- 야간 RAW: 같은 프레임에서 중앙·중간·가장자리 타일 모두 솔빙 가능한 별 영역,
  달이 중앙/주변에 있는 경우, 지평선·기구 간섭
- 기존 16 mm의 동일 장소·조건 정상 solve 기준선

수집 원본과 보정 결과는 별도 실측 리포트에 저장한다. config에는 승인된 작은
profile ID와 계수만 저장하며 RAW를 넣지 않는다.

## 5. 야간 승인 매트릭스

| 시나리오 | 기대 결과 | 금지 결과 |
| --- | --- | --- |
| 16 mm, flag off | 현재 solve path·좌표·지연 유지 | 광각 모듈이 실행/설정 변경 |
| 4/6/8 mm, 미보정 | 기존 solver 또는 안전한 실패 | provisional 계수로 자동 보정/발행 |
| TV distortion 사양 입력 | 센서 사용 반경으로 환산한 `manual-tv` provisional profile을 다음 프레임부터 사용 | 기준 image height/방향 없이 % 값을 `k1`로 직접 적용 |
| 광각, 보정 수집 | 중앙+mid+edge 타일의 독립 solve와 hold-out 개선 뒤 영속 profile을 저장하고 다음 프레임부터 자동 갱신 | 중앙 실패/2-타일 emergency 해/한 반경의 표본만으로 갱신 |
| 보정 뒤 재부팅 | 같은 camera+lens+crop fingerprint면 마지막 활성 자동 profile 복원 | 다른 렌즈/센서 profile을 재해석·자동 적용 |
| 광각, 중앙 정상 | 중앙 tile 해만 발행, 주변 tile 불필요 | 불필요한 다중 합의로 지연 증가 |
| 광각, 중앙 달 포화/이동 | 인접 2개가 엄격 일치하거나, 3개 이상 주변 tile이 합의할 때만 발행 | 주변 하나의 해가 Integrator 갱신 |
| 광각, 기구 간섭 | 선택 mask tile/centroid 제외, 저장 후 reboot 복원 | 다른 렌즈 profile까지 마스크 오염 |
| tile 해 상호 불일치 | `FailedSolve`, 마지막 좋은 추정 유지 | 평균낸 잘못된 좌표 발행 |

## 6. 배포/운영 절차

1. 개발 장비에서 `wide_solver_enabled=false` 상태로 P1–P5 회귀 테스트를 통과한다.
2. `/api/camera/wide-solver`에 TV 기본 profile을 저장하고, 특정 4/6/8 mm
   camera+lens 조합에서만 flag를 켠 뒤 **서비스를 재시작**한다. LiveCam 제외
   타일·로그·좌표를 기록한다. 자동 실측 계수 갱신은 중앙·mid·edge coverage와
   hold-out 검증이 끝날 때까지 활성화하지 않는다.
3. 실측 리포트 검토 후 사용자 승인이 있을 때만 `wide_solver_shadow=false`와
   해당 렌즈 allow-list를 켠다.
4. 문제 시 먼저 `wide_solver_enabled=false`로 서비스 재시작 없이 새 시도를
   막거나, 필요 시 기능 커밋만 revert한다. 기존 16 mm 설정·마스크·캘리브레이션
   원본은 삭제하지 않는다.

## 7. 작업 시작 전 사용자 결정이 필요한 항목

구현은 P1부터 안전하게 시작할 수 있다. P2 이후에는 실제 장비 정보가 필요하다.

1. 우선 지원할 4/6/8/10 mm 렌즈의 정확한 모델과 첫 대상 센서
2. 보정 보드(ChArUco 권장) 준비 가능 여부와 촬영 환경
3. 4 mm에서 허용할 최대 solve 지연/배터리·CPU 예산
4. LiveCam의 제외 영역을 “tile 단위 토글만”으로 시작할지, 설계대로 다각형
   편집까지 한 번에 제공할지

이 결정 전에는 P1과 문서/테스트 기반만 진행하고, P2 이후의 실측 계수나 활성화
정책을 추정해 넣지 않는다.
