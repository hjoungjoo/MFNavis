# 사용자 정렬·영상 추적 시험 구현과 실행 절차

작성일: 2026-09-28. 설계 정본은
[영상 추적 연속성 설계](mf_visual_tracking_continuity_design_ko.md)를 참조한다.

## 적용 범위

**기본 동작은 기존 로직이다.** 새 코드는 기본 Off이며 운영 정렬 결과,
PointingEstimate, 성공 솔빙 시각, 마운트 명령 경로를 대체하지 않는다.
환경 변수를 지정하지 않으면 solver는 새 모듈을 import하지 않고, 추가 영상
검출·파일 접근도 하지 않는다. 기존 정렬 함수의 응답·타임아웃은 그대로다.

이번 구현은 **시험 가능한 계산 엔진, 오프라인 재생, 실시간 shadow 연결**이다.
shadow는 같은 입력에서 새 방법의 좌표·오차를 계산해 별도 파일에 기록한다.
새 기능이 실제 마운트를 보정하는 active 모드는 구현하지 않았으며, 설정에
active를 넣어도 거절한다. 이는 전체 설계 P4/P5의 실장 제어 완료를 뜻하지 않는다.
환경이 정해지면 우선 실제 영상에서 shadow 결과를 검증하고, 그 결과로 축 보정과
제어 통합 범위를 확정한다. 이 구분을 유지한 상태에서 시험 소스를 사용할 수 있다.

| 구현된 부분 | 경계/제약 |
|---|---|
| 사용자 대상 정렬과 generation 관리 | 시험 세션의 별도 기준. 운영 Align의 성공/실패를 바꾸지 않음 |
| 고정 기준 별의 대응·구면 회전 적합 | 3개 이상 대응과 분포/잔차 검증; 1~2개는 완전 자세로 승인하지 않음 |
| 누적 드리프트·구름 소실/재획득 | 관측 소실은 예측으로 표시; 장시간 공백은 uncertain |
| 솔빙 복구·다시 실패 | 동일 시각/기하의 승인된 RAW 솔빙만 재기준에 사용; 큰 차이는 추가 확인 |
| 달 중심 측정 | 외곽의 기울기 방향·두께·커버리지 검사. 독립적으로 정한 원반 반지름 필요 |
| 기존 천체 식별·위치 재사용 | planet_at_coordinates/calc_planets 사용; RA·Dec 둘 다 반영 |
| 경위대·EQ 예상 자세 | 경위대 수직 방향 변화와 EQ 모델 분리; 실장 검증 전 |
| 축 보정량 계산 함수 | 실측 Jacobian으로 제한된 펄스 길이 **제안만** 반환; 전송 연결 없음 |
| 실시간 shadow / JSONL 재생 | 명령 큐 없음. 프레임 수·만료 시각으로 기록 제한 |

실시간 경로는 기존 MFDS RAW 검출을 재사용하고 기존 전체 왜곡 보정·회전을
같이 적용한다. 오프라인 NPY 영상의 기본 검출기는 NumPy/SciPy 기반 시험용
검출기이며 MFDS 대체품이 아니다. 이 차이는 실제 검출 성능 비교 때 구분한다.
OpenCV나 MFDS 변경 없이 구현했으며 추가 런타임 의존성 설치는 하지 않았다.

## 소스와 기본 격리

- [visual_tracking.py](../../python/MFNavis/visual_tracking.py): 기하, 별 대응,
  기준/전환, 잔차와 시험용 보정량 계산.
- [visual_tracking_images.py](../../python/MFNavis/visual_tracking_images.py):
  달 외곽 측정 및 오프라인 시험용 별 검출.
- [visual_tracking_target.py](../../python/MFNavis/visual_tracking_target.py):
  기존 천체 식별·관측지 에페메리스·마운트별 예상 회전.
- [visual_tracking_runtime.py](../../python/MFNavis/visual_tracking_runtime.py):
  환경 확인, 실시간 입력 pairing, 별도 세션·기록.
- [visual_tracking_experiment.py](../../python/MFNavis/visual_tracking_experiment.py):
  preflight/demo/replay/align/stop/manual_move/status CLI.

기존 solver와 UI/SkySafari 정렬, GoTo/Guide 세션 취소에는 환경 변수로 감싼
선택적 연결만 추가했다.
shadow 예외가 솔빙을 중단하지 않도록 격리하며, 파일 기록 자체가 실패하면
시험 경로를 해제한다. 운영 좌표와 입력 배열/solution dict는 수정하지 않는다.

## 1. 장비 없이 자동·재생 시험

저장소 루트에서 개발 환경 Python을 사용한다. 기존 파일 덮어쓰기를 방지하기
위해 demo와 replay의 출력은 새 파일이어야 한다.

~~~bash
cd /home/mfnavis/MFNavis
mkdir -p /tmp/mfnavis-visual-trial
PYTHONPATH=python .venv-dev-trixie/bin/python -m PiFinder.visual_tracking_experiment \
  demo --output /tmp/mfnavis-visual-trial/demo.jsonl
PYTHONPATH=python .venv-dev-trixie/bin/python -m PiFinder.visual_tracking_experiment \
  replay /tmp/mfnavis-visual-trial/demo.jsonl \
  --output /tmp/mfnavis-visual-trial/replayed.jsonl
~~~

demo는 알려진 별 배치와 태양계 천체에 해당하는 2차원 운동·회전,
가림과 솔빙 복구를 포함한다. 하드웨어나 서비스에 연결하지 않는다.
출력의 commands_sent는 **새 시험 경로가 보낸 명령 수**이며 항상 0이다.

새 시험과 관련 회귀는 python 디렉터리에서 다음과 같이 실행한다.

~~~bash
../.venv-dev-trixie/bin/python -m pytest \
  tests/test_visual_tracking.py tests/test_visual_tracking_runtime.py \
  tests/test_ui_align.py tests/test_pos_server.py \
  tests/test_alignment_tracking_flow.py tests/test_track_freq_policy.py \
  tests/test_nonsidereal.py tests/test_solver_frame_pairing.py -q
~~~

## 2. 실시간 시험 환경 확인

[환경 파일 예제](visual_tracking_environment.example.json)를 장비 로컬의 별도
경로에 복사해 실제 값으로 채운다. 예제 자체는 확인되지 않은 상태이고 만료되어
있으므로 실행되지 않는다. 운영 config.json에는 새 기본값을 저장하지 않는다.

| 필드 | 확인할 의미 |
|---|---|
| environment_confirmed | 실제 시험 장비와 아래 값을 확인했을 때만 true |
| mount_type | 실제 Alt/Az 또는 EQ; 알 수 없는 값 자동 추정 안 함 |
| camera_type / lens | 해당 시험 프로세스의 shared_state 값과 정확히 일치 |
| calibration_id | 기존 활성 보정 ID; 활성 보정 없음은 문자열 none. 이것이 광학 검증 완료를 뜻하지는 않음 |
| raw_shape | 회전 이전 원본 높이·너비. 예제 512×512를 실제 센서 값으로 교체 |
| alignment_roll_deg / roll_confirmed | 지정 방향을 기준으로 한 솔버 공간 Roll과 확인 여부. 기본 숫자 0을 미확인 상태에서 승인하지 않음 |
| identify_planets | 좌표만 있는 대상에 기존 천체 식별을 사용할지 선택. 명시 body를 지정한 요청은 이를 우선 |
| moon_radius_px | 원본 센서에서 예상한 달 반지름. null이면 달 직접 측정 비활성, 별 경로는 사용 가능 |
| expires_at | 시험 종료 UTC Unix 시각. 만료되면 추가 계산/기록 종료 |
| max_frames | 최대 1~10000회 관측 처리. 실패/대기 호출도 포함 |
| output_dir | 절대 경로의 별도 시험 출력 디렉터리 |

~~~bash
PYTHONPATH=python .venv-dev-trixie/bin/python -m PiFinder.visual_tracking_experiment \
  preflight /path/to/confirmed-visual-environment.json
~~~

preflight는 설정·의존성 확인만 수행한다. hardware_verified=false는 정상이며,
이 명령만으로 장비 검증 완료라고 표시하지 않는다. 실시간 입력에서 카메라·렌즈·
보정·크기·마운트 종류를 다시 비교하고, 같은 frame_id의 RAW/검출/메타데이터와
최근 마운트 상태를 확인해야 실제 관측 처리가 시작된다.

EQ의 pier side/회전기 상태 변경은 알려진 telemetry 값의 변화를 기준으로
세션을 보류한다. 현재 드라이버가 그 값을 게시하지 않는 경우 GEM 반전 검증이
된 것이 아니다. EQ 실제 제어와 반전 후 재개는 후속 시험 범위다.

## 3. 확인된 시험 프로세스에서만 shadow 선택

해당 시험 프로세스의 시작 환경에 아래 변수를 지정한다.

~~~bash
export MFNAVIS_VISUAL_TRACKING_EXPERIMENT=/path/to/confirmed-visual-environment.json
~~~

이미 실행 중인 서비스에는 현재 셸의 export가 적용되지 않는다. 이 문서 작성·
코드 구현 과정에서 운영 서비스의 환경 변경이나 재시작은 하지 않았다.
실장 시험 때 사용할 프로세스/카메라/마운트 연결은 운영 인스턴스와 충돌하지
않는 환경으로 먼저 정한다. 별도의 마운트 제어 서비스를 중복 실행하지 않는다.

시작 시 환경 변수가 없거나 파일이 부적합하면 기존 경로로 실행한다. shadow가
동작하더라도 기존 GoTo/Sync/Guide는 원래 설정대로 동작한다. **shadow 옵션은
기존 마운트 동작 전체를 무동작 모드로 바꾸는 옵션이 아니다.**

시험 세션의 정렬만 검증하려면 새 CLI를 사용한다. 아래 명령은 정렬 요청 파일만
작성하며 기존 UI 정렬이나 INDI Sync를 호출하지 않는다. RA/Dec는 도 단위다.

~~~bash
PYTHONPATH=python .venv-dev-trixie/bin/python -m PiFinder.visual_tracking_experiment \
  align /path/to/confirmed-visual-environment.json \
  --ra 123.0 --dec 20.0 --frame catalog --body MOON
~~~

body가 있으면 실제 정렬 좌표는 현재 에페메리스에서 계산한다. RA/Dec는 요청
출처 값으로만 남고, 예제 좌표를 달의 실제 좌표로 사용하지 않는다. 고정 대상은
body를 생략하고 정확한 대상 좌표/좌표계를 제공한다. 명시 대상 없이 SkySafari
좌표를 시험할 때는 frame=of_date와 identify_planets 설정을 사용한다.

요청은 시험 프로세스 시작 이후의 것이어야 하며 30초 뒤에는 만료된다. 첫
정지 프레임에서 적용하고 적용 시각을 기록한다. 이 초기 shadow에서는 요청부터
기준 프레임까지의 사용자/기계 이동을 IMU 이력으로 완전히 재구성하지 않는다.
정렬 직후 움직이지 않는 조건에서 시험하며, 해당 지연 오차도 결과에 포함한다.

기존 LCD 정렬 및 최초 솔빙 전 SkySafari 정렬도 opt-in일 때 의도를 복사한다.
원래 정렬의 성공·실패 및 마운트 전송은 바뀌지 않는다. 특히 기존 정렬이 솔빙
실패로 timeout해도 shadow 기준만 생성될 수 있으므로 두 결과를 구분해서 읽는다.

## 4. 결과 확인·중단·재생

~~~bash
PYTHONPATH=python .venv-dev-trixie/bin/python -m PiFinder.visual_tracking_experiment \
  status /path/to/confirmed-visual-environment.json
PYTHONPATH=python .venv-dev-trixie/bin/python -m PiFinder.visual_tracking_experiment \
  stop /path/to/confirmed-visual-environment.json
~~~

stop은 새 시험 세션만 중단하며 마운트 Stop 명령을 보내지 않는다. 환경 변수
제거 후 시험 프로세스를 다음에 시작하면 새 경로가 로드되지 않는다.

출력 디렉터리에는 status.json과 실행별 shadow-<run_id>.jsonl이 생성된다.
로그에는 기준, 시간, 유효 별 수, 잔차, 실제 영상 관측/예측 구분과 재생용 input이
포함된다. 같은 로그를 replay 명령에 전달하면 저장된 측정 입력으로 상태 전환을
재현한다. 이 로그는 전체 RAW 영상 대신 작은 좌표 입력을 저장한다. 검출기를
다시 평가하려면 기존 solver_capture로 원본도 별도 확보해야 한다.

오프라인 JSONL은 align, frame, manual_move, mount_changed, geometry_changed,
stop 이벤트를 지원한다. demo 출력이 기본 스키마 예시다. frame에 image 경로를
지정하면 allow_pickle=False로 2차원 NPY 영상을 읽는다. 해당 영상은 align에
선언한 기하와 같은 보정/회전 공간이어야 한다. 실제 센서 RAW를 보정된 좌표로
속여 넣지 않는다. frame의 moon_radius_px는 그 영상 공간에서의 반지름이다.

## 검증 상태와 후속 조건

개발 환경은 Python 3.13.5, NumPy 2.2.4, SciPy 1.16.3이다. 합성 기하·영상,
기존 천체 계산 및 모의 라이브 연결을 시험했다. 초승달의 명암 경계를 원반 외곽과
구분하도록 경사 방향과 에지 두께 검사를 적용했다. 실제 구름/광륜에서의 성능은
합성 시험 통과로 보장하지 않는다.

현재 작업 환경에는 /dev/shm/mfnavis 실장 상태 디렉터리가 없으며, 확인된 카메라·
마운트 시험 환경과 실제 영상 코퍼스는 아직 확보되지 않았다. 서비스 재시작,
실제 마운트 이동, 펌웨어/드라이버 설정 변경은 수행하지 않았다.

다음 단계는 실제 경위대 영상으로 오대응·달 중심 편향·처리 지연을 측정하는 것이다.
이후 사용자 기준의 운영 좌표 반영, IMU 이력 전파, 실측 축 보정과 단일 제어기
연결을 검증한다. EQ 실장, GEM 반전, 국소 카탈로그 재솔빙과 시간적 합성은
아직 구현·검증 완료로 표시하지 않는다.

### 2026-09-28 자동 검증 결과

- 전체 회귀: **3,739 passed / 3 skipped**, 219.55초. 웹 브라우저 테스트와
  실제 IMU 하드웨어 import를 요구하는 test_imu_runtime.py는 실행 범위에서 제외했다.
- 이후 좌표계/세션 취소/투영 불가 경계를 보완한 최종 관련 회귀: **265 passed**.
  새 실험 전용 시험 45개가 포함된다.
- 전체 Ruff 검사, 변경 Python 파일 11개의 포맷 검사, 신규 모듈 5개의 MyPy 검사 통과.
- 실제 CLI demo → replay 프로세스 실행: predicted 4, visual 4, solved 1 상태;
  commands_sent=0. 실시간 모의 로그의 재생 상태·좌표 잔차 일치도 확인했다.
- 문서 내부 링크와 공백 검사 통과. Graft 인덱스를 갱신했다.

전체 회귀 명령은 python 디렉터리에서 다음과 같다.

~~~bash
../.venv-dev-trixie/bin/python -m pytest tests \
  --ignore=tests/website --ignore=tests/test_imu_runtime.py \
  -q --tb=short --junitxml=/tmp/mfnavis-visual-tracking-tests.xml
~~~

이 결과는 합성·재생·모의 연결 및 기존 코드 회귀 결과이며, 실제 경위대/EQ의
도입 정확도나 자동 추적 성능을 검증한 결과가 아니다.
