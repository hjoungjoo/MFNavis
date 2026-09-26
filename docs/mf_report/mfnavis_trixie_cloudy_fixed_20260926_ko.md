# Trixie 구름 많은 하늘·고정 장비 점검 — 2026-09-26

## 조건과 결론

- 사용자 현장 조건: **구름이 많은 환경에서 솔빙 중, 장비 고정, 마운트 연결 없이 테스트**.
- 점검 시간: 2026-09-26 22:57–23:06 KST. 연속 API 표본은 약 3분.
- Raspberry Pi 5, Debian 13.7 Trixie arm64, Python 3.13.5, MFNavis m2.6.14.
- 기준 커밋: `854b293105e9dac21260cc20229385220b3fa235`. 기존 미커밋 설치·권한·네트워크 수정이 있는 작업 트리에서 검사했다.
- 운영 `.venv-trixie`, 회귀 검사 `.venv-dev-trixie`; 두 환경의 Skyfield는 1.55.
- IMX462 color, 수동 렌즈 8.2661 mm, Flat V3, 솔버 전처리 활성화, RAW LiveCam, 스택 비활성화.

**실제 촬영·솔빙·GPS·IMU·SQM은 동작하지만, 추가 문제가 없는 상태는 아니다.**
운영 중 혜성 일괄 계산 예외가 재현된다. 한국어 번역 누락과 테스트 기대값·
실행 순서 의존 문제도 발견했다. 아래 결과는 모든 하드웨어 기능의 보증이 아니며,
고정 장비에서 실행한 실측과 회귀 검사 범위를 구분한다.

이번 작업은 검사와 기록이다. 애플리케이션 코드·운영 설정을 수정하거나 서비스를
재시작하지 않았다. 실제 마운트 연결·이동·Sync·GoTo·추적·가이딩 명령을 보내지 않았다.

## 실제 장비 결과

| 항목 | 결과 |
| --- | --- |
| MFNavis / GPSD / INDI Web Manager | active. MFNavis PID 1382 유지, `NRestarts=0` |
| 마운트 연결 | INDI Web Manager `status=False`, active profile 없음, 7624 수신 포트 없음 |
| 카메라 | RAW PNG와 LiveCam JPEG HTTP 200; 원본 uint16 / SRGGB12 / 1920×1080 |
| 연속 프레임 | 5초 간격 36개 표본 모두 다른 frame ID |
| 솔버 전처리 | 36/36 ready, 5프레임 버퍼. 표본 내 전처리 오류 없음 |
| 실제 솔빙 | 새 성공 시각 20개 관측. 성공 상태 14개, 실패 상태 22개 표본 |
| 솔빙 중단 후 회복 | 실패 후 성공 재관측. 마지막 성공 후 경과 시간 최대 66.35초 |
| GPS | 36/36 lock, 최초 3D fix; GPSD 2947 JSON 스트림 수신 |
| IMU | 36/36 sensor_healthy, 최초 fresh/usable, 오류 횟수 0, imuplus |
| SQM | 표본 15.017–15.094. 구름 아래 Radiometer 출력이며 정확도 교정 검증은 아님 |
| 웹·API | 공개 읽기 경로 12개 HTTP 200, 홈 Chromium 렌더링·장비 화면 이미지 확인 |
| 시스템 | 실패 systemd unit 0, `throttled=0x0`, 점검 시 66.4°C, swap 사용 0 |
| 저장 공간 | 루트 86% 사용, 4.1 GiB 여유. /dev/shm 약 1.4 MiB 사용 |

표본 기간은 175.83초이며 **14/36은 시도별 솔빙 성공률이 아니다**. 5초 사이의
전체 시도는 집계하지 않았다. 마지막 성공 시각에는 표본 시작 직전 성공도 포함될 수 있다.
`solve_state=true`가 유지돼도 최신 시도는 실패할 수 있으므로 LiveCam의
`solver.state`, `last_attempt`, `last_success`를 함께 확인했다.
솔루션에 남은 RMSE 범위는 약 134.85–179.24 arcsec이다. 구름·렌즈·검출·시간에
대한 비교 기준이 없으므로 이 값만으로 정확도 합격이나 Trixie 회귀를 판정하지 않는다.
회귀 테스트도 같은 장비에서 동시에 실행했으므로 성능 수치는 무부하 기준이 아니다.

읽기 API: `/`, `/api/status`, `/api/time`, `/api/location`, `/api/imu`,
`/api/sqm`, `/api/observation`, `/api/camera/controls`,
`/api/camera/raw-stack/status`, `/api/screen`, `/api/camera/raw`,
`/api/camera/raw-stack/image`. `/api/solution`도 최초 실시간 성공 응답을 확인했다.

## 회귀 검사

| 검사 | 결과 |
| --- | --- |
| 전체 비-Selenium 테스트, IMU 파일 별도 | **3508 passed, 18 failed, 3 skipped**, 242.33초 |
| IMU 오류·회복 모의 테스트 별도 | **3 passed** |
| 혜성 파일 독립 재현 | 2 passed, 5 failed — 전체 검사와 동일 예외 |
| 웹 언어·테마 파일 독립 재현 | 72 passed, 3 failed — 전체 검사 중 INDI 10개 실패는 독립 실행에서 통과 |
| Ruff lint | 통과 |
| Ruff format | 404 files already formatted |
| git diff --check | 통과 |

중복 재실행을 제외한 합계는 **3511 passed, 18 failed, 3 skipped**다.
처음 전체 수집은 샌드박스에서 `test_imu_runtime.py` import 중 GPIO 접근 거부로
중단됐다. 해당 파일을 제외해 전체를 실행하고, 실제 센서 생성 없이 모의 객체만
사용하는 IMU 테스트 3개를 샌드박스 밖에서 별도로 실행했다. 이를 장비 IMU 고장으로
분류하지 않는다.

Skip 3개: 구형 `~/PiFinder_data/observations.db`가 없는 복원 테스트 1개와,
일반 메뉴 순회로 실행할 수 없는 UIAlign 상태형 정렬 마법사 cold/warm 2개.

## 발견 사항

### 1. 혜성 일괄 계산 실패 — 실제 런타임 문제

운영 journal의 `comets.py:254 → skyfield/keplerlib.py:613`에서:

```text
VECTORIZED COMET PROPAGATION FAILED — using slow per-comet fallback
ValueError: cannot reshape array of size 2877 into shape (3,)
```

앱이 다수 궤도를 단일 시각에 전달하지만 설치된 Skyfield 1.55의 `propagate()`는
최종 모양을 `(3,) + t1.shape`로 지정한다. 단일 시각과 다수 혜성의 결과 크기가
일치하지 않는다. 실제 자료는 959개, 시험 fixture는 957개라 오류 크기가 다르다.
회귀 검사 5개와 운영 로그가 같은 실패 경로를 가리킨다. 예외 뒤 느린 혜성별
계산으로 전환하므로 추가 CPU 부하와 UI·솔빙 자원 경쟁의 원인이 될 수 있다.
직접 측정한 수정 전후 성능 비교는 없으며, Trixie OS 자체 결함으로 단정하지 않는다.

### 2. 한국어 번역 누락 — 독립 실행에서도 재현

`test_every_web_message_has_a_compiled_korean_translation`에서
`Applying network settings`의 한국어 번역 항목이 없다. 기존 미커밋 네트워크 화면
변경과 함께 확인된 문제다. 해당 메시지가 검사에서 최초로 발견된 누락이며,
다른 메시지가 모두 완전하다고 보장하지 않는다.

### 3. INDI 웹 테스트 10개 — 전체 실행에서만 실패

전체 검사에서 6개는 `onstep_device_name`에 MagicMock이 전달되어 JSON 직렬화가
실패했고, 4개는 비-OnStep 장치에서도 guide form이 있다고 판정했다.
동일 웹 언어·테마 파일을 새 pytest 프로세스로 실행하면 이 10개는 통과했다.
테스트 간 mock/상태 오염 또는 실행 순서 의존을 우선 조사해야 한다.
실제 INDI 웹 장애나 Trixie 고유 문제로 확정하지 않았다.

### 4. 웹 테마 기대값 2개 — 현재 템플릿과 불일치

- 테스트는 언어 선택기가 없어야 한다고 기대하지만 현재 UI에는 영어/한국어 선택기가 있다.
- 테스트는 CSS cache key `v=8`을 기대하지만 현재 템플릿은 `v=11`이다.

독립 실행에서도 재현된다. 이 실패만으로 실제 화면 고장을 뜻하지 않는다.
홈 화면은 실제 Chromium에서 표시됐다.

### 5. 마운트 미연결 조건과 설정의 차이

운영 설정 `mount_control=true`이지만 연결 프로필이 없어 시작 시
`No complete INDI or MFNavis OnStep connection configuration`이 기록됐다.
실제 마운트 연결은 관측되지 않았다. 기존 설정은 보존했다.

## 검증 한계

- 마운트 이동·추적·가이딩·실제 극축 정렬, 장비 회전이 필요한 IMU 보정은 미실행.
- 네트워크 모드 전환·재부팅·서비스 재시작·카메라 종류 전환은 진행 중인 관측을
  중단하므로 실제 적용하지 않았다. 해당 경로의 격리 회귀 테스트는 전체 검사에 포함된다.
- 문서의 기본 비밀번호로 실제 웹 인증이 되지 않았다. 보호된 14개 경로는 로그인
  화면으로 이동했으며, 내부 페이지 기능 통과로 집계하지 않았다.
- Selenium Grid/ChromeDriver가 준비되지 않아 `tests/website`는 제외했다.
  수동 Chromium headless로 공개 홈 렌더링을 확인했다. 초기 브라우저 시도는
  page-load timeout이었고 별도 프로필·프록시 비활성 재시도에서는 정상 표시됐다.
- GPSD CLI `gpspipe`는 PATH에 없어서 TCP JSON 프로토콜로 대체 점검했다.
- RAW 스택 활성화·노출/게인 변경·현장 설정 변경의 실물 A/B는 하지 않았다.
  관련 계산·설정·오류 처리는 격리 회귀 테스트 범위다.
- 구름량 센서 실측·맑은 하늘 대조군·장시간 안정성 검사는 없다. 날씨는 사용자 설명이다.

## 재현 및 원자료

원자료 디렉터리: `/home/mfnavis/trixie-fixed-cloudy-20260926/`.
GPS 위치·장비 화면·이미지가 포함되어 있으므로 Git에는 집계 보고서만 추가한다.

```bash
cd /home/mfnavis/MFNavis
source scripts/activate_dev_trixie.sh
nice -n 15 python -m pytest tests --ignore=tests/website \
  --ignore=tests/test_imu_runtime.py -q --tb=short
python -m pytest tests/test_imu_runtime.py -q --tb=short
python -m pytest tests/test_comets.py -q --tb=short
python -m pytest tests/test_web_language.py tests/test_web_theme_static.py -q --tb=short
```

주요 파일: `pytest-full.log`, `pytest-imu.log`, `pytest-comets-isolated.log`,
`pytest-web-isolated.log`, `collected.txt`, `live-samples.jsonl`, `live-summary.json`,
`http-check.jsonl`, `pages.json`, `gpsd.jsonl`, `journal-initial.log`,
`journal-test.log`, `service-final.txt`, `home-browser-retry.png`,
`api_screen.png`, `api_camera_raw.png`, `ruff.log`, `format.log`.
