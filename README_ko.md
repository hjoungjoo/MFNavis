# MFNavis

정식 저장소는 **https://github.com/hjoungjoo/MFNavis** 입니다. 설치 경로는 `~/MFNavis`, 데이터 경로는 `~/MFNavis_data`입니다.

제품 **MFNavis** · 판매·배포 **FNPD 한국** · 제작·수정 **MagicFly**.
[제3자 고지](THIRD_PARTY_NOTICES.md) · [판매 및 대응소스 제공 기준](docs/MFNAVIS_RELEASE_ko.md).

아래 설치 절차는 개발용입니다. 판매 이미지는 별도 commercial 패키지와 판매용 lock을 사용합니다.

[English](./README.md) | **한국어**

MFNavis는 원본 [PiFinder™](https://github.com/brickbots/PiFinder)를 기반으로
Raspberry Pi OS Bookworm 64-bit가 설치된 Pi 4/Pi 5/CM5에서 동작합니다.
한국어 운영 문서, 웹 카탈로그, INDI 마운트 제어 등 실사용 기능을 확장합니다.
원 제작자의 기본 사용법과 프로젝트 설명은 [원본 프로젝트 안내 보관본](./README.upstream.md#original-pifinder-project)를 참고하세요.

## 빠른 시작

### 1. Raspberry Pi OS 준비

Raspberry Pi Imager로 Pi 4/Pi 5/CM5의 부팅 저장장치에
**Raspberry Pi OS Bookworm 64-bit**를 설치합니다. 처음 부팅하기 전에 사용자명,
호스트명, SSH, Wi-Fi를 설정하고, 부팅 후 해당 사용자로 로그인해 인터넷 연결을
확인하세요. 이 설치에서는 OS 버전을 Bookworm으로 명시적으로 선택합니다.

이미지 기록과 첫 부팅의 자세한 절차는
[Raspberry Pi 공식 OS 설치 안내](https://www.raspberrypi.com/documentation/computers/getting-started.html#install-an-operating-system)를,
보드별 배선 차이는 [Pi 4/Pi 5/CM5 호환성 안내](./docs/mf_dev/mf_pifinder_rpi4_pi5_compatibility_ko.md)를 참고하세요.

### 2. MFNavis 설치: 릴리즈 또는 main

최신 공개 버전과 정확한 태그명, 버전별 설치 안내는
[MFNavis 릴리즈 페이지](https://github.com/hjoungjoo/MFNavis/releases)에서 확인하세요.
고정된 버전을 설치하려면 릴리즈를, 최신 개발 변경 사항을 사용하려면 `main`을
선택하세요. 아래 명령은 준비한 OS 위에 MFNavis를 설치합니다.

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
새 설치 또는 기존 릴리즈 업데이트에서 실행하는 명령입니다.

```bash
MFNAVIS_RELEASE_TAG="$(python3 -c 'import json, urllib.request; print(json.load(urllib.request.urlopen("https://api.github.com/repos/hjoungjoo/MFNavis/releases/latest"))["tag_name"])')" &&
[ -n "$MFNAVIS_RELEASE_TAG" ] &&
wget -O /tmp/mfnavis-setup.sh "https://raw.githubusercontent.com/hjoungjoo/MFNavis/${MFNAVIS_RELEASE_TAG}/mfnavis_setup.sh" &&
MFNAVIS_INSTALL_BRANCH="$MFNAVIS_RELEASE_TAG" bash /tmp/mfnavis-setup.sh
```

**개발 버전(main) 설치:**

```bash
wget -O /tmp/mfnavis-setup.sh https://raw.githubusercontent.com/hjoungjoo/MFNavis/main/mfnavis_setup.sh &&
MFNAVIS_INSTALL_BRANCH=main bash /tmp/mfnavis-setup.sh
```

설치 완료 메시지를 확인한 뒤 재부팅합니다.

```bash
sudo reboot
```

#### 기존 설치를 최신 main 또는 릴리즈로 업데이트

장치의 설치 대상 사용자 계정으로 SSH 접속하여 먼저 상태를 확인하고,
`~/MFNavis_data`와 로컬 수정 사항을 백업하세요. 아래 설치 스크립트는
코드뿐 아니라 의존 패키지와 서비스 설정도 다시 적용합니다.

**최신 `main`으로 업데이트:**

```bash
git -C ~/MFNavis status -sb
wget -O /tmp/mfnavis-setup.sh https://raw.githubusercontent.com/hjoungjoo/MFNavis/main/mfnavis_setup.sh &&
MFNAVIS_INSTALL_BRANCH=main bash /tmp/mfnavis-setup.sh &&
sudo reboot
```

**최신 공개 릴리즈로 업데이트:** 위의 **공개 릴리즈 설치** 명령을 다시
실행하고, 완료되면 `sudo reboot`합니다. `release` 브랜치가 아닌 GitHub의
최신 공개 릴리즈 태그를 선택합니다. 기존 설치에서 태그를 전환하려면 대상
릴리즈에 이 체크아웃 전환 기능이 포함된 설치 스크립트가 있어야 합니다.

기존 설치가 릴리즈 태그의 detached HEAD여도 `main` 또는 새 릴리즈 태그를
명시하면 전환할 수 있습니다. 추적 파일에 로컬 수정이 있거나 대상 버전이
현재 설치에서 fast-forward되지 않으면 스크립트가 중단합니다. 이 경우
`git -C ~/MFNavis status -sb`로 상태를 확인하고 수동으로 해결하세요.
별도 데이터 경로를 사용한다면 업데이트 명령에도
`MFNAVIS_DATA_DIR=/절대/경로`를 지정하세요.

#### 설치 경로와 기존 설치에 따른 차이

| 상황 | 동작 및 안내 |
| --- | --- |
| 사용자명이 `pifinder` | 코드: `/home/pifinder/MFNavis`, 데이터: `/home/pifinder/MFNavis_data`. |
| 다른 사용자명 | 같은 명령으로 해당 사용자 홈의 `~/MFNavis`, `~/MFNavis_data`에 설치합니다. 이후 명령도 같은 사용자로 실행하세요. |
| `~/MFNavis_main` 등 별도 코드 경로 | 설치 스크립트는 어디서 실행해도 대상 사용자 홈의 `MFNavis`를 사용합니다. `MFNAVIS_REPO_DIR`로 바꿀 수 없으므로 새 설치에는 기본 경로를 사용하세요. |
| 별도 데이터 경로 | 설치 명령 앞에 `MFNAVIS_DATA_DIR=/절대/경로`를 지정합니다. 이후 업데이트와 캐시 명령에도 같은 값을 지정해야 합니다. 기존 데이터는 자동 이동하지 않습니다. |
| `~/MFNavis`가 이미 있음 | `MFNAVIS_INSTALL_BRANCH`로 지정한 브랜치 또는 태그로 fast-forward 갱신합니다. 생략하면 현재 브랜치를 갱신하며, 태그 checkout에서는 대상을 반드시 지정해야 합니다. |
| 태그로 설치한 기존 릴리즈 | 위 최신 `main` 명령으로 브랜치에 전환하거나 공개 릴리즈 명령으로 더 새로운 태그에 전환합니다. |

`mfnavis_update.sh`는 현재 브랜치의 **코드만** 갱신하는 별도 경로입니다.
태그 설치에서는 사용할 수 없고, 의존 패키지·서비스 템플릿·OS 설정이 바뀌면
안전상 중단합니다. 위의 `main`·릴리즈 갱신에는 전체 설치 스크립트를 사용하세요.

패키지 구성은 [MFDS 바이너리 설치 안내](./docs/MFDS_BINARY_DISTRIBUTION_ko.md)를 참고하세요.
INDI 마운트 지원은 선택 사항으로, 설치 스크립트가 INDI 아카이브를 찾거나 지정받은
경우에만 설치합니다. 그 외에는 [INDI 설치 안내](./docs/mf_dev/mf_indi_mount_install_ko.md)를 따르세요.

### 3. 오프라인 캐시 다운로드

**전체 이미지 다운로드는 시간이 오래 걸리는 작업입니다.** 수천 장의 서베이 이미지를
받으므로 네트워크와 서버 상태에 따라 수 시간이 걸릴 수 있습니다. 관측 당일 직전에
시작하기보다 미리 준비하세요. 장치 전원과 인터넷 연결을 유지하고, POSS+SDSS 전체
캐시에는 **최소 6 GB의 여유 공간**을 확보하세요. 휴대전화가 MFNavis AP에 연결된
것만으로는 MFNavis 자체에 인터넷이 제공되지 않을 수 있습니다.

설치된 저장소에서 별·카탈로그 런타임 캐시와 POSS/SDSS 이미지를 모두 준비합니다.

```bash
cd ~/MFNavis
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
`MFNAVIS_DATA_DIR=/절대/경로`를 지정하세요.

용량·진행 확인과 문제 해결은 [캐시 다운로드 가이드](./docs/mf_dev/mf_cache_download_ko.md)를 참고하세요.

### 4. 장치 기본 설정

1. **부팅과 조작 확인:** 재부팅 후 LCD와 키패드가 동작하는지 확인합니다.
   [입력 조작](./docs/mf_dev/mf_input_controls_ko.md)과
   [키보드 매핑](./docs/mf_dev/mf_keyboard_mapping_ko.md)을 참고하세요.
2. **하드웨어 선택:** `Settings > Advanced`에서 장착 방향에 맞는 `MFNavis Type`,
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
   MFNavis와 망원경의 시선을 맞춥니다. 카탈로그 대상을 선택해 Push-to 방향을 확인합니다.
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

## Upstream reference / 원본 프로젝트 자료

[Historical upstream documentation](README.upstream_ko.md) is preserved for provenance.

[Product paths / 제품 경로 이전](docs/MFNAVIS_PATHS_ko.md)
