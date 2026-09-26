# Trixie 개발 환경

Raspberry Pi 5 / Trixie arm64 / Python 3.13에서 개발 환경을 구성한다.
현재 OS의 Python 헤더, gcc/g++, make, CMake, SWIG, pkg-config를 사용한다.
운영 서비스는 `.venv-trixie`, 개발 도구는 `.venv-dev-trixie`를 사용한다.

## 설치와 활성화

MFNavis와 INDI 네이티브 런타임이 설치된 체크아웃에서 일반 사용자로 실행한다.

```bash
cd ~/MFNavis
bash scripts/setup_dev_trixie.sh
source scripts/activate_dev_trixie.sh
```

활성화하면 작업 디렉터리가 `~/MFNavis/python`으로 바뀐다. Python 모듈 경로,
Nox Python 3.13 선택, 개발용 데이터·runtime 디렉터리도 설정한다.

| 항목 | 위치 |
| --- | --- |
| 개발 Python | `~/MFNavis/.venv-dev-trixie/bin/python` |
| 개발 데이터 | `~/MFNavis_dev_data` |
| 개발 runtime | `/tmp/mfnavis-dev-<UID>` |
| INDI/Python wheelhouse | `~/MFNavis/.dev-indi` |
| Node.js·Graft·rg·ShellCheck | `~/.local/bin` |
| 설치·검증 로그 | `~/.cache/mfnavis-dev-setup` |

다른 개발 데이터 경로는 활성화 전에 `MFNAVIS_DEV_DATA_DIR`, runtime 경로는
`MFNAVIS_DEV_RUNTIME_DIR`로 지정한다. `deactivate`는 Python PATH를 복구하며,
개발용 환경변수까지 초기화하려면 새 셸을 연다.

## 도구와 의존성

- Ruff 0.4.8, Nox 2024.4.15, pytest 8.4.2, mypy 1.15.0, pre-commit 3.7.1.
- debugpy 1.8.16, Babel 2.16.0, Selenium 4.15.0 및 타입 stubs.
- Sphinx 8.2.3, sphinx-rtd-theme 3.0.2, sphinxcontrib-mermaid 1.0.0.
- Node.js 22.23.2, npm 10.9.8, Graft 0.18.0.
- ripgrep 14.1.1, ShellCheck 0.10.0.

Bookworm의 `requirements_dev.txt`는 Bookworm 런타임을 포함하므로 이 환경에서는
`requirements_dev-trixie.txt`를 사용한다. Sphinx와 pytest/mypy도 Python 3.13에
맞는 버전을 지정했다. pandas 타입 stubs는 실행 버전 2.3.3과 맞췄다.

개발 설치 스크립트는 INDI 아카이브의 checksum·OS·SOABI를 먼저 검증하고,
PyIndi와 커스텀 INDI Web Manager wheel을 가상환경에 설치한다. 전체 tarball과
분할 아카이브를 지원한다. `.dev-indi/python-custom.txt`의 절대 경로는 설치할 때
생성하므로 다른 체크아웃으로 이동한 뒤에는 설치 스크립트를 다시 실행한다.

Python 3.13에서 `imp` 모듈을 사용하는 `python-libinput`의 구형 sdist가 빌드되지
않아 piwheels의 순수 Python wheel을 사용한다. Pi 5에서는 pip의 구형 RPi.GPIO를
제거하고 OS의 rpi-lgpio 모듈을 사용한다. 시스템 Picamera2/GPIO 접근을 위해
가상환경과 Nox 세션에 `--system-site-packages`를 설정한다.

## 검사와 디버깅

활성화한 `python/` 디렉터리에서 실행한다.

```bash
python -m pytest tests/test_setup_indi_archive.py tests/test_mountcontrol_indi.py -q
nox -s lint format
nox -s unit_tests
nox -s docs
```

Nox는 Python 3.13에서 Trixie 개발·문서 requirements를 선택하고, 별도 세션
가상환경에도 INDI wheel을 설치한다. `MFNAVIS_DEV_USE_OS_GPIO=1`이면 세션의
pip RPi.GPIO를 제거한다. 활성화 스크립트가 장치 종류에 맞게 이 값을 설정한다.

이미 설치한 개발 가상환경을 그대로 사용하려면 `nox --no-venv -s lint format`처럼
`--no-venv`를 지정한다. 선택한 테스트만 실행하는 예:

```bash
nox --no-venv -s unit_tests -- tests/test_setup_indi_archive.py tests/test_mountcontrol_indi.py
```

개별 검사도 가능하다.

```bash
python -m ruff check MFNavis tests noxfile.py
python -m mypy MFNavis
python -m debugpy --listen 127.0.0.1:5678 --wait-for-client \
  -m pytest tests/test_mountcontrol_indi.py -q
```

마지막 명령은 IDE의 debugger가 연결될 때까지 기다린다. 개발용 앱 실행은
동일 장치의 카메라·GPIO·웹 포트를 사용하는 운영 서비스와 실행 시간을 조정한다.
Selenium 브라우저 검증에는 저장소 테스트 안내의 별도 Selenium Grid가 필요하다.

## Graft와 셸 검사

```bash
cd ~/MFNavis
DO_NOT_TRACK=1 graft map
DO_NOT_TRACK=1 graft ask "mountcontrol_indi" --source
DO_NOT_TRACK=1 graft check
shellcheck -S warning scripts/setup_dev_trixie.sh scripts/activate_dev_trixie.sh
```

현재 장비에는 `~/.local/lib`에 공식 arm64 Node 배포본을 checksum 검증 후 설치했고,
npm의 프로젝트 지정 Graft 0.18.0과 Debian Trixie ripgrep/ShellCheck 패키지를
사용자 디렉터리에 설치했다. 로그인 셸은 `~/.profile`의 `~/.local/bin` 설정을
사용한다. Graft 텔레메트리는 껐고 구조 인덱스를 생성했다.

MFDS는 고정된 바이너리 릴리즈를 사용한다. 다운로드된 `python/MFDS` 파일은
개발 소스가 아니며, MFDS 변경은 별도 정본 저장소에서 진행한다.

## 현재 장비 검증 기록 (2026-09-26)

- 개발 Python 3.13.5에서 PyIndi, Picamera2, NumPy, pandas, SEP, quaternion,
  debugpy import와 OS rpi-lgpio 경로를 확인했다.
- Nox 단위 테스트 288개와 단위 마커 밖의 관련 테스트 19개가 통과했다.
  총 307개이며, 개발 가상환경에서 실행했다.
- 전체 Ruff lint 및 421개 Python 파일 format 검사, Sphinx 경고를 오류로 처리하는
  문서 빌드가 통과했다. 일반 Nox Python 3.13 가상환경 생성과 lint도 통과했다.
- 셸 구문, ShellCheck, `git diff --check` 검사를 통과했다. Graft 인덱스를 생성했다.
- MFNavis, INDI Web Manager, GPSD는 active이며 두 웹 서비스 HTTP 200을 확인했다.

`pip check`에는 공유한 OS 패키지에서 비롯된 진단 7개가 남는다. 운영 환경에서도
같은 진단을 확인했고, 개발 환경에서는 기존 pandas-stubs 누락 진단 한 개를
해결했다. 따라서 전체 `pip check` 성공으로 보고하지 않는다.

- Blinka의 RPi.GPIO 배포판 요구: Pi 5에서는 실제 동작하는 OS rpi-lgpio API를 사용한다.
- OS apt-listchanges의 debconf Python 패키지 metadata 요구.
- OS 타입 stub의 Flask-SQLAlchemy, matplotlib, tree-sitter 요구.
- OS h2의 hpack/hyperframe 버전 요구.

도구 버전·Python 경로·진단 목록은
`~/.cache/mfnavis-dev-setup/manifest.json`에 기록했다. 상세 로그는
`python-install.log`, `nox-quality.log`, `nox-tests.log`, `additional-tests.log`,
`additional-archive-tests.log`, `nox-docs.log`, `nox-isolated-lint.log`,
`pip-check.log`와 `production-pip-check.log`다.

개발 설치 requirements, 설치·활성화 스크립트, Nox 설정과 문서는
Trixie 브랜치에서 함께 관리한다.
