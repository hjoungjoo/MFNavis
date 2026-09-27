# 2026-09-27 Trixie → main 병합 점검

원격을 fetch한 결과 `main`은 `e10407c0`, 검증한 Trixie 기능 커밋은
`39a57168`이었다. `main`에만 있는 커밋은 없고 Trixie에 13개가 추가되어 있어
기존 커밋을 모두 보존하는 fast-forward 병합이 가능했다.

## 보완한 누락

- 한국어·영어 설치 문서를 Trixie 64-bit / Python 3.13 기준으로 갱신하고,
  병합 전 임시 브랜치 안내를 `main` 설치 명령으로 정리했다. 과거 Bookworm
  설치·실측 기록은 당시 OS를 보존하고 현재 매뉴얼로 연결했다.
- INDI 문서의 초기 통합 범위 설명을 현재 GoTo 복구·미세보정·제한값 설정에
  맞췄다. 소스 빌드 예제에도 앱 Python과 Web Manager의 가상환경을 명시했다.
- GitHub Actions에 Python 3.13 lint·format·Sphinx 및 INDI 아카이브/설치 검사
  job을 추가했다. 전체 Python 3.11 CI는 Bookworm 호환성 검사로 유지한다.
  arm64 INDI wheel과 Pi OS 패키지가 필요한 전체 Trixie 앱 회귀는 실장비의
  개발 가상환경에서 실행한다.
- Trixie 타입 검사에서 발견한 6개 파일의 7개 오류를 보완했다. 독립 실행하는
  카메라 보조 스크립트의 import 경로를 타입 검사와 구분하고, NumPy/Pillow의
  배열·픽셀·노출값 타입을 명시했다. 백래시 통계의 상한 None 검사도 명시했다.

## 검증 결과

Raspberry Pi 5 / Trixie / Python 3.13의 `.venv-dev-trixie`를 사용했다.

- 전체 비-Selenium 회귀: **3,644 passed / 3 skipped**, 187.35초.
- 타입 보완 후 관련 회귀: **357 passed**, 7.51초.
- CI에 추가한 플랫폼·아카이브·설치 선택 검사: **41 passed**.
  위 테스트 수는 서로 겹치므로 합산하지 않는다.
- `nox --no-venv -s lint format type_hints docs` 모두 통과했다.
  Ruff format은 428개 파일, mypy는 213개 소스 파일을 검사했다.
  Sphinx는 경고를 오류로 처리하는 `-n -W --keep-going -E` 설정을 사용했다.
- 변경한 셸 스크립트 15개 `bash -n`, workflow YAML·셸 명령 구문,
  수정 문서의 로컬 파일 링크와 `git diff --check`를 확인했다.
- Trixie INDI 아카이브 조각 4개가 모두 Git에 포함되어 있고 재조립한 바이트의
  SHA-256이 배포 sidecar와 일치했다:
  `f8ff56905e3499a2d340297771d61e8729ce4d11a4843751bbe19e8c082bea12`.
- Cedar-free 배포 구성 검사도 통과했다.

전체 회귀의 3개 skip은 테스트용 observations DB가 없는 사례 1개와 실제
solve·정렬별 순서를 요구하는 UIAlign 사례 2개다. Selenium 및 실제 하드웨어
import를 요구하는 `test_imu_runtime.py`는 전체 회귀에서 제외했다.
외부 라이브러리·multiprocessing 관련 warning 20개가 있었으며 테스트 실패는
없었다. 사용자 GoTo 실테스트 결과는 [별도 기록](mfnavis_trixie_goto_field_20260927_ko.md)을
따른다. 이번 병합 점검에서 마운트를 움직이거나 운영 서비스를 재시작하지 않았다.

검사 로그와 JUnit XML은 장비의 `/tmp/mfnavis-trixie-merge/`에 저장했다.
