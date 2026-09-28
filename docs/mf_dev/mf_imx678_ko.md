# IMX678: Linux 공식 드라이버 기반 준비와 사용

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

## 지원 범위

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

## 하드웨어 없이 소프트웨어 준비

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

## 실제 모듈 연결 후

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

### CAM0·4레인·입력 클록 설정

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

## 최초 촬영 확인

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

## 이번 검증과 남은 확인

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
