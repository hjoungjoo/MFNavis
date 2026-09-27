# MFNavis Raspberry Pi 4/5 Trixie 호환성 요약

작성일: 2026-06-26 / 갱신: 2026-09-27

이 문서는 `main` 브랜치가 Raspberry Pi OS Trixie 64-bit에서
Raspberry Pi 4와 Raspberry Pi 5 계열(Pi 5, CM5)을 같은 설치/실행 흐름으로
다루도록 정리한 호환성 노트이다.

가상환경과 `main` 설치 명령은 [Trixie 설치 안내](mf_trixie_install_ko.md)를
따른다.

## 결론

- 새 설치는 `mfnavis_setup.sh`를 일반 사용자로 실행하는 흐름을 유지한다.
- Trixie boot config는 `/boot/firmware/config.txt`를 우선 사용하고, legacy OS는
  `/boot/config.txt`로 fallback한다.
- 기본 GPS 포트 설정은 `gps_port: auto`이며, 보드 profile이 실제 포트를 결정한다.
- Pi 5 계열은 OLED CS와 충돌하는 `uart3` 대신 `uart2-pi5`를 사용한다.
- Pi4는 기존 PiFinder SPI/OLED 경로를 유지하면서 GPS UART를 `/dev/ttyAMA3`로
  사용한다.
- Bluetooth HID 키보드는 Trixie BlueZ에서 userspace HID 설정을 켜야 안정적으로
  `/dev/input/event*` 장치가 생성된다.

## 보드 Profile

| Profile | 대상 | UART overlay | 기본 GPS port |
| --- | --- | --- | --- |
| `pi5_class` | Raspberry Pi 5, Compute Module 5 | `dtoverlay=uart2-pi5` | `/dev/ttyAMA2` |
| `pi4` | Raspberry Pi 4 | `dtoverlay=uart3` | `/dev/ttyAMA3` |
| `legacy` | 그 외/미확인 Raspberry Pi | `dtoverlay=uart3` | `/dev/ttyAMA1` |

## 추상화 위치

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

## 설치 시 적용되는 항목

`mfnavis_setup.sh`는 다음 작업을 보드/OS에 맞게 적용한다.

- 필요한 Trixie 패키지 설치
- `/etc/default/gpsd`에 보드별 GPS device 초기값 적용
- `MFNavis_data` 디렉터리를 현재 OS 사용자 소유로 생성
- `/etc/wpa_supplicant/wpa_supplicant.conf`가 없으면 생성
- `/boot/firmware/config.txt` 또는 `/boot/config.txt`에 SPI/I2C/PWM/UART 설정 추가
- Pi 5 계열에서 `uart3`가 남아 있으면 주석 처리하고 `uart2-pi5` 사용
- Bluetooth input 설정에 `UserspaceHID=true`, `LEAutoSecurity=true` 적용
- systemd/Samba 설정을 현재 OS 사용자와 경로 기준으로 렌더링

## 보드별 확인 포인트

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

## 검증 명령

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

## 현재 실측 상태

- CM5 Bookworm 64-bit: CM5/Pi5 계열 대응의 기준 장비로 사용했다.
- Raspberry Pi 4 Bookworm 64-bit: 설치, 서비스 시작, 카메라, GPS UART 인식,
  Bluetooth HID 키보드 event 생성까지 확인했다.
- Raspberry Pi 5 Trixie/Python 3.13: 2026-09-26/27 설치·서비스·OnStepX를
  점검했고, 사용자는 2026-09-27 GoTo 실테스트에서 큰 문제를 발견하지 못했다고
  보고했다.
- Pi 4와 CM5의 Trixie 실기 검증은 과거 Bookworm 결과와 구분한다.
  같은 profile을 사용한다는 사실만으로 실기 검증 완료를 뜻하지 않는다.
