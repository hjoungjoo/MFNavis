# MFNavis INDI 마운트 제어

이 문서는 Raspberry Pi 4와 Raspberry Pi 5 Bookworm 64-bit 빌드에서 사용할 수 있는 선택형 INDI 마운트 제어 작업을 설명합니다.

이 기능은 기본값이 꺼짐입니다. `mount_control` 설정을 켜기 전까지 일반 MFNavis 설치에서는 PyIndi를 import하지 않고 INDI 마운트 제어 프로세스도 시작하지 않습니다.

설치 스크립트는 Raspberry Pi 4 Model B Bookworm 64-bit에서 검증했습니다. Pi 5와 CM5도 같은 Bookworm 64-bit 패키지와 aarch64 빌드 경로를 사용하며, 스크립트에는 Pi 4 전용 경로나 모델별 분기가 없습니다.

## 현재 범위

INDI 마운트 제어는 실험 기능입니다. 먼저 INDI Telescope Simulator로 테스트하고, 실제 마운트는 실내의 안전한 상태에서 충분히 확인한 뒤 야외에서 사용하세요.

이번 1차 통합 범위는 다음과 같습니다.

- PyIndi를 통한 INDI 서버 연결
- telescope/mount 장치 자동 감지
- MFNavis의 위치와 UTC 시간 동기화
- MFNavis plate-solve RA/Dec 기준 마운트 Sync
- Object Details 화면에 표시된 대상 GoTo
- Stop 명령
- 작은 RA/Dec 오프셋 기반 수동 이동

구버전 참고 브랜치에 있던 자동 target refinement, drift compensation, INDI alignment subsystem 관리 기능은 이번 1차 모듈화 포트에는 포함하지 않았습니다.

## INDI 지원 설치

기본 설치 방식은 **Pi 4/Pi 5 공용 바이너리 아카이브**입니다. MFNavis 배포본에
포함된 Bookworm 64-bit/aarch64 아카이브를 설치하면 검증된 INDI core, third-party
드라이버, PyIndi와 MFNavis의 OnStepX 패치 구성이 그대로 설치됩니다. 소스 수정이나
드라이버 패치 변경이 필요할 때만 아래의 전체 소스 설치·빌드 방식을 사용하세요.

```bash
cd ~/MFNavis
bash scripts/install_indi_mount_archive.sh \
  dist/mfnavis-indi-bookworm-arm64-v2.2.3.1-current.tar.gz
```

전체 `mfnavis_setup.sh` 설치에서는 아카이브가 `dist/`에 있거나
`MFNAVIS_INDI_ARCHIVE`로 지정되면 이 방식을 자동으로 사용합니다.

### 수정용: 전체 소스 설치·빌드

MFNavis 체크아웃에서 전용 설치 스크립트를 실행합니다.

```bash
cd ~/MFNavis
bash scripts/install_indi_mount_OnstepX.sh
```

이 스크립트는 INDI, INDI third-party 드라이버, PyIndi, INDI Web Manager, Chrony GPS 시간 동기화 지원을 설치합니다. 바이너리 설치 단계에서는 실행 중인 `mfnavis`와 INDI Web Manager 서비스를 멈추고, 성공·실패와 관계없이 원래 실행 중이던 서비스를 다시 시작합니다.

INDI Web Manager는 현재 `FastAPI 0.103.2`, `Starlette 0.27.0`, `Uvicorn 0.23.2`, `AnyIO 3.7.1` 조합으로 고정되어 있습니다. 최신 Starlette 계열에서는 INDI Web Manager의 기존 템플릿 호출 방식과 맞지 않아 Web UI 루트 페이지가 `500 Internal Server Error`를 반환할 수 있습니다.

필요하면 환경 변수로 버전과 빌드 병렬 수를 바꿀 수 있습니다.

```bash
JOBS=4 bash scripts/install_indi_mount_OnstepX.sh
```

Pi 4에서는 메모리 여유를 위해 기본 `JOBS=2`를 권장합니다. Pi 5나 CM5에서는 냉각과 전원 상태가 안정적이면 `JOBS=3` 또는 `JOBS=4`로 빌드 시간을 줄일 수 있습니다. `INDI_VERSION` / `INDI_3RDPARTY_VERSION`도 같은 방식으로 바꿀 수 있습니다.

이 스크립트는 INDI `v2.2.3.1`을 `~/indi-latest` 아래에 받아 빌드하고, `scripts/patches/indi-v2.2.3.1-onstepx.patch`를 자동으로 적용합니다. 패치는 원본 `LX200 OnStep` 드라이버를 변경하지 않고 `LX200 OnStepX` 장치와 실행 링크를 추가합니다. OnStepX 패치에는 MFNavis Backlash 범위/readback 수정과 드라이버 호환성을 위한 writable `GUIDE_RATE` 처리도 포함됩니다.

`install_indi_mount_OnstepX.sh`는 Pi 5에서 빌드하더라도 Pi 4에서 실행될 수 있도록 `-march=native`, `-mcpu=*`, `-mtune=*`를 제거하고 `-march=armv8-a`를 사용합니다. 패치 적용을 끄고 순수 upstream INDI만 테스트하려면 다음처럼 실행할 수 있습니다.

```bash
INDI_PATCH_DIR=none bash scripts/install_indi_mount_OnstepX.sh
```

`INDI_PATCH_DIR=none`은 변경되지 않은 INDI 소스 체크아웃에서만 동작한다.
이전에 OnStepX 패치를 적용한 `~/indi-latest/indi`가 있다면 별도의 빈
`BUILD_ROOT`를 지정해 새 소스를 받아 시험한다. 설치 대상과 빌드 작업 수는
시스템 패키지를 변경하기 전에 검사한다.

### 기본 설치: Pi 4/Pi 5 공용 바이너리 아카이브

일반 설치에는 미리 만든 Bookworm 64-bit/aarch64 아카이브를 사용합니다. 소스
수정이나 새 패치 검증이 필요한 경우에만 앞 절의 전체 소스 빌드로 전환합니다.

```bash
cd ~/MFNavis
bash scripts/install_indi_mount_archive.sh dist/mfnavis-indi-bookworm-arm64-v2.2.3.1-current.tar.gz
```

Git 저장소에는 큰 아카이브가 `.tar.gz.part-00`, `.part-01` 같은 조각 파일로
저장될 수 있습니다. 이 경우에도 위 명령처럼 같은 `.tar.gz` 경로를 넘기면
`install_indi_mount_archive.sh`가 조각을 다시 합치고 `.sha256` checksum을
검증한 뒤 설치합니다.

전체 MFNavis 설치 스크립트인 `mfnavis_setup.sh`에서도 같은 아카이브 설치 경로를 사용할 수 있습니다.

```bash
cd ~
MFNAVIS_INDI_ARCHIVE="$HOME/MFNavis/dist/mfnavis-indi-bookworm-arm64-v2.2.3.1-current.tar.gz" \
  bash "$HOME/MFNavis/mfnavis_setup.sh"
```

`MFNAVIS_INSTALL_INDI_ARCHIVE`는 기본값이 `auto`입니다. `dist/mfnavis-indi-bookworm-arm64-*.tar.gz` 파일이 있거나 `MFNAVIS_INDI_ARCHIVE`가 지정되어 있으면 INDI 지원을 설치하고, 없으면 일반 MFNavis 설치만 진행합니다. 강제로 끄려면 다음처럼 실행합니다.

```bash
MFNAVIS_INSTALL_INDI_ARCHIVE=false bash "$HOME/MFNavis/mfnavis_setup.sh"
```

새 바이너리 아카이브를 만들 때는 다음 스크립트를 사용합니다.

```bash
cd ~/MFNavis
bash scripts/package_indi_mount_archive.sh
```

`package_indi_mount_archive.sh`는 전체 `.tar.gz`와 `.sha256`을 만들고,
아카이브가 GitHub에 올리기 좋은 크기 제한을 넘으면 `.tar.gz.part-*`
조각 파일도 자동으로 생성합니다. 소스와 함께 배포할 때는 이 조각 파일들을
커밋하면 됩니다.

최신 소스 빌드 스크립트로 만든 뒤 아카이브를 생성하면 패치된 `LX200 OnStepX`가 포함된 설치 결과를 Pi 4/Pi 5 공용 아카이브로 배포할 수 있습니다. 아카이브 metadata에는 OnStepX patch 이름과 checksum이 기록되어 설치된 바이너리가 어떤 patch에서 만들어졌는지 추적할 수 있습니다.

## 마운트 드라이버 설정

INDI Web Manager를 엽니다.

```text
http://<hostname>.local:8624
```

mDNS 이름이 동작하지 않으면 MFNavis IP 주소를 사용합니다.

```text
http://<pifinder-ip>:8624
```

Profile을 만들고 사용하는 마운트에 맞는 telescope driver를 선택합니다. 필요하면 Auto Start와 Auto Connect를 켠 뒤 profile을 시작합니다. 흔한 드라이버는 EQMod, LX200, iOptron, Celestron, Telescope Simulator입니다.

활성 INDI profile이 `LX200 OnStepX`를 사용할 때는 MFNavis 웹 UI의 다음 영역에서 연결 방식을 설정할 수 있습니다.

```text
INDI > LX200 OnStepX Driver Connection
```

USB 연결은 감지된 `/dev/serial/by-id`, `/dev/serial/by-path`, `/dev/ttyUSB*`, `/dev/ttyACM*`
목록에서 선택하거나 수동으로 포트 이름을 입력하고, Communication Speed에서
`9600`/`19200`/`38400`/`57600`/`115200`/`230400`/`460800` baud를
선택합니다.
같은 실제 장치를 가리키는 by-id와 ttyUSB/ttyACM alias는 목록에서 한 항목으로
합치며, 가능한 경우 재삽입에도 안정적인 `/dev/serial/by-id/...`를 표시합니다.
Serial Port에서 `Auto (Find connected OnStep)`를 선택하면 Communication Speed도
Auto로 전환됩니다. Apply 시에만 현재 local serial 후보를 configured GPS와
중복 제거한 뒤, 읽기 전용 `:GVP#`/`:GVN#` 응답을 지원 baud별로 확인합니다.
검증된 OnStep이 정확히 하나일 때만 concrete stable port와 실제 baud를 적용하며,
후보가 없거나 둘 이상이면 기존 연결을 원복하고 설정을 저장하지 않습니다.
적용 시 드라이버를 먼저 disconnect하고 `DEVICE_PORT`와 INDI 표준
`DEVICE_BAUD_RATE`를 함께 쓴 다음 reconnect·readback 검증·`CONFIG_SAVE`를
수행합니다. 속도 선택은 USB Serial일 때만 적용되며 기본값은 9600 baud입니다.
네트워크 연결은 AP에 접속된 장치 목록에서 IP를 선택하거나, 목록에 없으면
IP/host와 TCP port를 수동으로 입력합니다. OnStep 네트워크 연결의 기본 TCP
port는 `9999`입니다.

OnStep transport의 운용 기준은 INDI live property, INDI가 저장한 XML,
MFNavis mirror 순입니다. 시작 시 live/XML이 유효하면 MFNavis mirror만 해당
값으로 맞추며 정상 driver 설정을 되돌리거나 재적용하지 않습니다. live/XML이
모두 불완전할 때만 마지막으로 검증된 MFNavis mirror를 한 번 적용하고 live
readback을 확인합니다. 모두 불완전하면 잘못된 기본값으로 접속하지 않고
`config_invalid` 상태로 자동 접속을 중지합니다.

Web에서 저장할 때는 INDI reconnect와 live readback, `CONFIG_SAVE`까지 성공해야
MFNavis의 transport/server 설정이 한 번의 atomic write로 갱신됩니다. 실패하면
기존 mirror를 유지합니다. reconciliation 상태는 tmpfs의
`mount_control_status.json`에 기록됩니다.

## MFNavis INDI 웹 메뉴

MFNavis 웹 UI 상단 메뉴에는 `INDI` 항목이 별도로 표시됩니다. 이 페이지에서 INDI Web Manager로 바로 이동하고, 실행 중인 INDI profile에서 active driver 이름을 읽습니다. OnStepX 전용 설정과 제어 영역은 active driver가 `LX200 OnStepX`일 때만 표시됩니다.

### Current INDI Driver State

활성 INDI profile, active driver, 사용 가능한 driver 속성을 표시합니다. OnStepX의 연결 방식, serial/network 설정, OnStep 위치, OnStep UTC 시간은 INDI profile이 시작되고 `LX200 OnStepX` 드라이버가 로드된 뒤에 표시됩니다.

### Location and Time

`Location and Time` 영역은 `LX200 OnStepX`에서 표시되며 MFNavis의 현재 위치와 UTC 시간을 OnStep에 전송합니다.

- 위치는 GPS lock이 있으면 GPS/loaded location 값을 사용합니다.
- GPS lock이 없으면 `GPS Lock: Not locked`로 표시하고, MFNavis `Locations`의 기본 위치를 `Location to Send`로 사용합니다.
- UTC 시간 입력칸은 화면을 열어 둔 동안 초 단위로 계속 갱신됩니다.
- `Reload Current Values`는 MFNavis 위치/시간과 OnStep의 현재 위치/시간 표시를 다시 읽습니다.
- `Send Location and Time`을 누르면 서버가 요청을 받은 바로 그 시점의 MFNavis system UTC를 다시 계산해서 OnStep에 전송합니다. 따라서 브라우저나 휴대폰 시간이 틀려 있어도 최종 전송 시간은 MFNavis 기준입니다.
- Web 요청은 driver가 느리거나 사용할 수 없는 경우에도 페이지가 멈추지 않도록 제한된 background sync로 시작합니다. 완료되면 상태 영역을 자동으로 새로 고치고, 결과와 driver readback 값을 표시합니다.
- GPS가 새로 lock한 위치는 자동 적용합니다. 이후 GPS 변화는 jitter로 인한 mount 갱신을 막기 위해 500 m 초과이고 1분에 한 번 이하일 때만 적용합니다. `Locations`에서 위치를 Load하거나 기본 위치로 지정하는 것은 명시적 선택이므로 선택한 좌표를 즉시 적용합니다.
- LX200 OnStepX 드라이버는 MFNavis용 커스텀 INDI 드라이버입니다. 위치/시간 동기화는 INDI `GEOGRAPHIC_COORD`/`TIME_UTC` 전체 벡터를 통해 처리하며, 드라이버 내부에서 OnStep LX200 명령으로 변환합니다.
- `indi_setprop` CLI로 일부 element만 쓰는 방식은 피합니다. MFNavis는 PyIndi 전체 벡터 전송을 사용합니다.
- 한국 시간대처럼 UTC+9인 환경에서 INDI `TIME_UTC.OFFSET`은 `+9.00`으로 전송되고, 드라이버가 OnStep의 `:SG-09:00#` convention으로 변환합니다.

### Mount Control

`Mount Control` 영역은 `LX200 OnStepX`에서 표시되며 간단한 초기화/주차/수동 이동 기능을 제공합니다.

- Home 상태와 Park 상태를 분리해서 표시합니다. OnStep은 `At Home`이면서도
  `Unparked`일 수 있습니다. OnStep Web UI는 `At Home`과 `Parked` 모두에서
  Park 버튼을 비활성화하므로, MFNavis는 디버깅을 위해 원시 `:GU#` 마운트
  상태도 함께 표시합니다.
- `At Home`, `Return Home`, `Park`, `Unpark`, `Set-Park` 명령을 보낼 수 있습니다.
- Slew Rate는 OnStep의 0-9 단계를 그대로 사용합니다: `Off`, `1/2`, `1`, `2`, `4`, `8`, `20`, `48`, `1/2 MAX`, `MAX`.
- 방향 버튼은 누르고 있는 동안 이동하고, 손을 떼면 정지 명령을 보냅니다.
- 대각선 버튼은 North/South와 East/West 명령을 함께 보냅니다.

이 웹 제어는 INDI 드라이버에 직접 명령을 보내는 보조 UI입니다. Object Details 화면의 숫자 키 기반 Sync/GoTo 기능과 함께 사용할 수 있습니다.

### OnStepX 설정

`Settings > INDI Setting` 메뉴에는 OnStepX 유지보수 제어가 포함됩니다.
(이전에는 `Start > INDI > Setting`에 있었으나, 이제 다른 설정 메뉴와 함께
`Settings` 아래에 위치합니다.)

- `Multi Align`은 Web/LCD/SkySafari가 같은 공통 session controller를
  사용합니다. 시작 시 MFNavis 위치/시간을 mount에 전송하고, MFNavis가
  현재 보고 있다고 판단하는 좌표로 mount를 sync한 뒤 readback을 검증합니다.
  OnStepX native `:A<n>#` 시작은 home/frame reset 부작용 때문에 즉시 호출하지
  않고 지연하며, stale native align 상태가 남아 있으면 `:SX09,0#` 직접 명령으로
  정리한 뒤 진행합니다. 자세한 흐름은
  `docs/mf_dev/mf_multipoint_align_flow_ko.md`를 참고하세요.
- `Backlash`는 INDI driver의 `Backlash.Backlash RA`,
  `Backlash.Backlash DEC` 속성을 읽고 씁니다. 이 값은 OnStep의 RA/Azm,
  Dec/Alt 백래시 arc-second 값에 대응합니다.
- Alt/Az 모드 UI에서는 OnStep 축 이름에 맞춰 첫 번째 값
  `Backlash.Backlash RA`를 `AZ`(Axis1 RA/Azm), 두 번째 값
  `Backlash.Backlash DEC`를 `ALT`(Axis2 Dec/Alt)로 표시합니다. EQ 모드에서는
  기존처럼 `RA` / `DEC`로 표시합니다.
- 수동 `Save Backlash` 동작은 설정값만 갱신하고 마운트 이동 명령을 보내지
  않으므로 실내에서도 안전하게 테스트할 수 있습니다.
- `Auto Backlash`는 현재 내부 이름은 `compass_goto_loop`로 유지하지만,
  실제 측정 이동은 INDI GoTo로 수행합니다. 계산, 필터, 추천값 산출 방식은
  유지하고, Alt/Az 마운트에서는 `AZ`와 `ALT`, EQ 마운트에서는 `RA`와 `DEC`를
  한 축씩 따로 움직입니다. 자세한 순서도와 계산식은
  `docs/mf_dev/mf_backlash_measurement_flow_ko.md`를 참고하세요.
- 자동 Backlash 테스트는 테스트 전 `TELESCOPE_TRACK_STATE.TRACK_OFF`로
  tracking을 끄고, 정상 완료 시 원래 tracking이 켜져 있었다면 다시 복구합니다.
  Tracking이 켜진 상태에서는 sidereal motion이 IMU 변화로 섞여 백래시로
  오판될 수 있습니다.
- 자동 Backlash 테스트는 더 이상 IMU 지자계를 확인하지 않습니다. 대신
  `PointingCoordinateService.solved`의 plate-solved 좌표가 유효해야 합니다.
  fresh solved 좌표가 없으면 mount 이동 명령을 보내기 전에 대기/실패합니다.
- 측정값이 `3600 arc-sec` 상한에 도달하면 UI는 낮은 신뢰도 경고를 표시합니다.
  이 경우 실제 백래시가 설정 범위를 넘었거나 solved 좌표가 stale이거나 잘못된
  시점에 저장되었을 수 있으므로 바로 저장하지 말고 반복 데이터와 장비 기계
  상태를 확인합니다.
- 현재 자동 측정은 Backlash 값을 0으로 초기화하거나 자동 적용하지 않습니다.
  측정 결과는 추천값으로만 표시되며, 사용자가 입력값을 확인한 뒤
  `Save Backlash`로 저장합니다. 테스트 완료 시 원래 tracking 상태가 켜져
  있었다면 다시 복구합니다.

## MFNavis 제어 켜기

MFNavis UI에서 다음 메뉴로 이동합니다.

```text
Tools > Experimental > Mount Control > On
```

이 값을 변경하면 선택형 `MountControl` 프로세스를 깨끗하게 시작하거나 종료하기 위해 MFNavis가 재시작됩니다.

Mount Control 프로세스는 켜져 있어도 시작 직후 INDI에 바로 연결하지 않습니다. Object Details 화면에서 `1`, Sync, GoTo 같은 마운트 명령을 실행할 때 INDI 연결을 초기화합니다.

고급 설정 키는 `default_config.json`에 있습니다.

```json
"mount_control": false,
"mount_control_indi_host": "localhost",
"mount_control_indi_port": 7624,
"onstep_connection_type": "network",
"onstep_serial_port": "",
"onstep_serial_baud": 9600,
"onstep_network_host": "",
"onstep_network_port": 9999
```

## Object Details 숫자 키 맵

Mount Control이 켜져 있으면 Object Details 화면의 숫자 키가 마운트 명령을 보냅니다.

| 키 | 동작 |
| --- | --- |
| 0 | 마운트 정지 |
| 1 | INDI 연결 초기화, MFNavis solve가 있으면 Sync |
| 2 | 현재 step 크기만큼 South 이동 |
| 3 | step 크기 줄이기 |
| 4 | 현재 step 크기만큼 West 이동 |
| 5 | 현재 표시 중인 대상 GoTo |
| 6 | 현재 step 크기만큼 East 이동 |
| 7 | 현재 MFNavis solve 위치로 마운트 Sync |
| 8 | 현재 step 크기만큼 North 이동 |
| 9 | step 크기 키우기 |

수동 이동은 현재 마운트 RA/Dec 좌표에서 작은 GoTo 오프셋을 보내는 방식입니다. 기본 step은 1도이고, `3`은 절반으로 줄이며 `9`는 두 배로 키웁니다.

## 로그와 상태 확인

MFNavis 로그에는 `MountControl.Indi` 이름으로 마운트 제어 로그가 남습니다.

상태 파일은 다음 위치에 기록됩니다.

```text
~/MFNavis_data/mount_control_status.json
```

확인에 유용한 명령은 다음과 같습니다.

```bash
systemctl status indiwebmanager.service
systemctl status mfnavis.service
journalctl -u indiwebmanager.service -n 100
tail -n 100 ~/MFNavis_data/pifinder.log
```

## 안전 테스트 순서

1. INDI 지원을 설치합니다.
2. INDI Web Manager에서 Telescope Simulator를 시작합니다.
3. MFNavis Mount Control을 켭니다.
4. 아무 대상의 Object Details 화면을 엽니다.
5. `1`을 눌러 초기화합니다.
6. MFNavis solve가 잡힌 뒤 `7`을 눌러 Sync합니다.
7. `5`를 눌러 GoTo를 보냅니다.
8. `0`으로 Stop 동작을 확인합니다.

시뮬레이터 동작을 이해한 뒤 실제 마운트 테스트로 넘어가세요.
