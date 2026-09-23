# 기기의 PiFinder 잔여 표기 조사 — 2026-09-23

조사만 수행했다. 프로그램·시스템 설정·이미지·번역·테스트를 수정하거나 서비스를
재시작하지 않았다. 아래는 현재 장비의 실측과 변경 중인 작업 트리의 조사 결과다.

## 핵심 결론

현재 기기 화면과 외부 앱에 응답하는 제품명은 아직 **PiFinder**다. 서비스가
2026-09-23 02:43:13 KST부터 계속 실행 중이어서, 이후 디스크에 수정한 MFNavis
Python 코드를 아직 로드하지 않은 상태다. 반면 실제 웹 로그인 제목·로고·PWA
manifest는 MFNavis로 제공된다. 소스 변경과 실행 상태를 구분해야 한다.

서비스를 다시 시작해도 **Wi-Fi AP 이름, 도움말 PNG 2개, 일부 INDI 동적 메시지,
내보내기·백업 이름**은 별도 수정 없이는 남는다. 4개 언어의 번역 소스에도
검토 대기(fuzzy) 잔여분이 있지만 현재 컴파일된 번역에서는 제외되어 있다.

## 조사 범위와 원본 목록

- 서비스가 사용하는 `/home/pifinder/PiFinder`의 Git 추적 파일과 ignore되지 않은
  미추적 파일 1,875개를 조사했다. 대소문자 구분 없이 `pifinder`, `Pi Finder`,
  `Pi_Finder`, `Pi-Finder`, `파이파인더`·`파이 파인더`를 찾았다.
- 텍스트 일치: **696개 파일 / 11,998개 줄**. 경로명 일치: **331개 경로**.
  여기에는 import·주석·테스트·문서·저작권도 들어 있으므로 제품명 수정 건수와 다르다.
- 텍스트 검색에서 제외된 binary 파일 889개 중 실제 기기 도움말 PNG **23개 전부**,
  기존 부팅 로고와 웹 로고·아이콘 **4개**, 현재 기기 화면을 육안 확인했다.
- `/etc`의 장비 정체성·네트워크·서비스 설정과 systemd/NetworkManager/Bluetooth의
  읽기 전용 상태를 확인했다. 웹 GET과 LX200 `:GVP#` 제품명 조회를 수행했다.
- 설치된 `python/MFDS`의 고지도 별도 확인했다. `PiFinder_main`, 과거 백업·이전
  릴리스 캐시 전체는 현재 서비스 실행 경로가 아니므로 전수 검색 범위에서 제외했다.
- 모든 하드웨어 CAD/STL·PDF·문서 사진의 픽셀/OCR 검사, 실제 외장 케이스·PCB
  인쇄 검사까지 끝난 결과는 아니다. 현재 화면 이외의 기기 메뉴를 조작하지 않았다.

원본 결과 디렉터리:
`/home/pifinder/PiFinder_test_data/results/mfnavis_brand_audit_20260923/`

| 파일 | 내용 |
|---|---|
| `repo_occurrences.tsv` / `.json` | 일치한 전체 파일·줄 번호·텍스트. credential 관련 줄은 가림 |
| `path_names.txt` | 이름 자체에 PiFinder가 들어간 경로 목록 |
| `python_string_constants.json` | Python 주석/docstring을 제외한 문자열 상수 302개 |
| `binary_files.txt` | 텍스트 검사에서 제외한 binary 파일 목록 |
| `summary.json` | 범위·집계 |
| `device_config.json`, `device_aux_config.json` | 디스크상의 장비 설정 조사 |
| `live_state.json`, `live_product_identity.json` | 실행 중 서비스·웹·제품명 응답 |
| `translation_audit.json` | .po fuzzy 상태와 .mo 실제 번역 본문 대조 |
| `device_screen.png` | 조작 없이 GET으로 받은 당시 기기 화면 |

## 1. 지금 실제로 노출되는 표기

| 항목 | 확인 결과 | 근거 / 조치 성격 |
|---|---|---|
| 기기 메뉴 상단 | **PiFinder** | `device_screen.png` 실측. 소스 `python/PiFinder/ui/menu_structure.py:52`는 MFNavis이므로 다음 서비스 시작 시 재확인 |
| 외부 앱 제품명 | **PiFinder#** | localhost:4030에 `:GVP#` 읽기 전용 조회. `python/PiFinder/pos_server.py:813`의 소스는 MFNavis이지만 실행 프로세스는 이전 코드 |
| Wi-Fi AP | **PiFinderAP** | `/etc/hostapd/hostapd.conf:3`, 저장소 `pi_config_files/hostapd.conf:3`. hostapd 서비스 active 확인. 무선 RF 수신기로 SSID를 별도 관측한 것은 아님 |
| NetworkManager 연결 이름 | **PiFinder &lt;SSID&gt;** 형식 2개 | 실제 연결 profile 목록 확인. 상대 공유기의 SSID 자체와 구분. 생성 코드 `python/PiFinder/sys_utils.py:2468` |
| 서비스 설명 | **PiFinder**, **PiFinderSplash**, **PiFinder AP+STA Channel Monitor**, **PiFinder AP / AP+STA Virtual AP Interface** | 설치된 `/lib/systemd/system/pifinder*.service`의 Description. 이름·ExecStart 경로와 별개로 Description만 변경 가능 |
| 웹 로그인 제목 | **MFNavis - Login** | 실제 localhost 웹 응답에서 확인, 정상 |
| 웹 로고·PWA | **MFNavis**, 사용자 지정 PNG | 실제 이미지 SHA256이 원본과 동일: `422f662648deed0a60753f1d0aee99ca482c0fc3301cf8ec72279468f8ff434f` |
| 호스트명 | **mfpi5** | `/etc/hostname:1`. PiFinder 아님 |
| Bluetooth Name / Alias | **mfpi5 / mfpi5** | 읽기 전용 상태 확인. Powered=yes, Discoverable=no. PiFinder 아님 |
| Samba 공유명 | **shared** | `/etc/samba/smb.conf`의 `[shared]`. 공유명은 PiFinder 아님. 사용자와 저장 경로는 pifinder/PiFinder_data 유지 |

실행 중인 main 서비스의 WorkingDirectory는 `/home/pifinder/PiFinder/python`이다.
부팅 splash 서비스는 당시 inactive/dead로, 현재 화면이 부팅 splash라는 뜻은 아니다.
서비스 재시작·AP 재구성은 이번 조사에서 실행하지 않았다.

## 2. 재시작만으로 없어지지 않는 사용자 노출 표기

| 영역 | 남은 표기 | 위치 / 노출 경로 |
|---|---|---|
| 기기 메뉴 도움말 | `Thank you for using a PiFinder` | `help/menu/2.png` 이미지 안의 글자 |
| 기기 정렬 도움말 | `telling the PiFinder where ...` | `help/align/2.png` 이미지 안의 글자 |
| INDI 위치 출처 | `PiFinder synced location` | `python/PiFinder/sys_utils.py:536` → `python/views/indi_mount.html:194`의 위치 출처 표시 |
| INDI GoTo 동작·상태 | `pifinder sync + goto ...`, `pifinder pulse align ...`, `pifinder final sync complete`, `pifinder_goto_blocked` 등 | `python/PiFinder/indi_goto_guide_service.py:484`, `:844`, `:846`, `:900`, `:1005`, `:1150` → `python/views/indi_mount.html:588`, `:596`, `:1335` |
| INDI 오류·정렬 안내 | `PiFinder GoTo requires a recent plate solve`, `No PiFinder solve available for alignment sync`, `Mount synced to PiFinder ...` 등 | `python/PiFinder/indi_goto_guide_service.py:1830`, `mountcontrol_indi.py:5101`, `:5144` → 기기 `ui/indi.py:808` 및 웹 `indi_mount.html:336`의 메시지 표시 |
| 번역 소스: 독일어·스페인어·프랑스어·중국어 | 언어당 3개 INDI 재시작 문구가 PiFinder 재시작으로 잘못 번역됨 | `python/locale/{de,es,fr,zh}/LC_MESSAGES/messages.po`의 `Restart INDI`, `REBOOT INDI`, `Restarting INDI`. 합계 **12개**. 모두 fuzzy이며 현재 .mo에는 미포함. MFNavis 일괄 치환이 아니라 **INDI**로 번역 수정해야 함 |
| 번역의 사용자 계정 안내 | 현재 시스템 사용자라는 원문을 `pifinder` 계정으로 고정 번역 | 위 4개 언어의 계정/비밀번호 변경 안내, 합계 **4개**. 모두 fuzzy이며 현재 .mo에는 미포함. 실제 계정명을 반영하거나 원문처럼 일반화 |
| 관측목록 Stellarium 내보내기 | `Exported from PiFinder` | `python/PiFinder/obslist_formats.py:562` |
| 관측목록 Autostar 내보내기 | `/ PiFinder export` | 같은 파일 `:626` |
| 관측목록 EQMOD 내보내기 | `exported from PiFinder` | 같은 파일 `:908` |
| 백업 다운로드 파일명 | `PiFinder_backup.zip` | `python/PiFinder/sys_utils.py:42`, `server.py:2885`. 복원 경로 `server.py:2896`, `:2900`도 함께 고려 |
| 종료 API 안내 | `Shutting down PiFinder` | `python/PiFinder/api_extensions.py:1347`. 코드를 확인했으며 종료 API를 호출하지는 않음 |
| 설치 완료 문구 | `PiFinder setup complete, please restart the Pi` | `pifinder_setup.sh:342` |
| 로그 및 브라우저 개발자 콘솔 | `Starting PiFinder ...`, `PiFinder running ...`, `PiFinder SPA: ...` | `python/PiFinder/main.py:542`, `:1450`, `server.py:3079`, `python/views/js/spa.js:190` 등. 일반 화면과 진단 표시를 구분 |

기기 도움말은 `python/PiFinder/ui/base.py:271`에서 PNG를 직접 로드하므로
코드 문자열이나 gettext 번역만 바꿔서는 남은 두 도움말을 바꿀 수 없다.
다른 21개 도움말에서는 PiFinder 문구를 발견하지 못했다.

현재 다섯 언어의 컴파일된 `.mo` 번역 본문에는 PiFinder 잔여 문자열이 **0개**다.
한국어 `.po`의 비obsolete 번역 본문에도 잔여분이 없다. 다른 네 언어의 16개
잔여분은 모두 fuzzy여서 기본 컴파일에서 제외된다. 이를 검토 없이 승인하면
표기가 다시 나타날 수 있다. 과거 obsolete 번역과 소스 경로 주석은 별도이며
실행 표시로 계산하지 않았다. 증거는 `translation_audit.json`에 기록했다.

GoTo의 일부 사람용 오류 문자열은 조건문에서도 비교한다(`indi_goto_guide_service.py:488`).
표시 문자열만 일부 바꾸면 동작에 영향을 줄 수 있어 호출자·비교문을 함께 확인해야 한다.
`phase` 같은 상태 코드는 원래 값을 유지하고 UI에서 표시 이름을 매핑하는 편이 안전하다.

## 3. 교체된 화면과 별개로 남은 기존 이미지·매뉴얼

| 항목 | 확인 |
|---|---|
| `images/welcome.png` | PiFinder 로고 이미지. 현재 splash/console은 새 `branding.welcome_image()`를 쓰므로 기존 시작 경로에서는 미참조 |
| `python/views/images/WebLogo_RED.png` | PiFinder 로고 이미지. 현재 공통 헤더 미참조 |
| `python/views/images/pwa-icon-192.png`, `pwa-icon-512.png` | PiFinder 아이콘. 현재 manifest 미참조 |
| 기존 웹 이미지 URL | 파일은 여전히 static images 경로에 있으므로 판매 패키지 정리 대상인지 결정 필요. 홈 화면에 이미 설치한 앱의 아이콘 캐시와도 구분 |
| `docs/source/conf.py:9`, `:44` | Sphinx project가 PiFinder, html_logo가 기존 WebLogo_RED.png |
| `docs/source/index.rst:1` | `PiFinder™ Welcome` 및 upstream 홍보·지원 링크. 그대로 빌드하면 PiFinder 매뉴얼이 됨 |
| `docs/source/connectivity.rst`, `user_guide.rst`, `skysafari.rst` 등 | PiFinderAP 연결 안내, 원 프로젝트 제품 안내와 예전 화면 캡처 다수 |
| `README.upstream*.md`, 과거 release_notes·감사 기록 | 원본/역사 기록으로 구분해서 유지. 현재 제품 매뉴얼과 혼용하지 않아야 함 |
| KiCad 문서 | `kicad/PiFinder_v2/PiFinder.kicad_pcb:3919`, `PiFinder_rev4/PiFinder4.kicad_pcb:45404` 등의 `PiFinder by BBLabs` 도면 문자열. v2의 예시는 Eco1.User 문서 레이어이나 **rev4:45404는 F.SilkS 전면 실크 레이어**여서 해당 설계로 생산하면 제품 인쇄에도 영향을 줌. 현재 기기에 실제 장착된 PCB의 인쇄는 별도 실물 확인 필요 |

## 4. 내부 호환성·출처 표기: 일괄 치환하면 안 되는 항목

- Python 패키지·import: `PiFinder.*`, `python/PiFinder/`, `python -m PiFinder.main`.
- 서비스 식별자: `pifinder.service`, `pifinder_splash.service`, AP+STA helper 및 옵션
  GPS time sync 서비스. 설치/업데이트/복구·권한·의존 서비스가 같은 이름을 참조한다.
- 시스템 계정과 경로: `pifinder`, `/home/pifinder`, `PiFinder`, `PiFinder_data`,
  lock/log/cache·shared-memory 경로. Samba의 guest account와 데이터 경로도 포함.
- 설정·IPC 값: `indi_goto_method="pifinder"`, `skysafari_pifinder_align`,
  `indi_pifinder_goto_*`, `pifinder_imu_estimate`, `pifinder_mount_synced` 등.
- 웹 내부 식별자: `pifinderWebTheme`, `pifinderWantFullscreen`, `pifinderSpa`,
  CSS/DOM 이름, `PiFinderSPA` 요청 헤더, `/system/restart_pifinder` URL.
- 파일 형식: `.pifinder` 관측목록 확장자와 reader/writer. 외부 도구 호환성을 고려한다.
- 실제 저장소·다운로드 주소: `hjoungjoo/MF_PiFinder`, upstream PiFinder URL.
  제품명과 달리 실제 원격 저장소 이름이므로 문자열만 바꾸면 갱신이 깨진다.
- 원저작권·라이선스·출처: PiFinder 기여자, 원본 MIT/GPL attribution, Tetra3 출처,
  SOURCE/PUBLICATION 같은 역사 기록. 제품명 변경의 대상으로 취급하지 않는다.

설치된 MFDS 일반 v0.4.0의 `python/MFDS/LICENSE:3`와 `LICENSING.md:10`은
이전 `PiFinder contributors` 표기다. 수정된 별도 판매용 후보 패키지를 운영 장비에
설치하지 않았기 때문이다. legacy MIT 파일의 같은 표기는 원래 고지이므로 보존한다.

## 5. 기존 검증 코드의 잔여 기대값

`python/tests/test_web_theme_static.py` 실행 결과: **23 passed / 2 failed**.

- `:194`의 manifest.name 기대값이 아직 `PiFinder`이고, `:202`·`:203`에서
  이전 pwa-icon 파일을 기대한다. 현재 MFNavis/사용자 로고 규격과 불일치.
- `:456`의 CSS 캐시 버전 기대값이 `v=7`. 현재 로고 스타일 변경 후 `v=8`과 불일치.

이는 앞선 브랜드/로고 변경 후 갱신이 빠진 테스트다. 이번 조사에서 확인했으며
테스트 실패를 숨기거나 조사 범위를 넘어 수정하지 않았다.

## 권장 처리 순서

1. 원래 PiFinder 저작권·출처 및 내부 식별자 보존 범위를 고정한다.
2. 도움말 2개·동적 INDI 표시·4개 언어 번역·export/API/설치 안내를 정리한다.
3. 백업 파일 표시명·AP SSID·NetworkManager 이름은 기존 사용자 데이터/접속의
   호환성을 고려해 이행한다. AP 변경은 접속을 끊을 수 있어 화면 변경과 분리한다.
4. 판매 이미지에서 기존 미사용 로고와 원본 매뉴얼의 포함 여부를 결정한다.
5. 위 테스트 기대값을 현재 제품 규격에 맞추고 관련 화면·네트워크 검증을 수행한다.
6. 필요한 변경이 준비된 뒤 서비스를 다시 시작하고, 실제 기기 화면과 `:GVP#`,
   웹·PWA·도움말을 다시 확인한다. 현재 소스만 변경된 상태를 최종 적용으로 간주하지 않는다.
