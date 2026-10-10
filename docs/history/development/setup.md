# 설치·개발 환경 — 이전 설계와 조사 기록

> 2026-10-10 통합 보관. 아래 본문의 “현재/현행”, 기본값, 완료 상태와 명령은 원문 작성 당시 기준이다.
> 오늘의 동작은 [개발 기준 문서](../../mf_dev/README.md)를 따른다. 이력에 적힌 절차를 현재 설치 절차로 사용하지 않는다.

- [TRIXIE_20260926_ko.md](#TRIXIE_20260926_ko)
- [TRIXIE_DEVELOPMENT_ko.md](#TRIXIE_DEVELOPMENT_ko)
- [mf_bookworm_install_ko.md](#mf_bookworm_install_ko)
- [mf_imx678_ko.md](#mf_imx678_ko)
- [mf_pifinder_new_device_tasks_ko.md](#mf_pifinder_new_device_tasks_ko)
- [mf_pifinder_rpi4_pi5_compatibility_ko.md](#mf_pifinder_rpi4_pi5_compatibility_ko)
- [mf_trixie_install_ko.md](#mf_trixie_install_ko)


---

<a id="TRIXIE_20260926_ko"></a>

## TRIXIE_20260926_ko.md

<a id="TRIXIE_20260926_ko--trixie-브랜치-설치배포-기록"></a>
## Trixie 브랜치 설치·배포 기록

2026-09-26, Raspberry Pi 5 / Debian 13 Trixie arm64 / CPython 3.13.5에서
확인했다. 기준 MFNavis main 커밋은
`e10407c0662fbf3141cc1a28611a64f7985d0679`이다.

<a id="TRIXIE_20260926_ko--포함한-변경"></a>
### 포함한 변경

| 영역 | 배포 내용 |
| --- | --- |
| 앱 Python | `python/requirements-trixie.txt`로 Python 3.13 패키지 버전 고정. `.venv-trixie`에서 OS Picamera2/GPIO 패키지를 공유한다. Pi 5에서는 Blinka가 설치한 구형 RPi.GPIO를 제거하고 `python3-rpi-lgpio`를 사용한다. |
| NumPy 2 | Tetra3의 `np.math.factorial`을 표준 `math.factorial`로 변경한다. |
| 장치 타입 선택·재시작 | 비대화형·비동기 `systemctl` 재시작 요청과 해당 명령만 허용하는 sudoers 설치를 추가한다. 재시작 실패는 UI 메시지와 웹 HTTP 503으로 처리한다. |
| 전체 설치 | OS에 맞는 INDI 아카이브를 필수로 선택·검증·설치한다. Trixie 앱, splash, INDI Web Manager가 같은 가상환경을 사용한다. 소스 빌드로 자동 대체하지 않는다. |
| 아카이브 플랫폼 | Bookworm/aarch64/Python 3.11 및 Trixie/aarch64/Python 3.13 지원. checksum, 안전한 멤버 경로, OS, Python 버전과 SOABI를 확인한다. |
| Trixie 패키징 | 현재 설치된 PyIndi/Web Manager를 재배치 가능한 wheel로 포장하고 의존성 wheel 26개와 ELF에서 수집한 apt 런타임 패키지 71개를 포함한다. `wsproto==1.2.0`을 추가한다. |
| 설치 보호 | usrmerge 심볼릭 링크를 유지한다. 파일 교체 전 실행 중인 앱·Web Manager를 정지하고 작업 성공·실패 후 복구한다. |
| 테스트 | 실제 운영 INDI 프로필과 격리한 fixture, 플랫폼·아카이브·전체 설치 선택·재시작 회귀 테스트를 포함한다. |

이 브랜치에는 기존 Bookworm 아카이브 조각도 유지한다. 다운로드된 MFDS 패키지는
수정하거나 커밋하지 않았다. 장치에 적용한 systemd 가상환경 override와 재시작
sudoers 규칙은 설치 스크립트가 다시 생성한다. 장치 전용 설치 조정본과 복구
wrapper가 수행하는 변경도 이 설치 경로에 포함돼 있다.

<a id="TRIXIE_20260926_ko--trixie-아카이브"></a>
### Trixie 아카이브

배포 경로: `dist/mfnavis-indi-trixie-arm64-v2.2.3.1-current.tar.gz`.
전체 tarball은 194,139,872 bytes (185.15 MiB)다. Git에는 다음 파일을 포함하며,
설치 시 `/var/tmp`에 재조립한다.

- `.tar.gz.part-00`, `.part-01`, `.part-02`: 각 49,283,072 bytes.
- `.tar.gz.part-03`: 46,290,656 bytes.
- `.tar.gz.sha256`: 재조립한 tarball의 SHA-256.

```text
f8ff56905e3499a2d340297771d61e8729ce4d11a4843751bbe19e8c082bea12
```

INDI core/third-party v2.2.3.1, MFNavis OnStepX 패치, PyIndi 2.1.2,
커스텀 INDI Web Manager 1.0.0을 포함한다. SOABI는
`cpython-313-aarch64-linux-gnu`, 형식은 `mfnavis-indi-binary-v2`다.
아카이브 metadata에는 소스 커밋, 패치, 라이선스, 설치 manifest, 빌드 플래그,
패키지 버전과 독립적으로 사용할 수 있는 설치 도구도 들어 있다.

<a id="TRIXIE_20260926_ko--설치"></a>
### 설치

일반 OS 사용자로 실행한다. 스크립트가 필요한 단계에서 sudo 인증을 요청한다.

```bash
wget -O /tmp/mfnavis-setup.sh https://raw.githubusercontent.com/hjoungjoo/MFNavis/Trixie/mfnavis_setup.sh
MFNAVIS_INSTALL_BRANCH=Trixie bash /tmp/mfnavis-setup.sh
```

이후 해당 설치를 업데이트할 때도 `MFNAVIS_INSTALL_BRANCH=Trixie`를 지정한다.
아카이브를 다른 곳에 둘 때는 `MFNAVIS_INDI_ARCHIVE`로 절대 경로를 지정한다.
기존 체크아웃의 tracked 변경과 fast-forward 제한은 그대로 유지한다.

설치 없이 아카이브를 검증하려면:

```bash
cd ~/MFNavis
bash scripts/install_indi_mount_archive.sh \
  dist/mfnavis-indi-trixie-arm64-v2.2.3.1-current.tar.gz --verify-only
```

기존 설치에서 재시작 권한만 복구하려면:

```bash
cd ~/MFNavis
bash scripts/install_service_control.sh "$(id -un)"
sudo systemctl restart mfnavis.service
```

<a id="TRIXIE_20260926_ko--검증과-제한"></a>
### 검증과 제한

- 앱 설치 단계에서는 계산·마운트·솔버·카메라 RAW 등 선택 테스트 412개가 통과했다.
- 아카이브 제작 후 플랫폼·아카이브·마운트 테스트 199개가 통과했다.
- 설치 스크립트 통합 후 설치 브랜치 선택·아카이브·마운트·재시작 테스트 232개가
  통과했다. 이 수치는 서로 겹치는 테스트 실행이므로 합산하지 않는다.
- 브랜치 배포 전 `test_sys_utils.py`, `test_server_login_account.py`까지 포함한
  최종 관련 테스트 307개가 통과했다. 변경한 Python 파일의 Ruff 0.4.8 lint·format,
  셸 구문, `git diff --check` 검사와 분할 아카이브 SHA-256 검사를 통과했다.
- 전체 tarball, 분할 조각만 있는 경로, 동봉한 설치 도구에서 실제 검증이 통과했다.
  시스템 패키지를 공유하지 않는 새 가상환경에 wheel을 오프라인 설치하고
  `pip check`가 성공했다.
- 아카이브의 네이티브 실행 파일과 새 PyIndi를 실제 사용해 시뮬레이터
  GoTo·이동 중 Stop, Web Manager 프로필 시작·장치 조회·종료, 장치 페이지,
  WebSocket 업그레이드·ping/pong을 확인했다. OnStepX는 DRIVER_INFO 응답을 확인했다.
- Flat V3 선택 후 `Restarting...`에서 멈추던 sudo 인증 오류를 수정하고,
  인증 캐시 없이 서비스 재시작 성공·설정 보존·메인 UI 복구를 확인했다.
  IMX462는 재부팅 후 센서 조회와 Picamera2 초기화가 성공했다.
- 운영 MFNavis, INDI Web Manager, GPSD는 active다. 두 웹 서비스 HTTP 200을 확인했다.
  새 아카이브로 운영 `/usr`를 다시 덮어쓰는 전체 재설치는 수행하지 않았다.
- 실제 OnStepX 마운트 연결과 Bookworm/Pi 4 물리 검증은 수행하지 않았다.
- 시뮬레이터 Sync+GoTo의 좌표 승인 시간 초과는 미해결이다. 기존 Web Manager가
  사용자 지정 INDI 포트를 적용하지 않는 문제도 미해결이며, Web Manager 검증은
  기본 INDI 포트 7624를 사용했다.
- Graft 실행 파일이 없어 그래프 기반 검사·갱신은 수행하지 못했다.

원본 장치 로그와 상세 결과는 `/home/mfnavis/`의 `mfnavis-trixie-report.md`,
`indi-archive-diagnostic.md`, `indi-trixie-archive-report.md` 및 관련 JSON·로그에
보존돼 있다. 이 문서는 배포 시점의 변경과 결과를 정리한 기록이다.

<a id="TRIXIE_20260926_ko--현장-사용을-위한-서비스-권한-2026-09-26-보완"></a>
### 현장 사용을 위한 서비스 권한 (2026-09-26 보완)

AP+STA 적용 시 `/network/update`가 HTTP 500으로 실패한 원인은 서비스
계정에 `sudo cp /tmp/hostapd.conf /etc/hostapd/hostapd.conf`의 비대화형
실행 권한이 없었기 때문이다. 앱 재시작 권한만 설치되어 있어 다른 장비
관리 명령도 같은 인증 오류가 발생할 수 있었다.

`mfnavis_setup.sh`는 최초 설치 시 `scripts/install_runtime_control.sh`를
서비스 계정으로 호출한다. `/etc/sudoers.d/90-mfnavis-runtime-control`을
`visudo`로 검증하고 root 소유·0440 모드로 설치한다. 네트워크 설정 파일
저장, AP/Client/AP+STA 전환, Wi-Fi 검색·연결·복구, GPS 설정, INDI 서비스
제어, 카메라 선택, 재부팅·종료와 Bluetooth 페어링의 Wi-Fi 복구를 포함한다.
기존 Bookworm의 광범위한 사용자 sudo 설정에 의존하지 않으며, 설치 후
웹과 장비 메뉴에서 사용할 때 비밀번호 입력이나 터미널 접속이 필요 없다.

카메라와 Bluetooth Wi-Fi 복구 보조 스크립트는 `/usr/local/lib/mfnavis`에
root 소유로 설치한다. 임의 셸 명령 실행 권한은 추가하지 않는다. Bluetooth
페어링 시 복구 명령 권한이 없으면 Wi-Fi를 끊지 않는다. 백업 파일 삭제는
사용자 데이터 디렉터리에서 일반 계정 권한으로 처리한다. 권한 실패 시 웹은
HTTP 503과 안내 메시지를 반환하고 장비 메뉴는 오류를 표시하고 유지한다.

기존 장비에서는 관리자 인증 가능한 설치 환경에서 한 번 복구할 수 있다.
이 작업은 장비의 Wi-Fi 모드를 바꾸거나 재부팅하지 않는다.

```bash
cd ~/MFNavis
bash scripts/install_runtime_control.sh "$(id -un)"
sudo systemctl restart mfnavis.service
```

일반 설치·시스템 업데이트 경로에도 포함한다. 코드만 교체하는 트랜잭션
업데이트(`MFNAVIS_CODE_UPDATE=1`)는 시스템 설정을 변경하지 않는 기존
규칙을 유지하므로, 이 권한이 없는 구형 설치에는 별도 설치 단계가 필요하다.

<a id="TRIXIE_20260926_ko--apsta-적용-응답재부팅-후-wi-fi-목록-보완"></a>
### AP+STA 적용 응답·재부팅 후 Wi-Fi 목록 보완

Trixie/Netplan이 생성한 연결은 `/etc/NetworkManager/system-connections`가
아닌 `/run/NetworkManager/system-connections`에 있었다. 기존 가져오기
도구가 이 경로를 누락했고, 일반 서비스 계정은 root 전용 프로필을 직접
읽을 수 없어 실제 연결은 유지되면서 웹 목록은 비어 보였다.

가져오기 도구는 두 경로를 모두 읽는다. 최초 설치의 권한 설치 단계에서
`70-wifi-profile-import.conf`를 설치하여 NetworkManager 시작 이후,
앱 시작 전에 root 소유 보조 스크립트로 최초 목록을 가져온다. 결과 파일은
서비스 계정 소유·0600이다. 기존 목록은 보존하고, 성공 표시 파일로 이후
사용자가 삭제한 네트워크가 재시작 때 되살아나는 것을 막는다. 프로필이
아직 준비되지 않았다면 다음 앱 시작 때 재시도한다.

모드 전환 스크립트는 다음 부팅의 설정·서비스 활성화만 준비한다. 기존의
동기 `nmcli device connect`, AP 채널 대기·인터페이스 변경을 제거하여
HTTP 응답 전에 연결이 끊어지거나 재연결을 기다리지 않는다. 실제 무선
설정은 다음 부팅의 `mfnavis_apsta_prepare`가 수행한다. 웹은 적용 클릭
직후 진행 화면을 표시하고 서버 응답 뒤 기존 재부팅 화면으로 이동한다.

검증: 프로필 가져오기(런타임 경로·중복·기존 목록 보존·삭제 후 재시작·
부팅 시 준비 지연), 모드 전환·권한·네트워크 관련 회귀 테스트 112개 통과.
실제 무선 전환·재부팅은 테스트 과정에서 실행하지 않는다.


---

<a id="TRIXIE_DEVELOPMENT_ko"></a>

## TRIXIE_DEVELOPMENT_ko.md

<a id="TRIXIE_DEVELOPMENT_ko--trixie-개발-환경"></a>
## Trixie 개발 환경

Raspberry Pi 5 / Trixie arm64 / Python 3.13에서 개발 환경을 구성한다.
현재 OS의 Python 헤더, gcc/g++, make, CMake, SWIG, pkg-config를 사용한다.
운영 서비스는 `.venv-trixie`, 개발 도구는 `.venv-dev-trixie`를 사용한다.

<a id="TRIXIE_DEVELOPMENT_ko--설치와-활성화"></a>
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

<a id="TRIXIE_DEVELOPMENT_ko--도구와-의존성"></a>
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

<a id="TRIXIE_DEVELOPMENT_ko--검사와-디버깅"></a>
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

<a id="TRIXIE_DEVELOPMENT_ko--ci-검사-범위"></a>
### CI 검사 범위

`main` push와 PR에서 Python 3.13의 lint·format·Sphinx 문서 빌드 및
INDI 아카이브 플랫폼·검증·설치 선택 테스트를 실행한다. 이 검사는 arm64
wheel이나 Pi 장비 없이 실행할 수 있는 범위다. 전체 앱 회귀는 설치된
Trixie 개발 환경에서 실행하며, 기존 Python 3.11 CI는 Bookworm 호환성을
확인한다. 수동 실행하는 Selenium workflow도 기존 Python 3.11 환경이다.

<a id="TRIXIE_DEVELOPMENT_ko--graft와-셸-검사"></a>
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

<a id="TRIXIE_DEVELOPMENT_ko--현재-장비-검증-기록-2026-09-26"></a>
### 현재 장비 검증 기록 (2026-09-26)

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
MFNavis 저장소에서 함께 관리한다.


---

<a id="mf_bookworm_install_ko"></a>

## mf_bookworm_install_ko.md

<a id="mf_bookworm_install_ko--mf_pifinder-bookworm-64-bit-설치-매뉴얼"></a>
## MF_PiFinder Bookworm 64-bit 설치 매뉴얼

> 과거 Bookworm 설치 기록입니다. 현재 설치는
> [MFNavis Trixie 64-bit 안내](setup.md#mf_trixie_install_ko)를 따릅니다.
> 아래 절차와 장비 상태는 당시 PiFinder 설치 환경을 기록한 것입니다.

이 문서는 Raspberry Pi Compute Module 5(CM5), Raspberry Pi OS Bookworm
64-bit 환경에 brickbots/PiFinder `release` 브랜치를 설치한 절차를 정리한
것입니다. CM5 실기 설치를 기준으로 작성했으며, `mf_pifinder` 브랜치의 Pi4/Pi5/CM5
호환성 작업에서 기준 설치 문서로 사용합니다.

Raspberry Pi 4, Raspberry Pi 5, CM5를 같은 `mf_pifinder` 브랜치에서 설치/운영할
때의 보드별 profile과 자동 설정값은
`docs/mf_dev/mf_pifinder_rpi4_pi5_compatibility_ko.md`에 정리되어 있습니다.

공식 PiFinder 문서는 안정적인 사용에는 배포 이미지를 권장하고, 직접 설치는
주로 이미지 제작자/개발자용 절차라고 설명합니다. 또한 공식 직접 설치 절차는
Raspberry Pi OS Legacy Bullseye를 기준으로 작성되어 있습니다. CM5 Bookworm에서는
아래 차이를 반드시 고려해야 합니다.

- 부트 설정 파일은 `/boot/config.txt`가 아니라 `/boot/firmware/config.txt`입니다.
- Python은 3.11이며, `pip` 전역 설치에는 `--break-system-packages`가 필요합니다.
- Bookworm 기본 네트워크 관리는 NetworkManager입니다. PiFinder의 Wi-Fi/AP 전환
  스크립트는 `dhcpcd`, `wpa_supplicant`, `hostapd`, `dnsmasq` 모델을 전제로 합니다.
- 저장소의 Nox 설정은 Python 3.9를 우선하지만, `noxfile.py`가 3.9 부재 시
  실행 인터프리터로 자동 폴백하므로 Bookworm 3.11에서 `nox -s <session>`이
  그대로 동작합니다(구버전 안내였던 `--force-python 3.11`은 더 이상 불필요).

<a id="mf_bookworm_install_ko--무선-키보드-전원-키-차단"></a>
### 무선 키보드 전원 키 차단

이 변경을 포함한 `pifinder_setup.sh`와 `pifinder_post_update.sh`는
XING WEI 2.4G USB 키보드(USB ID `1915:1025`)의 전원 종료 키를 자동으로
무효화합니다. 설치 시 키보드가 없어도 되며 재부팅·USB 재연결 후에도 유지됩니다.
일반 키, 절전/깨우기 키, Raspberry Pi 본체 전원 버튼 및 메뉴 종료는 변경하지 않습니다.
다른 모델의 키보드까지 일괄 차단하는 설정은 아닙니다.

아래 수동 설치 절차를 따르거나 기존 장치에 이 설정만 적용할 때는,
이 변경이 포함된 저장소에서 다음을 실행합니다.

```bash
bash scripts/install_keyboard_power_ignore.sh
```

스크립트는 필요 시 sudo를 사용해 저장소의
`pi_config_files/90-pifinder-keyboard-power-ignore.hwdb`를
`/etc/udev/hwdb.d/`에 설치하고 DB 갱신 및 연결된 해당 키보드에 즉시 적용합니다.
PiFinder나 logind를 재시작하지 않으며 반복 실행해도 같은 설정이 유지됩니다.
원복하려면 해당 `/etc/udev/hwdb.d/90-pifinder-keyboard-power-ignore.hwdb`만 삭제하고
`sudo systemd-hwdb update` 후 키보드를 재연결합니다. 후속 설치/업데이트는 다시 적용합니다.

<a id="mf_bookworm_install_ko--현재-장비에-적용한-설치-상태"></a>
### 현재 장비에 적용한 설치 상태

- 소스 위치: `/home/pifinder/PiFinder`
  - 이 장비는 OS 사용자를 `pifinder`로 만든 사례입니다.
  - 새로 설치할 때는 원하는 사용자명과 hostname을 사용해도 됩니다.
- 브랜치: `release`
- 서브모듈: 초기화 완료
- Python 런타임/개발 의존성: 설치 완료
- 데이터 디렉터리: `/home/pifinder/PiFinder_data`
- systemd 서비스: `pifinder`, `cedar_detect`, `pifinder_splash` enable 완료
- CM5 부트 설정: `/boot/firmware/config.txt`에 PiFinder용 SPI/I2C/PWM/UART 설정 추가
- 원격 SSH 보호를 위해 `dhcpcd`, `dnsmasq`, `hostapd` 자동 시작은 비활성화
- 부팅은 콘솔 자동로그인(`raspi-config nonint do_boot_behaviour B2`)으로 전환 —
  헤드리스 상태에서 데스크톱 패널 `wf-panel-pi`가 CPU 한 코어를 상시 점유하는
  문제 회피. `pifinder_setup.sh`가 자동 적용하며, 데스크톱이 필요하면
  `do_boot_behaviour B4`로 되돌린다.
- Bookworm 호환 패치: PiFinder가 `/boot/firmware/config.txt`를 우선 사용하도록
  `PiFinder.boot_config`를 추가하고 카메라 전환/표시 코드를 수정
- CM5/Pi 5 SPI 호환 패치: `/dev/spidev0.0`가 없고 `/dev/spidev10.0`만 있는
  경우에도 OLED/LCD 디스플레이 초기화가 가능하도록 SPI 포트를 자동 선택
- CM5/Pi 5 UART 주의: `dtoverlay=uart3`는 Pi 5 계열에서 GPIO8/9를 사용하므로
  SSD1351 OLED의 `CS=GPIO8/CE0` 배선과 충돌합니다. 이 회로에서는 `uart3`를
  끄고 GPS용 UART는 GPIO4/5의 `dtoverlay=uart2-pi5`를 사용합니다.
- IMX462 카메라: Bookworm 펌웨어에는 `imx462.dtbo`가 있으므로 전용 오버레이를
  사용합니다. CM5 IO 보드의 `CAM0`에 연결한 경우에는 `cam0` 파라미터가 필요합니다.
  `CAM1`에 연결하는 경우에는 `cam0` 없이 기본 오버레이를 사용합니다.

재부팅해야 부트 오버레이와 사용자 그룹 변경이 완전히 적용됩니다. 원격 접속 중이면
재부팅은 모든 확인을 끝낸 뒤 마지막에 하십시오.

<a id="mf_bookworm_install_ko--단순-사용자용-설치"></a>
### 단순 사용자용 설치

이 절차는 소스 수정 없이 PiFinder를 실행하려는 사용자를 위한 것입니다. CM5
Bookworm에서는 공식 설치 스크립트를 그대로 실행하지 말고 아래처럼 나누어 진행하는
것을 권장합니다.

<a id="mf_bookworm_install_ko--1-기본-os-준비"></a>
#### 1. 기본 OS 준비

1. Raspberry Pi OS Bookworm 64-bit를 설치합니다.
2. 사용자 이름과 hostname은 원하는 고유한 이름으로 만듭니다. 여러 대를 같이
   쓸 예정이면 예를 들어 `scope-a`, `scope-b`처럼 서로 다르게 지정합니다.
3. SSH와 Wi-Fi를 Raspberry Pi Imager에서 미리 설정합니다. 이후 mDNS 접속 주소는
   `<hostname>.local`이 됩니다.
4. 최초 접속 후 현재 네트워크가 안정적인지 확인합니다.

```bash
hostname -I
nmcli device status

export PI_USER="$(id -un)"
export PI_HOME="$(getent passwd "$PI_USER" | cut -d: -f6)"
export PF_REPO="$PI_HOME/PiFinder"
export PF_DATA="$PI_HOME/PiFinder_data"
```

<a id="mf_bookworm_install_ko--2-소스-받기"></a>
#### 2. 소스 받기

```bash
cd "$PI_HOME"
git clone --recursive --branch release https://github.com/brickbots/PiFinder.git
```

이미 받은 저장소가 있으면 다음으로 갱신합니다.

```bash
cd "$PF_REPO"
git fetch --all
git checkout release
git pull
git submodule update --init --recursive
```

<a id="mf_bookworm_install_ko--3-debian-패키지-설치"></a>
#### 3. Debian 패키지 설치

서비스가 자동 시작되어 네트워크를 흔들지 않게, 원격 작업 중에는 `policy-rc.d`로
자동 시작을 잠시 막는 것이 안전합니다.

```bash
sudo bash -c '
set -e
trap "rm -f /usr/sbin/policy-rc.d" EXIT
printf "%s\n" "#!/bin/sh" "exit 101" > /usr/sbin/policy-rc.d
chmod 755 /usr/sbin/policy-rc.d
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  git python3-pip python3-venv python3-dev build-essential pkg-config \
  samba samba-common-bin dnsmasq hostapd dhcpcd gpsd \
  libinput10 libcap2-bin libjpeg-dev zlib1g-dev libfreetype6-dev \
  liblcms2-dev libopenjp2-7-dev libtiff-dev libffi-dev libssl-dev \
  python3-picamera2 rpicam-apps i2c-tools spi-tools
'
```

<a id="mf_bookworm_install_ko--4-python-런타임-의존성-설치"></a>
#### 4. Python 런타임 의존성 설치

```bash
cd "$PF_REPO"
sudo python3 -m pip install --break-system-packages -r python/requirements.txt
```

<a id="mf_bookworm_install_ko--5-데이터-디렉터리와-서비스-설정"></a>
#### 5. 데이터 디렉터리와 서비스 설정

```bash
source "$PF_REPO/pifinder_paths.sh"

sudo install -d -o "$PI_USER" -g "$PI_USER" -m 755 \
  "$PF_DATA" \
  "$PF_DATA/captures" \
  "$PF_DATA/obslists" \
  "$PF_DATA/screenshots" \
  "$PF_DATA/solver_debug_dumps" \
  "$PF_DATA/logs" \
  "$PF_DATA/migrations"

printf Client > "$PF_REPO/wifi_status.txt"

sudo cp "$PF_REPO/pi_config_files/gpsd.conf" /etc/default/gpsd
pifinder_render_config "$PF_REPO/pi_config_files/smb.conf" /etc/samba/smb.conf
pifinder_render_config "$PF_REPO/pi_config_files/pifinder.service" /lib/systemd/system/pifinder.service
pifinder_render_config "$PF_REPO/pi_config_files/pifinder_splash.service" /lib/systemd/system/pifinder_splash.service
pifinder_render_config "$PF_REPO/pi_config_files/cedar_detect.service" /lib/systemd/system/cedar_detect.service

sudo systemctl daemon-reload
sudo systemctl enable cedar_detect pifinder pifinder_splash smbd nmbd gpsd.socket
```

하드웨어 접근 그룹도 확인합니다.

```bash
for group in input video render dialout gpio i2c spi; do
  getent group "$group" >/dev/null && sudo usermod -aG "$group" "$PI_USER"
done
```

<a id="mf_bookworm_install_ko--6-cm5-bookworm-부트-설정"></a>
#### 6. CM5 Bookworm 부트 설정

`/boot/firmware/config.txt`에 다음 값이 있는지 확인하고 없으면 추가합니다.

```bash
sudo cp -a /boot/firmware/config.txt /boot/firmware/config.txt.before-pifinder
for line in \
  "dtparam=spi=on" \
  "dtparam=i2c_arm=on" \
  "dtparam=i2c_arm_baudrate=10000" \
  "dtoverlay=pwm,pin=13,func=4" \
  "dtoverlay=uart2-pi5"
do
  grep -qxF "$line" /boot/firmware/config.txt || echo "$line" | sudo tee -a /boot/firmware/config.txt
done
```

IMX462 카메라를 사용할 때는 자동 감지를 끄고 전용 오버레이를 추가합니다. CM5 IO
보드의 `CAM0` 포트를 쓰는 경우:

```bash
sudo sed -i 's/^camera_auto_detect=1/#camera_auto_detect=1/' /boot/firmware/config.txt
grep -qxF "dtoverlay=imx462,cam0,clock-frequency=74250000" /boot/firmware/config.txt || \
  echo "dtoverlay=imx462,cam0,clock-frequency=74250000" | sudo tee -a /boot/firmware/config.txt
```

`CAM1` 포트를 쓰는 경우에는 `cam0`를 빼서
`dtoverlay=imx462,clock-frequency=74250000`처럼 설정합니다.

<a id="mf_bookworm_install_ko--7-네트워크-관련-주의"></a>
#### 7. 네트워크 관련 주의

원격 SSH가 Wi-Fi 위에 있다면 `dhcpcd`, `dnsmasq`, `hostapd`를 바로 켜지 마십시오.
현재 장비처럼 NetworkManager로 Wi-Fi에 연결한 상태에서는 다음처럼 PiFinder AP
서비스를 꺼 두는 편이 안전합니다.

```bash
sudo systemctl disable dhcpcd dnsmasq hostapd
```

PiFinder의 Wi-Fi/AP 전환 메뉴까지 공식 이미지처럼 쓰려면 로컬 콘솔, 유선 LAN,
또는 쉽게 복구할 수 있는 물리 접근을 확보한 뒤 별도로 전환하십시오.

<a id="mf_bookworm_install_ko--8-마지막에-재부팅"></a>
#### 8. 마지막에 재부팅

모든 작업을 끝낸 뒤 마지막에 재부팅합니다.

```bash
sudo reboot
```

재접속 후 확인합니다.

```bash
systemctl status pifinder cedar_detect pifinder_splash
journalctl -u pifinder -n 100 --no-pager
```

선택 사항으로 카탈로그 이미지를 받을 수 있습니다. 약 5GB 이상이며 오래 걸릴 수
있습니다.

```bash
cd "$PF_REPO/python"
python3 -m PiFinder.get_images
```

<a id="mf_bookworm_install_ko--개발자용-설치"></a>
### 개발자용 설치

개발자는 단순 사용자 설치에 더해 개발 의존성과 테스트 도구를 설치합니다.

<a id="mf_bookworm_install_ko--1-개발-의존성-설치"></a>
#### 1. 개발 의존성 설치

```bash
cd "$PF_REPO"
sudo python3 -m pip install --break-system-packages -r python/requirements_dev.txt
```

<a id="mf_bookworm_install_ko--2-forkremote-구성"></a>
#### 2. Fork/remote 구성

본인 GitHub fork에 push하려면 origin을 fork로 바꾸고 upstream을 원본으로 둡니다.

```bash
cd "$PF_REPO"
git remote rename origin upstream
git remote add origin git@github.com:<YOUR_ID>/PiFinder.git
git fetch --all
```

쓰기 권한 없이 읽기만 할 때는 현재 `origin` 그대로 두어도 됩니다.

<a id="mf_bookworm_install_ko--3-bookworm에서-테스트-실행"></a>
#### 3. Bookworm에서 테스트 실행

권장 절차는 프로젝트 고정 버전(ruff/mypy/pytest 등)을 격리 설치하는 venv입니다
(CLAUDE.md의 개발 절차와 동일; Bookworm에는 3.9가 없으므로 시스템 3.11 사용).

```bash
cd "$PF_REPO/python"
python3 -m venv .venv
source .venv/bin/activate
# pifinder_setup.sh 설치본은 /tmp가 256M tmpfs라 pip 임시 파일이 넘칠 수 있음
TMPDIR=/var/tmp pip install -r requirements.txt -r requirements_dev.txt

nox -s lint format type_hints smoke_tests   # 또는 개별 세션
nox -s docs                                 # 사용자 매뉴얼 빌드 (경고 1건이면 실패)
pytest -m smoke
```

`requirements_dev.txt`가 `docs/source/requirements.txt`를 참조하므로 위
설치 한 번으로 Sphinx 툴체인(Sphinx, RTD 테마, mermaid 확장)까지 함께
들어옵니다. Read the Docs가 쓰는 것과 같은 고정 버전이라 로컬 빌드 결과가
발행본과 어긋나지 않습니다.

`docs/source/*.rst`를 건드렸다면 `nox -s docs`를 돌려 보십시오. 문서 간
참조(`:ref:`), 치환자(`|v3_docs|` 등), 이미지 경로가 끊겼는지 잡아냅니다 —
upstream 문서 커밋을 부분 적용했을 때 특히 필요합니다. 빌드 결과는
`docs/build/html/index.html`이고 gitignore 대상입니다.

`noxfile.py`는 Python 3.9를 우선하되 없으면 실행 인터프리터로 자동 폴백하므로,
3.11 venv 안에서 `nox -s <session>`이 그대로 동작합니다. 구버전 안내였던
`--force-python 3.11` 강제는 더 이상 필요 없습니다. venv 없이 빠르게 확인만
할 때는 시스템 python3로 직접 실행해도 됩니다.

```bash
python3 -m ruff check PiFinder tests
python3 -m pytest -m smoke
```

<a id="mf_bookworm_install_ko--4-명령행-실행디버깅"></a>
#### 4. 명령행 실행/디버깅

서비스와 수동 실행을 동시에 띄우면 같은 하드웨어를 잡으려 해서 충돌할 수 있습니다.
수동 실행 전 서비스를 멈춥니다.

```bash
sudo systemctl stop pifinder cedar_detect
```

실제 PiFinder 하드웨어에서 실행합니다.

```bash
cd "$PF_REPO/python"
python3 -m PiFinder.main -x
```

하드웨어 없이 UI/카탈로그 쪽을 개발할 때는 fake 옵션을 사용합니다.

```bash
cd "$PF_REPO/python"
python3 -m PiFinder.main -fh -k local --camera debug --display pg_128 -x
```

Cedar detect 서버를 따로 띄워야 할 때는 별도 터미널에서 실행합니다.

```bash
"$PF_REPO/bin/cedar-detect-server-aarch64" -p 50551
```

<a id="mf_bookworm_install_ko--5-코드-수정-뒤-반영"></a>
#### 5. 코드 수정 뒤 반영

서비스로 돌리는 상태에서 Python 코드를 바꾼 뒤에는 서비스를 재시작합니다.

```bash
sudo systemctl restart cedar_detect pifinder
```

부트 설정, 사용자 그룹, 카메라 오버레이, 네트워크 스택을 바꾼 경우에는 재부팅이
필요합니다. 원격 접속 중이면 반드시 마지막에 수행하십시오.

<a id="mf_bookworm_install_ko--검증-체크리스트"></a>
### 검증 체크리스트

- `python3 -m PiFinder.main -h`가 도움말을 출력한다.
- `python3 -m pytest -m smoke`가 통과한다.
- Python 소스 변경을 push하기 전에는 저장소 CI와 같은 전체 NOX 세션을 실행한다.

  ```bash
  cd "$PF_REPO/python"
  nox -s lint format type_hints smoke_tests unit_tests ui_tests
  ```

  PiFinder 실장 환경의 Python 3.11 집중 시험만으로는 CI 기준인 Python 3.9의
  annotation 문법·런타임 호환 실패를 찾을 수 없다. NOX가 Python 3.9를 사용할 수
  있는 환경에서 실행되었는지 시작 로그도 확인하고, 원격 push 뒤 GitHub Actions의
  동일 workflow가 성공할 때까지 완료로 판정하지 않는다.
- `/boot/firmware/config.txt`에 PiFinder용 오버레이가 들어 있다.
- `id pifinder`에 `input`, `video`, `render`, `dialout`, `gpio`, `i2c`, `spi`가 보인다.
- `systemctl is-enabled pifinder cedar_detect pifinder_splash`가 `enabled`를 출력한다.
- 원격 Wi-Fi 접속 중에는 `dhcpcd`, `dnsmasq`, `hostapd`가 자동 시작되지 않는다.

<a id="mf_bookworm_install_ko--주변기기-연결-순서"></a>
### 주변기기 연결 순서

주변기기는 가능하면 전원을 끈 상태에서 하나씩 연결하고, 부팅 후 아래 항목을
확인합니다.

1. OLED/LCD 및 키패드

   ```bash
   ls /dev/spidev*
   sudo systemctl restart pifinder_splash pifinder
   journalctl -u pifinder -b -n 80 --no-pager
   ```

   CM5에서는 `/dev/spidev10.0`만 보여도 정상일 수 있습니다.
   `pinctrl get 8`이 `TXD3`로 나오면 `dtoverlay=uart3`가 OLED CS를 빼앗은
   상태입니다. `/boot/firmware/config.txt`에서 `uart3`를 끄고 재부팅하십시오.

2. IMU(BNO055)

   ```bash
   i2cdetect -y 1
   sudo systemctl restart pifinder
   journalctl -u pifinder -b -n 100 --no-pager
   ```

   기본 주소는 `0x28`입니다. `No I2C device at address: 0x28` 로그가 사라지면
   IMU 인식이 된 것입니다.

3. 카메라

   ```bash
   rpicam-hello --list-cameras
   sudo systemctl stop pifinder
   rpicam-still -n -t 2000 -o /tmp/imx462-test.jpg
   sudo systemctl start pifinder
   journalctl -u pifinder -b -n 120 --no-pager
   ```

   카메라가 없을 때의 기준 출력은 `No cameras available!`입니다. 카메라 연결 후
   이 문구가 사라지고 카메라 모델이 표시되어야 합니다.
   IMX462가 `imx290`으로 보이거나 `Error writing reg 0x303a: -121`,
   `Failed to queue buffer`, `Remote I/O error`가 나오면 목록 인식은 됐지만
   스트림 시작에 실패한 상태입니다. 이 경우 `/boot/firmware/config.txt`의
   카메라 줄이 실제 연결 포트와 맞는지 확인합니다. CM5 IO 보드의 `CAM0`이면
   `dtoverlay=imx462,cam0,clock-frequency=74250000`, `CAM1`이면
   `dtoverlay=imx462,clock-frequency=74250000`을 사용합니다. 그 다음 CSI 케이블
   방향, 카메라 전원, I2C 풀업, 2-lane/4-lane 모듈 종류를 차례로 확인합니다.

4. GPS

   ```bash
   gpspipe -r -n 5
   journalctl -u gpsd -b -n 80 --no-pager
   ```

   UART GPS는 PiFinder의 `GPS Settings > GPS Port`에서 실제 배선 포트를 선택합니다.
   CM5에서 이번 보드는 `/dev/ttyAMA2`, 기본 PiFinder 계열 보드는 보통
   `/dev/ttyAMA1`을 사용합니다. 포트나 baud를 바꾸면 PiFinder가
   `/etc/default/gpsd`의 `DEVICES`와 `GPSD_OPTIONS`를 갱신하고 gpsd를 재시작합니다.

<a id="mf_bookworm_install_ko--참고-링크"></a>
### 참고 링크

- PiFinder 저장소: https://github.com/brickbots/PiFinder
- PiFinder Software Setup: https://pifinder.readthedocs.io/en/release/software.html
- PiFinder Contributors Guide: https://pifinder.readthedocs.io/en/release/dev_guide.html


---

<a id="mf_imx678_ko"></a>

## mf_imx678_ko.md

<a id="mf_imx678_ko--imx678-linux-공식-드라이버-기반-준비와-사용"></a>
## IMX678: Linux 공식 드라이버 기반 준비와 사용

MFNavis는 IMX678의 **Linux upstream 드라이버와 공식 Raspberry Pi libcamera**를
사용한다. 현재 Raspberry Pi OS 커널 패키지에 없는 IMX678 드라이버는 Linux
공식 소스를 변경하지 않고 DKMS 모듈로 빌드한다. MFNavis의 Raspberry Pi용
오버레이와 설치 스크립트는 별도 통합 코드이며, Raspberry Pi가 배포하는
공식 IMX678 패키지라는 뜻은 아니다.

- Linux 소스: [bf40cc53b1e00c312046f6dd88e9054bc91865af](https://github.com/torvalds/linux/commit/bf40cc53b1e00c312046f6dd88e9054bc91865af)
- 출처·해시·라이선스: [deployment/imx678](../../../deployment/imx678/README.md)
- libcamera: [0.7.2부터 IMX678 helper 포함](https://lists.libcamera.org/pipermail/libcamera-devel/2026-July/060247.html)
- 검증 기준: Pi 5 / Trixie 64-bit / `6.18.50+rpt-rpi-2712`,
  libcamera `0.7.2+rpt20260817-1`, Picamera2 `0.3.37-1`.

<a id="mf_imx678_ko--지원-범위"></a>
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

<a id="mf_imx678_ko--하드웨어-없이-소프트웨어-준비"></a>
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

<a id="mf_imx678_ko--실제-모듈-연결-후"></a>
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

<a id="mf_imx678_ko--cam04레인입력-클록-설정"></a>
#### CAM0·4레인·입력 클록 설정

`/boot/firmware/config.txt`의 `[all]` 아래, 카메라 선택 **전에 주석으로**
원하는 설정을 넣을 수 있다. 메뉴 전환은 이 줄의 옵션을 보존해 활성화한다.

```ini
# CAM0, 4레인 예시
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

<a id="mf_imx678_ko--최초-촬영-확인"></a>
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

<a id="mf_imx678_ko--이번-검증과-남은-확인"></a>
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


---

<a id="mf_pifinder_new_device_tasks_ko"></a>

## mf_pifinder_new_device_tasks_ko.md

<a id="mf_pifinder_new_device_tasks_ko--새-디바이스-작업-체크리스트"></a>
## 새 디바이스 작업 체크리스트

이 체크리스트는 MFNavis `main` 브랜치의 Trixie 64-bit / Python 3.13 기준이다.
현재 설치·검증 범위는 [Trixie 안내](setup.md#mf_trixie_install_ko)를 참고한다.
아래 과거 Bookworm 키보드 실측은 당시 OS를 그대로 기록한다.

작성일: 2026-06-26 / 갱신: 2026-09-27

이 문서는 `hjoungjoo/MFNavis` fork의 `main` 브랜치를 새 Raspberry Pi
디바이스에서 설치하고 검증하기 위한 실행 순서이다. Raspberry Pi 4, Raspberry Pi 5,
CM5는 `docs/mf_dev/mf_pifinder_rpi4_pi5_compatibility_ko.md`의 보드 profile 기준으로
확인한다.

상세 배경은 다음 문서를 참고한다.

```text
docs/mf_dev/mf_pifinder_rpi4_pi5_compatibility_ko.md
docs/mf_dev/mf_change_history_ko.md
docs/mf_dev/mf_trixie_install_ko.md
```

<a id="mf_pifinder_new_device_tasks_ko--목표"></a>
### 목표

새 디바이스에서 확인할 핵심 목표는 네 가지이다.

1. `main` 브랜치가 새 OS에서 설치되는지 확인한다.
2. CM5/Trixie 대응 수정이 Raspberry Pi 4 동작을 깨지 않는지 확인한다.
3. Raspberry Pi 5 계열은 `pi5_class` profile의 UART/GPS/SPI 경로를 타는지 확인한다.
4. 문제가 생기면 로그를 남기고 같은 브랜치에 수정 커밋을 반영한다.

<a id="mf_pifinder_new_device_tasks_ko--시작-전-준비"></a>
### 시작 전 준비

권장 OS:

```text
Raspberry Pi OS Trixie 64-bit
```

Raspberry Pi Imager 설정:

```text
SSH: enable
hostname: 기존 장비와 겹치지 않는 이름
username: 가능하면 pifinder가 아닌 이름
Wi-Fi: 필요하면 미리 설정
```

예:

```text
hostname: mf-pi4-test
username: mfpi4
```

네트워크 권장 순서:

```text
1순위: 유선 LAN + SSH
2순위: 모니터/키보드 직접 연결
3순위: Wi-Fi SSH만 사용
```

주의:

- 원격 접속만 가능한 상태에서는 네트워크 설정 변경과 재부팅을 마지막에 한다.
- 카메라 리본, LCD, IMU, GPS 등 하드웨어는 한 번에 모두 연결하지 말고 단계별로 연결한다.
- 카메라 리본은 반드시 전원을 끈 상태에서 연결한다.

<a id="mf_pifinder_new_device_tasks_ko--1-새-디바이스-최초-접속-후-기본-확인"></a>
### 1. 새 디바이스 최초 접속 후 기본 확인

```bash
hostname -I
cat /etc/os-release
uname -a
python3 --version
id
groups
```

기록 디렉터리를 만든다.

```bash
mkdir -p ~/mfnavis-test-logs
```

초기 상태를 저장한다.

```bash
{
  date
  hostnamectl
  cat /etc/os-release
  uname -a
  python3 --version
  id
  groups
  nmcli device status 2>/dev/null || true
  ip addr
} | tee ~/mfnavis-test-logs/00_initial_state.txt
```

<a id="mf_pifinder_new_device_tasks_ko--2-소스-받기"></a>
### 2. 소스 받기

```bash
sudo apt update
sudo apt install -y git

cd ~
git clone --recursive --branch main https://github.com/hjoungjoo/MFNavis.git MFNavis
cd ~/MFNavis
```

브랜치와 커밋을 확인한다.

```bash
git status --short --branch
git log --oneline --decorate -n 5
git submodule status
```

기대 상태:

```text
branch: main
remote: hjoungjoo/MFNavis
```

<a id="mf_pifinder_new_device_tasks_ko--3-호환성변경-이력-문서-읽기"></a>
### 3. 호환성/변경 이력 문서 읽기

```bash
cd ~/MFNavis
sed -n '1,220p' docs/mf_dev/mf_pifinder_rpi4_pi5_compatibility_ko.md
sed -n '1,180p' docs/mf_dev/mf_change_history_ko.md
```

새 대화에서 Codex와 이어서 작업할 때는 아래 문장을 먼저 전달한다.

```text
PiFinder CM5/Trixie 작업을 새 Raspberry Pi 디바이스에서 테스트하려고 해.
저장소는 hjoungjoo/MFNavis이며 설치 브랜치는 main이야.
docs/mf_dev/mf_pifinder_rpi4_pi5_compatibility_ko.md,
docs/mf_dev/mf_pifinder_new_device_tasks_ko.md,
docs/mf_dev/mf_change_history_ko.md를 읽고 이어서 진행해줘.
설치/하드웨어 테스트 중 생기는 문제를 같은 브랜치에 반영하고 싶어.
```

<a id="mf_pifinder_new_device_tasks_ko--4-설치-전-상태-저장"></a>
### 4. 설치 전 상태 저장

```bash
cd ~/MFNavis

{
  date
  git status --short --branch
  git rev-parse HEAD
  git remote -v
  ls -l /boot/config.txt /boot/firmware/config.txt 2>/dev/null || true
  grep -n "dtparam\|dtoverlay\|camera_auto_detect" /boot/config.txt /boot/firmware/config.txt 2>/dev/null || true
} | tee ~/mfnavis-test-logs/01_before_install.txt
```

<a id="mf_pifinder_new_device_tasks_ko--5-설치-스크립트-실행"></a>
### 5. 설치 스크립트 실행

중요:

```text
sudo ./mfnavis_setup.sh 실행 금지
```

설치 스크립트는 일반 사용자로 실행한다.

```bash
cd ~/MFNavis
MFNAVIS_INSTALL_BRANCH=main bash ./mfnavis_setup.sh 2>&1 | tee ~/mfnavis-test-logs/02_mfnavis_setup.log
```

설치 중 확인할 것:

- `apt-get install` 실패 여부
- `dhcpcd` 패키지 설치 성공 여부
- `gpsd` 설정 단계가 입력을 요구하거나 멈추는지
- `.venv-trixie` Python 3.13 / `requirements-trixie.txt` 설치 성공 여부
- Trixie INDI 아카이브 checksum·OS·Python ABI 검증
- MFDS 바이너리 설치와 앱·INDI 서비스 Python 선택
- `hip_main.dat` 다운로드 성공 여부
- service/Samba 템플릿 렌더링 성공 여부
- 사용자 그룹 추가 성공 여부

설치가 실패하면 바로 다음 정보를 저장하고 멈춘다.

```bash
{
  date
  git -C ~/MFNavis status --short --branch
  tail -n 120 ~/mfnavis-test-logs/02_mfnavis_setup.log
  systemctl status mfnavis mfnavis_splash indiwebmanager --no-pager 2>/dev/null || true
} | tee ~/mfnavis-test-logs/02_install_failed_summary.txt
```

<a id="mf_pifinder_new_device_tasks_ko--6-재부팅-전-확인"></a>
### 6. 재부팅 전 확인

설치가 끝났다면 아직 재부팅하지 말고 상태를 저장한다.

```bash
{
  date
  git -C ~/MFNavis status --short --branch
  groups
  ls -l /boot/config.txt /boot/firmware/config.txt 2>/dev/null || true
  grep -n "dtparam\|dtoverlay\|camera_auto_detect" /boot/config.txt /boot/firmware/config.txt 2>/dev/null || true
  systemctl is-enabled mfnavis mfnavis_splash indiwebmanager 2>/dev/null || true
  systemctl status mfnavis mfnavis_splash indiwebmanager --no-pager 2>/dev/null || true
} | tee ~/mfnavis-test-logs/03_before_reboot.txt
```

원격 접속이 Wi-Fi뿐이면 재접속 방법을 먼저 확인한다.

```bash
hostname -I
```

<a id="mf_pifinder_new_device_tasks_ko--7-첫-재부팅"></a>
### 7. 첫 재부팅

```bash
sudo reboot
```

재접속 후:

```bash
mkdir -p ~/mfnavis-test-logs

{
  date
  hostname -I
  groups
  systemctl status mfnavis mfnavis_splash indiwebmanager --no-pager
} | tee ~/mfnavis-test-logs/04_after_reboot_services.txt

journalctl -u mfnavis -b --no-pager > ~/mfnavis-test-logs/04_mfnavis_after_reboot.log
journalctl -u indiwebmanager -b --no-pager > ~/mfnavis-test-logs/04_indiwebmanager_after_reboot.log
```

<a id="mf_pifinder_new_device_tasks_ko--8-하드웨어-연결-순서"></a>
### 8. 하드웨어 연결 순서

처음에는 주변기기를 모두 연결하지 말고 아래 순서로 확인한다.

```text
1. LCD / 키패드 / IMU
2. 카메라
3. GPS
4. USB 키보드
5. Bluetooth 키보드
```

각 단계마다 연결 후 로그를 확인한다.

```bash
journalctl -u mfnavis -b -n 200 --no-pager
```

<a id="mf_pifinder_new_device_tasks_ko--9-lcd--키패드--imu-확인"></a>
### 9. LCD / 키패드 / IMU 확인

연결 후 장치 노드를 확인한다.

```bash
ls -l /dev/i2c-* /dev/spidev* 2>/dev/null
i2cdetect -y 1
```

확인할 것:

- Pi4에서 `/dev/spidev0.0`가 보이는지
- OLED/LCD 화면이 켜지는지
- 키패드 입력이 반응하는지
- IMU가 I2C에서 보이는지
- PiFinder 서비스 로그에 display 또는 IMU 오류가 없는지

로그 저장:

```bash
{
  date
  ls -l /dev/i2c-* /dev/spidev* 2>/dev/null || true
  i2cdetect -y 1 || true
} | tee ~/mfnavis-test-logs/05_lcd_keypad_imu.txt
```

<a id="mf_pifinder_new_device_tasks_ko--10-카메라-확인"></a>
### 10. 카메라 확인

카메라 리본 연결은 전원을 끈 상태에서 한다.

카메라 확인:

```bash
rpicam-hello --list-cameras
```

카메라 타입 전환이 필요하면:

```bash
cd ~/MFNavis
sudo python3 python/PiFinder/switch_camera.py imx477
# 또는 imx296 / imx462
sudo reboot
```

재부팅 후:

```bash
rpicam-hello --list-cameras
rpicam-still -o ~/mfnavis-test-logs/camera-test.jpg --timeout 2000
journalctl -u mfnavis -b -n 300 --no-pager | tee ~/mfnavis-test-logs/06_camera_journal.txt
```

확인할 것:

- Pi4에서 카메라가 감지되는지
- `switch_camera.py`가 올바른 boot config 파일을 수정하는지
- Pi4 카메라 포트에서 `cam0` 파라미터가 불필요하게 들어가지 않는지
- Focus 화면이 검게만 보이지 않는지
- 노출/gain 메뉴가 정상 동작하는지

<a id="mf_pifinder_new_device_tasks_ko--11-gps-확인"></a>
### 11. GPS 확인

GPS를 연결한 뒤:

```bash
ls -l /dev/serial* /dev/ttyAMA* /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
systemctl status gpsd gpsd.socket --no-pager
cgps -s
```

PiFinder 메뉴에서 확인:

```text
Settings > Advanced > GPS Settings > GPS Port
```

확인할 것:

- 실제 GPS 포트가 메뉴에 있는지
- 포트 변경 후 `/etc/default/gpsd`가 업데이트되는지
- `gpsd`가 재시작 또는 재연결되는지
- GPS lock 상태가 PiFinder UI에 반영되는지

Pi4 + `uart3` overlay 기준:

- 내장 UART GPS는 `/dev/ttyAMA3`로 확인한다.
- `GPS Port` 기본값 `auto`는 Pi4에서 `/dev/ttyAMA3`로 해석된다.
- u-blox 수신기가 115200bps로 설정된 장비에서는 `GPS Baud Rate`도 `115200`으로
  맞춘 뒤 gpsd가 `driver:"u-blox"`로 인식하는지 확인한다.
- 수신기는 인식되지만 `TPV mode=1`, `nSat=0/uSat=0`이면 통신 문제보다는
  안테나/하늘 시야/cold start 문제로 보고 야외에서 다시 확인한다.

로그 저장:

```bash
{
  date
  ls -l /dev/serial* /dev/ttyAMA* /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || true
  systemctl status gpsd gpsd.socket --no-pager || true
} | tee ~/mfnavis-test-logs/07_gps.txt
```

<a id="mf_pifinder_new_device_tasks_ko--12-usbbluetooth-키보드-확인"></a>
### 12. USB/Bluetooth 키보드 확인

USB 키보드:

```bash
ls -l /dev/input/by-id /dev/input/by-path 2>/dev/null
```

Bluetooth 상태:

```bash
bluetoothctl show
bluetoothctl devices
bluetoothctl devices Paired
bluetoothctl info <MAC>
ls -l /dev/input /dev/input/by-id /dev/input/by-path 2>/dev/null
journalctl -u bluetooth -b -n 120 --no-pager
```

PiFinder 메뉴:

```text
Settings > Advanced > Bluetooth
```

확인할 것:

- Bluetooth scan에서 장치 이름이 보이는지
- MAC만 보이는 장치도 선택 가능한지
- Pair+Connect가 성공하는지
- 재시작 후 자동 재연결되는지
- 알파벳은 실제 알파벳으로 입력되는지
- Space는 Space로 처리되는지
- 실제 길게 누르는 long key가 동작하는지
- USB 키보드와 GPIO 키패드가 서로 방해하지 않는지
- 연결됐다고 보이는데 키 입력이 없으면 `/dev/input/event*`가 새로 생겼는지
  먼저 확인한다.
- `/dev/input`에 키보드 event 장치가 없고 `bluetoothd`에 HID Information 또는
  Report Reference read 실패가 보이면 PiFinder 입력 매핑 이전의 BlueZ/HID
  연결 문제로 분류한다.
- 과거 Pi4 Bookworm 실측에서 `K06 BLE Keyboard`는 `/etc/bluetooth/input.conf`의
  `UserspaceHID=true`, `LEAutoSecurity=true` 적용 후 event 장치가 생성됐다.
  기존 설치에서는 설정 변경 뒤 `sudo systemctl restart bluetooth`와
  `sudo systemctl restart mfnavis`를 실행한다.
- `libinput debug-events --device /dev/input/eventX`로 실제 키 이벤트가 들어오는지
  확인한다.

<a id="mf_pifinder_new_device_tasks_ko--13-한국어-메뉴-확인"></a>
### 13. 한국어 메뉴 확인

PiFinder 메뉴에서 한국어를 선택한다.

```text
Settings > User Pref... > Language > Korean
```

확인할 것:

- 재시작 후 한국어 메뉴가 표시되는지
- 한글 글자가 깨지지 않는지
- 천문 용어가 너무 어색하지 않은지
- 미번역 문자열은 영어로 자연스럽게 fallback되는지

<a id="mf_pifinder_new_device_tasks_ko--14-문제-발생-시-codex에게-줄-자료"></a>
### 14. 문제 발생 시 Codex에게 줄 자료

문제가 생기면 아래 명령을 실행하고 출력 또는 파일을 전달한다.

```bash
mkdir -p ~/mfnavis-test-logs

{
  date
  hostnamectl
  cat /etc/os-release
  uname -a
  python3 --version
  id
  groups
  git -C ~/MFNavis status --short --branch
  git -C ~/MFNavis log --oneline --decorate -n 5
  git -C ~/MFNavis rev-parse HEAD
  ls -l /boot/config.txt /boot/firmware/config.txt 2>/dev/null || true
  grep -n "dtparam\|dtoverlay\|camera_auto_detect" /boot/config.txt /boot/firmware/config.txt 2>/dev/null || true
  ls -l /dev/i2c-* /dev/spidev* /dev/serial* /dev/ttyAMA* /dev/ttyUSB* /dev/ttyACM* /dev/video* /dev/media* /dev/input/event* 2>/dev/null || true
  systemctl status mfnavis mfnavis_splash indiwebmanager gpsd gpsd.socket --no-pager || true
} | tee ~/mfnavis-test-logs/problem-summary.txt

journalctl -u mfnavis -b --no-pager > ~/mfnavis-test-logs/problem-mfnavis.log
journalctl -u indiwebmanager -b --no-pager > ~/mfnavis-test-logs/problem-indiwebmanager.log
dmesg > ~/mfnavis-test-logs/problem-dmesg.log
```

Codex에게 전달할 때는 아래처럼 시작한다.

```text
새 Pi4 디바이스에서 MFNavis Trixie 변경을 테스트하던 중 문제가 생겼어.
docs/mf_dev/mf_pifinder_new_device_tasks_ko.md 기준으로 진행했고,
문제는 <간단한 설명>이야.
아래 로그를 확인해서 수정해줘.
```

<a id="mf_pifinder_new_device_tasks_ko--15-수정-후-github에-반영"></a>
### 15. 수정 후 GitHub에 반영

문제를 수정한 뒤:

```bash
cd ~/MFNavis
git status --short
git add -A
git commit -m "Fix Pi4 <problem summary>"
git push
```

예:

```bash
git commit -m "Fix Pi4 SPI display detection"
git commit -m "Fix setup package install on Trixie"
git commit -m "Update Pi4 install checklist"
```

장비 수정 사항의 PR 대상 브랜치는 `main`이다.

<a id="mf_pifinder_new_device_tasks_ko--16-pr-준비"></a>
### 16. PR 준비

GitHub에서 Pull Request를 만들 때:

```text
base repository: hjoungjoo/MFNavis
base branch: main
head repository: hjoungjoo/MFNavis
compare branch: <your-fix-branch>
```

처음에는 Draft PR로 만든다.

Pi4 테스트가 끝난 뒤:

- 남은 문제 목록을 정리한다.
- 큰 변경을 기능별 PR로 나눌지 관리자와 상의한다.
- 리뷰 요청 전 `main` 브랜치의 최신 로그와 테스트 결과를 PR 본문에 정리한다.

<a id="mf_pifinder_new_device_tasks_ko--17-금지-또는-주의-작업"></a>
### 17. 금지 또는 주의 작업

- 원격 접속만 가능한 상태에서 네트워크 전환 메뉴를 무작정 테스트하지 않는다.
- `sudo ./mfnavis_setup.sh`로 설치 스크립트를 실행하지 않는다.
- `/usr/bin/python3`를 다른 버전으로 바꾸지 않는다.
- 원본 `brickbots/PiFinder`의 `release`나 `main`에 직접 push하지 않는다.
- 인증 토큰이나 GitHub token을 채팅에 붙여넣지 않는다.
- `git reset --hard`, `git checkout -- <file>` 같은 되돌리기 명령은 변경 내용을 확인하기 전에는 실행하지 않는다.


---

<a id="mf_pifinder_rpi4_pi5_compatibility_ko"></a>

## mf_pifinder_rpi4_pi5_compatibility_ko.md

<a id="mf_pifinder_rpi4_pi5_compatibility_ko--mfnavis-raspberry-pi-45-trixie-호환성-요약"></a>
## MFNavis Raspberry Pi 4/5 Trixie 호환성 요약

작성일: 2026-06-26 / 갱신: 2026-09-27

이 문서는 `main` 브랜치가 Raspberry Pi OS Trixie 64-bit에서
Raspberry Pi 4와 Raspberry Pi 5 계열(Pi 5, CM5)을 같은 설치/실행 흐름으로
다루도록 정리한 호환성 노트이다.

가상환경과 `main` 설치 명령은 [Trixie 설치 안내](setup.md#mf_trixie_install_ko)를
따른다.

<a id="mf_pifinder_rpi4_pi5_compatibility_ko--결론"></a>
### 결론

- 새 설치는 `mfnavis_setup.sh`를 일반 사용자로 실행하는 흐름을 유지한다.
- Trixie boot config는 `/boot/firmware/config.txt`를 우선 사용하고, legacy OS는
  `/boot/config.txt`로 fallback한다.
- 기본 GPS 포트 설정은 `gps_port: auto`이며, 보드 profile이 실제 포트를 결정한다.
- Pi 5 계열은 OLED CS와 충돌하는 `uart3` 대신 `uart2-pi5`를 사용한다.
- Pi4는 기존 PiFinder SPI/OLED 경로를 유지하면서 GPS UART를 `/dev/ttyAMA3`로
  사용한다.
- Bluetooth HID 키보드는 Trixie BlueZ에서 userspace HID 설정을 켜야 안정적으로
  `/dev/input/event*` 장치가 생성된다.

<a id="mf_pifinder_rpi4_pi5_compatibility_ko--보드-profile"></a>
### 보드 Profile

| Profile | 대상 | UART overlay | 기본 GPS port |
| --- | --- | --- | --- |
| `pi5_class` | Raspberry Pi 5, Compute Module 5 | `dtoverlay=uart2-pi5` | `/dev/ttyAMA2` |
| `pi4` | Raspberry Pi 4 | `dtoverlay=uart3` | `/dev/ttyAMA3` |
| `legacy` | 그 외/미확인 Raspberry Pi | `dtoverlay=uart3` | `/dev/ttyAMA1` |

<a id="mf_pifinder_rpi4_pi5_compatibility_ko--추상화-위치"></a>
### 추상화 위치

Shell 설치 단계:

- `mfnavis_paths.sh`
- `mfnavis_board_model()`: `/proc/device-tree/model`을 읽는다.
- `mfnavis_board_profile()`: `pi5_class`, `pi4`, `legacy` 중 하나를 반환한다.
- `mfnavis_uart_overlay()`: 설치 시 boot config에 넣을 UART overlay를 반환한다.
- `mfnavis_gps_device()`: 설치 시 `/etc/default/gpsd`의 `DEVICES` 초기값을 반환한다.

Python 런타임 단계:

- `python/MFNavis/board_config.py`
- `BoardProfile`: 보드별 `gps_device`, `uart_overlay`를 묶은 profile이다.
- `get_board_profile()`: 런타임 보드 profile을 반환한다.
- `get_default_gpsd_device()`: `gps_port: auto`가 실제 gpsd device로 해석될 때 사용된다.

기타 하드웨어 추상화:

- `python/MFNavis/boot_config.py`: active boot config 경로를 반환한다.
- `python/MFNavis/displays.py`: `/dev/spidev0.0`, `/dev/spidev10.0` 순서로 사용 가능한
  SPI 장치를 선택한다.
- `python/MFNavis/sys_utils.py`: GPS port/baud 설정을 `/etc/default/gpsd`와 동기화한다.
- `python/MFNavis/ui/menu_structure.py`: `GPS Port` 메뉴에 `Auto`, `ttyAMA1`,
  `ttyAMA2`, `ttyAMA3` 및 USB serial 후보를 제공한다.

Shell과 Python에 profile 판별이 각각 있는 이유는 설치 스크립트가 Python 패키지 설치와
서비스 배치 전에 먼저 실행되기 때문이다. 두 구현은 같은 profile 이름과 같은 기본값을
사용하도록 맞췄고, Python 쪽은 단위 테스트로 보드별 값을 검증한다.

<a id="mf_pifinder_rpi4_pi5_compatibility_ko--설치-시-적용되는-항목"></a>
### 설치 시 적용되는 항목

`mfnavis_setup.sh`는 다음 작업을 보드/OS에 맞게 적용한다.

- 필요한 Trixie 패키지 설치
- `/etc/default/gpsd`에 보드별 GPS device 초기값 적용
- `MFNavis_data` 디렉터리를 현재 OS 사용자 소유로 생성
- `/etc/wpa_supplicant/wpa_supplicant.conf`가 없으면 생성
- `/boot/firmware/config.txt` 또는 `/boot/config.txt`에 SPI/I2C/PWM/UART 설정 추가
- Pi 5 계열에서 `uart3`가 남아 있으면 주석 처리하고 `uart2-pi5` 사용
- Bluetooth input 설정에 `UserspaceHID=true`, `LEAutoSecurity=true` 적용
- systemd/Samba 설정을 현재 OS 사용자와 경로 기준으로 렌더링

<a id="mf_pifinder_rpi4_pi5_compatibility_ko--보드별-확인-포인트"></a>
### 보드별 확인 포인트

Raspberry Pi 4:

- `/dev/spidev0.0`가 OLED/LCD SPI 장치로 보이는지 확인한다.
- boot config에 `dtoverlay=uart3`가 적용됐는지 확인한다.
- GPS UART는 기본적으로 `/dev/ttyAMA3`로 확인한다.
- Pi4 카메라 포트에서는 보통 CM5 `cam0` 파라미터가 필요하지 않다.

Raspberry Pi 5 / CM5:

- `/dev/spidev10.0`만 보여도 정상일 수 있다.
- `uart3`는 GPIO8/9를 사용해 SSD1351 OLED의 `CS=GPIO8/CE0`와 충돌할 수 있으므로
  `dtoverlay=uart2-pi5`를 사용한다.
- GPS UART는 기본적으로 `/dev/ttyAMA2`로 확인한다.
- CM5 IO 보드의 `CAM0`에 카메라를 연결한 경우 camera overlay에 `cam0` 파라미터가
  필요할 수 있다.

Bluetooth 키보드:

- `bluetoothctl devices Paired`로 paired 장치를 확인한다.
- 연결 후 `/dev/input/event*`와 `libinput list-devices`에 키보드가 보여야 한다.
- 키 입력이 없으면 `libinput debug-events --device /dev/input/eventX`로 실제 이벤트를
  확인한다.

<a id="mf_pifinder_rpi4_pi5_compatibility_ko--검증-명령"></a>
### 검증 명령

```bash
cd ~/MFNavis
bash -n mfnavis_paths.sh mfnavis_setup.sh

source ./mfnavis_paths.sh
mfnavis_board_profile
mfnavis_uart_overlay
mfnavis_gps_device

source scripts/activate_dev_trixie.sh
python -m ruff check MFNavis tests
python -m pytest tests/test_sys_utils.py -q
python -m pytest -m smoke
```

하드웨어 상태 확인:

```bash
ls -l /boot/config.txt /boot/firmware/config.txt 2>/dev/null || true
grep -n "dtparam\|dtoverlay\|camera_auto_detect" /boot/config.txt /boot/firmware/config.txt 2>/dev/null || true
ls -l /dev/i2c-* /dev/spidev* /dev/ttyAMA* /dev/ttyUSB* /dev/ttyACM* /dev/input/event* 2>/dev/null || true
systemctl status mfnavis mfnavis_splash indiwebmanager gpsd gpsd.socket bluetooth --no-pager
```

<a id="mf_pifinder_rpi4_pi5_compatibility_ko--현재-실측-상태"></a>
### 현재 실측 상태

- CM5 Bookworm 64-bit: CM5/Pi5 계열 대응의 기준 장비로 사용했다.
- Raspberry Pi 4 Bookworm 64-bit: 설치, 서비스 시작, 카메라, GPS UART 인식,
  Bluetooth HID 키보드 event 생성까지 확인했다.
- Raspberry Pi 5 Trixie/Python 3.13: 2026-09-26/27 설치·서비스·OnStepX를
  점검했고, 사용자는 2026-09-27 GoTo 실테스트에서 큰 문제를 발견하지 못했다고
  보고했다.
- Pi 4와 CM5의 Trixie 실기 검증은 과거 Bookworm 결과와 구분한다.
  같은 profile을 사용한다는 사실만으로 실기 검증 완료를 뜻하지 않는다.


---

<a id="mf_trixie_install_ko"></a>

## mf_trixie_install_ko.md

<a id="mf_trixie_install_ko--mfnavis-trixie-64-bit-설치-매뉴얼"></a>
## MFNavis Trixie 64-bit 설치 매뉴얼

[English](setup.md#mf_trixie_install_ko) | [한국어](setup.md#mf_trixie_install_ko)

갱신일: 2026-10-04. 기본 설치 환경은 Raspberry Pi 4/Pi 5/CM5의
Raspberry Pi OS Trixie 64-bit / Python 3.13입니다. 보드 profile은 공통으로
지원하지만 이번 Trixie 실기 검증 장비는 Raspberry Pi 5입니다.
Pi 4와 CM5의 Trixie 실기 확인은 별도로 필요합니다. 이전 Bookworm 실측은
[과거 설치 기록](setup.md#mf_bookworm_install_ko)에 보존합니다.

<a id="mf_trixie_install_ko--os-준비"></a>
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

<a id="mf_trixie_install_ko--mfnavis-설치갱신"></a>
### MFNavis 설치·갱신

설치 대상 OS 사용자로 `sudo` 없이 실행합니다. 스크립트가 패키지·서비스 설정에
필요한 sudo 인증을 요청합니다. Trixie 기반 `main` 브랜치를 다음과 같이
설치·갱신합니다.

```bash
wget -O /tmp/mfnavis-setup.sh https://raw.githubusercontent.com/hjoungjoo/MFNavis/main/mfnavis_setup.sh &&
MFNAVIS_INSTALL_BRANCH=main bash /tmp/mfnavis-setup.sh
```

공개 버전은 [README의 태그 설치 절차](../../../README_ko.md#2-mfnavis-설치-릴리즈-또는-main)를
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
드라이버 개발은 [INDI 안내](mount.md#mf_indi_mount_install_ko)를 참고합니다.
MFDS는 native child worker로 실행하므로 별도 Cedar 서비스가 필요하지 않습니다.

새 설치의 광학 기본값은 **IMX462 Color + 수동 초점거리 8.2409 mm**입니다.
하늘 실측 Brown–Conrady 보정은 `k1=-0.12`, `k2=k3=p1=p2=0`이며, 렌즈 키와
fingerprint가 맞는 활성 프로파일을 `default_config.json`에 함께 제공합니다.
초점거리는 화면상 약 8.24 mm라도 보정 조회를 위해 네 자리 정밀도로 저장합니다.
설치된 앱이 처음 설정을 읽을 때 자동 적용하므로 보정 파일을 따로 복사할 필요가
없습니다. 기존 `~/MFNavis_data/config.json`의 렌즈·보정 설정은 재설치·갱신 시
그대로 우선합니다. 다른 카메라·렌즈 조합에서는 Lens → Auto (Measure)와
Distortion → Measure Sky로 해당 장비를 측정합니다.

<a id="mf_trixie_install_ko--하드웨어기동-확인"></a>
### 하드웨어·기동 확인

실제 부트 설정은 `/boot/firmware/config.txt`입니다.
[보드 호환성 안내](setup.md#mf_pifinder_rpi4_pi5_compatibility_ko)에 따라 Pi 4는
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
여유 공간을 확보합니다. [오프라인 캐시 안내](interfaces.md#mf_cache_download_ko)를 참고합니다.

<a id="mf_trixie_install_ko--개발-환경문서-검사"></a>
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
독립 Nox 세션은 [Trixie 개발 안내](setup.md#TRIXIE_DEVELOPMENT_ko)에 정리되어 있습니다.

<a id="mf_trixie_install_ko--검증-범위"></a>
### 검증 범위

사용자는 2026-09-27 Trixie GoTo 실테스트에서 큰 문제를 발견하지 못했다고
보고했습니다. 이는 해당 현장 사용 결과이며 모든 보드·마운트 기능의 검증 완료를
뜻하지는 않습니다. 앞선 상세 점검과 수정은 [실측 보고서 목록](../../mf_report/README.md)의
시리얼 Auto 탐색, 솔빙 실패 전환, Sync 확인 응답, INDI 제한값 기록을 참고합니다.
[2026-09-26 배포 기록](setup.md#TRIXIE_20260926_ko)은 그 날짜의 결과와 제한을 보존하며
이후 현장 시험 결과와 구분합니다.
