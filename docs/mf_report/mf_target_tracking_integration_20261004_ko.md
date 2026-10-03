# 대상별 영상 추적 구현과 최종 시험 인계

작성일: 2026-10-04 KST. 기존 시험 기준: `main`의 `a10d6395`.

상태: **정렬 분기와 달·행성·상대 별의 영상 측정을 기존 부드러운 보정 엔진에 연결했다. 자동 회귀 시험을 수행했으며 실제 하늘과 장비의 최종 시험은 대기 중이다.** 운영 설정 변경, 서비스 재시작, 실제 마운트 이동은 수행하지 않았다.

요구사항과 구현 전 검토는 [통합 개선 계획](../mf_dev/mf_moon_smooth_tracking_integration_plan_20261003_ko.md)을 따른다. 이전 [부드러운 보정 구현 보고서](mf_smooth_tracking_implementation_20261003_ko.md)는 기존 시험의 기록으로 유지한다. 이후 통합 수정과 결과는 이 문서에 기록한다.

## 기존 최종 시험과 이번 통합 시험의 경계

| 구분 | 설정과 코드 | 시험 목적 |
|---|---|---|
| 기존 보정 최종 시험 | `smooth_tracking_target_integration_enabled=false` | 기존 카탈로그 별 ROI·펄스·예측·교정·인계·복구를 검증한다. 기존 Start와 정렬 경로를 사용한다. |
| 새 대상별 통합 시험 | 위 설정을 `true`로 지정 | 공통 비동기 Align, 최초 미솔빙·관측 중 실패, 달 중심, 행성 중심·주변 별, 상대 별 기준과 솔빙 복구를 검증한다. |

새 설정의 **기본값은 false**다. 기존 `smooth_tracking_mode=active` 기본값과 저장된 사용자 설정을 유지했다. 통합 기능을 저장하는 것과 세션을 시작하는 것은 다르다. 웹의 **Moon, planet and manual alignment tracking** 선택을 저장하고 Align 또는 Start를 요청해야 새 경로가 동작한다.

두 경로는 같은 controller와 시간 제한 펄스 adapter를 사용한다. 대상 선택과 측정·정렬 정책은 새 모듈로 분리했다. 최종 시험에서 controller나 adapter를 수정하면 두 시험군 모두 실행하고, 대상 측정 또는 정렬 분기를 수정하면 새 통합 시험군과 해당 진입 경로의 회귀 시험을 실행한다. 기존 시험 파일을 새 동작에 맞춰 약화하거나 이름을 바꾸지 않았다.

## 정렬 요청의 실제 처리

LCD, 웹 `/indi/smooth_tracking`의 `action=align`, MFNavis 모드의 SkySafari Align은 동일한 서비스 처리기를 사용한다. LCD는 요청을 큐에 넣고 즉시 돌아온다. 대기 중 Stop·새 GoTo·수동 이동을 처리할 수 있으며 웹 상태에서 결과와 남은 시간을 확인한다. `request_id`와 제어·이동 세대를 사용해 이전 요청의 결과를 버린다.

| 상태 | 처리 |
|---|---|
| 현재 자세에 유효한 승인 솔빙 있음 | 새 솔빙을 요구하지 않고 즉시 정상 정렬한다. IMU 원점이 없는 실제 솔빙도 사용할 수 있다. |
| 관측용 이동이 진행 중이거나 정지 근거가 부족함 | 중심 도착으로 완료하지 않고 이동 확인을 기다린다. |
| 이동이 끝났고 솔빙 대기시간이 남음 | 마지막 관측용 이동 완료부터 정한 deadline의 남은 시간만 기다린다. 승인 솔빙이 도착하면 바로 정상 정렬한다. |
| 해당 이동 후 솔빙 경로가 최종 실패함 | 사용자 중심 도착 확인으로 완료한다. 독립 확인을 기다리는 솔빙 후보는 실패 확정으로 처리하지 않는다. |
| deadline 경과 후 미솔빙 | 새 전체 timeout을 시작하지 않고 사용자 중심 도착 확인으로 완료한다. |
| 같은 tick에 유효 솔빙과 deadline 경과가 함께 확인됨 | 취소·문맥 변경을 먼저 검사한 뒤 정상 솔빙을 우선 사용한다. 완료는 한 번이다. |

`alignment_solve_wait_max_s`의 초기값은 15초이며 허용 범위는 0초 초과, 300초 이하다. **15초는 장비에서 최악 지연을 실측해 확정한 값이 아니다.** 최종 시험에서 이동 정착, 진행 중 촬영·솔빙 잔여량, 새 촬영·읽기, 활성 탐색 경로, 독립 확인 프레임, 승인 게시와 서비스 지연을 포함해 상한을 정해야 한다.

deadline은 이동 완료 때 고정한다. 재요청·솔빙 재시도·대기시간 설정 변경으로 이미 진행 중인 창을 연장하지 않는다. 가이드 펄스, 자동 refine, 복구 GoTo는 관측용 이동과 구분하며 deadline을 리셋하지 않는다. 보정 이동과 정착 중에는 현재 영상·솔빙 사용만 별도로 보류한다.

수동 축 이동은 Stop 명령 전송만으로 완료라고 기록하지 않고 idle·축 Off 근거를 다시 확인한다. GoTo를 Stop으로 중단한 경우도 같은 정지 확인을 거친다. 관측용 중단은 완료 시각을 기록하고 보정용 중단은 기존 deadline을 유지한다. GoTo의 확인된 완료는 refine 대기와 분리해 기록한다. GoTo의 기존 “완료로 가정” timeout을 새 정렬의 완료 근거로 사용하지 않는다. 완료 이력이 없으면 확인된 정지 시각을 새 대기 기준으로 사용하고, 서비스 재시작 시에는 이전 정렬 기록을 초기화한다.

Align을 받으면 이전 자동 Sync+GoTo 예약과 refine·guide 예약을 중단한다. 이미 이동 중인 관측용 GoTo는 완료를 확인한다. 이전 제어 세대의 자동 명령이 늦게 도착해 다시 실행되지 않도록 마운트 처리기에서도 거른다.

완료 결과는 `solved_alignment` 또는 `user_center_arrival`이다. 후자는 **사용자가 지정 위치에 대상을 맞췄다는 확인**이며 절대 솔빙이나 절대 Sync 근거가 아니다. 모드·장비·추적 상태가 허용하면 같은 요청으로 영상 세션을 시작한다. Off, tracking Off, park, 미검증 응답은 명령을 허용하지 않으며 획득 또는 보류 이유를 게시한다.

SkySafari의 정상 솔빙 정렬은 기존 `skysafari_indi_sync` 설정에 따라 마운트 Sync도 수행한다. 카탈로그 좌표를 INDI의 of-date 좌표로 변환하고, 로컬 픽셀 정렬은 즉시 적용한다. `waiting_mount_sync`에서 해당 요청의 실제 전송 결과를 확인한 뒤 영상 세션을 시작한다. 전송 실패·15초 응답 만료는 영상 보정을 보류하며 만료되거나 이전 제어 세대의 Sync는 실행하지 않는다. 사용자 중심 도착에는 이 Sync를 보내지 않는다. 이 응답은 INDI 전송 성공 근거이며 마운트 좌표 readback 정밀도 시험을 대신하지 않는다.

## 대상별 측정과 솔빙 복구

기존 `TargetEphemeris`와 천체 식별을 재사용한다. 명시적인 달·행성 ID는 보존하고, 좌표만 있는 요청은 기존 식별기를 사용한다. LCD의 명시적인 항성과 항성·딥스카이 선택은 행성으로 재분류하지 않는다. 세션 정체성과 유지 픽셀은 고정하고 천체 RA·Dec는 촬영 시각마다 계산한다.

| 대상 | 영상 측정 |
|---|---|
| 달 | 기존 달 외곽 검출기로 원반 중심을 측정한다. 내부 포화는 허용할 수 있지만 외곽 포화·광륜·클리핑·품질 부족은 보류한다. |
| 목성·토성 등 | 모호성이 없는 대상 중심과 주변 별을 사용한다. 중심 검출은 밝기 임계값에 따른 중심 일치·대칭·클리핑·경쟁 물체를 검사한다. 중심을 사용할 수 없으면 유효한 주변 별로 이어간다. |
| 항성·딥스카이 | 주변 별의 상대 배치를 새 사용자 기준으로 사용한다. 카탈로그 ID나 영상에 보이는 DSO 본체를 요구하지 않는다. 별 개수·분포·PSF·대응·잔차 검사 수준은 유지한다. |

행성 주변 별은 고정된 배경 광선이고 행성은 시간별 위치를 가진다. 행성의 RA·Dec 변화와 Alt/Az 시야 회전을 반영한 예상 자세에서 잔차를 계산한다. 장비가 이미 대상을 따라가는 경우 정상 운동을 추가 보정하지 않는다. 고정 대상과 이동 천체를 같은 운동 모델로 처리하지 않는다.

펄스 응답은 교정 당시 기준면에서 세션의 고정 기준면으로 옮긴다. 천체가 움직인다는 이유로 controller context를 매 프레임 교체하지 않는다. 모델 위치·장비·드라이버·pier side·추적·촬영 시각의 기존 실행 검사는 유지한다.

RAW를 다시 검출하지 않고 기존 MFDS 우선 검출기의 작은 결과를 기준 생성에 재사용한다. worker는 기존 최신 프레임 슬롯과 ROI를 사용한다. 별 ROI는 기존 반경 32px 이하, 대상 ROI는 한 개와 반경 256px 이하로 제한한다. 달 외곽의 전체 ROI를 왜곡·회전 보정한 뒤 원을 맞추며, 중심점 하나만 보정하지 않는다.

같은 프레임에서는 최종 측정 한 건을 게시한다. 승인된 신선한 솔빙을 우선하고, 솔빙 사이에는 영상 측정으로 이어간다. 늦게 도착한 솔빙을 현재 영상 시각으로 연결하며 과거 프레임으로 측정을 되돌리지 않는다. 큰 솔빙 차이는 다른 솔빙 프레임의 확인을 요구한다. 직접 중심과 별의 잔차가 모순되면 보류하고, 소스 전환에는 새 관측 확인과 기존 controller의 재확인·ramp를 사용한다.

새로 보이는 주변 별은 그 RAW 시각의 유효한 대상 자세가 남아 있을 때 기준으로 추가할 수 있다. 현재 자세를 과거 별 영상에 붙이지 않으며 64개 관측의 제한된 기록만 사용한다. 기준을 갱신할 때 이전 중심 측정의 불확실성을 없애지 않는다.

달 중심과 상대 별 기준은 `model_pointing`을 통해 검증된 로컬 펄스의 위치 검사를 받는다. 완전한 `camera_radec_roll`과 `aligned_radec`를 만들어 integrator에 넘기지 않는다. `camera.solve`, `aligned.solve`, `last_solve_success`, Matches는 실제 솔빙으로만 갱신된다.

새 대상별 세션은 axis recovery·복구 GoTo·소실 중 coast를 허용하지 않는다. 유효한 영상 동안의 기존 제한 예측은 유지한다. 이 제한은 새 경로의 실장 근거가 확보될 때까지 적용하며 기존 카탈로그 별 세션의 검증된 복구 설정을 바꾸지 않는다.

## 최초 미솔빙의 광학 준비

사용자 확인은 FOV·Roll·왜곡·펄스 방향을 교정하지 않는다. 첫 솔빙 없이 시작하려면 기존 검증된 펄스·시각 프로필에 `local_reference`를 추가해야 한다. 기준이 없으면 `verified_local_optics_required`, 별 분포가 부족하면 `waiting_distributed_stars`로 획득을 기다린다.

현재 자세의 승인 솔빙이 있는 동안 웹의 **Download local optical model for review**로 작은 후보 JSON을 받을 수 있다. 후보는 `verified=false`이며 자동으로 저장·활성화하지 않는다. 실제 장비에서 광학·Roll과 오차 상한을 확인한 후 장비 프로필의 `local_reference`로 넣는다.

```json
{
  "local_reference": {
    "verified": true,
    "optics": "후보의 광학 식별값",
    "raw_shape": [480, 640],
    "info": {
      "rotation_deg": 0,
      "crop_width_px": 480,
      "saturation_level": 4095,
      "distortion_coefficients": null
    },
    "fov_deg": 4.0,
    "roll_deg": 12.0,
    "bound_arcsec": 5.0,
    "roll_target": [40.0, 20.0],
    "roll_timestamp": 1790982000.0
  }
}
```

위 숫자는 **형식 설명용 예시**다. 실제 `info`에는 후보가 제공하는 항목을 모두 보존하고 RAW 크기·카메라·왜곡·회전·crop과 맞춰야 한다. Alt/Az는 Roll의 기준 대상·UTC 시각도 필요하다. `bound_arcsec`는 실제 검증한 광학·중심·방향 불확실성의 상한이며 전체 프로필의 허용 오차 이하여야 한다.

정상 솔빙으로 유지 픽셀이 바뀌는 정렬은 같은 검증된 광학 모델을 새 픽셀에 세션 안에서 연결한다. 프로필 파일을 자동으로 덮어쓰거나 장비 교정을 새로 완료한 것으로 표시하지 않는다. 실제 광학 변경·연결 변경·모델 범위 이탈은 보류 또는 새 Start가 필요하다.

## 수정 위치

| 위치 | 담당 |
|---|---|
| `tracking_alignment.py` | 이동·deadline 기록, 요청 취소, 공통 정렬 분기와 완료 |
| `tracking_targets.py` | 사용자 기준, 달·행성 중심, 운동을 반영한 별 측정, 솔빙 연결, 광학 후보 |
| `state.py`, `solver.py` | 작은 기준 입력과 촬영 시각, bounded 대상 ROI |
| `smooth_tracking_runtime.py` | 기존/통합 경로 선택, 대상 세션·권한·측정·진단 |
| `tracking_contracts.py`, `tracking_control.py`, `tracking_mount_adapter.py` | 부분 측정과 모델 방향, 기준면과 기존 펄스 실행 계약 |
| `smooth_mount_runtime.py` | 로컬 세션을 절대 복구 기준으로 사용하지 않음 |
| `indi_goto_guide_service.py`, `mountcontrol_indi.py`, `tracking_commands.py` | 공통 Align, 이동 목적과 실제 완료, 이전 예약 중단과 세대 검사 |
| `ui/align.py`, `ui/object_details.py`, `pos_server.py`, 웹 패널 | LCD·SkySafari·웹 진입, 대상 정체성과 비동기 상태 |
| `test_tracking_target_integration.py` | 이번 통합의 독립 시험군 |

## 자동 검증과 실장 인계

2026-10-04 최종 자동 회귀 결과는 **24개 파일, 847 passed, 45.28초**다. 기존 보정 시험 121개와 새 통합 시험 39개를 포함한다. 정렬·INDI GoTo/Guide·LCD·SkySafari/Stellarium·solver·좌표 서비스·integrator 회귀도 실행했다. 기존 시험 파일은 수정하지 않았다. pytz·SWIG·multiprocessing의 deprecation 경고 4건이 있었으며 실패는 없다. 이 결과는 실제 하늘 시험 완료를 의미하지 않는다.

변경한 Python 19개 파일의 Ruff 검사와 형식 검사, JavaScript `node --check`, 기본 설정 JSON, 문서 6개의 상대 링크·코드 블록·새 파일 공백 검사를 통과했다. 코드 변경 후 Graft 그래프도 재생성했다.

같은 날 제품 렌즈 기본값을 실측 8.2409 mm와 `k1=-0.12`로 갱신한 뒤 푸시 전 통합 확인도 수행했다. 위 24개 파일에 config·카메라 렌즈·수동 렌즈·렌즈 측정·왜곡 적용·왜곡 측정 시험 6개 파일을 더한 **30개 파일, 910 passed, 43.24초**다. 변경 Python 20개 파일의 Ruff·형식 검사와 JavaScript 구문 검사도 통과했다. 렌즈 기본값 변경과 대상별 추적 통합은 별도 커밋으로 관리한다.

기존 보정 시험군의 재현 명령은 그대로다.

```bash
cd /home/mfnavis/MFNavis/python
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 ../.venv-dev-trixie/bin/python -m pytest \
  tests/test_visual_tracking.py tests/test_visual_tracking_runtime.py \
  tests/test_smooth_tracking.py tests/test_smooth_tracking_runtime.py \
  tests/test_smooth_tracking_api.py tests/test_smooth_tracking_handover.py \
  tests/test_track_freq_policy.py -q --tb=short
```

새 통합 시험군은 별도로 실행한다.

```bash
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 ../.venv-dev-trixie/bin/python -m pytest \
  tests/test_tracking_target_integration.py -q --tb=short
```

최종 회귀 전체의 재현 명령은 다음과 같다. 위와 같은 `python` 디렉터리에서 실행한다.

```bash
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 ../.venv-dev-trixie/bin/python -m pytest \
  tests/test_tracking_target_integration.py \
  tests/test_visual_tracking.py tests/test_visual_tracking_runtime.py \
  tests/test_smooth_tracking.py tests/test_smooth_tracking_runtime.py \
  tests/test_smooth_tracking_api.py tests/test_smooth_tracking_handover.py \
  tests/test_track_freq_policy.py tests/test_ui_align.py \
  tests/test_mountcontrol_indi.py tests/test_indi_goto_guide_service.py \
  tests/test_pos_server.py tests/test_pos_server_stellarium.py \
  tests/test_alignment_projection.py tests/test_alignment_tracking_flow.py \
  tests/test_solver_fullframe.py tests/test_solver_frame_pairing.py \
  tests/test_solver_sqm.py tests/test_solver_scheduling.py \
  tests/test_solver_preprocessed_candidates.py tests/test_solver_sep_emergency.py \
  tests/test_pointing_estimate.py tests/test_integrator_drift.py \
  tests/test_pointing_coordinate_service.py -q --tb=short
```

| 실장 시험 | 기록할 조건과 합격 근거 |
|---|---|
| 기존 보정 최종 시험 | 통합 설정 false, 기존 프로필·노출·장비·버전, 펄스·예측·Stop·재연결 결과 |
| 정렬 분기 | 즉시 솔빙 정렬, 이동 직후 대기, 대기 중 성공/실패, 이미 경과한 대기, 보정 반복, 재요청·Stop·새 이동 |
| 달 | 초승달·반달·보름달, 내부/외곽 포화, 광륜·부분 구름·클리핑, 중심 오차와 명령 0 보류 |
| 행성 | 목성·토성 중심과 주변 별, 위성·고리·다중 물체, RA·Dec 운동, 시야 회전, 모델 범위 |
| 상대 별 | 첫 솔빙 전과 솔빙 이력 후 실패, 보이지 않는 DSO, 별 소실·재등장, 장시간 유지 |
| 솔빙 복구 | 소스 반복 전환, 늦은 결과, 큰 차이 확인, 유지 픽셀·같은 대상 보존, 펄스 중복 없음 |

각 시험은 장비·프로필·설정·기준 커밋 또는 작업 diff·UTC/촬영 시각·대상 ID를 함께 기록한다. 허용 중심 오차를 px와 arcsec로 정하고 RMS·상위 분위수·최댓값, 관측 유효 비율·처리 지연·펄스 duty·overshoot·재획득 시간을 측정한다. controller 출력과 별개인 실제 영상·짧은 노출·수동 외곽 측정 등을 기준으로 사용한다.

달 근접 direct GoTo의 전체 계획 선택·자동 경로 계산과 자동 노출 소유권 전환은 이번 코드의 완료 범위가 아니다. 이번 구현은 사용자 정렬 이후의 영상 추적 인계와 이전 자동 복귀 중단을 처리한다. 대상이 ROI를 넘거나 충분한 외곽·별·검증 모델이 없으면 보류한다.
