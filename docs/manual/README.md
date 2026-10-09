# MFNavis LCD 사용자 매뉴얼 작업 파일

일반 사용자가 관측 준비부터 천체 탐색과 종료까지 따라갈 수 있는 별도 매뉴얼이다.
빠른 시작, 메뉴 구조 그림, 공통 키 조작, 화면별 절차와 설정표, 문제 해결,
자주 쓰는 경로 순서로 구성한다.

## 파일

| 파일 | 용도 |
|---|---|
| [user_manual_ko.pdf](user_manual_ko.pdf) | A4 인쇄·배포·검토용 |
| [user_manual_ko.html](user_manual_ko.html) | 목차 링크가 있는 오프라인 열람용. 한글 글꼴과 그림이 파일 안에 포함됨 |
| [user_manual_ko.md](user_manual_ko.md) | 본문 편집 원본 |
| [menu_labels_ko.json](menu_labels_ko.json) | 메뉴·선택값·화면 문구의 정식 영문명과 실제 한국어 UI 표시명 대조표 |
| [assets](assets) | 메뉴 구조와 조작 그림 8개. PNG와 편집 가능한 SVG를 함께 보관 |
| [build_manual.py](build_manual.py) | 본문과 그림으로 오프라인 HTML 생성 |
| [render_manual.py](render_manual.py) | 한글 글꼴 로딩 후 Chromium으로 PDF 인쇄 |

그림은 설명용 개념도이며 실제 장비 화면 캡처가 아니다. 배포용 PDF는 사용자
매뉴얼의 형태로 읽을 수 있도록 기존 Sphinx 문서와 독립적으로 구성했다.
기존 사용자 문서와 장비 설정, 실행 소스는 수정하지 않았다.

본문·표·진입 경로는 `Start(시작)`처럼 **영문명(한국어 UI 표시명)**으로
표기한다. `User Pref...`, `Chart...`, `Image...`, `Align (Day)`,
`Place & Time`, `Goto/Guide`의 원래 철자와 문장부호를 유지한다.
실제로 영어로 표시되는 항목은 같은 이름을 두 번 쓰지 않는다.

한국어 이름의 기준은 실행 중 사용하는
`python/locale/ko/LC_MESSAGES/messages.mo`다. `.po`의 fuzzy 번역은
현재 UI에 적용되지 않으므로 정식 표시명으로 사용하지 않는다.
예를 들어 `Lens`, `Distortion`, `Recovery Range`, `CALIB`, `SWEEP`은
한국어 UI에서도 영어로 표시된다. 번역 파일을 갱신하면 대조표와 본문을
함께 검토한다. 그림은 영어 메뉴 이름으로 구성한 개념도다.

## 다시 생성하기

저장소 루트에서 실행한다. HTML 생성에는 Pillow와 Markdown, PDF 생성에는
개발 가상환경의 trio와 trio-websocket 및 설치된 Chromium이 필요하다.

```bash
python3 docs/manual/build_manual.py
.venv-dev-trixie/bin/python docs/manual/render_manual.py
```

브라우저로 `user_manual_ko.html`을 열고 **인쇄 또는 PDF 저장** 버튼을 눌러도
인쇄할 수 있다. 그림을 바꾸려면 `build_manual.py`를 수정하고 다시 생성한다.
SVG의 텍스트는 별도 벡터 편집기에서도 편집할 수 있다.

## 동작 확인에 사용한 코드

초안 기준은 2026년 10월 9일 로컬 소스의 커밋 `5eb7c28a`다.
같은 날 추가된 Push 추적 테두리는 `UIObjectDetails._render_push_tracking_border`를
기준으로 빠른 시작과 6.5절에 반영했다. GoTo 완료 후 현재 대상의 추적 표시,
밝고 어두운 배경에서의 이중 선, 정지·재이동·상태 만료 시 표시 해제를 설명한다.

| 확인 대상 | 코드 |
|---|---|
| 정적 메뉴와 선택값 | `python/MFNavis/ui/menu_structure.py` |
| 메뉴 이동·길게 누르기·퀵 메뉴 | `python/MFNavis/ui/menu_manager.py:515`, `python/MFNavis/ui/text_menu.py:144` |
| INDI 메뉴 표시 조건·장비 목록 | `python/MFNavis/ui/menu_manager.py:94` |
| LCD 밝기·화면 저장 | `python/MFNavis/main.py:1164` |
| 초점 화면 | `python/MFNavis/ui/preview.py:949` |
| 밤·낮 정렬 | `python/MFNavis/ui/align.py:457`, `python/MFNavis/ui/align_daytime.py:323` |
| 천체 목록·상세·기록 | `python/MFNavis/ui/object_list.py:855`, `python/MFNavis/ui/object_details.py:984`, `python/MFNavis/ui/log.py:286` |
| 사용자 좌표 입력 | `python/MFNavis/ui/radec_entry.py:929` |
| 마운트 숫자키와 Guide의 예외 | `python/MFNavis/ui/base.py:887`, `python/MFNavis/ui/indi.py:511` |
| 다점 정렬·백래시 | `python/MFNavis/ui/indi.py:328`, `python/MFNavis/ui/indi.py:931` |
| SQM·보정·진단 측정 | `python/MFNavis/ui/sqm.py:266`, `python/MFNavis/ui/sqm_calibration.py:1091`, `python/MFNavis/ui/sqm_sweep.py:437` |
| 위치·시간·저장 장소 관리 | `python/MFNavis/ui/locationentry.py:263`, `python/MFNavis/ui/timeentry.py:213`, `python/MFNavis/ui/location_list.py:83` |
| 입력장치 설정 | `python/MFNavis/ui/bluetooth_keyboard.py:534`, `python/MFNavis/ui/joystick.py:163`, `python/MFNavis/ui/keyboard_mapping.py:140` |
| LCD 오류 알림 | `docs/mf_dev/mf_lcd_operation_errors_ko.md` |

## 배포 전 실제 장비 확인

이 초안은 소스 확인과 문서 출력 검수까지 진행한 상태다. 실물 장비의 동작을
확인한 것으로 간주하지 않는다. 배포 전에 다음 사항을 확인한다.

- LCD 종류별 글자·선택 표시, 실물 버튼의 짧게·길게 누르기와 조합키.
- 한국어 UI에서 경로와 메뉴 이름, 장비에 따라 나타나는 동적 메뉴.
- 카메라 초점·밤/낮 정렬·좌표 입력·관측 기록의 실제 완료 표시.
- 연결된 마운트에서 INIT, Guide, GoTo, Sync, Multi Align, Backlash의 응답.
- WiFi 전환·GPS·시간 동기화·입력장치 연결·업데이트·전원 종료.

장비 화면을 추가할 때는 개념도와 실제 캡처를 구분하고, 버전과 장비 종류를
함께 기록한다.
