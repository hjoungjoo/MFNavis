# 새 디바이스 작업 체크리스트

이 체크리스트는 MFNavis `main` 브랜치의 Trixie 64-bit / Python 3.13 기준이다.
현재 설치·검증 범위는 [Trixie 안내](mf_trixie_install_ko.md)를 참고한다.
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

## 목표

새 디바이스에서 확인할 핵심 목표는 네 가지이다.

1. `main` 브랜치가 새 OS에서 설치되는지 확인한다.
2. CM5/Trixie 대응 수정이 Raspberry Pi 4 동작을 깨지 않는지 확인한다.
3. Raspberry Pi 5 계열은 `pi5_class` profile의 UART/GPS/SPI 경로를 타는지 확인한다.
4. 문제가 생기면 로그를 남기고 같은 브랜치에 수정 커밋을 반영한다.

## 시작 전 준비

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

## 1. 새 디바이스 최초 접속 후 기본 확인

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

## 2. 소스 받기

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

## 3. 호환성/변경 이력 문서 읽기

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

## 4. 설치 전 상태 저장

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

## 5. 설치 스크립트 실행

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

## 6. 재부팅 전 확인

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

## 7. 첫 재부팅

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

## 8. 하드웨어 연결 순서

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

## 9. LCD / 키패드 / IMU 확인

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

## 10. 카메라 확인

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

## 11. GPS 확인

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

## 12. USB/Bluetooth 키보드 확인

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

## 13. 한국어 메뉴 확인

PiFinder 메뉴에서 한국어를 선택한다.

```text
Settings > User Pref... > Language > Korean
```

확인할 것:

- 재시작 후 한국어 메뉴가 표시되는지
- 한글 글자가 깨지지 않는지
- 천문 용어가 너무 어색하지 않은지
- 미번역 문자열은 영어로 자연스럽게 fallback되는지

## 14. 문제 발생 시 Codex에게 줄 자료

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

## 15. 수정 후 GitHub에 반영

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

## 16. PR 준비

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

## 17. 금지 또는 주의 작업

- 원격 접속만 가능한 상태에서 네트워크 전환 메뉴를 무작정 테스트하지 않는다.
- `sudo ./mfnavis_setup.sh`로 설치 스크립트를 실행하지 않는다.
- `/usr/bin/python3`를 다른 버전으로 바꾸지 않는다.
- 원본 `brickbots/PiFinder`의 `release`나 `main`에 직접 push하지 않는다.
- 인증 토큰이나 GitHub token을 채팅에 붙여넣지 않는다.
- `git reset --hard`, `git checkout -- <file>` 같은 되돌리기 명령은 변경 내용을 확인하기 전에는 실행하지 않는다.
