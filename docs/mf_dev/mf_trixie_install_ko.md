# MFNavis Trixie 64-bit 설치 매뉴얼

[English](mf_trixie_install_en.md) | [한국어](mf_trixie_install_ko.md)

갱신일: 2026-10-04. 기본 설치 환경은 Raspberry Pi 4/Pi 5/CM5의
Raspberry Pi OS Trixie 64-bit / Python 3.13입니다. 보드 profile은 공통으로
지원하지만 이번 Trixie 실기 검증 장비는 Raspberry Pi 5입니다.
Pi 4와 CM5의 Trixie 실기 확인은 별도로 필요합니다. 이전 Bookworm 실측은
[과거 설치 기록](mf_bookworm_install_ko.md)에 보존합니다.

## OS 준비

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

## MFNavis 설치·갱신

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
드라이버 개발은 [INDI 안내](mf_indi_mount_install_ko.md)를 참고합니다.
MFDS는 native child worker로 실행하므로 별도 Cedar 서비스가 필요하지 않습니다.

새 설치의 광학 기본값은 **IMX462 Color + 수동 초점거리 8.2409 mm**입니다.
하늘 실측 Brown–Conrady 보정은 `k1=-0.12`, `k2=k3=p1=p2=0`이며, 렌즈 키와
fingerprint가 맞는 활성 프로파일을 `default_config.json`에 함께 제공합니다.
초점거리는 화면상 약 8.24 mm라도 보정 조회를 위해 네 자리 정밀도로 저장합니다.
설치된 앱이 처음 설정을 읽을 때 자동 적용하므로 보정 파일을 따로 복사할 필요가
없습니다. 기존 `~/MFNavis_data/config.json`의 렌즈·보정 설정은 재설치·갱신 시
그대로 우선합니다. 다른 카메라·렌즈 조합에서는 Lens → Auto (Measure)와
Distortion → Measure Sky로 해당 장비를 측정합니다.

## 하드웨어·기동 확인

실제 부트 설정은 `/boot/firmware/config.txt`입니다.
[보드 호환성 안내](mf_pifinder_rpi4_pi5_compatibility_ko.md)에 따라 Pi 4는
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
systemctl status mfnavis mfnavis_splash indiwebmanager gpsd gpsd.socket --no-pager
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
여유 공간을 확보합니다. [오프라인 캐시 안내](mf_cache_download_ko.md)를 참고합니다.

## 개발 환경·문서 검사

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
독립 Nox 세션은 [Trixie 개발 안내](TRIXIE_DEVELOPMENT_ko.md)에 정리되어 있습니다.

## 검증 범위

사용자는 2026-09-27 Trixie GoTo 실테스트에서 큰 문제를 발견하지 못했다고
보고했습니다. 이는 해당 현장 사용 결과이며 모든 보드·마운트 기능의 검증 완료를
뜻하지는 않습니다. 앞선 상세 점검과 수정은 [실측 보고서 목록](../mf_report/README.md)의
시리얼 Auto 탐색, 솔빙 실패 전환, Sync 확인 응답, INDI 제한값 기록을 참고합니다.
[2026-09-26 배포 기록](TRIXIE_20260926_ko.md)은 그 날짜의 결과와 제한을 보존하며
이후 현장 시험 결과와 구분합니다.
