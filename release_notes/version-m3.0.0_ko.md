# MFNavis m3.0.0 — Finder와 IMU 차트

Finder에서 차트 또는 카메라를 보며 수동으로 위치를 맞춘 뒤, 화면의 원형
마크 중심 좌표를 GOTO 목표로 지정할 수 있습니다.

## Finder

- 메인 메뉴의 Chart 바로 위에 Finder를 추가했습니다.
- 사각 버튼으로 카메라와 차트 모드를 순환합니다. 카메라 모드는 상하 정보
  없이 영상과 원형 마크를 표시하며, `+` / `-`로 1×·2×·4× 확대를 조절합니다.
- 두 모드에서 `5` 키와 ALIGN은 표시된 마크 중심의 RA/Dec로 GOTO를 요청합니다.
  수동 이동과 정지 키도 그대로 사용할 수 있습니다.
- 오른쪽 키를 짧게 또는 길게 눌러도 Finder에 머무릅니다. 기본 푸시 화면으로
  이동하는 단축키와 상세 화면 진입 화살표를 제거했습니다.

## 차트와 위치 추정

- 기존 Chart와 Finder 차트는 솔빙 실패 후에도 보정된 IMU 추정 좌표를 사용합니다.
- 아직 솔빙되지 않았다면 유효한 IMU 방향, GPS 또는 저장된 기본 관측 위치,
  현재 시간을 이용해 차트를 표시합니다. Finder의 GOTO도 이 중심 좌표를 사용합니다.
- 유효한 좌표가 없으면 GOTO를 보내지 않습니다. 화면용 IMU 좌표를 광학 솔빙
  성공으로 기록하거나 공유 위치 상태에 덮어쓰지 않습니다.

## m2.6.16 이후의 개선

- GOTO 접근·정착과 PID 펄스 보정, 추적 복구, 수동 이동 우선 처리 개선.
- 솔빙 손실 중 추적 유지, 마운트 한계 검사, 실내 초기화와 OnStep 재연결 개선.
- 푸시 화면의 추적·도착 표시와 카메라 안내 개선.
- 한국어·영어 사용자 매뉴얼 및 LCD 화면 예시, 웹 캐시 다운로드 재개,
  카탈로그 검색·Nearby 정렬 개선.
- MFDS v0.4.4 고정 패키지 사용. Raspberry Pi OS Trixie 64-bit / Python 3.13 기준.

## 설치

설치 계정으로 실행합니다.

```bash
wget -O /tmp/mfnavis-m3.0.0-setup.sh https://raw.githubusercontent.com/hjoungjoo/MFNavis/m3.0.0/mfnavis_setup.sh &&
MFNAVIS_INSTALL_BRANCH=m3.0.0 bash /tmp/mfnavis-m3.0.0-setup.sh
```

완료 후 재부팅하세요. [설치 안내](https://github.com/hjoungjoo/MFNavis/blob/m3.0.0/README_ko.md)를 참조하세요.
이 릴리즈는 소프트웨어 소스와 설치 자료를 제공합니다.

Finder의 화면·키 입력·GOTO 명령 전달은 자동 테스트로 검증했습니다.
이번 Finder 검증에서는 실제 마운트를 연결하지 않아 실제 이동과 관측 중 추적은
실기 검증하지 않았습니다.

[전체 변경 비교](https://github.com/hjoungjoo/MFNavis/compare/m2.6.16...m3.0.0)
