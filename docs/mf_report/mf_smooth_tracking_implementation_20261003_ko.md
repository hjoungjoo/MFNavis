# 부드러운 추적 보정 구현 및 실내 검증 — 2026-10-03

기준 작업 디렉터리: `/home/mfnavis/MFNavis`, 착수 HEAD `50367660`.
기존 미커밋 GoTo/Guide·마운트·시험 변경을 유지한 상태에서 추가했다. 운영 설정은 Off이고 실행 중 서비스는 재시작하지 않았다. 본 보고서의 모의 시험은 실제 별 추적 정확도나 마운트 정지 시간을 인증하지 않는다.

## 확정한 사용자 정책

- 영상 보정의 기본 모드는 **On (`active`)**으로 변경했다. 기존에 명시 저장한 모드는 유지하며, 현재 장비에는 별도 저장값이 없어 새 기본값이 적용된다. 기본 On은 세션 자동 시작이나 장비 검증 생략을 뜻하지 않는다.
- 기존 Tracking Guide에서 반복 솔빙·보정을 학습해 솔빙 사이에 보내던 예측 펄스는 제거한다. 아래 예측·제한 유지 정책은 새 영상 보정 엔진에 대한 것이며 그대로 유지한다.
- 최초 활성화부터 위치 보정과 검증된 드리프트 예측 펄스를 포함한다.
- 축 이동·자동 GoTo는 별도의 장비 검증 후 허용한다.
- 전체 솔빙이 중단되어도 RAW 기준 별 추적이 유효하면 보정을 이어간다. 기준의 수명과 광학·시각·세션 일치 조건은 유지한다.
- 기준 별도 일시 소실되면 마지막 검증 예측값을 **검증된 짧은 시간·오차·누적 이동 한도 안에서만** 유지한다. 무제한 유지나 실패 프레임으로 속도 재학습은 하지 않는다.
- 실내 장비 시험은 허용되었다. 이번 장비 조회는 추적 Off·모든 수동 축 Off인 상태에서 수행했다.

## 구현 경로

| 경계 | 구현과 확인 사항 |
|---|---|
| 계약·설정 | [tracking_contracts.py](../../python/MFNavis/tracking_contracts.py): 시각, 측정, 권한, 실행 계획·결과, 장비 프로필. 유한성·정수·대응 행렬 rank·반대 방향·종료 상한 검사. |
| 카메라 시각 | [tracking_capture.py](../../python/MFNavis/tracking_capture.py): 명시한 센서 시각 의미·시계 변환·rolling skew. 카메라/backend 식별, 시계 변화 세대. capture 호출 시작을 실제 노출 시작으로 간주하지 않음. |
| 기준 별·RAW | [tracking_quality.py](../../python/MFNavis/tracking_quality.py): 승인 RAW 솔빙의 catalog ID만 기준으로 사용. 왜곡·회전 왕복, bounded ROI, 형태·포화·모호한 점·공간 분포·오차 상한 검사. |
| 최신 측정 | [tracking_mailbox.py](../../python/MFNavis/tracking_mailbox.py), [smooth_tracking_runtime.py](../../python/MFNavis/smooth_tracking_runtime.py): 별도 worker, 최신 프레임, 역순·중복 거부, invalid 우선, 세션/worker 실패 시 권한 철회. |
| 추정 좌표 | Integrator의 `VISUAL` estimate와 솔빙 사실을 분리. 늦은 솔빙은 현재 estimate를 되돌리지 않음. 검증된 영상 시각의 IMU 원점이 없는 동안 IMU 진행 보류. |
| 외란·펄스 | [tracking_motion.py](../../python/MFNavis/tracking_motion.py), [tracking_control.py](../../python/MFNavis/tracking_control.py): robust drift, step·왕복 진동 보류, 새 프레임 3건/0.5초 확인, ramp, packet/duty, 종료·정착 이후 노출만 응답 학습. 포화 상태에서 개선이 없고 승인된 복구도 없으면 LIMITED로 고정. |
| 취소·실행 | [tracking_commands.py](../../python/MFNavis/tracking_commands.py), [tracking_mount_adapter.py](../../python/MFNavis/tracking_mount_adapter.py): FIFO 삽입 전 공유 취소 세대 게시, 실제 전송 직전 재검사, 반대 방향 0, 한 번에 한 패킷, 전송 지연/예외는 결과 unknown으로 보류. |
| 응답 교정 | [tracking_calibration.py](../../python/MFNavis/tracking_calibration.py): 명시 calibration 권한만 사용. 무명령 drift 구간, N/S/E/W 각 3회, 전후 clean 관측, 신호/분산·시간·누적 이동 제한. 결과는 `verified:false` 후보로만 반환. |
| 복구 | [tracking_recovery.py](../../python/MFNavis/tracking_recovery.py), [smooth_mount_runtime.py](../../python/MFNavis/smooth_mount_runtime.py): 독립 절대 솔빙 2건, 좌표 변환, 한도·진행 관측, 부분 SYNC 성공 보존, 취소/시간 초과. |
| 웹·기록 | `/indi`에 모드/프로필·시작/중단·교정·상태 및 후보 다운로드. `/indi/smooth_tracking` 인증 API. 명령 계획·결과와 상태 변화는 기존 프로세스 로그에 기록. |

## 솔빙 중단과 예측 유지

전체 솔빙 성공 간격과 ROI 관측 간격을 분리했다. 같은 catalog reference로 새 RAW들을 측정하므로 솔빙 실패 자체가 예측값을 지우지 않는다. reference 기본 유효기간은 120초의 **프로필 시험 후보**이며, 무제한 절대 정확도 보장이 아니다. 기준이 오래되거나 광학·카메라·세대가 바뀌면 보류한다.

기준 별까지 소실되면 `PREDICTION_COAST`에서 마지막 valid drift만 사용한다. 허용 사유는 별 소실·별 수 부족·공간 분포 부족이다. 시계 변화, 노출 전환, 별 움직임 불일치, worker 중단, Stop, 사용자 이동에는 적용하지 않는다. `coast_verified` 외에 `coast_max_s`, `coast_error_bound_arcsec`, `coast_travel_arcsec`, `coast_external_rate_bound`를 검사한다. 코드의 절대 시간 상한은 2초이며 프로필의 더 짧은 한도가 우선한다. 기본 후보는 0.5초이나 **현재 장비에서 승인된 유지 시간은 아직 없다**. 한도가 펄스 종료까지 포함하지 못하면 펄스를 내보내지 않는다.

별이 복귀하면 새 독립 프레임들을 다시 확인하고 ramp를 새로 시작한다. 가림 중 위치 오차나 펄스 잔여량을 쌓아 두었다가 한꺼번에 적용하지 않는다.

## 장비별 계약과 활성화 절차

1. `/indi`에서 Shadow를 저장하고 고정 별 목표의 J2000 적경·적위를 입력해 시작한다. 저장 자체는 세션을 시작하지 않는다.
2. `/indi/smooth_tracking`의 reference 진단에서 실제 카메라/backend, geometry key와 센서 metadata를 확인한다. 센서 timestamp 의미와 버퍼·노출·rolling skew 상한을 별도로 측정한다.
3. 실제 장비 이름, `DRIVER_EXEC:DRIVER_VERSION`, guide rate, mount type, EQ라면 pier-side 의미를 프로필에 기록한다. 재연결·광학·guide rate·드라이버 변경은 기존 프로필을 자동 승인하지 않는다.
4. 짧은 timed pulse의 장비 자체 종료와 전송/Stop 상한을 검증한 후에만 `equipment_verified:true`로 명시 교정 세션을 허용한다. `verified:false`이면 일반 active 추적은 거부한다.
5. 응답 교정을 실행하고 방향별 3회 관측 후보를 내려받는다. 실패한 교정은 LIMITED로 종료하며 pulse를 늘려 신호를 강제로 확보하지 않는다. 후보의 `response` 단위는 목표 접평면의 arcsec/ms, 열은 N/S/E/W다.
6. 독립 자료로 모델과 자세 유효 범위를 확인한 뒤 `verified:true`로 승인한다. 별 소실 예측 유지와 자동 GoTo는 각 기능의 별도 검증 필드가 필요하다. 설정을 저장한 뒤 명시 Start로 새 세션을 시작한다.

[프로필 파서](../../python/MFNavis/tracking_contracts.py)의 기본값은 시험용 출발점이다. 빈 프로필이나 플래그 변경만으로 실측 증거를 대신할 수 없다. IMU 건강 상태나 마운트 cache의 좌표만으로 광학 검증을 완료 처리하지 않는다.

## 실내 장비 확인

[check_smooth_tracking.py](../../python/scripts/check_smooth_tracking.py)는 INDI 속성 조회만 수행하며 모터 명령을 보내지 않는다.

```bash
cd /home/mfnavis/MFNavis/python
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 ../.venv-dev-trixie/bin/python \
  scripts/check_smooth_tracking.py --device 'LX200 OnStepX' \
  --output /tmp/mf_smooth_indoor_readback.json
```

이번 조회 결과: `indi_lx200_OnStepX:1.27`, 두 timed guide vector 모두 `rw`, WE/NS guide rate 모두 `0.5`, `EQUATORIAL_EOD_COORD=Idle`, `TRACK_ON=Off`, `UNPARK=On`, 네 수동 방향 모두 Off. 조회 소요 약 1.00초. 운영 장비의 추적·설정을 바꾸거나 펄스/축 이동/Sync/GoTo를 보내지 않았다.

현재 실내 조건과 읽기 결과만으로 실제 하늘 기준 응답, 소실 중 예측 오차, 장비 전원/통신 단절 시 정지 상한을 측정할 수는 없다. 이 승인 없이 실제 보정 엔진을 활성화하지 않았다.

## 남은 실장 범위와 제한

- 표준 INDI `TELESCOPE_MOTION_*`는 장비 자체 시간 제한이 없는 지속 이동이다. 현재 adapter의 자동 축 복구는 **unsupported**이며, JSON의 `axis.verified`만 바꿔도 활성화되지 않는다. 장비 자체 만료 계약을 제공하는 adapter가 추가되어야 한다.
- 자동 GoTo는 검증된 Alt/Az 장비·of-date 변환·장비 물리 경로 제한이 있을 때만 허용한다. 작은 하늘 보간 경로의 고도 검사만으로 실제 축 경로를 증명하지 않는다. EQ 자동 복구는 차단한다.
- `off`는 기존 동작을 유지한다. 새 엔진 active 실패는 기존 자동 GoTo로 무조건 넘기지 않는다. 재시작·worker 실패 후 자동 활성화하지 않는다.
- 달/행성, 최초 미솔빙 정렬, 시각에 대응한 IMU 원점의 결합은 설계의 후속 P6 범위다.
- 실제 흐린 하늘·건물 불빛·바람 corpus의 오승인율, 독립 평가 별의 정확도, 실기 CPU/지연, 모든 드라이버와 전원 장애 시험은 미완료다. 합성 RAW/모의 드라이버 통과를 이 결과로 확대하지 않는다.

## 시험 결과

최종 실행 결과는 아래에 기록한다. 관련 파일은 `test_smooth_tracking.py`, `test_smooth_tracking_runtime.py`, `test_smooth_tracking_api.py`다.

| 실행 | 결과 | 범위 |
|---|---|---|
| 전체 unit (`test_imu_runtime.py`와 website 별도) | **3,208 passed**, 656 deselected, 72.61초 | GPIO import 제약 파일을 분리한 전체 단위 회귀. 마지막 프로필·예측 유지·복구 권한·능력 부족 보강은 아래 새 시험으로 재확인. |
| GPIO 접근 환경의 `test_imu_runtime.py` | **3 passed** | 실제 GPIO 모듈 import 후, 센서 I/O 실패/복구는 모의 객체로 검증. 실제 I2C 고장 주입은 아님. |
| 새 보정 시험 3개 파일 | **46 passed** | 합성 RAW 4방향 회전, 솔빙 공백, 별 소실/복귀, 제한 예측, 교정 12 probe, Stop·프로세스 공유 세대·재시작·지연 결과·복구 부분 성공·웹 API. |
| 관련 경로 확장 회귀 | **418 passed** | 새 기능 + mount/service/integrator/camera/frame pairing/한국어 UI. 전체 unit과 중복되므로 합산하지 않음. |
| smoke | **7 passed** | 저장소의 smoke 표시 시험. 실행 중 서비스 재시작 시험은 아님. |
| 정적 검사 | 통과 | 변경 Python의 Ruff 검사/포맷, Python compileall, 새 JavaScript 구문, `git diff --check`. Graft 인덱스 갱신. |

전체 unit을 처음 넓혔을 때 발견한 속도 명령 분기 fixture 호환성, 한국어 번역 누락, 웹 시험 fixture 등록 문제를 수정한 뒤 재실행했다. Stop 취소를 추가하면서 정상적인 “속도 선택 → 방향 이동”의 FIFO 순서를 잃지 않도록 별도 회귀 시험도 추가했다. 경고는 기존 pytz UTC/SWIG deprecation과 Python 3.13의 fork 경고다.

```bash
cd /home/mfnavis/MFNavis/python
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 ../.venv-dev-trixie/bin/python -m pytest \
  -m unit --ignore=tests/website --ignore=tests/test_imu_runtime.py -q
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 ../.venv-dev-trixie/bin/python -m pytest \
  tests/test_smooth_tracking.py tests/test_smooth_tracking_runtime.py \
  tests/test_smooth_tracking_api.py -q
```

최종 현장 승인은 아직 수행하지 않았다. 현재 설정 Off를 유지하고, 장비별 시각·응답·종료와 예측 유지 상한을 검증한 프로필을 확보한 후 새 서비스를 로드해 단계적으로 시험해야 한다. 브라우저의 실제 클릭/시각 렌더링은 Selenium으로 시험하지 않았으며 Flask API·템플릿·JS 구문과 기존 웹 단위 시험으로 확인했다.

## 추가 검증: 기존 예측 펄스와 부드러운 영상 보정의 충돌

기존 Tracking Guide의 예측 펄스와 새 엔진의 영상 위치 보정은 동시에 장비를 제어하면 안 된다. 새 엔진 내부의 예측 보정은 같은 controller의 단일 pending/in-flight 명령과 duty 제한을 공유하며, 위치 보정 잔여량이 없을 때 계획된다. 적용한 펄스의 모델 이동량을 관측 오차에 되더해 외부 드리프트를 추정한다. 이 계산의 정확도는 장비 응답 모델의 실측 정확도에 의존한다.

정상 active 경로에는 기존 루프를 막는 소유권 검사가 있었지만 전환 경로에서 아래 문제를 발견해 보완했다.

| 경로 | 발견 사항과 보완 |
|---|---|
| Shadow 취소·중단 | 장비를 제어하지 않은 세션의 취소가 기존 가이드를 끄는 부작용을 재현했다. 실제 소유권을 획득한 경우에만 기존 루프를 정리한다. 새 기능의 중단은 전역 장비 Stop과 구별하며, 관계없는 대기 GoTo를 취소하지 않는다. |
| 지연된 기존 보정 명령 | OFF도 가이드 속도를 복원하므로 새 펄스의 응답 모델을 바꿀 수 있었다. 소유권 유지 중에는 ON/OFF 모두 기존 toggle의 장비 변경을 차단한다. 인계 이전에 대기하던 GoTo·Sync·속도 변경도 세대로 차단한다. |
| 기존 펄스에서 새 엔진으로 전환 | 펄스 종료뿐 아니라 프로필의 안정화 시간까지 기다리고, 그 이전에 노출된 RAW를 새 보정의 관측으로 소비하지 않는다. |
| 새 세션 종료 후 자동 복구 | 설정 변경으로 세션이 사라진 뒤 기존 Tracking Guide의 자동 GoTo가 다시 큐에 들어가는 상황을 모의 시험으로 재현했다. 별도 중단 상태를 유지해 기존 상태 머신·자동 복구를 막고, 명시 GoTo·추적 목표 설정·Resume으로만 기존 소유권을 재개한다. |
| 명시 Resume과 미완료 펄스 | 마지막 새 펄스의 종료·안정화 및 미완료 전송 처리가 끝날 때까지 기존 보정 재개를 보류한다. 그 사이 새로운 제어 명령이 오면 보류한 재개도 폐기한다. |

[전환 회귀 시험](../../python/tests/test_smooth_tracking_handover.py) **15개 통과**: 위 전환 경로, 자체 보정량의 드리프트 학습 배제, 예측과 위치 보정의 단일 명령 공유를 검증했다. 새 보정·기존 mount/service·솔빙 fallback·드리프트 시험을 함께 실행한 결과는 **419 passed**다. Ruff 검사·포맷 검사와 `git diff --check`도 통과했다.

이번 추가 시험은 모의 장비와 합성 관측으로 수행했다. 서비스 재시작, 실제 펄스 발행, 운영 설정 변경은 하지 않았다. 소프트웨어상 충돌 경로 보완을 실장 응답·통신 지연·정지 상한 검증 완료로 해석하지 않는다.

## 후속 변경: 기존 반복 보정의 예측 펄스만 제거

사용자가 삭제 대상으로 지정한 것은 기존 `GuideDrift` 학습에 따른 솔빙 사이의 예측 펄스다. 기존 `_check_predictive_guide`, `_send_drift_pulse`, 예측 주기·펄스 한도와 학습 연결을 제거했다. 기존 위치 보정은 실제 새 솔빙 오차로 `_send_guide_pulse`를 호출한다. 이전 클라이언트의 `predictive_tracking=true`는 무시하고 상태는 false를 유지한다. `guide_drift.py` 계산 유틸리티와 독립 시험은 남아 있지만 운영 제어에서는 가져오거나 호출하지 않는다.

새 영상 보정의 `smooth_tracking_prediction_enabled`, 예측 명령 전송, 별 소실 시 검증된 짧은 한도 내 `PREDICTION_COAST`는 유지했다. 삭제 범위를 넓게 해석하며 잠시 변경했던 새 엔진의 설정·정책·전송 차단·화면 안내는 복구했다. 해당 중간 변경은 운영 서비스에 적용하지 않았다.

기존 예측 옵션·남은 학습 이력으로 펄스가 재개되지 않는 시험과 새 엔진의 예측 설정·정책·제한 유지 시험을 포함해 관련 회귀 **421 passed**. 기존 GoTo·관측 기반 위치 보정·인계 시험도 포함한다. 서비스 재시작과 실제 장비 동작 시험은 수행하지 않았다.
