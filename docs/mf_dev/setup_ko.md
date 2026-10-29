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

**새 설치의 기본 카메라는 IMX462**입니다. 위 일반 설치 명령을 그대로
사용하면 Pi 5/CM5 Trixie에서 IMX678 드라이버·오버레이·튜닝·메뉴 권한도
함께 준비됩니다. 사용자가 설치 옵션을 지정할 필요는 없습니다.

설치 이후 `Settings > Advanced > Camera Type > IMX678 (Auto)`를 선택하면
CM5에서는 **CSI0, 4레인, 74.25 MHz, GPIO34/35 전원·리셋 시퀀스**가 자동
적용되고 재부팅됩니다. IMX462·IMX296·IMX477로 바꿨다가 IMX678로 돌아와도
컨버터 설정을 유지합니다. 이미 선택된 IMX678을 다시 선택하면 재부팅하지
않습니다. 센서 교체는 전원을 끈 상태에서 진행합니다.

아래 환경 변수는 관리·자동화용 선택사항이며 일반 설치에는 필요하지 않습니다.

| 설치 옵션 | 동작 |
| --- | --- |
| `MFNAVIS_CAMERA=keep` (기본) | 기존 카메라 보존, 선택이 없는 새 설치만 IMX462 |
| `MFNAVIS_CAMERA=imx678-cm5-converter` | CM5 CSI0 컨버터 드라이버 설치 및 선택 |
| `MFNAVIS_CAMERA=imx678` | IMX678 설치 및 선택; CM5는 CSI0 컨버터 기본값, 저장된 배선 옵션 우선 |
| `MFNAVIS_CAMERA=imx462` / `imx296` / `imx477` | 해당 카메라를 명시적으로 선택 |
| `MFNAVIS_INSTALL_IMX678=auto` (기본) | Pi 5/CM5 Trixie 또는 IMX678 선택 장치에 지원 설치 |
| `MFNAVIS_INSTALL_IMX678=true` | 다른 환경에서도 IMX678 준비 요청; 호환성 검증 필수 |
| `MFNAVIS_INSTALL_IMX678=false` | IMX678 지원 설치 생략; 현재/요청 카메라가 IMX678이면 오류 |

카메라를 바꾸지 않는 재설치에는 `MFNAVIS_CAMERA`를 생략합니다. 설치된
IMX678은 자동으로 다시 준비하며 부팅 옵션과 사용자 튜닝을 보존합니다.
기본 지원 준비만으로 기존 IMX462를 IMX678로 바꾸지는 않습니다.
CM5의 최초 IMX678 선택은 CSI0 컨버터 설정입니다. 다른 보드는 일반 모듈의
CAM1·2레인·24 MHz 기본값을 사용합니다. 기존에 저장한 사용자 지정 IMX678
배선 옵션이 있으면 해당 옵션을 우선 보존합니다.

**MFNavis_A0 키패드 LED 자동 감지**: 시작할 때 GPIO12 리셋을 해제한 뒤
주소 `0x5B`의 ID 레지스터 `0x10`을 읽는다. `0x23`이면 A0로 판별하여
`~/MFNavis_data/config.json`에 `"board_mode": "MFNavis_A0"`를 저장하고
AW9523BTQR 드라이버를 사용한다. CM5 모델명으로 보드를 추정하지 않는다.
매번 시작할 때 실제 칩을 다시 확인하며, 저장값이 같으면 파일을 다시 쓰지 않는다.
칩이 없으면 이전 저장값과 관계없이 `legacy` 모드를 저장하고 기존 GPIO13 PWM을
사용한다. `legacy → MFNavis_A0 → legacy` 전환에 설정 삭제나 수동 옵션은 필요 없다.
ID 읽기 무응답은 세 번 재시도한 뒤 부재로 판단한다. 권한 오류·버스 오류·타임아웃은
칩 부재와 구분하여 모드를 덮어쓰지 않고 LED만 비활성화한다.

모드 판정은 `python/MFNavis/keypad_led.py`, 공통 모드 이름과 조회 함수는
`python/MFNavis/board_config.py`의 `get_board_mode(cfg)`에서 관리한다.
향후 A0 전용 기능도 이 함수를 사용하며 CPU 모델명으로 A0를 추정하지 않는다.
보드 감지 자체가 변경하는 항목은 `board_mode`뿐이다. 기존 모드에서는 사용자 설정을
그대로 사용한다. A0에서는 아래 FRAM 동기화 정책에 따라 설정을 읽고 저장한다.
보드 교체는 전원을 끈 상태에서 수행하며 새 보드는 다음 앱 시작에 감지한다.

**A0 키 입력 자동 선택**: 동일한 판정으로 SW1 숫자 조이스틱, SW2 방향 조이스틱,
SW3~SW10 전용 배치를 적용한다. 예약 키도 Keyboard → Test Keys에서 인식하며
기본 기능은 비워 둔다. 기존 보드의 키 배치는 유지한다. 추가 설치 옵션·패키지는
필요 없으며, 소스 업데이트와 앱 재시작으로 적용된다.
[입력 배치·설정·실물 검사](../MFNAVIS_A0_KEYPAD_ko.md)를 참고한다.

**A0 IMU 자동 선택**: 같은 `board_mode` 판정으로 A0에서는 I2C1 `0x4B`의
BNO086을, 기존 보드에서는 BNO055를 사용한다. 일반 설치에
`adafruit-circuitpython-bno08x==1.3.3`이 포함되므로 별도 설치 옵션이 없다.
A0는 시작할 때만 지자계로 대략적인 자북 방향을 얻고, 그 방위를 유지한
Game Rotation Vector로 계속 동작한다. 초기 자기장 벡터를 Game RV의 기울기로
보정하고 안정된 여러 샘플의 방위 오프셋을 평균한다. 이후에는 자기장 보고서와
자기장 보정을 끄며, 고정 오프셋만 자세에 적용하므로 전환 중 방위가 초기화되지 않는다.
획득은 최대 5초간 시도하며 자기장 이상·수신 지연·큰 움직임 등으로 실패하면
기존 상대 자세로 시작한다. 새 앱 시작이나 센서 재초기화 시 다시 획득하고, 방위는
FRAM/config.json에 저장하지 않는다. A0에서는 저장된 `imu_use_magnetometer`
값과 관계없이 이 방식으로 동작한다. 해당 설정은 기존 보드용으로 보존한다.
네이티브 센서 축과 기존 `screen_direction` 변환을 유지한다.
`/api/imu`의 `heading_reference=startup_magnetic`, `startup_heading_status=acquired`로
획득을 확인하고, 실패 시 `relative`/`unavailable`로 표시한다. 이후 `fusion_mode`는
`game_rotation_vector`, `uses_magnetometer`는 false다. 이 초기 좌표는 자북 기준의
대략적인 좌표이며 진북·정밀 정렬로 취급하지 않는다. 기존 위치·시간으로 기본
RA/Dec를 계산하고, 별 솔빙이나 사용자 정렬 결과가 생기면 그 좌표를 우선한다.

**설치·전체 업데이트 반영**: 기본 설치와 `mfnavis_post_update.sh`의 전체 업데이트는
동일한 Python 설치 함수를 사용한다. Trixie는 운영 `.venv-trixie`, Bookworm은
선택한 운영 Python에 두 IMU 드라이버를 설치하고 패키지 메타데이터로 확인한다.
확인 과정은 GPIO/I2C를 열지 않으므로 센서를 연결하지 않아도 설치할 수 있다.
Pi 5/CM5의 I2C1 400 kHz와 이전 Pi의 소프트웨어 I2C3 설정도 공통 함수로
정규화한다. 전체 업데이트는 오래된 마이그레이션이 끝난 뒤 이 설정과 GPIO12
AW9523 리셋 예약을 적용하며 카메라·팬 설정과 `config.json`은 초기화하지 않는다.
새 부팅 설정이 적용된 경우 재부팅 후 사용한다. A0 여부와 초기 지자계 사용은
앱이 판단하므로 별도 설치 옵션은 필요 없다.

`mfnavis_update.sh`는 코드 전용 트랜잭션 업데이트다. 이번처럼 드라이버 의존성이
추가되는 릴리스는 적용 전 중단하고 일반 `mfnavis_setup.sh` 설치를 안내한다.
이 경로에서 실행 중인 환경의 패키지나 부팅 설정을 임의로 바꾸지는 않는다.

BNO086 보정 저장은 센서 내부 플래시 DCD를 사용하며 BNO055 보정 파일과
혼용하지 않는다. 자동 저장 옵션이 켜져 있으면 필요한 보고서 정확도가 모두 3이 된
뒤 실행당 한 번 저장한다. 수동 저장은 센서 응답까지 확인하며, 불러오기는 센서를
재초기화해 내부 DCD를 불러온다(저장된 DCD 존재 여부는 별도 판별하지 못한다).
기존 보정 삭제 메뉴는 A0에서 **RAM 보정 초기화**이며 저장된 플래시 DCD를
삭제하지 않는다. 콘솔에 `RAM cal reset; flash retained`로 구분해 표시한다.
이는 [CEVA SH-2의 Clear DCD and Reset 동작](https://github.com/ceva-dsp/sh2/blob/master/sh2.c)에 따른다.
자기장 사용 시에는 자기장 보정을 별도로 완료해야 절대 방위를 신뢰할 수 있다.

SHTP 송수신 순번 분리, 제어 채널 분리, 보고서 순서 보정은
`python/MFNavis/imu_bno086.py`에서 처리한다. 1초간 필수 센서 보고서가 끊기거나
통신 오류가 반복되면 IMU를 사용 불가로 표시하고 재초기화한다. A0에서 BNO086이
없거나 실패해도 BNO055로 바꿔 정상으로 표시하지 않는다.

2026-10-29 CM5/A0 실물 검사에서는 제품 ID `10004563`, 펌웨어 `3.12.6`
(build 62)를 읽었다. 앱과 같은 `Imu` 진입점의 30초 검사에서 자세 334개를
수신했고 통신 오류는 없었다. 최종 정확도는 `(3,3,2,0)`이며 기본 상대 자세 모드의
추적 상태는 3이었다. 앞선 움직임 검사에서도 회전·정지 응답을 확인했다.
플래시 보정 삭제나 절대 방위 보정, 실제 망원경/카메라 축 정렬 검증은 수행하지 않았다.

같은 날 초기 지자계 방위 획득 기능을 추가한 뒤 실물에서 `startup_magnetic` /
`acquired`를 확인했다. Game RV 전환 후 30초간 자세 308개를 오류 없이 수신했고,
전환 직후 잔여 패킷을 제외한 자기장 보고서는 0개였다. 활성 보고서는
가속도·자이로·선형 가속도·Game RV뿐이다. 검증 결과는 장비의
`MFNavis_data/test_data/bno086-20261029/startup-heading.json`에 보관한다.

추가 설치 옵션이나 패키지는 필요 없다. 설치는 GPIO12를 비워 두고
`gpio=12=op,dl,pd`와 **GPIO13만 사용하는** `dtoverlay=pwm,pin=13,func=4`를
설정한다. 두 드라이버가 시작 시 감지 결과에 따라 선택될 수 있도록 준비하는
것이며 A0에서는 PWM 출력을 시작하지 않는다. 이전 `pwm-2chan` 설정은 제거한다.
부팅 설정 변경 후 재부팅이 필요하다.

- I2C1: SDA=GPIO2, SCL=GPIO3, 주소 `0x5B` (AD1/AD0 모두 HIGH).
- RSTN=GPIO12 (헤더 32번), LED1~16은 DIM0~15에 순서대로 대응한다.
- 기존 키패드 밝기 메뉴의 `Off`, 상대 밝기, 화면 밝기 연동, 절전 시 1/4 감광을 유지한다.
- [AW9523B 데이터시트 V2.4](https://xpulabs.github.io/files/datasheet/DS_AW9523B_EN_V2.4.pdf)에
  따라 GCR `ISEL=3`으로 전류 범위를 9.25mA(typical)로 낮추고,
  DIM을 128 이하로 제한하여 LED당 약 4.64mA(typical)를 넘지 않도록 한다.
  기존 메뉴 환산을 유지하므로 화면 밝기 255에서 키패드 `0`은 약 1.20mA,
  `+3`은 약 2.36mA다. 아주 낮은 비영 밝기는 DIM=1이며 `Off`는 DIM=0이다.
- 시작 시 16개 DIM을 0으로 만든 뒤 LED 모드로 전환한다. 종료/SIGTERM 또는
  통신 오류 시 GPIO12를 LOW로 내려 소등한다. A0 초기화 실패 시에는
  LED만 비활성화하고 앱은 계속 실행한다.

기존 CM5 장비를 A0 보드로 교체할 때는 전체 설치를 다시 실행하고 재부팅한다.
코드만 갱신하는 `mfnavis_update.sh`는 부팅 설정을 변경하지 않는다.
커널 `6.18.50+rpt-rpi-2712`에서는 PWM의 실행 중 `unbind`가
`rp1_pwm_remove` 커널 오류를 일으키므로, PWM 점유 해제는 재부팅으로 수행한다.
부팅 설정만 이행하려면 새 소스에서 아래를 실행하고 재부팅한다.

```bash
cd ~/MFNavis
source mfnavis_paths.sh
mfnavis_configure_keypad_boot "$(mfnavis_boot_config_path)"
```

검증 범위: 모의 I2C/GPIO로 레지스터 초기화 순서, 16채널 밝기·전류 제한,
오류 시 소등, 메뉴·절전 연동, 실칩 ID 기반 모드 저장·재조회와 설치 설정을 검사한다.
2026-10-29 CM5/A0 실물에서 초기화 3회, 밝기 명령 12회의 ACK와 ID·LED 모드
레지스터 응답, 종료 시 GPIO12 LOW를 확인했다. 앱을 두 번 재시작하여
AW9523 드라이버 선택과 `board_mode=MFNavis_A0` 저장·유지를 확인했다.
양방향 보드 전환과 전체 사용자 설정 보존을 포함해 관련 자동 테스트는 103개
통과했다. 사용자가 점등과 밝기 변화도 확인했다. DIM 레지스터는 쓰기 전용이므로
밝기를 읽어 비교할 수 없다. 전류·온도는 계측기로 별도 확인한다.

**MFNavis_A0 FRAM 실물 검사 (2026-10-29)**: U12 FM24CL64B-GTR은
I2C1 주소 `0x50` (A0/A1/A2 LOW)의 8KiB 메모리다.
[제조사 데이터시트](https://www.infineon.com/assets/row/public/documents/10/49/infineon-fm24cl64b-64-kbit-8-k-8-serial-i2c-f-ram-datasheet-en.pdf)
기준으로 2바이트 메모리 주소와 쓰기 지연 없는 즉시 읽기를 검사했다.

- 전체 `0x0000–0x1FFF`를 두 번 읽어 일치 확인 후 원본을 파일로 백업했다.
- 앱을 잠시 중지하고 `00`, `FF`, `55`, `AA`, 주소 하위/상위 바이트,
  의사난수의 7개 전체 영역 패턴 쓰기·즉시 읽기가 모두 통과했다.
- 첫/끝 주소와 128·256·4096바이트 경계 등 10개 주소에서 단일 바이트 쓰기와
  나머지 전체 영역 보존을 확인했다.
- 원본을 복원하고 전체 SHA-256 일치를 확인했으며 앱 재시작 후에도 동일했다.
- 해당 장비의 원본 백업·검사 스크립트·JSON 결과는
  `~/MFNavis_data/test_data/fram-20261029-8abe582d/`에 보관했다.

읽기·쓰기 기능과 쓰기 보호 해제 상태를 확인한 검사다. 전원 차단 후 보존성은
검사하지 않았다. 아래 설정 백업 기능은 이 실물 검사 이후 추가했다.

**A0 FRAM 파일 저장소와 설정 동기화**

FRAM은 파일명별로 데이터를 보관하는 작은 파일 저장소로 사용한다.
`/config.json`은 그중 하나이며 다른 파일을 추가하거나 삭제해도 유지된다.
파일 경로는 절대 경로 형태이고 하위 경로는 가상 이름 공간이다. OS에 마운트하는
일반 파일시스템은 아니며 전용 Python API로 접근한다.

- 물리 8KiB를 4KiB 은행 두 개로 나눠 디렉터리 전체를 교대로 기록한다.
  새 은행의 내용·해시를 읽어 검증한 뒤 유효 표시를 마지막에 기록한다.
  중간에 저장이 끊기거나 최신 은행이 손상되면 이전 정상 은행을 사용한다.
- 각 파일의 원본 바이트에 SHA-256을 저장한다. 은행의 버전·세대·길이와 압축된
  디렉터리에도 별도 SHA-256을 저장하여 데이터와 관리 정보의 손상을 검사한다.
- 파일 데이터와 메타데이터 전체를 압축한다. 헤더를 제외한 압축 스냅샷 한도는
  **4,039바이트**이며 모든 파일이 공유한다. 현재 설정은 약 2.35KB이고 여유는
  약 1.69KB다. 새 파일의 메타데이터도 공간을 사용한다. 용량 초과 시 기존
  파일을 건드리지 않고 오류를 반환한다.
- 파일 작업은 프로세스 간 공통 잠금으로 직렬화하여 서로 다른 데이터의 동시 저장이
  다른 파일을 잃게 하지 않는다. 세션 설정은 FRAM 백업 대상이 아니다.

시작 시 실제 A0 칩을 확인한 뒤, 설정을 사용하는 GPS·디스플레이·작업 프로세스보다
먼저 FRAM을 검사한다. `/config.json`의 해시가 정상이면 FRAM을 우선하여 로컬
`config.json`과 비교하고 다를 때만 원자적으로 교체한다. 교체 전 로컬 파일은
`config.before-fram-<hash>.json`으로 보존한다. FRAM 설정 파일이 없거나 정상
백업이 전혀 없으면 `default_config.json`과 감지된 A0 모드로 초기화하고 백업한다.
다른 정상 FRAM 파일은 유지한다. 버스 오류는 빈 백업으로 간주하지 않으며,
알 수 없는 파일 저장소 버전도 덮어쓰지 않는다.

이번 최초 이관은 사용자가 요청한 **현재 설정을 먼저 백업**한다. 이후 시작에는
위의 FRAM 우선/백업 없음 시 기본값 정책을 적용한다. 일반 설정 저장과 사용자
ZIP 백업 복원도 FRAM에 검증된 새 버전을 만든다. FRAM 저장 실패·용량 초과 시
설정 변경을 성공 처리하지 않으며 이전 백업과 로컬 설정을 보존한다.
수동으로 로컬 `config.json`만 편집하면 다음 시작에 FRAM 값으로 돌아간다.
설정 변경은 앱의 메뉴·웹 또는 `Config.set_option/set_options`를 사용한다.
FRAM이 없는 기존 모드는 종전 파일 저장 방식을 유지한다.

두 보드 모드 모두 `config.json`의 `source_version`에 실행 소스의
`version.txt` 버전(`version`), 전체 Git 커밋(`git_commit`), 미커밋 변경 여부
(`git_dirty`)를 자동 기록한다. Git 정보가 없는 배포본은 해당 필드를 `null`로
남긴다. 시작 시 FRAM 복원 후 현재 소스 정보로 갱신하며, 일반 설정 저장에도
같은 정보를 포함한다. 버전 정보만 달라도 A0의 검증된 FRAM 백업을 함께
갱신한다. 이 값은 설정을 마지막으로 사용·저장한 소스의 식별 정보이며,
설정 스키마나 FRAM 파일 저장소의 포맷 버전과는 별개다.

2026-10-29 실물에 현재 설정을 이관했다. 설정 원본은 5,492바이트,
파일 관리 정보를 포함한 압축 스냅샷은 2,348바이트이며 여유는 1,691바이트다.
파일 추가·읽기·삭제 중 설정 보존, 손상된 SD 설정 복사본 복구, 실행 중
`Config.set_option`의 자동 FRAM 저장, 실제 앱 재시작 시 로컬 설정 차이 복원을
확인했다. 임시 검증 파일·설정은 제거했다. 관련 자동 테스트는 146개 통과했다.
원본 백업과 실물 검증 결과는 해당 장비의
`~/MFNavis_data/test_data/fram-config-20261029-504457cb/activation-report.json`에
기록했다. 전원을 물리적으로 끊는 검사는 수행하지 않았다.

A0 전용 데이터 파일의 API 예시(설정 변경에는 위의 Config API 사용):

```python
from PiFinder.fram_fs import open_filesystem

files = open_filesystem()
files.write_file("/calibration/imu.bin", b"calibration data")
data = files.read_file("/calibration/imu.bin")
listing = files.list_files()  # 파일별 크기와 SHA-256
space = files.stat()         # 압축 사용량/여유 공간
files.delete_file("/calibration/imu.bin")
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

푸시 전에는 기본 Nox 세션 전체를 실행한다. 일부 파일의 pytest 통과만으로는
타입 검사나 다른 테스트의 모의 객체 불일치를 확인할 수 없다.

```bash
nox --no-venv
```

기본 세션은 lint·format·type_hints·smoke_tests·unit_tests·ui_tests다.
`--no-venv`는 준비된 개발 가상환경을 재사용하며, 운영 서비스는 재시작하지 않는다.
아래 명령은 문제를 좁히기 위한 개별 검사다.

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

GitHub의 `Bookworm compatibility (Python 3.11)`은 호환성 작업 이름이며,
그 작업이 실패했다고 Python 3.11 설치가 실패한 것은 아니다. 펼쳐진
`Type checking`, `Unit tests`, `UI integration tests` 등 실제 실패 단계를
확인한다. 2026-10-11 실패는 테스트용 마운트 객체의 누락 속성이 원인이었고,
후속 복귀 오차 변수의 `Optional[float]` 선언 누락도 타입 검사에서 발견해
수정했다. 검사 생략이나 `continue-on-error`로 실패를 숨기지 않는다.

Pi 장비의 테스트 수집에서도 실제 GPIO를 열지 않도록 IMU 하드웨어 드라이버는
`Imu` 생성 시 불러온다. 순수 상태·오류 처리 함수 import는 GPIO 접근 권한이나
센서 연결을 요구하지 않으며, 실제 IMU 초기화에는 기존 드라이버를 사용한다.

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
공식 원본 소스의 해시를 검증하고, CM5 컨버터 전원 시퀀스 패치를 별도로
적용해 DKMS 0.2.0 모듈로 빌드한다. 일반 Sony 호환 장치의 시퀀스는 유지한다.
MFNavis의 Raspberry Pi용
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

전체 설치는 Pi 5/CM5 Trixie에서 IMX678 지원을 기본으로 준비한다.
새 설치는 IMX462로 시작하며 설치 이후 카메라 메뉴에서 IMX678을 선택한다.
CM5에서는 컨버터 설정이 자동 적용되므로 설치 옵션은 필요하지 않다.
재설치의 기본 `keep`은 기존 카메라 선택을 유지한다. 필요한 libcamera·빌드 패키지를
설치한 뒤 호환성을 검사하며, 커널 헤더 메타패키지를 설치해 이후 OS 커널
업데이트 시 DKMS 재빌드가 가능하게 한다. 이미 설치된 같은 종류의 새 커널도
재부팅 전에 모듈을 빌드한다. 빌드 실패나 헤더 누락은 설치 오류로 처리한다.
코드 전용 `mfnavis_update.sh`는 OS 패키지·드라이버·부팅 설정을 변경하지
않으므로 드라이버 갱신에는 전체 설치 또는 `install_imx678.sh --install`을 쓴다.

### 실제 모듈 연결 후

**MFNavis A0 PWR2-PD 컨버터 + CM5 CSI0**는 일반 설치를 마친 뒤 메뉴에서
`IMX678 (Auto)`를 선택하면 된다. 이전 버전의 설치를 수동으로 보완하거나
메뉴 접근이 어려운 경우에만 다음 명령으로 준비·선택할 수 있다:

```bash
sudo bash scripts/install_imx678.sh --activate-converter
sudo reboot
```

GPIO34 전원, GPIO35 리셋/발진기, 74.25 MHz, CSI0 4레인 전용
`imx678-mfnavis-cm5-converter` 설정을 사용한다. 설치 시 기존 부팅 설정을
백업한다. GPIO0 HIGH 후 150 ms, GPIO1 HIGH 후 5 ms를 기다리며,
종료 시 전용 I2C의 SDA/SCL을 LOW로 유지한 뒤 GPIO1 LOW → 1 ms →
GPIO0 LOW → 150 ms 순서를 적용한다. 배선·제약과 패치 출처는
[컨버터 설명](../../deployment/imx678/README.md)을 참조한다.

다음은 일반 IMX678 모듈용 절차다.

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

### 이전 일반 모듈 준비 단계의 검증 기록

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
