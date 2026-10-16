# MFNavis m3.0.1 — GoTo 접근과 추적 복구 개선

## GoTo와 추적

- 한계 초과 원인이 해소되고 현재 위치와 목표가 안전한 경우, 사용자의 새 GoTo로
  이전 한계 잠금을 해제할 수 있습니다. 새 요청의 확인 응답을 기다리며 실제 한계
  검사와 정지 우선권은 유지합니다.
- 근거리 접근에서 짧은 GoTo를 반복하는 대신 제한된 수동 축 이동을 사용합니다.
  남은 거리에 따라 4×·8×·20×·48× 속도를 선택하고, 한 번에 한 축을 최대
  1.2초 이동합니다. 이동 종료나 사용자 수동 조작 시 원래 수동 속도를 복원합니다.
- 충분히 가까워진 후 펄스로 전환합니다. 기본 정확도 1′에서는 1.5′ 이내이며,
  정지 후 새 솔빙으로 실제 도착을 확인합니다.
- 도착 후 펄스 비수렴이 발생했을 때 오차가 커질 때까지 `settling`으로 보정을
  중단하던 경로를 개선했습니다. 새 솔빙을 확인해 근거리 재접근과 펄스 보정으로
  복구하고, 성공하면 정상 추적 보정과 솔빙 소실 중 잔량 보정을 재개합니다.
- 근거리 복구 실패는 10초 대기 후 최대 3회까지 시도합니다. 계속 실패하면
  실패 상태를 표시하고 새 GoTo 또는 새 광학 도착 확인을 기다립니다.
  사용자 정지·수동 조작, 주차, 추적 Off와 한계 보호가 복구보다 우선합니다.
- Finder 카메라 화면에서 솔빙 전 IMU 좌표로 GoTo할 수 있으며, 키 입력 진동이
  가라앉도록 Finder GoTo를 1초 지연합니다.

## 화면

- LCD 상단 상태 아이콘 간격을 넓히고 제목과의 겹침을 줄였습니다.
- 웹 INDI 페이지의 Smooth optical tracking 설정을 맨 아래로 이동했습니다.

## 설치와 검증

Raspberry Pi OS Trixie 64-bit / Python 3.13, MFDS v0.4.4 고정 패키지를 사용합니다.
설치 계정으로 실행하고 완료 후 재부팅하세요.

```bash
wget -O /tmp/mfnavis-m3.0.1-setup.sh https://raw.githubusercontent.com/hjoungjoo/MFNavis/m3.0.1/mfnavis_setup.sh &&
MFNAVIS_INSTALL_BRANCH=m3.0.1 bash /tmp/mfnavis-m3.0.1-setup.sh
```

[설치 안내](https://github.com/hjoungjoo/MFNavis/blob/m3.0.1/README_ko.md) ·
[검증 기록](https://github.com/hjoungjoo/MFNavis/blob/m3.0.1/docs/mf_report/m3.0.1_validation_ko.md) ·
[전체 변경 비교](https://github.com/hjoungjoo/MFNavis/compare/m3.0.0...m3.0.1)

수동 근거리 접근은 사용자 실기 확인을 받았습니다. 도착 후 비수렴 복구는
재현·시뮬레이션 테스트와 서비스 재시작까지 확인했으며, 수정 후 장시간 실기
추적과 기계 응답은 추가 확인이 필요합니다. 이 릴리즈는 OS 이미지가 아닌
소프트웨어 소스와 설치 자료를 제공합니다.
