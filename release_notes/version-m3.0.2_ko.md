# MFNavis m3.0.2 — 웹 UI와 Tools 상태 표시 개선

## 변경 사항

- 네트워크 STA 추가 폼이 좁은 표 열에 갇히던 문제를 수정하고, 검색된 SSID 선택과 수동 입력 전환이 실제 입력값에 반영되도록 개선했습니다. 저장 전 필수값과 비밀번호 길이를 검사합니다.
- GPS 날짜·시간 자동 입력과 긴 선택 항목의 라벨 겹침을 수정했습니다. 모바일 입력 폼 여백과 긴 버튼 문구를 조정하고, 장비·위치·관측 표는 내부 가로 스크롤로 표시합니다.
- Tools를 반복 방문하면 다운로드 상태가 ‘로딩 중’에 멈추던 문제를 수정했습니다. 이전 페이지의 늦은 응답은 현재 화면을 덮어쓰지 않으며, 초기 조회 실패 시 오류와 재시도 상태를 표시합니다.
- 일반·작은·아이콘·링크형 버튼의 비활성 표시를 회색·적색 테마에서 통일했습니다. 비활성 버튼은 어두운 배경, 흐린 글자, 점선 테두리와 그림자 없는 형태로 구분합니다. INDI HOLD 버튼도 실제 비활성 속성을 갖습니다.
- 결과가 없을 때 숨겨져야 하는 다운로드 버튼과 선택 상자의 화살표 표시를 수정했습니다.

## 설치와 검증

Raspberry Pi OS Trixie 64-bit / Python 3.13과 기존 MFDS v0.4.4 고정 패키지를 사용합니다.
설치 계정으로 실행하고 완료 후 재부팅하세요.

```bash
wget -O /tmp/mfnavis-m3.0.2-setup.sh https://raw.githubusercontent.com/hjoungjoo/MFNavis/m3.0.2/mfnavis_setup.sh &&
MFNAVIS_INSTALL_BRANCH=m3.0.2 bash /tmp/mfnavis-m3.0.2-setup.sh
```

웹 UI는 업데이트 후 새로고침하세요. 관련 회귀 테스트 48개와 변경된 Python 테스트의 린트·포맷 검사를 통과했습니다. Firefox에서 한국어·영어 25종 화면을 375px·1280px로 점검했으며, 버튼은 23종 화면의 두 테마에서 별도로 확인했습니다. 실제 다운로드 시작이나 망원경 이동을 실행하지 않는 UI 검증입니다.

[설치 안내](https://github.com/hjoungjoo/MFNavis/blob/m3.0.2/README_ko.md) ·
[검증 기록](https://github.com/hjoungjoo/MFNavis/blob/m3.0.2/docs/mf_report/m3.0.2_validation_ko.md) ·
[전체 변경 비교](https://github.com/hjoungjoo/MFNavis/compare/m3.0.1...m3.0.2)

이 릴리즈는 소프트웨어 소스와 설치 자료를 제공합니다. 새 SD 카드 전체 설치 및 OS 이미지 제작은 이번 검증 범위에 포함하지 않습니다.
