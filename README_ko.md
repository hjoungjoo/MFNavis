# MF PiFinder

[English](./README.md) | **한국어**

MF PiFinder는 원본 [PiFinder™](https://github.com/brickbots/PiFinder)를 기반으로
Raspberry Pi OS Bookworm 64-bit가 설치된 Pi 4/Pi 5/CM5에서 동작합니다.
한국어 운영 문서, 웹 카탈로그, INDI 마운트 제어 등 실사용 기능을 확장합니다.
원 제작자의 기본 사용법과 프로젝트 설명은 [영문 README의 원본 프로젝트 안내](./README.md#original-pifinder-project)를 참고하세요.

## 빠른 시작

### 1. 설치

처음 사용하는 경우에는 원본 프로젝트의 사전 제작 릴리스 이미지가 가장 간단합니다.
Bookworm에서 소스 기반으로 설치하거나 Pi 4/Pi 5/CM5를 사용하는 경우에는 다음
문서를 먼저 읽으세요.

- [Bookworm 64-bit 설치 매뉴얼](./docs/mf_dev/mf_bookworm_install_ko.md)
- [Pi 4/Pi 5/CM5 호환성](./docs/mf_dev/mf_pifinder_rpi4_pi5_compatibility_ko.md)
- [AP+STA Wi-Fi 구성](./docs/mf_dev/mf_wifi_apsta_ko.md)

설치 후 PiFinder와 같은 네트워크에 휴대기기를 연결하고 `http://pifinder.local`을
열어 웹 UI에 접속합니다. AP 모드에서 이름 해석이 되지 않으면
`http://10.10.10.1`을 사용합니다.

### 2. 오프라인 캐시 다운로드

인터넷 연결이 가능한 때 별·카탈로그 런타임 캐시와 천체 서베이 사진을 미리
준비하면, 오프라인에서도 카탈로그 탐색과 상세 화면을 더 빠르게 사용할 수 있습니다.

```bash
cd /home/pifinder/PiFinder
python3 scripts/warm_pifinder_caches.py
```

웹 카탈로그에 필요한 POSS 사진만 내려받으려면 아래처럼 실행합니다.

```bash
python3 scripts/warm_pifinder_caches.py --images poss
```

[캐시 다운로드 가이드](./docs/mf_dev/mf_cache_download_ko.md)에서 용량, 진행
상태 확인, 중단·재개 방법을 확인할 수 있습니다.

### 3. INDI 마운트 설정

INDI는 기본으로 꺼져 있는 선택 기능입니다. 먼저 Telescope Simulator로 연결과
GoTo/Sync를 확인한 뒤 실제 마운트에 적용하세요.

- [INDI 마운트 설치·설정](./docs/mf_dev/mf_indi_mount_install_ko.md)
- [마운트 모드 호환성](./docs/mf_dev/mf_mount_mode_compatibility_ko.md)

### 4. 키패드·키보드 조작

LCD 화면의 전역 키, 화면별 키 동작, USB·Bluetooth 키보드 매핑은 아래 문서를
기준으로 합니다.

- [입력 조작 가이드](./docs/mf_dev/mf_input_controls_ko.md)
- [키보드 매핑](./docs/mf_dev/mf_keyboard_mapping_ko.md)

### 5. MF 추가 기능 문서

웹 카탈로그, 위치 카탈로그, LiveCam, 자동 노출, Cedar/SEP 솔빙, SQM, IMU 보정 등
원본에 없거나 확장된 기능은 [MF 추가 기능 안내](./docs/mf_dev/mf_additional_features_ko.md)에서
분야별 상세 문서로 이동할 수 있습니다. 현재 기능의 검증 상태와 변경 내역은
[기능 검토 체크리스트](./docs/mf_dev/mf_feature_review_checklist_ko.md)와
[변경 이력](./docs/mf_dev/mf_change_history_ko.md)을 확인하세요.

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
