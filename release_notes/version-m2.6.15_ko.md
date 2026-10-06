# MFNavis m2.6.15 — Trixie 지원 및 좌표·마운트 추적 개선

## 주요 변경

- 첫 부팅 후 GoTo를 실행하지 않아도 SkySafari 좌표가 기구 및 수동 이동을 반영합니다. 솔빙 전에는 유효한 IMU 좌표를 사용하고, 솔빙 후에는 솔빙으로 정렬된 좌표를 사용합니다. GPS 위치가 준비되지 않았을 때는 설정 위치 또는 마지막으로 OnStep에 전송한 위치를 좌표 변환에 사용합니다. 정렬 전 IMUPLUS의 절대 방향은 임시 추정치입니다.
- LCD `0` 키의 Mount Stop이 수동 이동·GoTo·가이드 보정과 마운트 자체 추적을 함께 중단합니다. 실제 추적 Off 확인에 실패하면 정지 성공 메시지를 표시하지 않습니다. 방향키를 놓을 때는 기존처럼 수동 이동만 끝내고 추적을 유지합니다.
- LCD Push 카메라 오버레이의 중복 제목을 제거했습니다. Push 목표 유지와 조준점 중앙 확대, Focus 카메라 보기 및 확대 조작도 개선했습니다.
- Raspberry Pi OS **Trixie 64-bit / Python 3.13** 설치·개발 환경을 지원합니다. 검증된 Trixie INDI 아카이브, ABI·해시 검사와 설치 복구를 포함하고 `.local` 접속용 Avahi 설치·기동을 확인합니다.
- INDI 시리얼 Auto 탐색, 지속 수동 이동, OnStep Sync 확인 응답, 고도·자오선 제한 및 솔빙 중단 시 native GoTo·추적 연속성을 개선했습니다.
- RAW 별 영상 기반 드리프트 보정과 비동기 정렬, 달·행성·수동 목표 추적 통합을 추가했습니다. 새 보정 모드는 기본 On이며 기존 명시 설정을 유지합니다. 실제 보정에는 검증된 장비 프로필과 시작 요청이 필요합니다. 별 소실 시 예측 보정은 검증된 시간·오차·이동 한도로 제한합니다.
- IMX678 흑백·컬러 프로파일과 선택 설치 가능한 드라이버를 추가했습니다. 센서별 광도·SQM 보정은 별도 측정이 필요합니다.
- 웹 API 인증, 백업 복원, 한국어 트래킹 화면 번역을 수정했습니다. 신규 설치용 IMX462 Color 렌즈 기본값과 정렬 저장을 개선했습니다.
- 별 검출기는 **MFDS v0.4.2**로 고정합니다.

## 설치·업데이트

이번 버전은 Trixie 64-bit를 기본으로 합니다. 소스 업데이트가 Bookworm OS를 Trixie로 바꾸지는 않습니다. 기존 설정·관측 자료와 로컬 변경을 백업하고 [Trixie 설치 안내](../docs/mf_dev/mf_trixie_install_ko.md)를 따르세요. Trixie 실기 검증은 Pi 5에서 수행했으며 Pi 4·CM5의 별도 실기 확인은 남아 있습니다.

설치 계정으로 다음 명령을 실행합니다. 설치 스크립트 내부에서 필요한 sudo 인증을 요청합니다.

```bash
wget -O /tmp/mfnavis-m2.6.15-setup.sh https://raw.githubusercontent.com/hjoungjoo/MFNavis/m2.6.15/mfnavis_setup.sh &&
MFNAVIS_INSTALL_BRANCH=m2.6.15 bash /tmp/mfnavis-m2.6.15-setup.sh
```

완료 후 재부팅하고 열려 있는 웹 페이지를 새로고침하세요. 기존 사용자 렌즈·왜곡 보정 설정은 유지됩니다.

## 검증 및 배포 범위

[m2.6.15 검증 기록](../docs/mf_report/m2.6.15_validation_ko.md)에 자동 검사와 실기 확인 범위를 기록합니다. 이 릴리즈는 소프트웨어 소스와 설치 자료입니다. OS 이미지 및 개인 관측 영상·장비 설정을 포함하지 않습니다.

[전체 변경 비교](https://github.com/hjoungjoo/MFNavis/compare/m2.6.14...m2.6.15)
