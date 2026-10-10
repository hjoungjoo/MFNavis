# MFNavis 설치·개발 환경

기준: 2026-10-10 작업 트리. Raspberry Pi OS Trixie 64-bit / Python 3.13을 설치 기준으로 사용한다.
운영은 `.venv-trixie`, 개발·문서 검사는 `.venv-dev-trixie`를 사용한다.
아래 설치와 개발 절차를 한 곳에서 관리한다. 명령은 실행 위치를 확인하고 필요한 작업에만 사용한다.

| 구분 | 기준 |
|---|---|
| 소스 | `~/MFNavis/python/MFNavis`; `PiFinder`는 호환 import 이름 |
| 사용자 데이터 | `~/MFNavis_data`; 설치·갱신 시 기존 설정을 우선 |
| MFDS | 고정 바이너리 릴리즈와 `deployment/mfds.lock.json`; 내려받은 패키지를 수정하지 않음 |
| INDI | OS·아키텍처·Python/SOABI·checksum이 맞는 아카이브 |
| 개발 검사 | 활성화 후 `python/`에서 pytest·Nox·Ruff·Sphinx 실행 |

INDI 연결 및 이동 정책은 [마운트 제어](mount_control_ko.md),
오프라인 캐시는 [입력·웹·카탈로그](interfaces_ko.md),
보드별 UART·네트워크·시각은 [연결과 시간](connectivity_ko.md)을 함께 참조한다.
[MFDS 배포 절차](../MFDS_BINARY_DISTRIBUTION_ko.md)와
[경로 계약](../MFNAVIS_PATHS_ko.md)은 별도의 배포 기준이다.

## Trixie 설치와 첫 기동

[English](setup_en.md) | [한국어](setup_ko.md)

갱신일: 2026-10-04. 기본 설치 환경은 Raspberry Pi 4/Pi 5/CM5의
Raspberry Pi OS Trixie 64-bit / Python 3.13입니다. 보드 profile은 공통으로
지원하지만 이번 Trixie 실기 검증 장비는 Raspberry Pi 5입니다.
Pi 4와 CM5의 Trixie 실기 확인은 별도로 필요합니다. 이전 Bookworm 실측은
[과거 설치 기록](../history/development/setup.md#mf_bookworm_install_ko)에 보존합니다.

### OS 준비

Raspberry Pi Imager에서 **Raspberry Pi OS Trixie 64-bit**를 선택합니다.
첫 부팅 전에 사용자명, 장비별로 다른 호스트명, SSH, Wi-Fi를 설정하고,
해당 사용자로 로그인해 OS·Python·네트워크를 확인합니다.

```bash
cat /etc/os-release
python3 --version
hostname -I
nmcli device status
```

`VERSION_CODENAME=trixie`, Python 3.13이어야 합니다. 소스 경로는 해당 사용자의
`~/MFNavis`, 설정·관측 데이터 경로는 `~/MFNavis_data`입니다. 별도 데이터 경로는
`MFNAVIS_DATA_DIR=/absolute/path`로 지정하고 이후 설치·캐시 명령에도 같은 값을
사용합니다.

### MFNavis 설치·갱신

설치 대상 OS 사용자로 `sudo` 없이 실행합니다. 스크립트가 패키지·서비스 설정에
필요한 sudo 인증을 요청합니다. Trixie 기반 `main` 브랜치를 다음과 같이
설치·갱신합니다.

```bash
wget -O /tmp/mfnavis-setup.sh https://raw.githubusercontent.com/hjoungjoo/MFNavis/main/mfnavis_setup.sh &&
MFNAVIS_INSTALL_BRANCH=main bash /tmp/mfnavis-setup.sh
```

공개 버전은 [README의 태그 설치 절차](../../README_ko.md#2-mfnavis-설치-릴리즈-또는-main)를
따르고 해당 태그의 OS 요구사항을 확인합니다. 소스 업데이트만으로 Bookworm이
Trixie로 바뀌지는 않습니다. 새 Trixie OS를 준비하기 전에 `~/MFNavis_data`와
로컬 변경을 백업합니다.

기존 체크아웃은 tracked 변경이 없고 선택한 브랜치·태그로 fast-forward할 수
있어야 합니다. `mfnavis_update.sh`는 코드만 갱신하므로 패키지·서비스·OS 설정이
바뀌면 전체 설치 스크립트를 사용합니다.

설치 스크립트는 다음을 수행합니다.

- OS 패키지와 `deployment/mfds.lock.json`에 고정된 MFDS 바이너리를 설치합니다.
- `.local` 주소 접속에 필수인 `avahi-daemon`을 설치하고 자동 시작을 활성화합니다.
  설치·재설치 때 서비스를 재시작하며 실행 상태 확인에 실패하면 설치를 중단합니다.
- `--system-site-packages`로 `.venv-trixie`를 만들고
  Python 3.13에서 빌드할 수 없는 `python-libinput` 소스 패키지 대신
  piwheels의 고정 버전 wheel을 먼저 설치한 뒤 `python/requirements-trixie.txt`를
  설치합니다. Picamera2/GPIO는 OS 패키지를
  공유하며 Pi 5에서는 pip RPi.GPIO 대신 `python3-rpi-lgpio`를 사용합니다.
- Trixie/aarch64/Python 3.13 INDI 아카이브를 선택·검증하고 PyIndi와
  INDI Web Manager wheel을 앱과 같은 환경에 설치합니다. 아카이브와 `.sha256`이
  필요하며 분할 `.part-*` 파일은 재조립합니다.
- `mfnavis.service`, `mfnavis_splash.service`, GPSD, 하드웨어 접근 그룹,
  보드별 부트 설정과 장비 관리 권한을 구성합니다.
- 초기 NetworkManager/Netplan Wi-Fi 프로파일을 MFNavis 네트워크 설정으로
  가져오고, 재설치 때 기존 Wi-Fi 설정을 보존합니다.
- 설치 시작부터 `~/MFNavis_data/logs/setup-*.log`에 기록하고, 시스템 journal을
  최대 64 MiB의 영구 저장으로 설정해 재부팅 후 진단에 사용할 수 있게 합니다.

INDI 아카이브 설치는 기본적으로 필수입니다. 파일이 없거나 ABI·checksum이
맞지 않으면 앱 Python 설치와 GPS·네트워크 변경 전에 중단합니다. 앱의 마운트
제어는 별도로 켜기 전까지 꺼져 있습니다. INDI 없는 설치, 사용자 지정 아카이브와
드라이버 개발은 아래 INDI 설치 절을 참고합니다.
MFDS는 native child worker로 실행하므로 별도 Cedar 서비스가 필요하지 않습니다.

새 설치의 광학 기본값은 **IMX462 Color + 수동 초점거리 8.2409 mm**입니다.
하늘 실측 Brown–Conrady 보정은 `k1=-0.12`, `k2=k3=p1=p2=0`이며, 렌즈 키와
fingerprint가 맞는 활성 프로파일을 `default_config.json`에 함께 제공합니다.
초점거리는 화면상 약 8.24 mm라도 보정 조회를 위해 네 자리 정밀도로 저장합니다.
설치된 앱이 처음 설정을 읽을 때 자동 적용하므로 보정 파일을 따로 복사할 필요가
없습니다. 기존 `~/MFNavis_data/config.json`의 렌즈·보정 설정은 재설치·갱신 시
그대로 우선합니다. 다른 카메라·렌즈 조합에서는 Lens → Auto (Measure)와
Distortion → Measure Sky로 해당 장비를 측정합니다.

### 하드웨어·기동 확인

실제 부트 설정은 `/boot/firmware/config.txt`입니다.
[보드 연결 안내](connectivity_ko.md)에 따라 Pi 4는
`uart3` / `/dev/ttyAMA3`, Pi 5·CM5는 `uart2-pi5` / `/dev/ttyAMA2`를 사용합니다.
Pi 5 계열의 이 설정은 OLED GPIO8/9 충돌을 피합니다. SPI 디스플레이 선택은
`/dev/spidev0.0`과 `/dev/spidev10.0`을 지원합니다. CM5 IO 보드 CAM0에 연결한
IMX462는 오버레이의 `cam0` 파라미터가 필요할 수 있습니다.

설치가 끝나면 부트 오버레이와 사용자 그룹을 적용하도록 재부팅합니다.

```bash
sudo reboot
```

재접속 후 확인합니다.

```bash
systemctl status mfnavis mfnavis_splash indiwebmanager gpsd gpsd.socket avahi-daemon --no-pager
journalctl -u mfnavis -b -n 100 --no-pager
~/MFNavis/.venv-trixie/bin/python -c 'import sys, PyIndi; print(sys.version)'
```

MFNavis는 `http://<hostname>.local`, INDI Web Manager는 같은 주소의 `8624`
포트로 접속합니다. GoTo 전에 디스플레이·키패드·카메라·GPS 위치와 시각·네트워크를
확인합니다. 런타임·오프라인 이미지 캐시는 다음으로 준비합니다.

```bash
cd ~/MFNavis
python3 scripts/warm_mfnavis_caches.py
```

이 명령은 `.venv-trixie`를 자동 선택합니다. POSS+SDSS 전체 캐시에는 최소 6 GB의
여유 공간을 확보합니다. [오프라인 캐시 안내](interfaces_ko.md)를 참고합니다.

### 개발 환경·문서 검사

설치가 완료된 체크아웃에서 실행합니다.

```bash
cd ~/MFNavis
bash scripts/setup_dev_trixie.sh
source scripts/activate_dev_trixie.sh
nox --no-venv -s lint format
nox --no-venv -s unit_tests
nox --no-venv -s docs
```

활성화하면 `.venv-dev-trixie`, Python 3.13, 별도 개발 데이터·runtime 경로를
선택하고 `python/`으로 이동합니다. `requirements_dev-trixie.txt`와
`requirements_docs-trixie.txt`를 사용합니다. INDI wheel, GPIO 처리, 디버깅과
독립 Nox 세션은 [Trixie 개발 안내](setup_ko.md)에 정리되어 있습니다.

### 검증 범위

사용자는 2026-09-27 Trixie GoTo 실테스트에서 큰 문제를 발견하지 못했다고
보고했습니다. 이는 해당 현장 사용 결과이며 모든 보드·마운트 기능의 검증 완료를
뜻하지는 않습니다. 앞선 상세 점검과 수정은 [실측 보고서 목록](../mf_report/README.md)의
시리얼 Auto 탐색, 솔빙 실패 전환, Sync 확인 응답, INDI 제한값 기록을 참고합니다.
[2026-09-26 배포 기록](../history/development/setup.md#TRIXIE_20260926_ko)은 그 날짜의 결과와 제한을 보존하며
이후 현장 시험 결과와 구분합니다.



## INDI 아카이브·개발 설치

전체 setup의 기본 `MFNAVIS_INSTALL_INDI_ARCHIVE=true`는 아카이브 설치를 필수로 수행한다.
다른 아카이브는 `MFNAVIS_INDI_ARCHIVE=/절대/경로`로 지정한다.
INDI를 사용하지 않는 별도 설치는 명시적으로 `false`를 지정한다.

```bash
MFNAVIS_INSTALL_INDI_ARCHIVE=false bash "$HOME/MFNavis/mfnavis_setup.sh"
```

이미 설치된 Trixie 앱의 INDI만 갱신하거나 설치 전에 검사할 때:

```bash
cd ~/MFNavis
bash scripts/install_indi_mount_archive.sh \
  dist/mfnavis-indi-trixie-arm64-v2.2.3.1-current.tar.gz --verify-only
MFNAVIS_PYTHON="$PWD/.venv-trixie/bin/python" \
  bash scripts/install_indi_mount_archive.sh \
  dist/mfnavis-indi-trixie-arm64-v2.2.3.1-current.tar.gz
```

전체 아카이브 대신 `.part-*`와 `.sha256`이 함께 있어도 같은 경로를 넘긴다.
설치기는 checksum·OS·Python ABI·안전한 경로와 디스크 여유를 검사한다.
파일 교체 전에 INDI 파일·가상환경·서비스 설정을 백업하고 실패 시 복원한다.
전원 차단/SIGKILL이나 복원 실패는 로그에 남긴 rollback 경로를 사용해 수동 복구한다.
설치 로그는 `~/MFNavis_data/logs/indi-install-*.log`에 보관한다.

드라이버 소스나 패치를 변경할 때는 앱 개발과 INDI 네이티브 빌드를 구분한다.

```bash
cd ~/MFNavis
MFNAVIS_PYTHON="$PWD/.venv-trixie/bin/python" \
  INDI_WEB_EXEC="$PWD/.venv-trixie/bin/indi-web" \
  bash scripts/install_indi_mount_OnstepX.sh
bash scripts/package_indi_mount_archive.sh
```

소스 빌드와 패키징은 필요한 경우에만 실행한다. 설치 결과와 아카이브의 플랫폼·
patch checksum을 함께 기록한다. 연결·GoTo 설정은 [마운트 제어](mount_control_ko.md)를 따른다.

## 개발 도구와 검사

Raspberry Pi 5 / Trixie arm64 / Python 3.13에서 개발 환경을 구성한다.
현재 OS의 Python 헤더, gcc/g++, make, CMake, SWIG, pkg-config를 사용한다.
운영 서비스는 `.venv-trixie`, 개발 도구는 `.venv-dev-trixie`를 사용한다.

### 설치와 활성화

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

### 도구와 의존성

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

### 검사와 디버깅

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

### CI 검사 범위

`main` push와 PR에서 Python 3.13의 lint·format·Sphinx 문서 빌드 및
INDI 아카이브 플랫폼·검증·설치 선택 테스트를 실행한다. 이 검사는 arm64
wheel이나 Pi 장비 없이 실행할 수 있는 범위다. 전체 앱 회귀는 설치된
Trixie 개발 환경에서 실행하며, 기존 Python 3.11 CI는 Bookworm 호환성을
확인한다. 수동 실행하는 Selenium workflow도 기존 Python 3.11 환경이다.

### Graft와 셸 검사

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



## IMX678 준비와 검증 범위

MFNavis는 IMX678의 **Linux upstream 드라이버와 공식 Raspberry Pi libcamera**를
사용한다. 현재 Raspberry Pi OS 커널 패키지에 없는 IMX678 드라이버는 Linux
공식 소스를 변경하지 않고 DKMS 모듈로 빌드한다. MFNavis의 Raspberry Pi용
오버레이와 설치 스크립트는 별도 통합 코드이며, Raspberry Pi가 배포하는
공식 IMX678 패키지라는 뜻은 아니다.

- Linux 소스: [bf40cc53b1e00c312046f6dd88e9054bc91865af](https://github.com/torvalds/linux/commit/bf40cc53b1e00c312046f6dd88e9054bc91865af)
- 출처·해시·라이선스: [deployment/imx678](../../deployment/imx678/README.md)
- libcamera: [0.7.2부터 IMX678 helper 포함](https://lists.libcamera.org/pipermail/libcamera-devel/2026-July/060247.html)
- 검증 기준: Pi 5 / Trixie 64-bit / `6.18.50+rpt-rpi-2712`,
  libcamera `0.7.2+rpt20260817-1`, Picamera2 `0.3.37-1`.

### 지원 범위

| 항목 | 구성 |
| --- | --- |
| RAW | 3856×2180, 12bit, 비닝 없음 |
| 흑백·컬러 | 드라이버의 센서 ID 판독과 RAW 모드로 자동 구분 |
| MFNavis 프로파일 | 흑백 `imx678` / 컬러 `imx678_color` |
| 프리뷰·중앙 솔빙 영역 | 2180×2180 중앙 영역, Bayer 위상 보존 |
| 전체 프레임 검출 | 3856×2180 RAW 전달, PiSP 행 패딩 제거 |
| 노출·게인 | 기존 수동/자동 노출 경로, 기본 아날로그 게인 30배 |
| HCG/LCG 자동 전환·HDR | 이 통합에서는 사용하지 않음 |
| 튜닝·SQM | 공식 generic 튜닝으로 시작, 센서별 측정 보정은 미완료 |

IMX678 전용 공식 튜닝 JSON은 아직 배포되지 않는다. 설치 스크립트는 공식
`uncalibrated.json`을 그대로 `imx678.json`으로 복사한다. 별도 보정 파일이
이미 있으면 덮어쓰지 않는다. 이는 촬영 파이프라인 초기화용이며 색 정확도나
SQM 정확도를 보장하지 않는다. 별 검출은 ISP 처리 영상 대신 RAW를 사용한다.
프로파일의 측정되지 않은 bias/noise/광도 보정값은 0으로 남기며, 다른 센서의
보정값을 복사하지 않는다. 실제 장치에서 dark/bias와 SQM을 보정해야 한다.

### 하드웨어 없이 소프트웨어 준비

저장소에서 실행한다. 커널 헤더가 현재 커널과 일치해야 한다.

```bash
cd ~/MFNavis
bash scripts/install_imx678.sh --build-only /tmp/imx678-build
sudo bash scripts/install_imx678.sh --install
bash scripts/install_imx678.sh --check
```

`--install`은 필요시 DKMS·빌드 도구·커널 헤더를 설치하고, 모듈·오버레이·
generic 튜닝·메뉴 전환 권한을 준비한다. 현재 카메라를 중지하거나
`config.txt`를 변경하거나 재부팅하지 않는다. DKMS는 이후 커널 업데이트 시
재빌드를 시도한다. 새 커널에서의 빌드 성공 여부는 업데이트 후 확인한다.

전체 설치 시에는 `MFNAVIS_INSTALL_IMX678=true`를 지정해 같은 준비를 포함할
수 있다. 기본 카메라 선택은 기존 설정을 유지한다.

### 실제 모듈 연결 후

1. 전원을 끈 상태에서 카메라를 연결한다.
2. 기본 연결은 **CAM1, 2레인, XCLK 24 MHz**다. 다른 연결은 아래 오버레이
   옵션을 먼저 지정한다.
3. MFNavis를 업데이트한 뒤 앱을 다시 시작해야 새 메뉴가 나타난다.
   `Settings > Advanced > Camera Type > IMX678 (Auto)`를 선택한다.
   부팅 설정을 전환하고 재부팅한다. 이전 카메라의 `camera_variant` 값은
   IMX678에 적용되지 않는다.
4. 초점을 맞춘 후 `Lens > Auto (Measure)`와 `Distortion > Measure Sky`를
   다시 실행한다. 이전 센서·렌즈 조합의 수동 초점거리나 보정을 그대로
   신뢰하지 않는다.

하드웨어를 바꾼 직후 기존 센서 설정 때문에 앱 메뉴가 열리지 않으면 SSH로:

```bash
sudo /usr/bin/python3 /usr/local/lib/mfnavis/switch_camera.py imx678
sudo reboot
```

#### CAM0·4레인·입력 클록 설정

`/boot/firmware/config.txt`의 `[all]` 아래, 카메라 선택 **전에 주석으로**
원하는 설정을 넣을 수 있다. 메뉴 전환은 이 줄의 옵션을 보존해 활성화한다.

```ini
## CAM0, 4레인 예시
#dtoverlay=imx678-mfnavis,cam0,4lane
```

| 옵션 | 의미 |
| --- | --- |
| 생략 | CAM1 / 2레인 / XCLK 24 MHz / link-frequency 445500000 Hz |
| `cam0` | CAM0 사용 |
| `4lane` | 센서·수신기 모두 4레인 |
| `clock-frequency=37125000` | 센서 입력 클록 설정 예시 |
| `link-frequency=720000000` | MIPI DDR 링크 주파수 설정 예시 |

`imx678-mfnavis`는 기존 외부 업체의 `imx678` 오버레이와 구분되는 이름이다.
일반 Raspberry Pi 케이블/모듈 전원 구성을 전제로 하며, 별도 보드의 전원·
리셋 배선에 대한 오버레이 조정은 해당 하드웨어에 맞춘다.

### 최초 촬영 확인

먼저 `rpicam-hello --list-cameras`에서 IMX678과 3856×2180 RAW12 모드를
확인한다. 다음 단독 촬영 검사는 앱과 카메라 사용이 겹치지 않도록 한다.

```bash
sudo systemctl stop mfnavis.service
rpicam-still -n -t 1000 --raw --shutter 100000 --gain 10 -o /tmp/imx678.jpg
sudo systemctl start mfnavis.service
```

완료 여부는 센서 인식, RAW 저장, 노출·게인 응답, 연속 촬영, 별 검출·솔빙,
실제 렌즈 화각 측정으로 확인한다. 설치 스크립트의 `--check`는 파일·모듈
준비 상태만 확인하며 실제 촬영 성공을 뜻하지 않는다.

### 이번 검증과 남은 확인

- 공식 소스 SHA-256 일치, 현재 커널 모듈 빌드 성공.
- 테스트 장비에 `mfnavis-imx678/0.1.0` DKMS 설치 및 `modprobe imx678`
  성공. `--check` 통과, `/sys/module/imx678` 확인. IMX462 부팅 설정 유지.
- Pi 5 DTB에 CAM0/CAM1 × 2/4레인 네 조합의 오버레이 병합 성공.
- 센서 식별·프로파일·RAW 패딩·카메라 전환·권한 및 기존 카메라/SQM/
  렌즈/LiveCam 관련 테스트 **308개 통과**. Ruff 및 ShellCheck 통과.
- 실제 IMX678은 미연결: I2C probe, MIPI 전송, 노출 시간, 처리 속도,
  색·광도 보정과 야간 솔빙은 아직 실측하지 않음.

8.4MP 전체 RAW는 IMX462보다 데이터량이 많다. 하드웨어가 준비되기 전에는
초당 처리 프레임 수나 솔빙 성능을 확정할 수 없다.
