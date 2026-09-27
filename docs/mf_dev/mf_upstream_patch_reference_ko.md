# MF_PiFinder upstream 패치 기준 문서

> 아래 OS 언급은 당시 설계·전환 기준이다. 현재 MFNavis 설치는
> [Trixie 64-bit / Python 3.13 안내](mf_trixie_install_ko.md)를 따른다.

작성일: 2026-07-03

이 문서는 `brickbots/PiFinder` 원본 소스가 변경되었을 때 `mf_pifinder`
브랜치(현재 개발 브랜치는 `main`)에 다시 적용하거나 유지해야 할 패치 내용을
빠르게 판단하기 위한 기준 문서이다.

목표:

- upstream 변경을 가져올 때 이미 적용한 패치와 의도적으로 제외한 패치를 구분한다.
- 충돌 가능성이 높은 파일과 기능 경계를 미리 확인한다.
- 다음 재동기화 작업에서 테스트와 검토 순서를 재사용한다.

## 현재 기준점

로컬 기준 브랜치:

- `main` (과거 비교 기록의 브랜치명은 `mf_pifinder`)

비교 대상 upstream:

- `brickbots/PiFinder main`

### 2026-09-06: 사용자 선택 9~12 선별 반영, 6~8 제외

비교 기준은 앞선 1~5 작업과 동일한 MF `9dfd3a3f`, upstream/main `803d41eb`다.
사용자의 후속 선택에 따라 **6~8은 제외**, **9는 MF 충돌 분석 후 수동 이식**,
**10~12는 필요한 변경만 반영**했다. 아래 내용은 아직 커밋하지 않은 작업 트리다.

| 번호 | upstream | 처리 및 MF 보호 |
| --- | --- | --- |
| 6 | #625 렌즈 변경 시 solver 재시작 | 사용자 요청으로 제외. 기존 동작 유지. |
| 7 | #624 렌즈 설정 self-heal | 사용자 요청으로 제외. 기존 동작 유지. |
| 8 | #632 미확인 optical train의 FOV gate 비활성화 | 사용자 요청으로 제외. 기존 동작 유지. |
| 9 | #621 `ef7e7928` | Stellarium 초기화용 사이트·시각 명령과 응답 추가. MF TCP 버퍼, `MS` 기반 실제 GoTo, Align, 음수 0도 적위, 좌표 epoch, 실제 이동 상태·정지, 짧은 연결 가이드 동작 유지. [상세 분석](mf_stellarium_push_port_analysis_ko.md). |
| 10 | #513 `ef4aab03`, #633 `3f94f65a` | Chart 목표 십자·주변 DSO·중앙 천체 읽기/상세 열기. 기존 MF 표시 방향·투영 수학·nearby 좌표 순서 보존. |
| 11 | #641 `803d41eb` | BOM의 BNO055 보드 경고만 적용. Adafruit 2472가 아닌 4646 필요. 실행 코드 변경 없음. |
| 12 | `81b4eae6` | `case/rev4/dovetail_bottom.stl` hardstop 수정 파일만 적용. Rev4 전원/보드 지원 패치는 가져오지 않음. |

#### 9번 핵심 판단

- upstream처럼 `Sd`에서 즉시 push/GoTo하면 MF의 Align 입력과 실제 마운트 제어에
  충돌한다. `Sr/Sd`는 좌표 보관, `MS`는 이동이라는 기존 MF 분리를 유지했다.
- `Q`는 응답만 보내는 함수가 아니라 기존 실제 정지 함수를 호출한다. 이동 상태
  `D`와 형식 `GW`도 기존 MF 정보를 반환하며 upstream의 고정 응답으로 바꾸지 않았다.
- 사이트·시각 초기화 명령은 GPS·시스템 시각·마운트 위치를 변경하지 않는다.
  접속 종료는 임시 좌표·사이트 echo만 지우고, 짧은 TCP 연결을 사용하는 기존
  가이드 이동은 중단하지 않는다. 기존 가이드 정지·시간 제한 경로는 유지했다.
- 모든 테스트는 소켓·설정·마운트 의존성을 격리했다. 실제 앱의 epoch 설정,
  연결 handshake와 물리적 이동은 현장 확인이 필요하다.

#### 10번 중복/충돌 검토

- `nearby.py`의 반경 검색과 #622 `[dec, ra]` 수정은 MF에 이미 있다. 파일을
  다시 적용하지 않았다. #513의 옛 좌표 순서를 가져오는 회귀도 피했다.
- `user_guide.rst`의 목표·주변 DSO 설명은 이미 있었으므로 중복 삽입하지 않고
  중앙 천체 기능 설명만 추가했다.
- 목표 십자는 DSO 밝기와 독립적이다. 관측 목록은 등급/개수 제한 없이 표시하며,
  주변 DSO만 시야별 등급 제한과 최대 20개 제한을 받는다. ID별로 중복을 제거한다.
- 중앙 천체는 화면에 표시한 마커 중에서 선택하며 선택 흔들림 방지와 이름 스크롤을
  사용한다. RIGHT로 해당 상세 화면과 거리순 목록을 연다. Chart 설정의
  `Center Object`(한국어 `중앙 천체`, 기본 On)로 표시를 끌 수 있다.
- 상세 화면/설정에서 복귀할 때 같은 solve 시각이어도 한 번 다시 그리도록 했다.
  세 화면 크기에서 설정 변경·목표 변경·무솔브·RA/Dec 표시 배치를 검사했다.
- `plot.py`는 기존 투영을 배열 계산으로 묶는 부분만 변경했다. 이전 MF scalar
  구현과 새 scalar/batch 결과가 RA 경계·고위도·회전에서 같은지 비교했다.

#### 최종 검증과 적용 경계

- 전체 단위·스모크: **1,793 passed, 860 deselected**. 기존 tetra3 `np.math`
  DeprecationWarning 8건. 앞선 1~5 변경까지 포함해 재검증했다.
- Chart/상세/Align 관련 UI 통합 선택 실행: **7 passed, 2 skipped, 285 deselected**.
  두 skip은 실제 solve와 정렬별 순서를 요구하는 기존 UIAlign 키 순회 테스트다.
  Chart의 cold/warm 화면과 대상 추적 통합 테스트는 실행·통과했다.
- mypy: **192개 소스 오류 없음**. Ruff lint 및 변경 파일 포맷 검사 통과.
  전체 포맷 검사에서 지적하는 기존 `indi_goto_guide_service.py`는 수정하지 않았다.
- 한국어 메시지 컴파일 완료. BOM diff와 STL은 지정 upstream 변경만 반영했다.
  STL Git blob은 `d6eff844019b8c65683e49e0cfde66400d0095d4`로 원본과 일치한다.
- 실행 서비스 재시작, 실제 마운트/GPS/카메라 명령, 커밋·푸시는 하지 않았다.
  STL 출력물의 물리적 맞물림은 검사하지 않았다. 기존 `test_images/260903/` 유지.
- 아래 1~5 기록의 “6번 이후 미반영”은 해당 단계 종료 시점의 기록이다.
  현재 최종 선택 상태는 이 절을 우선한다.

### 2026-09-06: 사용자 선택 1~5 선별 반영

비교 기준: MF `9dfd3a3f`, upstream/main `803d41eb`.
아래는 이번 작업 트리의 반영 내역이며 아직 커밋·푸시하지 않았다.
이전 문서의 마지막 기록(8/9) 이후 MF에서 별도로 수정된 소스까지 비교했다.
upstream 전체 병합이나 커밋 단위 일괄 cherry-pick은 하지 않았다.

| 번호 | upstream | 이번 반영 범위 / 기존 MF 보호 |
| --- | --- | --- |
| 1 | #571 `f5d70cf7` | 장비/GPS 폼 서버 검증, 소수 측정값, 오류 표시·입력 유지, 잘못된 장비 URL 인덱스 방어. MF INDI·LiveCam·위치 카탈로그·설정 원자적 저장 경로 유지. |
| 2 | #640 `97985713` | `python/tetra3` Git 추적 해제와 설치·업데이트·CI 링크 생성. MF의 기존 `set -e` 및 업데이트 실패 시 `False` 반환은 이미 반영되어 있으므로 재수정하지 않음. |
| 3 | #638 `e15662dc` | Update Now/Cancel 텍스트 두 곳만 기존 `msg_top/msg_bottom`에 맞춤. MF 릴리스 URL·m 버전 비교·업데이트 실패 처리 유지. |
| 4 | #614 `bcdc4981`, #620 `14d9ccaa` | Focus UP/DOWN 임시 노출 단계 조정과 하단 상태 표시. MF Auto Star·수동 Gain 복원을 위해 카메라 런타임 상태 보관 방식으로 조정. |
| 5 | #635 `bfeaeb0f` | STATUS의 GPS MSG, UBX 미지원/체크섬 오류 마커, 20 Hz 진단 이벤트 제한. MF 시간 유효성·동기화 경로와 위성 4개 값 유지. |

#### upstream 그대로 적용하지 않은 부분

- **Focus 복원**: `set_exp:auto_star`를 다시 보내면 MF에서는 Gain이 센서
  프로파일로 초기화되고 수동 Gain 잠금이 풀린다. 따라서 카메라 프로세스가 진입
  직전 노출·Gain·자동노출 모드·Gain 선택을 보관하고 복원한다. 설정 파일은 쓰지
  않고 기존 solver 기반 제어기 객체도 교체하지 않는다. framewise Auto Star는
  복귀 시 제어 상태를 리셋하되 수동 Gain 잠금 여부를 유지한다.
- **Focus 수명주기**: 기존 메뉴는 새 화면을 처음 열 때 항상 `inactive()`를
  호출하지 않는다. Focus만 `covered()` 훅으로 해제하도록 하고 다른 화면의
  기존 수명주기는 유지했다. 최근 목록 바로가기로 스택을 줄이는 경우도 해제한다.
  각 방문에 토큰을 부여해 이전 화면의 지연 명령이 새 노출 선택을 덮지 못하게 했다.
  외부 노출/Gain/AE 명령이 들어오면 hold를 해제하고 기존 명령 처리가 우선한다.
- **Focus MF 기능**: Gain 퀵 메뉴, INDI Guide 종료 처리, 광각 원본 픽셀 경로,
  주간 포화 영상의 Bayer 평균·스트레치·회전을 유지했다. 주간 원본 영상도 새
  상태 표시줄 위에 전체 장면이 들어가도록 표시 크기만 조정했다.
- **tetra3 복구**: 공통 `scripts/ensure_tetra3_link.sh`를 사용한다. 이미 올바른
  상대 링크면 그대로 둔다. 기존 일반 파일·디렉터리·다른 링크는 삭제하지 않고
  `python/tetra3.backup.*/original`에 보존한다. submodule 대상이 없으면 기존
  경로를 건드리기 전에 실패한다. 과거 v2.1.0 마이그레이션이 상대 링크를 다시
  절대 링크로 바꾸던 한 줄은 제거했다.
- **GPS**: 위성 튜플 `(seen, used, in_view, top_cno)`, NAV-SAT 우선순위와
  NAV-SVINFO fallback, NAV-PVT 및 GPSD 시간 처리 분기를 보존했다. GPS MSG
  경과 시간은 main의 이벤트 수신 시점 기준이고 GPS의 시스템 시각 변경과 무관하다.
- **번역**: upstream locale 파일 전체를 덮지 않고 새 검증 문구의 한국어 번역만
  추가·컴파일했다. 기존 MF 번역은 유지했다.

#### 반영·검증 경계

- 실제 `python/tetra3` 링크는 유지되어 현재 import가 가능하다. Git index에는
  추적 해제에 필요한 삭제만 staged 상태이며 다른 변경은 unstaged 상태다.
- 실행 중 서비스 재시작, 실제 GPS 시각/위치 설정, 실제 카메라·마운트 명령,
  설치/업데이트 스크립트 실행은 하지 않았다. 장비 설정도 이 작업으로 저장하지 않았다.
- 기존 사용자 파일 `test_images/260903/`와 선택하지 않은 6번 이후 항목은 손대지 않았다.
- 새 테스트는 폼 요청을 Flask 테스트 클라이언트/격리 설정에서, 카메라 명령을
  가짜 백엔드에서, 링크 복구를 임시 디렉터리에서 검증한다.
- 실기기 확인은 별도로 필요하다: Focus 진입/UP·DOWN/복귀와 Auto Star·수동 Gain,
  176px 업데이트 화면, GPS 연결/단절 표시, 브라우저 장비 폼 입력.

최종 검증 결과 (2026-09-06):

- `cd python && .venv/bin/python -m pytest -q -m 'unit or smoke'`:
  **1,612 passed, 857 deselected**. 기존 tetra3의 `np.math` 사용에 따른
  DeprecationWarning 8건만 발생했다. 웹 브라우저/실기기 통합 테스트는 제외했다.
- `.nox/type_hints/bin/mypy PiFinder`: **191개 소스 오류 없음**.
- Ruff lint 전체 통과. 변경한 Python 파일의 포맷 검사 통과. 전체 포맷 검사는
  기존 HEAD와 동일한 `PiFinder/indi_goto_guide_service.py` 한 파일만 지적하며,
  요청 범위 밖인 해당 파일은 수정하지 않았다.
- 변경된 설치·업데이트·마이그레이션·링크 스크립트 `bash -n` 통과.
  실제 설치나 업데이트는 실행하지 않았다.
- 한국어 메시지 `pybabel compile -d locale -l ko` 통과.
- 실제 작업 트리에서 `import tetra3` 성공. 링크 복구 테스트는 새 링크·멱등성,
  기존 절대/끊어진 링크·파일·폴더 보존, submodule 미초기화 시 무변경을 확인했다.
- `git diff --check`와 staged diff 검사 통과.

2026-07-03 기준 최근 반영 상황:

- upstream selected commits applied:
  - NixOS PR build CI (이후 미사용으로 2026-09-28 워크플로 제거)
  - case/accessory STL changes
  - observing list CSV import improvements
  - UTC-aware datetime handling
  - Set Time/Date self-gate when no location lock exists
  - OBJ_TYPES single-source refactor
- local MF-only patch:
  - SSD1333 automatic display detection, separated from the larger Rev-4 hardware patch

2026-07-13 추가 반영:

- upstream selected commits applied:
  - Stellarium 2.0 observing list import (#527, `39412ac`)
  - catalog filter cache: skip re-filtering unchanged catalogs on list open (#526, `f704a26`)
  - UBlox GPS NAV-SVINFO/NAV-SAT 디코딩 수정 (#524, `9cb0060`) — `gps_ubx_parser.py`/
    테스트는 clean 적용, `gps_ubx.py`는 NAV-PVT 핸들러에서 MF 시간 처리와 upstream
    numSV used-count를 둘 다 유지하도록 수동 병합
- 검토 후 이번엔 제외:
  - NixOS 마이그레이션 3건 (#523 `e22ac48`, #521 `0621d15`, #517 `02e6b30`) — MF의
    NixOS 이관 지원 여부 미결정
  - state datetime tz 수정 (#508, `e64f0b6`) — timez.py 기준 이미 반영됨, 재적용 시
    제외한 Rev-4 state.py 변경이 딸려오므로 하지 않음
  - Rev-4 hardware enablement (#498, `e82b809`) — 정책상 제외 유지

2026-07-29 추가 반영 (upstream `534fc809..a132bc36`, 20 commits 검토):

- upstream selected commits applied (clean cherry-pick):
  - DeepskyLog eyepiece import AttributeError 수정 (#529, `f68de732`) —
    `server.py` 한 줄 수정 clean 적용. 동봉된 테스트의 FakeConfig에 MF server가
    읽는 `get_option()`을 보강 (`be252f29`)
  - Polar Alignment 가이드 field feedback 반영 (#518, `56d428f6`)
  - filtered list 갱신 유지 + 천체별 observed status 파생 (#528, `d2c566b6`) —
    catalogs/object_list clean 적용, 관련 테스트(cache/cursor/identity) 통과
  - cedar shmem RemoveIPC 복구 (#548, `1afbd3c2`) — **수동 이식으로 적용 완료
    (2026-07-29)**. SSH 로그아웃 시 logind `RemoveIPC=yes`가
    `/cedar_detect_image` shmem을 삭제해 이후 solve가 전부 실패하던 문제.
    이식 내용: `PFCedarDetectClient._del_shmem` 오버라이드(사라진 세그먼트를
    정상 해제로 처리), INTERNAL 폴백 시 1회 경고 로그, 인라인 폴백에
    `detect_hot_pixels` 유지, `pifinder_setup.sh`의 `RemoveIPC=no` drop-in.
    마이그레이션은 upstream `v2.6.1.sh` 대신 MF 규칙의 `mf_removeipc.sh`로
    이식(멱등이라 이후 upstream v2.6.1이 와도 무해). 테스트
    `test_solver_cedar_client.py`는 라이브 solver의 실제 세그먼트를 건드리지
    않도록 테스트 전용 shmem 이름을 쓰게 수정해서 가져옴. 개발 기기에는
    drop-in을 즉시 적용하고 마이그레이션 마커를 남김
  - 위치 입력 comma/period decimal (#536, `447aec8b`) — **수동 이식으로 적용
    완료 (2026-07-29)**. `parse_coordinate()` 서버 헬퍼, location 입력
    type=text inputmode=decimal 전환, JS `normalizeDecimal()` 정규화.
    MF location catalog 마크업과의 충돌만 수동 해소, 변경 내용 자체는 동일.
    두 스타일시트 모두 `input[type=text]`를 스타일링하므로 Red Night 테마
    영향 없음. `test_server_coordinates.py` 동봉
  - SSD1333 3축 밝기 (`a132bc36`) — **적용 완료 (2026-07-29)**. gray scale
    ceiling을 3번째 밝기 축으로 추가, dim floor 13400:1 범위. `displays.py`
    충돌 해소: import 병합 + MF의 `__init__(bus_speed_hz)` 시그니처(Pi5 SPI
    `display_spi()` 헬퍼) 유지. upstream ADR `0023-ssd1333-brightness`는 새
    번호 규칙(숫자=upstream)에 따라 그대로 수용. 밝기 매핑 단조성/레지스터
    범위는 fake device 시뮬레이션으로 확인, 실제 SSD1333 패널 실측은 미실시
  - SQM 스택 (#532 `b5b16883`, #544 `69fe28c2`, #542 `b36cb8c6`,
    #543 `5ef6a1b2`) — **수동 이식으로 적용 완료 (2026-07-30, 5단계)**.
    radiometer 우선 SQM(솔브 독립 1 Hz 발행), raw-green 측광, Gaia-G/B−V
    색보정, wing/cloud/black-level 추정기, raw 전용 보정 위저드,
    full-sensor 스윕. 상세 계획·리스크·커밋은
    [mf_sqm_stack_port_plan_ko.md](mf_sqm_stack_port_plan_ko.md).
    #542가 revert한 cedar hunk는 적용하지 않았고(우리 hybrid+RemoveIPC
    유지), #543은 post-#544 최종 상태 기준 이식으로 자동 포함. rev4
    rename hunk는 #539와 함께 보류 유지. **잔여 완료 조건: bias 238 기준
    야간 재검증(웜맵/σ) + SQM 위저드 1회 실행**
- 충돌로 보류 (수동 병합 필요, 다음 라운드 대상):
  - Focus raw multi-star 뷰 (#531, `70e243b9`) — MF가 수정한 `ui/preview.py`와 충돌
  - quick start focus 문서 (#546, `e9cbfe52`) — #531의 새 focus 화면을 전제로 한
    문구라 #531과 함께 판단
  - keypad matrix 분리 (#551, `a90311e7`) — `keyboard_pi.py` 충돌, rev4 power
    button GPIO 처리가 딸려옴
- 정책상 제외 (rev4 battery/hardware 제외 정책 유지):
  - battery ADR/CONTEXT 문서 (`cb79a5bd`, `08da007d`) — `docs/ax/battery/` 자체가
    MF에 없음
  - low-battery UX (#541 `46e658b4`), warning latch (#549 `afcb80ad`) —
    `battery_bq25895.py` 미포함
  - bringup 벤치 검증 (#552 `81a522fe`, 문서 #550 `28f52a5a`) — `keypad`,
    `battery_bq25895`, `sound` 모듈 의존
  - rev4 rename (#539 `0edff3bb`) — rev4 enablement 미적용 상태에서 rename만
    가져오면 diff만 커짐

2026-08-04 추가 반영 (upstream `a132bc36..4a83d25b`, 2.6.1 릴리즈 포함 31 commits 검토):

- upstream selected commits applied (clean cherry-pick):
  - catalog_objects 인덱스 (#564, `8d357eb6`) — object 상세 진입 스톨 수정.
    이 Pi 실측 조회 36ms → 1.1ms. DB 블롭까지 수용(런타임 백필이 no-op이
    되고, git 추적 파일인 `astro_data/pifinder_objects.db`가 기기에서
    dirty해지는 문제 회피)
  - SQM 스윕 노출 정착 (#561, `351129a3`) — imx462가 노출 변경 후 3프레임
    stale인데 2프레임만 플러시하던 문제. **스윕 재촬영/위저드 실행 전에
    선행 적용 필수였음(이제 적용됨)**
  - focus 기법 문서 (#547, `3e23052b`) — 보류 중이던 #546의 release 브랜치
    백포트판. 현행(pre-#531) focus 화면 기준이라 clean 적용. #546 자체는
    제외로 종결
  - ADR 0020 3중 충돌 정리 (`0b76b3c7`) — upstream이
    `0020-sqm-raw-green-*`→`0024`, `0020-filter-freshness-*`→`0025`로 개명.
    MF 트리에도 0020이 두 개 공존하던 실결함이 해소됨. `m` 접두사 규칙과
    무충돌(m0024 ≠ 0024). plain 0020은 이 트리에서 미할당 상태로 남음
    (upstream SOC ADR 몫). `mf_sqm_stack_port_plan_ko.md`의 인용도 갱신
- 수동 병합으로 적용:
  - GPS NAV-SAT latch/floor (#563, `e87abe49`) — NAV-SAT 5초 신선도 창,
    `_publish_sats()` seen>=used floor(NAV-PVT 선착 시 "0/9" 표시 수정 —
    MF 수신기의 정상 기동 순서), 파서 uSat 품질 게이트 정합, timezone
    미해석 시 UTC 폴백(커밋 크래시 수정). MF의 4원소 sats(in_view,
    top_cno)와 `_gps_time_message()` 유지한 채 병합.
    **의도적 미수용: `ui/timeentry.py` 타임존 표시줄 복원 hunk** — MF가
    128px 화면 오버런 때문에 일부러 지운 줄이라 되살리지 않음(동봉 표시
    테스트도 미이식). 다음 동기화에서 재론 금지
- 검토 후 이번엔 제외/보류 (상세: 2026-08-04 조사):
  - SQM 색보정 zero point (#560, `b28f7d9d`) — **2026-08-05 mono 가드와
    함께 적용 완료** (보류 해제). `_mosaic_phase_is_rggb`가 `profile.mono`를
    먼저 거부 — 가드 없이는 실측 모노 imx462(R/G=1.000 고정)에 색보정이
    켜져 SQM이 조용히 ~+0.74 mag 이동했음(함정 확인 후 차단). imx462/
    imx290은 상수 zero point 유지(upstream 재적합값 15.159, 기존 15.25
    대비 −0.09), hq는 색보정 전체 수용. 테스트: shipped-profile 불변
    테스트를 모노 거부 기준으로 재작성, 샘플러 역학 테스트 4건은
    `replace(mono=False)`로 색경로 유지, MF 회귀 핀
    (`test_measured_mono_imx462_keeps_the_constant_zero_point`) 추가.
    오프라인 재적합 도구(`radiometric_fit.py`)도 수용 — 향후 모노 전용
    zero point 재적합에 필요
  - i18n 2.6.1 패스 (#562, `26e79dc3`) — `.po`/`.mo`는 절대 수용 금지
    (언어당 527 msgid 소실, 실번역 35~36건 파괴). `ui/software.py` 2곳 +
    `ui/telemetry_list.py` 3곳 문자열 래핑만 후보로 남김(ko 비용: 신규
    msgstr 3건)
  - SSD1333 4축 밝기 (#568 `03e2314d` + #570 `3b4a7974`) — **2026-08-05
    부분 이식으로 적용 완료** (SSD1333 채택 계획 확정에 따라 보류 해제).
    드라이버(displays.py, ssd1333_device.py)+테스트(17건)+모델 문서
    (ADR 0023, docs/ax/display/)만 수용. 측정 저널 44개·러너 스크립트·
    벤치 하네스(panel_photometry/precharge_sweep, ~6,250줄)는 제외 —
    재특성화가 필요하면 upstream 커밋에서 가져온다(ssd1333-response.md
    상단 MF note). CONTEXT-MAP 충돌은 Display 항목만 수용(Battery/Sound/
    NixOS/Bring-up은 제외 컨텍스트). MF displays.py 수정(display_spi,
    bus_speed_hz, rotate=0, get_display spi_speed_hz) 전부 보존 검증.
    부수 발견: MF 자동감지 테스트(test_hardware_detect_display)가
    cc7ae95e의 get_i2c 전환을 안 따라간 채 방치돼 있었음(마커 없어 전체
    실행에서 항상 제외) — get_i2c seam 기준으로 재작성+unit 마커 부여
  - 2.6.1 릴리즈 커밋 5건 (`2fbc5acc` 등) — 릴리즈 문서/버전. 내용 상당수가
    rev4 등 미포함 기능. version.txt는 m 접두사 체계로 전환(m2.6.0, 2026-08-05). **주의: upstream이
    2.6.1을 release 브랜치에 발행하면 `ui/software.py:164`의 릴리즈 체크가
    brickbots 기준 "Update Now"를 띄우게 됨 — 2026-08-05 해결: 릴리즈
    체크/마이그레이션 게이트 URL을 포크로 전환, "Unknown" 표시 분기 추가**
  - bringup 도구 (#556 `2c8f2606`, `ff57fb22`, `8c813f94`) — import 단계
    실패(`keypad`/`battery_bq25895`/`sound`/`types.hardware`/`types.sound`
    부재). #552 제외 결정의 재확인. `ff57fb22`는 기제외 `81a522fe`와
    바이트 동일
  - keypad matrix 분리 (#551) — **보류 사유 정정**: rev4 power GPIO가
    딸려오는 게 아니라(그건 base에 이미 있던 컨텍스트), 실제 장벽은
    MF 4열(20키) vs upstream 5열(25키) 매트릭스 상수 자체. 수용 시 키패드
    오배선이라 제외로 격상. 유일 소비자가 제외된 bringup 도구
  - Focus multi-star (#531, `70e243b9`) — **2026-08-05 적용 완료** (보류
    해제). 새 4모드 화면(stars/single/image/stats) 수용, MF 기능 3종을 새
    화면 위에 재구현: GuideKeyMixin 유지, camera_gain 마킹메뉴(right) 유지,
    주간/포화 프레임 raw 렌더 경로는 Image 모드로 이식(기존 stretch EMA
    대신 프레임 median≥220 기준 — 새 화면이 stretch 상태를 제거했기 때문).
    `types/positioning.py`는 upstream 실제 델타(독스트링 한 문장)만 수용 —
    전체 채택 시 MF 필드(SolveDiagnostics.Centroids/solve_path, ImuSample
    보정 텔레메트리)가 소실되는 것을 테스트 4건 실패로 확인 후 복원.
    문서(quick_start/troubleshooting)는 post-#546 상태로 수렴 — 새 화면
    채택으로 #547의 구화면용 문구가 대체되고, #531 전제로 제외했던
    #546(`e9cbfe52`)도 함께 종결. 헤드리스 실행으로 4모드 렌더·GAIN
    마킹메뉴·솔빙 정상 확인, 전체 1,105건 통과
  - NixOS/CI 8건, 이미 반영된 docs/case 커밋들 — 해당 없음 또는 기반영

2026-08-09 추가 반영 (upstream `4a83d25b..7eaf058c`, 12 commits 검토):

- **정책 변경 (2026-08-09, 사용자 결정)**: rev4 하드웨어 관련 변경의 수용을
  **허용**한다. 단 두 가지 조건이 붙는다 — (1) 현재 소스의 동작에 문제가
  없어야 하고, (2) 충돌이 발생하면 임의 병합하지 말고 사용자에게 보고해
  결정을 받는다. 이전의 "rev4 전면 제외" 정책은 이 항목으로 대체된다.
- upstream 브랜치 상태: `upstream/release`가 `upstream/main`에 수렴했다.
  release에만 있고 main에 없는 커밋은 0건이며, release는 main보다 `7eaf058c`
  하나 뒤에 있을 뿐이다. `v2.6.1` 태그 자체(`8c6ae841`, 08-02)는 이미
  2026-08-04 라운드에서 검토 완료였고, "2일 전 업데이트"의 실체는 태그가
  아니라 08-06~08-07에 release에 얹힌 문서/자산 커밋 11건이다.
- 이번 라운드의 성격: **런타임 파이썬 코드 변경 0건**. 전량 rev4 사용자
  매뉴얼 재작성, rev4 하드웨어 설계 자산, 문서 작성용 Claude 스킬 개선이다.
  적용 후 `git diff --name-only`로 `python/` 이하 변경이 없음을 확인했다.
- 적용 완료 (8건, clean cherry-pick):
  - `511b599d` (#572) rev4 문서 갱신 계획 + `pf_remote.py` `--display`/`-fb`
    플래그. **충돌 1건을 무손실로 해소**: `product-knowledge-base.md`는 포크가
    merge-base 이후 한 번도 수정한 적이 없어(diff 0) MF 저작 내용이 존재하지
    않는다. 충돌 원인은 MF 드리프트가 아니라 제외한 `0edff3bb`(rev4 rename)를
    건너뛴 순서 문제라, upstream의 `511b599d` 시점 버전을 그대로 채택했다.
    **주의: `pf_remote launch -fb`는 이 포크에서 실패한다** — `main.py`에
    `-fb/--fakebattery`가 없다(배터리 미이식). 기본 경로(`--display
    headless_176`)는 포크에 `DisplayHeadless176`이 실재하므로 정상 동작한다
  - `de285d96` (#574) 내부 브링업 레퍼런스 `docs/ax/bringup.md` + CONTEXT-MAP
  - `f71ff317` (#575) rev4 화면·조이스틱, "Which PiFinder do I have?" (WP3)
  - `746edad9` (#577) Power & Charging 전면 재작성 (WP1)
  - `b138894f` (#578) SD 카드 — rev4 외부 슬롯 우선, v3/v2.5 별도 절 + **신규
    v2.5 절차**(기존에 없던 정보)
  - `5460cc60` (#582) 누락 rev4 상호 링크 2건
  - `7eaf058c` (#585) 문서 스킬 Simplified Technical English 하우스 스타일.
    `.claude/skills/`는 포크가 merge-base 이후 무수정이라 드리프트 없음
  - `aac4a7fb` rev4 하드웨어 설계 자산(KiCad/거버/STL/f3z, 약 19MB).
    런타임 영향 0
- 충돌 3건 — **사용자 결정 후 수동 병합으로 적용 완료 (2026-08-09)**:
  - **문서 방침 결정 (사용자)**: rev4 문서는 **upstream 그대로 유지**한다.
    포크에 없는 기능(배터리 잔량 표시·충전·저전력 경고·자동 종료, 사운드)을
    설명하는 절이 생기지만, "미지원" note를 달지 않고 upstream diff를 최소로
    유지하는 쪽을 택했다. rev4 소프트웨어를 이식하면 문서가 자동으로 맞는다.
    **따라서 다음 동기화에서 "문서가 없는 기능을 설명한다"는 이유로 되돌리지
    말 것** — 의도된 상태다
  - `016e0282` (#576) rev4 사운드/Volume — `menu_map.rst` 충돌.
    **결정: MF의 IMU Settings 트리 유지 + upstream GPS Baud Rate 문구 채택 +
    Volume 항목은 제외.** menu_map은 실제 메뉴 구조를 그리는 문서라 포크
    메뉴와 일치시켰다(포크엔 `sound.py`도 Volume 메뉴 항목도 없음).
    `user_guide.rst`의 `Sounds` 절은 문서 방침 결정에 따라 upstream 그대로
    수용했다 — menu_map만 실물 기준, 산문은 upstream 기준이라는 비대칭이
    의도된 것임에 주의
  - `84a2fbaf` (#583) rev4 사진 배치 — `troubleshooting.rst` 충돌.
    **결정: upstream의 신규 "Align (Day)" 진단 산문을 받고, 그 Camera Type
    불릿에 MF의 Mono/Color 안내 문장을 복원.** 복원 시 em-dash를 문장 분리로
    바꿔 방금 도입한 STE 하우스 스타일(`7eaf058c`)에 맞췄다 — 의미는 동일
  - `43200f86` (#584) v3 매뉴얼 아카이브 링크(`conf.py`의 `|v3_docs|` 치환자)
    — 예상대로 **순수 cascade**였다. `84a2fbaf` 해소 후 clean 적용됨
- 이번 라운드 제외:
  - `27ca9624` (#573) ADR 0020 배터리 프로파일링 + SOC_LUT 주석 —
    `battery_bq25895.py`와 `docs/adr/0020-soc-as-runtime-fraction.md` **둘 다
    포크에 부재**. rev4가 허용으로 바뀌었어도 이 커밋만 단독 적용하는 것은
    불가능하다(존재하지 않는 파일에 대한 수정). 배터리 수용은 `#498`/`#541`/
    `#549` 일괄 이식 결정이 선행되어야 한다
  - `0edff3bb` (#539) rev4 rename — 이번 라운드에서 의도적으로 제외.
    `main.py`, `config.py`, `hardware_detect.py`, `splash.py`, `state.py`,
    `ui/menu_structure.py`, `camera_interface.py` 등 **MF가 수정한 런타임
    파일 다수**를 건드리고 PiFinder Type 식별자를 바꾼다. "현재 동작 무손상"
    조건상 문서 라운드와 섞으면 안 된다. rev4 본체 이식을 결정할 때 함께 다룬다
- 결과: 신규 12건 중 **11건 적용, 1건 제외**(`27ca9624` — 적용 대상 파일 부재)
- 검증 (2026-08-09, 충돌 해소 후 재실행):
  - `python/` 이하 변경 0건 — 런타임 회귀 가능성 구조적으로 없음
  - Sphinx가 미설치라 실제 빌드는 못 했고, 대신 구조 검증을 돌렸다:
    `:ref:` 타깃 전수 확인(244개 라벨, dangling 0건), `|치환자|` 정의
    `min_software`/`v3_docs` 2건에 미정의 사용 0건, `.. image::` 264건 전수
    확인(누락 0건 — `includes/` 상대경로는 포함 문서 기준으로 해석되는 정상
    케이스), 잔존 충돌 마커 0건
  - `pf_remote.py`/`screenshot_to_doc.py` py_compile 통과
  - `test_menu_struct.py`, `test_hardware_detect_display.py`,
    `test_obj_types_docs.py` 12건 통과
  - 커밋만 했고 push하지 않았다. 롤백 기준점: `5b49bc82`
- 다음 라운드로 넘긴 결정 (rev4 본체 이식):
  - `#498`(rev4 hardware enablement) / `#541`·`#549`(배터리 UX) /
    `#551`(keypad matrix) / `#552`·`#556`(bringup) / `0edff3bb`(#539 rename)
    — rev4 허용 정책으로 바뀌었으니 이제 "정책상 제외"가 아니라 **미결정
    백로그**다. 문서는 이미 rev4를 설명하고 있으므로, 이식하면 문서와
    소프트웨어가 비로소 일치한다. 착수 시 `0edff3bb`를 먼저 처리해야
    `product-knowledge-base.md` 류의 순서 충돌이 재발하지 않는다

ADR 번호 규칙 (2026-07-29 확정):

- upstream과 MF가 각자 ADR을 추가하면서 0020부터 번호가 갈라졌다 (upstream
  0020=SOC runtime fraction, 0021=blind-floor shutdown, 0023=SSD1333
  brightness vs MF의 star-count/auto-exposure/solve-hold/cedar+SEP hybrid).
- 그래서 번호 공간을 분리했다: **MF가 자체 작성하는 ADR은 `m` 접두사**를
  쓴다 (`docs/adr/mNNNN-*.md`). 기존 MF ADR 4건은 번호를 유지한 채
  `m0020`~`m0023`으로 개명했고, 새 MF ADR은 `m0024`부터 이어간다.
- **upstream ADR은 체리픽 시 번호를 그대로 유지**한다 — upstream 커밋
  메시지/문서가 인용하는 번호가 우리 트리에서도 유효해야 하기 때문.
  숫자만 있는 ADR = upstream 것, `m` 접두사 = MF 것으로 출처가 구분된다.
- 2026-07-29 이전의 커밋 메시지가 말하는 "ADR 0020~0023"은 문맥에 따라
  MF 것(현재 m0020~m0023)일 수 있다.

주의:

- 이 문서는 전체 변경 히스토리 문서가 아니다.
- 상세 기능 기록은 `docs/mf_dev/mf_change_history_ko.md`를 참고한다.
- 이 문서는 upstream 재동기화와 패치 재적용 기준에 집중한다.

## upstream에서 이미 반영한 변경

다음 upstream 변경은 `mf_pifinder`에 반영되어 있다.

| 영역 | 상태 | 비고 |
| --- | --- | --- |
| NixOS PR build CI | 워크플로 제거됨 | 최초 반영 후 미사용으로 2026-09-28 워크플로 제거. manifest script는 유지 |
| case/accessory files | 적용됨 | 코드 영향 없음. STL/JPG/README 변경 |
| Observing list CSV import | 적용됨 | `obslist_formats.py`, docs, tests 적용 |
| Observing list Stellarium 2.0 import | 적용됨 | #527 `39412ac`. `obslist_formats.py` Stellarium reader 확장 |
| catalog filter cache | 적용됨 | #526 `f704a26`. `catalog_base.py` 추가, 변경 없는 카탈로그 재필터 생략 |
| UBlox GPS NAV-SVINFO/NAV-SAT 디코딩 수정 | 적용됨 | #524 `9cb0060`. `gps_ubx_parser.py` 오프셋 수정, `gps_ubx.py` NAV-PVT 수동 병합 |
| UTC-aware datetime | 적용됨 | `timez.py` 추가, `state.py`, `server.py`, callback 시간 처리 변경 |
| Set Time/Date self-gate | 적용됨 | 위치 lock이 없으면 수동 시간/날짜 설정 UI가 inert 상태로 메시지 표시 |
| OBJ_TYPES single-source | 적용됨 | Type filter menu가 `OBJ_TYPES`에서 생성됨 |

이 변경들은 다음 upstream sync 때 중복 적용하지 않는다.

## upstream에서 의도적으로 제외한 Rev-4 하드웨어 변경

upstream의 Rev-4 hardware enablement 패치는 아직 전체 적용하지 않았다.

제외한 기능:

- BQ25895 battery telemetry
- BQ25895 fast-charge runtime configuration writes
- sound/earcon buzzer subsystem
- GPIO15 hardware power button
- GPIO14 gpio-poweroff latch
- battery titlebar icon
- Raspberry Pi red power LED shutdown

제외 이유:

- Rev-4 전용 GPIO/I2C/PWM 가정이 Pi4/Pi5/CM5 호환 경로에 영향을 줄 수 있다.
- GPIO14 poweroff latch는 하드웨어 배선이 맞지 않으면 위험할 수 있다.
- sound/earcon은 관측 환경에서 기본 OFF 정책이 필요하다.
- battery charger write 동작은 하드웨어 검증 후 별도 옵션으로 넣는 것이 안전하다.

부분 적용한 기능:

- SSD1333 display auto-detection only

현재 구현:

- `python/PiFinder/hardware_detect.py`
- `python/PiFinder/main.py`
- `python/PiFinder/splash.py`
- `python/tests/test_hardware_detect_display.py`

동작:

- BQ25895 I2C address `0x6A` ACK를 Rev-4/SSD1333 display marker로 사용한다.
- 감지 성공 시 기본 display hardware는 `ssd1333`이다.
- 감지 실패, Blinka import 실패, GPIO/I2C 접근 실패 시 기존 기본값 `ssd1351`로 fallback한다.
- `--display` 명령행 옵션이 있으면 자동 감지보다 우선한다.

다음에 Rev-4 변경을 추가로 가져올 때:

- battery/sound/power/latch를 한 번에 병합하지 않는다.
- `HardwareCapabilities` 같은 공통 타입을 추가하더라도 기존 `hardware_detect.py`의
  import-safe fallback을 유지한다.
- GPIO14 poweroff latch는 별도 설치 옵션과 명확한 문서가 필요하다.

## MF 전용 주요 패치 영역

다음 영역은 upstream에 아직 없거나 MF 브랜치에서 다르게 동작한다.
upstream 변경 시 이 기능들이 깨지지 않는지 우선 확인한다.

### Platform / Bookworm / Pi4-Pi5-CM5

주요 파일:

- `pifinder_paths.sh`
- `pifinder_setup.sh`
- `pifinder_update.sh`
- `pifinder_post_update.sh`
- `python/PiFinder/board_config.py`
- `python/PiFinder/boot_config.py`
- `python/PiFinder/sys_utils.py`
- `python/PiFinder/displays.py`
- `pi_config_files/*.service`

보존해야 할 정책:

- Bookworm boot config는 `/boot/firmware/config.txt` 우선, legacy는 `/boot/config.txt`.
- `PiFinder_data`와 systemd/Samba 경로는 현재 OS 사용자 기준으로 렌더링한다.
- Pi4/Pi5/CM5 보드 profile에 따라 GPS UART default가 달라진다.
- Pi5/CM5는 OLED CS 충돌을 피하기 위해 `uart2-pi5` 경로를 사용한다.
- SPI 장치는 `/dev/spidev0.0`과 `/dev/spidev10.0` 모두 지원한다.

### Camera / Focus / Gain

주요 파일:

- `python/PiFinder/camera_interface.py`
- `python/PiFinder/ui/preview.py`
- `python/PiFinder/ui/menu_structure.py`
- `python/PiFinder/ui/callbacks.py`
- `scripts/camera_lcd_preview.py`

보존해야 할 정책:

- focus preview와 camera gain runtime/profile 설정을 유지한다.
- LCD preview script는 하드웨어 디버깅용으로 유지한다.
- upstream camera 변경 시 exposure/gain menu callback 충돌을 확인한다.

### Korean localization

주요 파일:

- `python/locale/ko/LC_MESSAGES/messages.po`
- `python/locale/ko/LC_MESSAGES/messages.mo`
- `python/PiFinder/ui/fonts.py`
- `python/PiFinder/ui/menu_structure.py`

보존해야 할 정책:

- 언어 메뉴에서 `ko`를 유지한다.
- CJK font와 restart 안내 흐름을 유지한다.
- upstream i18n 업데이트 후 Korean `.po` drift를 확인한다.

### Bluetooth / USB HID keyboard

주요 파일:

- `python/PiFinder/keyboard_interface.py`
- `python/PiFinder/keyboard_pi.py`
- `python/PiFinder/ui/bluetooth_keyboard.py`
- `python/PiFinder/ui/textentry.py`
- `python/PiFinder/ui/menu_structure.py`

보존해야 할 정책:

- libinput 기반 HID keyboard event mapping을 유지한다.
- Bluetooth scan/pair/connect UI를 유지한다.
- INDI guide 이동용 `qwe/asd/zxc` 추가 키맵을 유지한다 (Guide page와
  `GuideKeyMixin` 기반 passive 화면).
- key press/release가 필요한 guide motion은 release/timeout fail-safe를 유지한다.

### Integrated time sync

주요 파일:

- `python/PiFinder/gps_time_sync.py`
- `python/PiFinder/gps_time_sync_helper.py`
- `python/PiFinder/ui/gps_time_sync_status.py`
- `scripts/install_chrony_time_sync.sh`
- `scripts/install_gps_time_sync_helper.sh`
- `pi_config_files/pifinder_gps_time_sync.service`

보존해야 할 정책:

- 기본 시간 관리는 `chronyd` 중심이다.
- PiFinder time sync UI는 GPS/NTP/RTC 상태와 helper를 관리한다.
- 실제 시스템 시간 변경은 privileged helper/service 층에서 수행한다.
- INDI/OnStep으로 보낼 시간은 사용자가 입력한 값이 아니라 PiFinder가 사용하는 현재
  정확한 UTC 시간이어야 한다.

### Wi-Fi AP+STA

주요 파일:

- `scripts/pifinder_apsta.sh`
- `scripts/import_initial_wifi_networks.py`
- `python/PiFinder/sys_utils.py`
- `python/PiFinder/server.py`
- `python/views/network.html`
- `pi_config_files/pifinder_apsta_prepare.service`
- `pi_config_files/pifinder_apsta_monitor.service`
- `pi_config_files/dhcpcd.conf.apsta`

보존해야 할 정책:

- Wi-Fi mode는 STA/AP/AP+STA를 지원한다.
- AP+STA에서는 STA channel을 기준으로 AP virtual interface를 재시작한다.
- AP IP는 설정 가능해야 한다.
- AP security/password 설정을 유지한다.
- AP+STA internet sharing은 option이며 default OFF이다.
- 설명 문구에는 부하와 속도 저하 가능성을 안내한다.
- OS 초기 설치 시 등록된 STA profile을 PiFinder 목록으로 가져온다.
- 새 STA 추가 시 주변 SSID scan 목록을 사용할 수 있어야 한다.
- STA band preference는 2.4G/5G 선택 정책을 유지한다.

### Locations catalog

주요 파일:

- `python/PiFinder/location_catalog.py`
- `python/PiFinder/data/location_catalog.json`
- `scripts/build_location_catalog.py`
- `python/views/locations.html`
- `python/views/location_form.html`

보존해야 할 정책:

- 국가/지역/군구/도시 선택으로 좌표와 고도를 자동 입력한다.
- 북한 데이터는 제외한다.
- 한국은 행정구역 데이터를 섞어 비교적 상세한 선택을 지원한다.
- 수동 위치 선택은 실내 GPS unlock 상태에서도 PiFinder location source로 사용 가능해야 한다.
- Red Night theme에서 form/select/action tooltip 색상이 하얗게 튀지 않아야 한다.

### Web UI theme / PWA

주요 파일:

- `python/views/base.html`
- `python/views/css/style.css`
- `python/views/js/init.js`
- `python/views/manifest.webmanifest`
- `python/views/service-worker.js`
- `python/views/images/pwa-icon-192.png`
- `python/views/images/pwa-icon-512.png`

보존해야 할 정책:

- Red Night theme는 관측 중 암시야를 해치지 않는 적색 UI여야 한다.
- Logs page의 log content 색은 원래 의미 색을 유지한다.
- Android PWA 전체화면에서 theme color와 display mode를 유지한다.
- 메뉴 이동 후 fullscreen/PWA 상태가 불필요하게 깨지지 않도록 한다.
- Theme 선택은 navigation의 select로만 제공하고, 별도 bar는 제거 상태를 유지한다.

### INDI / OnStepX

주요 파일:

- `python/PiFinder/mountcontrol_indi.py`
- `python/PiFinder/indi_align.py`
- `python/PiFinder/indi_backlash_calibration.py`
- `python/PiFinder/indi_goto_guide_service.py`
- `python/PiFinder/indi_multipoint_align.py`
- `python/PiFinder/pos_server.py`
- `python/PiFinder/ui/indi.py`
- `python/views/indi_mount.html`
- `scripts/install_indi_mount_OnstepX.sh`
- `scripts/install_indi_mount_archive.sh`
- `scripts/package_indi_mount_archive.sh`
- `scripts/patches/indi-v2.2.3.1-onstepx.patch`

보존해야 할 정책:

- INDI 기능은 optional이다. 기본 PiFinder 설치만으로 INDI가 강제 설치되면 안 된다.
- OnStepX는 커스텀 INDI driver 이름이며, 원본 LX200 OnStep driver를 직접 덮어쓰지 않는다.
- INDI profile에서 active driver name을 읽고, OnStepX일 때만 OnStepX 전용 화면/동작을 사용한다.
- OnStepX 위치/시간 sync는 driver readback 표시와 실제 OnStep 값이 일관되도록 유지한다.
- OnStep 위치/시간 설정 시 PiFinder 현재 UTC 시간을 사용한다.
- OnStepX `Backlash`는 OnStep 펌웨어와 맞춘 0..3600 arc-sec 범위를 유지한다.
- OnStepX `GUIDE_RATE`는 driver 호환성과 향후 guide-rate 제어를 위해
  writable/readback 동작을 유지하는 것이 좋다. 현재 Auto Backlash는 INDI
  GoTo를 사용하므로 `GUIDE_RATE`에 의존하지 않는다.
- OnStepX가 아닌 일반 INDI mount에서는 generic INDI path를 유지한다.
- INDI restart는 server/profile/driver를 모두 정지 후 다시 시작하고, 가능하면 자동 connect한다.

### LCD INDI UI

주요 파일:

- `python/PiFinder/ui/indi.py`
- `python/PiFinder/ui/menu_structure.py`
- `python/PiFinder/ui/base.py`
- `python/PiFinder/keyboard_pi.py`

보존해야 할 정책:

- Start 메뉴 하단에 INDI 항목을 둔다.
- INIT/STATUS/GUIDE 페이지를 유지한다.
- Guide page는 숫자키 `2/4/6/8`(동서남북)과 `qwe/asd/zxc` 키맵을 사용하고,
  `9/3`은 slew rate 조절이다. 대각선 이동은 키보드 문자키에만 있다.
- 5키는 guide motion에 사용하지 않는다.
- motion은 press-to-move, release-to-stop 방식이다.
- freeze나 key release 누락 시 timeout/fail-safe stop을 유지한다.
- 상단 bar의 `I` indicator는 INDI 연결 정상/문제 상태를 표시한다.

### SkySafari / mount mode integration

주요 파일:

- `python/PiFinder/pos_server.py`
- `python/PiFinder/pointing_coordinate_service.py`
- `python/PiFinder/mountcontrol_indi.py`
- `python/PiFinder/imu_pi.py`
- `python/PiFinder/imu_calibration.py`

보존해야 할 정책:

- SkySafari `:Sr/:Sd`(target 저장) → `:MS#`(GoTo) / `:CM#`(Sync/Align, 직전
  `Sr/Sd` 우선)의 forwarding 의미를 유지한다. 전체 흐름은
  [mf_goto_mount_source_structure_ko.md](mf_goto_mount_source_structure_ko.md) 참조.
- GoTo forwarding이 켜져 있으면 Align/Sync도 INDI/OnStep에 전달할 수 있어야 한다.
- solve 전에는 IMU fallback/보정값을 사용할 수 있다.
- solve가 성공하면 IMU alignment correction은 초기화한다.
- Reset Pointing은 IMU alignment correction을 폐기하고, 솔빙이 없으면 raw
  (보정 미적용) IMU 좌표로 마운트를 재-sync한다 — 잘못된 target으로 정렬했을 때
  IMU 원좌표로 복구하는 유일한 수단이다.
- mount mode가 Alt/Az, EQ, 기타 INDI mount에서 동작할 수 있도록 OnStep 전용 코드는 driver
  capability/name으로 gate한다.

### IMU compass / calibration

주요 파일:

- `python/PiFinder/imu_pi.py`
- `python/PiFinder/imu_calibration.py`
- `python/PiFinder/ui/menu_structure.py`
- `python/PiFinder/ui/callbacks.py`

보존해야 할 정책:

- magnetometer/compass fusion은 option이다.
- 기본 동작은 기존 IMU 안정성을 해치지 않아야 한다.
- calibration은 자동 저장/로드를 우선하고, 수동 save/load/clear 메뉴를 제공한다.
- calibration 상태 UI는 실제 BNO055 상태를 반영한다.

### 문서 빌드 툴체인 (2026-08-10 추가)

주요 파일:

- `python/requirements_dev.txt`
- `python/noxfile.py`
- `CLAUDE.md`
- `docs/mf_dev/mf_bookworm_install_ko.md` / `_en.md`

보존해야 할 정책:

- `requirements_dev.txt` 마지막의 `-r ../docs/source/requirements.txt` 한 줄을
  유지한다. upstream에는 없는 MF 추가분이며, 이것 때문에 기존 개발 환경 구축
  명령만으로 Sphinx가 함께 설치된다.
- 버전을 `requirements_dev.txt`에 직접 고정하지 않는다. Read the Docs가 쓰는
  `docs/source/requirements.txt`를 참조해 단일 출처를 유지한다.
- `noxfile.py`의 `docs` 세션을 유지한다. `-n -W --keep-going`이 핵심이다 —
  경고를 실패로 만들지 않으면 부분 적용으로 끊긴 참조를 놓친다.
- `docs` 세션은 `nox.options.sessions` 기본 목록에 넣지 않는다.
- upstream이 자체 docs 세션이나 docs extra를 추가하면 중복 여부를 확인하고
  한쪽으로 정리한다.

## 충돌 가능성이 높은 파일

upstream sync 때 먼저 확인할 파일:

```text
default_config.json
pifinder_setup.sh
pifinder_post_update.sh
python/PiFinder/main.py
python/PiFinder/server.py
python/PiFinder/sys_utils.py
python/PiFinder/sys_utils_fake.py
python/PiFinder/displays.py
python/PiFinder/splash.py
python/PiFinder/keyboard_interface.py
python/PiFinder/keyboard_pi.py
python/PiFinder/pos_server.py
python/PiFinder/mountcontrol_indi.py
python/PiFinder/ui/base.py
python/PiFinder/ui/callbacks.py
python/PiFinder/ui/menu_manager.py
python/PiFinder/ui/menu_structure.py
python/requirements_dev.txt
python/noxfile.py
python/views/base.html
python/views/css/style.css
python/views/network.html
python/views/locations.html
python/views/indi_mount.html
```

특히 다음 파일은 기능 경계가 많이 겹친다.

- `main.py`: startup process, display selection, GPS/camera/keyboard selection, time sync queue
- `server.py`: web routes, network/location/INDI APIs, time/location push
- `sys_utils.py`: privileged system operations, Wi-Fi, chrony, INDI service helpers
- `keyboard_pi.py`: GPIO keypad, HID keyboard, guide fail-safe
- `ui/menu_structure.py`: upstream menu additions과 MF menu additions가 자주 충돌
- `ui/base.py`: titlebar/status indicators/theme-independent LCD UI helpers
- `pos_server.py`: SkySafari LX200 protocol, GoTo/Sync/Guide/IMU fallback

## upstream sync 권장 절차

1. 현재 상태 확인:

```bash
git status --short --branch
git remote -v
git fetch upstream main
git rev-list --left-right --count upstream/main...HEAD
git log --oneline --left-right --cherry-pick upstream/main...HEAD --max-count=80
```

2. 변경 범위 확인:

```bash
git diff --stat HEAD...upstream/main
git diff --name-status HEAD...upstream/main
```

3. 충돌 dry-run:

```bash
git merge-tree --write-tree HEAD upstream/main
```

4. 적용 기준:

- 문서/CI/asset 같은 runtime 영향이 적은 변경부터 적용한다.
- Python runtime 변경은 기능 단위로 cherry-pick하거나 별도 sync branch에서 merge한다.
- Rev-4 hardware patch처럼 hardware side effect가 큰 변경은 쪼개서 적용한다.
- OnStepX/INDI/Network/Time sync 파일은 automatic resolution을 믿지 말고 diff를 읽는다.

5. 최소 검증:

```bash
python -m compileall -q python/PiFinder
python -m pytest \
  python/tests/test_hardware_detect_display.py \
  python/tests/test_obj_types_docs.py \
  python/tests/test_menu_struct.py \
  python/tests/test_time_date_gate.py \
  python/tests/test_state_datetime.py \
  python/tests/test_obslist_formats.py \
  python/tests/test_obslist_resolve.py \
  python/tests/test_pos_server.py \
  python/tests/test_mountcontrol_indi.py \
  python/tests/test_web_theme_static.py \
  python/tests/test_wifi_apsta_static.py \
  python/tests/test_location_catalog.py \
  python/tests/test_sys_utils.py
```

6. 하드웨어 검증:

- Pi4 Bookworm 64-bit
- Pi5 또는 CM5 Bookworm 64-bit
- Camera preview/focus
- GPS lock/unlock and manual location load
- Bluetooth keyboard key press/release
- Web Red Night theme
- AP+STA and AP client list
- INDI Web UI and LCD INDI Guide stop fail-safe
- SkySafari GoTo/Align/Guide path

## 알려진 테스트 주의사항

전체 `python -m pytest python/tests`는 현재 일부 기존 테스트가 환경/테스트 API 문제로
실패할 수 있다.

2026-07-03 확인된 대표 원인:

- `test_multiproclogging.py`: `pifinder_logconf.json` 경로 의존
- `test_radec_entry.py`: 테스트가 기대하는 생성자/API와 현재 코드 불일치
- `test_ui_modules.py`: `key_number_press(number)` 같은 인자 필요 key method를 무인자로
  sweep하는 테스트 구조

따라서 upstream sync 후에는 위의 최소 검증 목록을 우선 기준으로 삼고, 전체 테스트 실패는
첫 traceback을 기준으로 실제 회귀인지 기존 테스트 불일치인지 분리한다.

## 다음에 문서를 갱신해야 하는 경우

다음 변경이 발생하면 이 문서를 갱신한다.

- upstream main에서 `main.py`, `server.py`, `sys_utils.py`, `ui/menu_structure.py`,
  `pos_server.py`가 크게 바뀐 경우
- Rev-4 battery/sound/power 기능 중 일부를 추가 적용한 경우
- INDI generic path와 OnStepX-specific path를 다시 분리하거나 합친 경우
- SkySafari Align/GoTo/Guide 처리 정책이 바뀐 경우
- chronyd/time sync 정책이 바뀐 경우
- AP+STA 네트워크 정책이나 service 이름이 바뀐 경우
