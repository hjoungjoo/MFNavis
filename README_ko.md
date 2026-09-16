# MF PiFinder

[English](./README.md) | **한국어**

MF PiFinder는 원본 [PiFinder™](https://github.com/brickbots/PiFinder)를 기반으로
Raspberry Pi OS Bookworm 64-bit가 설치된 Pi 4/Pi 5/CM5에서 동작합니다.
한국어 운영 문서, 웹 카탈로그, INDI 마운트 제어 등 실사용 기능을 확장합니다.
원 제작자의 기본 사용법과 프로젝트 설명은 [영문 README의 원본 프로젝트 안내](./README.md#original-pifinder-project)를 참고하세요.

## 빠른 시작

### 1. Raspberry Pi OS 준비

Raspberry Pi Imager로 Pi 4/Pi 5/CM5의 부팅 저장장치에
**Raspberry Pi OS Bookworm 64-bit**를 설치합니다. 처음 부팅하기 전에 사용자명,
호스트명, SSH, Wi-Fi를 설정하고, 부팅 후 해당 사용자로 로그인해 인터넷 연결을
확인하세요. 이 설치에서는 OS 버전을 Bookworm으로 명시적으로 선택합니다.

이미지 기록과 첫 부팅의 자세한 절차는
[Raspberry Pi 공식 OS 설치 안내](https://www.raspberrypi.com/documentation/computers/getting-started.html#install-an-operating-system)를,
보드별 배선 차이는 [Pi 4/Pi 5/CM5 호환성 안내](./docs/mf_dev/mf_pifinder_rpi4_pi5_compatibility_ko.md)를 참고하세요.

### 2. MF PiFinder 설치: 릴리즈 또는 main

최신 공개 버전과 정확한 태그명, 버전별 설치 안내는
[MF PiFinder 릴리즈 페이지](https://github.com/hjoungjoo/MF_PiFinder/releases)에서 확인하세요.
고정된 버전을 설치하려면 릴리즈를, 최신 개발 변경 사항을 사용하려면 `main`을
선택하세요. 아래 명령은 준비한 OS 위에 MF PiFinder를 설치합니다.

새 설치에서는 아래 **두 방법 중 하나만** 실행합니다. 설치 대상 사용자 계정에서
`sudo` 없이 실행하세요. 스크립트가 필요한 작업에만 sudo를 사용합니다.
의존 패키지, 하드웨어 인터페이스, 서비스를 설정하고 **MFDS 검출기를 자동 설치**합니다.
버전에 따라 검출기 설치 방식에 차이가 있습니다.

| 버전 | 검출기 자동 설치 방식 |
| --- | --- |
| 공개 릴리즈 | 선택한 태그에 포함된 방식으로 검출기를 설치합니다. 설치 요구 사항과 빌드 여부는 해당 릴리즈 노트를 확인하세요. |
| `main` | `deployment/mfds.lock.json`에 고정된 MFDS 바이너리 릴리즈를 다운로드하고 검증합니다. 검출기 소스 빌드는 필요하지 않습니다. |

두 방식 모두 설치 스크립트가 처리하므로 MFDS를 별도로 수동 설치할 필요는 없습니다.

**공개 릴리즈 설치:**

GitHub에서 최신 공개 릴리즈 태그를 자동 조회하여 해당 버전을 설치합니다.
버전 번호를 입력할 필요가 없으며, 조회에 실패하면 설치를 중단합니다.
`~/PiFinder`가 없는 새 설치에서 실행하는 명령입니다.

```bash
PF_RELEASE_TAG="$(python3 -c 'import json, urllib.request; print(json.load(urllib.request.urlopen("https://api.github.com/repos/hjoungjoo/MF_PiFinder/releases/latest"))["tag_name"])')" &&
[ -n "$PF_RELEASE_TAG" ] &&
wget -O /tmp/mf-pifinder-setup.sh "https://raw.githubusercontent.com/hjoungjoo/MF_PiFinder/${PF_RELEASE_TAG}/pifinder_setup.sh" &&
PIFINDER_INSTALL_BRANCH="$PF_RELEASE_TAG" bash /tmp/mf-pifinder-setup.sh
```

**개발 버전(main) 설치:**

```bash
wget -O /tmp/mf-pifinder-setup.sh https://raw.githubusercontent.com/hjoungjoo/MF_PiFinder/main/pifinder_setup.sh &&
PIFINDER_INSTALL_BRANCH=main bash /tmp/mf-pifinder-setup.sh
```

설치 완료 메시지를 확인한 뒤 재부팅합니다.

```bash
sudo reboot
```

#### 설치 경로와 기존 설치에 따른 차이

| 상황 | 동작 및 안내 |
| --- | --- |
| 사용자명이 `pifinder` | 코드: `/home/pifinder/PiFinder`, 데이터: `/home/pifinder/PiFinder_data`. |
| 다른 사용자명 | 같은 명령으로 해당 사용자 홈의 `~/PiFinder`, `~/PiFinder_data`에 설치합니다. 이후 명령도 같은 사용자로 실행하세요. |
| `~/PiFinder_main` 등 별도 코드 경로 | 설치 스크립트는 어디서 실행해도 대상 사용자 홈의 `PiFinder`를 사용합니다. `PIFINDER_REPO_DIR`로 바꿀 수 없으므로 새 설치에는 기본 경로를 사용하세요. |
| 별도 데이터 경로 | 설치 명령 앞에 `PIFINDER_DATA_DIR=/절대/경로`를 지정합니다. 이후 업데이트와 캐시 명령에도 같은 값을 지정해야 합니다. 기존 데이터는 자동 이동하지 않습니다. |
| `~/PiFinder`가 이미 있음 | 설치 스크립트는 **현재 브랜치**를 fast-forward 갱신합니다. `PIFINDER_INSTALL_BRANCH`는 새로 복제할 때만 적용됩니다. 추적 파일에 로컬 수정이 있으면 중단합니다. |
| 태그로 설치한 기존 릴리즈 | 새 태그 설치는 가능하지만, 이후 detached HEAD 상태에서 설치 스크립트를 재실행하면 중단합니다. 위 새 설치 명령으로 기존 릴리즈와 `main`을 전환하지 마세요. |

기존 장치는 먼저 `git -C ~/PiFinder status -sb`로 상태를 확인하고
`~/PiFinder_data`와 로컬 수정 사항을 백업하세요. 브랜치 설치는 의도한 브랜치인지
확인한 뒤 갱신합니다. 기존 설치의 코드 갱신 후에는 해당 저장소 최상위에서
`bash pifinder_post_update.sh`를 실행해 MFDS 자동 설치를 포함한 런타임 변경을
적용합니다. 이 스크립트는 업데이트용이며 최초 OS·서비스 설치를 대신하지 않습니다.

패키지 구성은 [MFDS 바이너리 설치 안내](./docs/MFDS_BINARY_DISTRIBUTION_ko.md)를 참고하세요.
INDI 마운트 지원은 선택 사항으로, 설치 스크립트가 INDI 아카이브를 찾거나 지정받은
경우에만 설치합니다. 그 외에는 [INDI 설치 안내](./docs/mf_dev/mf_indi_mount_install_ko.md)를 따르세요.

### 3. 오프라인 캐시 다운로드

**전체 이미지 다운로드는 시간이 오래 걸리는 작업입니다.** 수천 장의 서베이 이미지를
받으므로 네트워크와 서버 상태에 따라 수 시간이 걸릴 수 있습니다. 관측 당일 직전에
시작하기보다 미리 준비하세요. 장치 전원과 인터넷 연결을 유지하고, POSS+SDSS 전체
캐시에는 **최소 6 GB의 여유 공간**을 확보하세요. 휴대전화가 PiFinder AP에 연결된
것만으로는 PiFinder 자체에 인터넷이 제공되지 않을 수 있습니다.

설치된 저장소에서 별·카탈로그 런타임 캐시와 POSS/SDSS 이미지를 모두 준비합니다.

```bash
cd ~/PiFinder
python3 scripts/warm_pifinder_caches.py
```

장치와 웹 카탈로그에서 사용하는 POSS 이미지만 받으려면:

```bash
python3 scripts/warm_pifinder_caches.py --images poss
```

이미지 다운로드 없이 런타임 캐시만 준비하려면 `--images none`을 사용합니다.
진행 상황은 터미널에 표시되며 `Cache warm-up complete`가 나오면 완료입니다.
`Ctrl-C`로 중단한 뒤 같은 명령을 다시 실행하면 기존 이미지를 건너뛰고 이어받습니다.
다운로드 중에는 SSH 세션을 유지하세요. 데이터 경로를 바꿨다면 명령 앞에
`PIFINDER_DATA_DIR=/절대/경로`를 지정하세요.

용량·진행 확인과 문제 해결은 [캐시 다운로드 가이드](./docs/mf_dev/mf_cache_download_ko.md)를 참고하세요.

### 4. 장치 기본 설정

1. **부팅과 조작 확인:** 재부팅 후 LCD와 키패드가 동작하는지 확인합니다.
   [입력 조작](./docs/mf_dev/mf_input_controls_ko.md)과
   [키보드 매핑](./docs/mf_dev/mf_keyboard_mapping_ko.md)을 참고하세요.
2. **하드웨어 선택:** `Settings > Advanced`에서 장착 방향에 맞는 `PiFinder Type`,
   실제 `Camera Type`, `GPS Settings`의 GPS 종류·포트·통신 속도를 설정합니다.
   재시작 안내가 나오면 따르세요.
3. **네트워크와 웹 UI 확인:** 같은 네트워크에서 `http://<호스트명>.local`을 엽니다.
   호스트명이 `pifinder`이면 `http://pifinder.local`입니다. AP 모드에서 이름으로
   접속되지 않으면 `http://10.10.10.1`을 사용합니다. 현장용 Wi-Fi는
   [AP+STA 구성](./docs/mf_dev/mf_wifi_apsta_ko.md)을 참고하세요.
4. **위치와 시간 확인:** 야외에서 `Start > GPS Status`를 열어 GPS 수신을 기다립니다.
   GPS를 사용하지 않으면 `Tools > Place & Time`에서 위치와 시간을 입력합니다.
5. **초점 조절:** 렌즈 캡을 벗기고 별이 보이는 하늘을 향합니다. `Start > Focus`에서
   별이 선명하고 HFD 값이 작아지도록 렌즈 초점을 조절합니다.
6. **Lens 자동 측정:** `Settings > Advanced > Lens > Auto (Measure)`를 선택하고
   장치를 움직이지 않은 채 진행 화면을 기다립니다. 안정된 별 프레임 5개가 확보되면
   `MEASURED`와 측정 화각·초점거리가 표시되고 결과가 **Manual** 렌즈로 자동 저장됩니다.
   측정 후 Lens가 Manual로 표시되는 것은 정상입니다. Auto는 자동 초점 기능이 아니라
   화각·실효 초점거리 측정이므로 앞 단계에서 초점을 먼저 맞춰야 합니다.
   별 부족·측정 실패 시 초점과 하늘 상태를 확인한 뒤 재시도하세요.
   측정 중 왼쪽 키로 돌아가면 취소되며 기존 렌즈 설정을 유지합니다.
7. **렌즈 왜곡 보정:** Auto 완료 후 `Settings > Advanced > Distortion > Measure Sky`를
   실행합니다. 화면 가장자리까지 별이 분포한 하늘을 향해 장치를 고정하고,
   유효 프레임 5개 이상과 안정된 결과가 확보되어 `MEASURED`가 나올 때까지 기다립니다.
   결과는 자동 저장됩니다. 왼쪽 키로 돌아가 `Distortion > Status`에서
   `Sky measured`와 `k1` 값을 확인하세요. `Need edge stars`가 계속 나오면
   별이 더 고르게 분포한 하늘로 방향을 바꾼 뒤 다시 고정합니다.
   Auto 측정과 왜곡 보정은 별도 작업입니다. 렌즈·카메라를 바꾸면 두 측정을 다시 하고,
   하늘 좌표가 솔빙되는지 확인하세요. 보정 프로파일의 적용 조건과 상세 설명은
   [렌즈 보정 안내](./docs/mf_dev/mf_lens_distortion_correction_ko.md)를 참고하세요.
8. **망원경과 정렬:** 알고 있는 별을 접안렌즈 중심에 놓고 `Start > Align`에서
   PiFinder와 망원경의 시선을 맞춥니다. 카탈로그 대상을 선택해 Push-to 방향을 확인합니다.
9. **마운트 제어 설정(선택):** INDI는 기본으로 꺼져 있습니다.
   [INDI 설치·설정](./docs/mf_dev/mf_indi_mount_install_ko.md)에 따라 먼저
   Telescope Simulator로 연결·GoTo·Sync를 확인한 뒤 실제 마운트를 연결합니다.

자세한 장치 조작은 [빠른 시작 설명서](./docs/source/quick_start.rst)와
[사용자 설명서](./docs/source/user_guide.rst)를 참고하세요.

### 5. MF 추가 기능 문서

웹 카탈로그, 위치 카탈로그, LiveCam, 자동 노출, MFDS, SQM, IMU 보정은
[MF 추가 기능 안내](./docs/mf_dev/mf_additional_features_ko.md)에서 확인할 수 있습니다.
기능별 검증 상태는 [기능 검토 체크리스트](./docs/mf_dev/mf_feature_review_checklist_ko.md)를 참고하세요.

---

# 원본 PiFinder™ 프로젝트 안내 — 한국어 번역

> 아래는 원작자 README의 한국어 번역입니다. 원문의 최신 내용과 라이선스 문구는
> [영문 README](./README.md#original-pifinder-project)를 기준으로 확인하세요.

이 절은 원작 프로젝트의 이력 설명이다. 현재 포크 main은 MF Detect Star를 사용하며
Cedar Detect 바이너리를 포함하지 않는다. [현재 통합](docs/DETECTOR_INTEGRATION_ko.md)과
[메인 병합·배포 기록](docs/MAIN_FINALIZATION_ko.md)을 참고한다.

PiFinder™는 Raspberry Pi, imx296 카메라, 맞춤형 UI HAT을 기반으로 하는
플레이트 솔빙 망원경 파인더입니다.

PiFinder™의 개요와 만들어진 배경은 [PiFinder.io](https://www.pifinder.io/build-yours)에서
볼 수 있습니다.

PiFinder™는 [smroid](https://github.com/smroid)가 만든
[Cedar Detect](https://github.com/smroid/cedar-detect) 및
[Cedar Solve](https://github.com/smroid/cedar-solve) 라이브러리를 사용합니다.
Cedar Solve는 Apache-2.0 라이선스로 제공됩니다.

**Cedar Detect**는 Functional Source License(`FSL-1.1-MIT`)로 공개되어 있습니다.
이 라이선스는 경쟁적인 상업적 사용을 제외한 폭넓은 비상업적 사용을 허용합니다.
PiFinder™ 역시 상업적으로 제공되므로, 프로젝트는 공개 FSL 조건이 아니라 저작권자가
명시적으로 부여한 **별도 라이선스**에 따라 Cedar Detect 바이너리를 묶어 배포합니다.
해당 바이너리는 원작 배포의 구성이며 이 포크에서는 제거했다.
현재 바이너리 정책은 [`bin/README.md`](./bin/README.md)를 참고하세요. 이는 PiFinder
프로젝트 자체의 GPL-3.0 [`LICENSE`](./LICENSE)와 별개입니다.

PiFinder를 지원해 주신 [smroid](https://github.com/smroid)에게 감사드립니다.

![PiFinder 배너](./docs/source/images/PiFinder_v3_banner.png)

PiFinder™는 망원경을 사용할 때의 경험을 더 좋게 만들고자 한 시도에서 시작되었습니다.
관측할 시간은 늘 부족하기에, 종이 성도와 이후 Nexus DSC를 사용해 온 경험을 바탕으로
다음과 같은 점을 개선하고자 했습니다.

- **신뢰할 수 있는 망원경 위치 결정:** Nexus DSC는 훌륭하지만, 제 망원경은 엔코더를
  견고하게 결합하기에 적합하지 않았습니다. 엔코더 결합부의 유격 때문에 포인팅 정확도가
  떨어졌습니다.
- **쉬운 설정:** Nexus DSC는 엔코더와 하늘의 좌표 관계를 이해하기 위해 여러 별로
  정렬해야 합니다. 아주 어려운 과정은 아니지만, 이 단계를 피하고 싶었습니다.
- **좋은 Push-to 기능:** 정확히 정렬되어 있다면 이것은 Nexus DSC가 특히 잘하는
  부분입니다. 카탈로그 시스템도 충분하지만, 대상을 선택한 뒤 망원경을 향하게 하는
  화면은 더 명확하고 도움이 되길 바랐습니다.
- **관측 기록:** 무엇을 어떤 접안렌즈로 보았는지, 관측 경험은 어땠는지를 밤마다
  기록하고 싶었습니다. 관측 현장에서 바로 기록할 수 있다면 더 편리합니다.

이 조합이 다른 사람에게도 도움이 되기를 바라며, 제안과 기여를 통해 함께 개선되기를
희망합니다. PiFinder™는 기성 부품과 초보자도 따라 할 수 있는 납땜 작업으로 비교적
쉽게 만들 수 있습니다.

## 원작의 주요 기능

- **즉시 사용:** 전원을 켜고 하늘을 향하면 됩니다.
- **정확한 위치 결정:** 내장 GPS가 위치와 시간을 제공하고, 카메라가 망원경이 향한
  하늘을 결정합니다. IMU는 카메라 솔브 사이의 망원경 움직임을 추적해 위치를 갱신합니다.
- **독립형 사용:** 기기 화면과 키패드만으로 카탈로그 검색·필터, 하늘/천체 차트,
  Push-to 안내, 관측 기록을 사용할 수 있습니다.
- **어두운 관측지에 적합:** 빨간 OLED 화면과 부드러운 백라이트 키는 밝기를 매우 낮게,
  필요하면 꺼짐까지 조절할 수 있어 밝은 휴대전화나 태블릿이 필요하지 않습니다.
- **간편한 장착:** 일반 파인더처럼 접안부 근처에 장착할 수 있습니다.
- **Wi-Fi AP / SkySafari 연동:** PiFinder™는 Wi-Fi 액세스 포인트로 동작하여 태블릿이나
  휴대전화를 연결하고 SkySafari 또는 다른 플라네타리움 소프트웨어와 망원경을 동기화할 수
  있습니다.

## 직접 만들기

PiFinder™는 완전한 오픈소스 하드웨어·소프트웨어 프로젝트입니다. 이 저장소의 파일로
PCB를 주문하고 케이스를 3D 프린팅한 뒤, [부품 목록](https://pifinder.readthedocs.io/en/release/BOM.html)을
참고해 부품을 준비할 수 있습니다.

조립된 PiFinder™나 키트 등 빠르게 시작할 수 있는 제품이 필요하다면
[PiFinder.io](https://pifinder.io/build-pifinder)를 방문하세요.

![Dobsonian 망원경에 장착한 PiFinder](./images/PiFinder_on_scope.jpg)

## 원작 문서

- [빠른 시작](https://pifinder.readthedocs.io/en/release/quick_start.html)
- [사용자 설명서](https://pifinder.readthedocs.io/en/release/user_guide.html)
- [부품 목록](https://pifinder.readthedocs.io/en/release/BOM.html)
- [빌드 가이드](https://pifinder.readthedocs.io/en/release/build_guide.html)
- [소프트웨어 설치](https://pifinder.readthedocs.io/en/release/software.html)
- [개발자 가이드](https://pifinder.readthedocs.io/en/release/dev_guide.html)

## 릴리스와 업데이트

PiFinder를 사용한다면 이 저장소의 릴리스를 구독하는 것을 권장합니다. GitHub 우측 상단의
**Watch** 버튼에서 **Custom**을 선택하고 **Releases**를 켜면 새 기능을 놓치지 않을 수
있습니다.

## Discord

빌드, 사용, 제안에 관한 지원은 [PiFinder™ Discord 서버](https://discord.gg/Nk5fHcAtWD)에서
받을 수 있습니다.
