# 입력·웹·카탈로그 — 이전 설계와 조사 기록

> 2026-10-10 통합 보관. 아래 본문의 “현재/현행”, 기본값, 완료 상태와 명령은 원문 작성 당시 기준이다.
> 오늘의 동작은 [개발 기준 문서](../../mf_dev/README.md)를 따른다. 이력에 적힌 절차를 현재 설치 절차로 사용하지 않는다.

- [mf_cache_download_ko.md](#mf_cache_download_ko)
- [mf_input_controls_ko.md](#mf_input_controls_ko)
- [mf_input_keymap_ko.md](#mf_input_keymap_ko)
- [mf_keyboard_mapping_ko.md](#mf_keyboard_mapping_ko)
- [mf_large_catalog_lazy_load_ko.md](#mf_large_catalog_lazy_load_ko)
- [mf_lcd_operation_errors_ko.md](#mf_lcd_operation_errors_ko)
- [mf_location_catalog_ko.md](#mf_location_catalog_ko)
- [mf_stellarium_push_port_analysis_ko.md](#mf_stellarium_push_port_analysis_ko)
- [mf_web_catalogs_dev_ko.md](#mf_web_catalogs_dev_ko)


---

<a id="mf_cache_download_ko"></a>

## mf_cache_download_ko.md

<a id="mf_cache_download_ko--mfnavis-오프라인-캐시-다운로드-가이드"></a>
## MFNavis 오프라인 캐시 다운로드 가이드

[English](interfaces.md#mf_cache_download_ko) | [한국어](interfaces.md#mf_cache_download_ko)

<a id="mf_cache_download_ko--목적과-범위"></a>
### 목적과 범위

`scripts/warm_mfnavis_caches.py`는 인터넷 연결이 가능한 때 MFNavis의
재생성 가능한 로컬 캐시를 미리 준비하는 도구다. 별도 인터넷 연결 없이도
카탈로그 탐색과 웹 카탈로그 상세 화면을 빠르게 열 수 있게 하는 것이 목적이다.

이 도구는 다음만 만들거나 내려받는다.

| 위치 | 내용 | 용도 |
| --- | --- | --- |
| `~/MFNavis_data/cache/hip_main.pkl` | Hipparcos 별 카탈로그 파싱 캐시 | 별 지도 초기화 단축 |
| `~/MFNavis_data/cache/hip_bv.npz` | Hipparcos B-V 색 지수 캐시 | SQM 색 보정 초기화 단축 |
| `~/MFNavis_data/cache/catalogs/` | 복합 천체 카탈로그 캐시 | 카탈로그 검색·목록 초기화 단축 |
| `~/MFNavis_data/catalog_images/` | POSS/SDSS 천체 서베이 이미지 | MFNavis 및 웹 카탈로그의 천체 사진 |

관측 기록, 장비 설정, Wi-Fi 정보, 사용자 사진 및 로그는 변경하거나
다운로드하지 않는다. 카메라의 warm-pixel map처럼 실제 장비·촬영 조건에서만
의미가 있는 캐시도 사전 생성하지 않는다.

<a id="mf_cache_download_ko--실행-전-준비"></a>
### 실행 전 준비

- MFNavis가 인터넷에 연결되어 있어야 한다. AP 모드로 휴대기기만 연결한
  상태는 인터넷 연결이 아닐 수 있다.
- 전원과 저장 공간이 충분한 상태에서 실행한다. 기존 배포 이미지의
  13,000개 이상 카탈로그 이미지는 약 5GB 수준이므로, 전체 POSS+SDSS
  다운로드에는 **최소 6GB 이상의 여유 공간**을 권장한다. 실제 크기는
  서베이 응답과 현재 카탈로그에 따라 달라질 수 있다.
- 관측 중에는 실행하지 않는 것이 좋다. 다운로드와 카탈로그 생성이 CPU,
  네트워크 및 SD 카드 I/O를 사용한다.

<a id="mf_cache_download_ko--tools-페이지에서-실행"></a>
### Tools 페이지에서 실행

웹 UI의 **Tools → 오프라인 캐시 다운로드**에서 이미지 범위(POSS+SDSS,
POSS만, 런타임 캐시만)와 동시 다운로드 수(1~10, 기본 4)를 선택하고
**다운로드 시작**을 누른다. **런타임 캐시 건너뛰기**로 이미지만 받을 수도 있다.

진행 상태는 2초마다 갱신된다. 현재 단계·천체, 처리 건수와 진행률,
기존 캐시·저장 이미지·서베이 범위 밖·실패 건수, 경과 시간·예상 남은 시간,
여유 공간과 최근 로그를 확인할 수 있다. 예상 남은 시간은 현재 실행에서
처리한 천체의 평균 시간으로 계산하며 네트워크 상태에 따라 달라진다.

**중지**는 다운로드 프로세스와 하위 작업을 종료한다. **다운로드 재개**는
이전 설정으로 다시 실행하여 완성된 파일과 SDSS 범위 밖 기록을 건너뛴다.
전송 중이던 이미지는 다음 실행에서 다시 요청한다. 동시에 한 작업만 실행된다.
페이지를 닫거나 다른 화면으로 이동해도 작업은 계속되며, Tools를 다시 열면
같은 작업의 상태가 표시된다. 서비스 재시작·재부팅으로 끊긴 작업은
**중단됨**으로 표시되고 재개 버튼으로 다시 실행할 수 있다.

작업 설정과 최근 상태는 `~/MFNavis_data/cache_download.json`에 저장한다.
실제 진행률은 처리한 천체 수이며 실패·범위 밖 천체도 처리 건수에 포함된다.
실패가 있으면 마지막 상태는 실패로 표시되고 재개하여 다시 시도할 수 있다.
런타임 캐시 단계는 3개 생성 단계의 진행 상태를 표시한다.

<a id="mf_cache_download_ko--기본-실행"></a>
### 기본 실행

저장소 최상위 디렉터리에서 다음 명령을 실행한다.

```bash
cd ~/MFNavis
python3 scripts/warm_mfnavis_caches.py
```

Trixie에서는 설치된 `.venv-trixie`의 Python을 자동으로 사용한다. 이미
가상환경을 활성화했다면 해당 환경을 사용한다. Python을 직접 지정하려면
`MFNAVIS_PYTHON=/경로/venv/bin/python`을 설정하며, 이 설정이 가장 우선한다.
이미지 다운로드에도 같은 Python을 사용한다.

기본값은 다음 순서로 동작한다.

1. Hipparcos 별 필드 및 B-V 색상 캐시를 생성한다.
2. 전체 복합 천체 카탈로그 캐시를 생성한다.
3. POSS와 SDSS 이미지를 기존 `MFNavis.gen_images` 모듈로 내려받는다.

이미지는 기본적으로 10개씩 동시 다운로드한다. 네트워크가 불안정하거나
다른 서비스를 함께 사용 중이면 `--workers 4`처럼 낮출 수 있다.

```bash
python3 scripts/warm_mfnavis_caches.py --workers 4
```

<a id="mf_cache_download_ko--필요한-범위별-실행"></a>
### 필요한 범위별 실행

웹 카탈로그와 MFNavis의 천체 사진은 POSS 이미지를 사용한다. SDSS까지
보관하지 않아도 되는 경우에는 다음처럼 실행한다.

```bash
python3 scripts/warm_mfnavis_caches.py --images poss
```

이미지 없이 빠른 시작용 데이터 캐시만 생성하려면 다음을 사용한다.

```bash
python3 scripts/warm_mfnavis_caches.py --images none
```

이미지 다운로드만 다시 수행하려면 다음을 사용한다.

```bash
python3 scripts/warm_mfnavis_caches.py --skip-runtime
```

<a id="mf_cache_download_ko--진행-상태와-완료-확인"></a>
### 진행 상태와 완료 확인

실행 중에는 런타임 캐시 단계와 이미지 다운로드 진행률이 터미널에 표시된다.
다른 터미널에서는 다음으로 크기와 파일 수를 확인할 수 있다.

```bash
du -sh ~/MFNavis_data/cache ~/MFNavis_data/catalog_images
find ~/MFNavis_data/catalog_images -name '*_POSS.jpg' | wc -l
find ~/MFNavis_data/catalog_images -name '*_SDSS.jpg' | wc -l
```

정상 완료 시 `Cache warm-up complete`가 표시된다. 이후 인터넷을 끊은 뒤
카탈로그 상세 화면을 열어, 이미 캐시된 천체의 사진이 표시되는지 확인할 수
있다.

<a id="mf_cache_download_ko--중단과-재실행"></a>
### 중단과 재실행

네트워크가 끊기거나 작업을 멈춰야 하면 `Ctrl-C`로 종료한 뒤, 인터넷이
가능해졌을 때 같은 명령을 다시 실행한다. 이미 완성된 이미지 파일은
`gen_images`가 건너뛰고, 유효한 런타임 캐시는 다시 사용한다.

정적 캐시를 만드는 동안에는 행성·혜성 갱신 타이머와 혜성 자료 다운로드를
시작하지 않는다. 이미지도 완전히 저장된 뒤에만 최종 JPEG 경로로 옮긴다.
다운로드 실패가 있으면 명령은 실패 코드로 끝나며, 같은 명령을 다시 실행할 수
있다. SDSS 범위 밖의 천체는 `unavailable`로 집계하고 실패로 보지 않는다.
SDSS 이미지 API의 `404` 응답 중 콘텐츠 형식이 `image/jpeg`인 경우는
촬영 범위 밖의 좌표를 뜻한다. 이런 응답과 빈 이미지는 JPEG 경로 옆의
`.unavailable.json`에 기록하여 다음 실행에서 같은 미지원 이미지를 다시
요청하지 않는다. 좌표·서베이 URL·이미지 설정이 같을 때만 기록을 재사용하며,
이미지 생성기의 `--force` 옵션으로 다시 조회할 수 있다. HTML `404` 응답,
서버 오류 및 시간 초과는 재시도 가능한 실패로 계속 집계한다.
이전 버전에서 남은 손상 이미지는 해당 JPEG만 삭제한 뒤 다시 실행한다.
사용자 설정·관측 기록은 삭제하지 않는다.

<a id="mf_cache_download_ko--문제-해결"></a>
### 문제 해결

| 증상 | 확인 및 조치 |
| --- | --- |
| 이미지가 전혀 늘지 않음 | MFNavis 자체가 인터넷에 연결되어 있는지, DNS와 HTTPS 연결이 가능한지 확인한다. |
| 저장 공간 부족 | `--images poss`로 SDSS를 제외하거나 더 큰 SD 카드/저장소를 사용한다. |
| 다운로드가 너무 느림 | `--workers`를 4~10 범위에서 조절한다. 네트워크가 불안정하면 낮은 값이 더 안정적일 수 있다. |
| 웹 상세 화면에 여전히 사진이 없음 | 해당 천체가 POSS 서베이 이미지가 없을 수 있다. 캐시가 있으면 웹 서버는 로컬 파일을 우선 사용한다. |

<a id="mf_cache_download_ko--구현-참조"></a>
### 구현 참조

- 실행 스크립트: `scripts/warm_mfnavis_caches.py`
- 이미지 생성기: `python/MFNavis/gen_images.py`
- 웹 카탈로그 이미지 제공 경로: `python/MFNavis/web_catalogs.py`
- 캐시 위치 정의: `python/MFNavis/utils.py`


---

<a id="mf_input_controls_ko"></a>

## mf_input_controls_ko.md

<a id="mf_input_controls_ko--mf-pifinder-입력-조작법-키패드--키보드"></a>
## MF PiFinder 입력 조작법 (키패드 & 키보드)

기준: 현재 소스 트리, 2026-08-18 점검.

이 문서는 PiFinder UI가 키패드/키보드 입력을 처리하는 방식을 소스에서 정확히
정리한 참조 문서입니다. 모든 화면이 공유하는 전역 동작과, 특수하게 동작하는
화면을 함께 다루며, 알려진 불일치와 목표 모델(권장안)까지 담아 입력 처리를 하나의
합의된 스펙에 맞춰 수정할 수 있게 합니다.

관련 문서: `docs/mf_dev/mf_keyboard_mapping_ko.md`는 물리 키 -> PiFinder 입력 이벤트
매핑(어떤 키가 어떤 이벤트를 내는지)을 다룹니다. 이 문서는 그 이벤트로 UI가
무엇을 하는지를 다룹니다.

`mf_input_keymap_ko.md`는 향후 통일을 위한 **목표 설계**입니다. 현재 LCD에서 실제로
어떤 키가 동작하는지 확인할 때는 이 문서를 기준으로 합니다.

<a id="mf_input_controls_ko--1-입력-소스와-이벤트-인코딩"></a>
### 1. 입력 소스와 이벤트 인코딩

입력 소스는 세 가지이며, **모두 같은 이벤트를 내보내지 않습니다.**

| 소스 | 모듈 | 숫자 | 문자 | 비고 |
| --- | --- | --- | --- | --- |
| GPIO 키패드 (기기) | `keyboard_pi.py` | **press/release** (`NUMBER_PRESS_BASE=3000`, `RELEASE=3100`; `0`만 단발) | 없음 | `SQUARE` 홀드 + 키 = `ALT_*` |
| USB/블루투스 HID 키보드 (기기) | `keyboard_pi.py` (libinput) | **press/release** (`0`은 현재 이벤트가 전달되지 않음) | **press/release** (`TEXT_PRESS/RELEASE`) | Alt/Ctrl/Shift 조합 = `ALT_*` / `LNG_*` |
| 개발용 호스트 키보드 | `keyboard_local.py` (`--keyboard local`) | **단발 0-9** (`key_number`) | 매핑된 키만 | pyhotkey, 개발용 |

숫자 press/release는 1-9에만 적용됩니다(`_direction_number_key`). `0`은 GPIO
키패드에서 릴리스 시 단발 키코드 0으로 도착하고, HID 키보드에서는 매핑값 0이
"키 없음"과 겹쳐 현재 아무 이벤트도 큐에 들어가지 않습니다
(`keyboard_pi.py`의 `get_keyboard_key` 반환값 0은 버려짐).

**핵심 결과(대부분 불일치의 근원):** 실제 하드웨어(키패드 + USB/BT)에서는 숫자·
문자 키가 **press/release** 이벤트로 도착하지만, 개발용 키보드는 **단발 숫자**를
냅니다. 따라서 화면이 어떻게 반응하는지는 그 화면이 `key_number`를 구현했는지
`key_number_press`/`key_number_release`를 구현했는지에 달려 있습니다.

키 이벤트 코드(`keyboard_interface.py`): 기본키 `LEFT=20 UP=21 DOWN=22 RIGHT=24
PLUS=11 MINUS=12 SQUARE=13`; `ALT_*=101..110`; `LNG_*=200..204`; 숫자·문자는 위
press/release base; 단발 숫자는 `keycode < 10`.

<a id="mf_input_controls_ko--2-전역-조작-menu_manager--모든-화면-공통"></a>
### 2. 전역 조작 (menu_manager — 모든 화면 공통)

`main.py`가 큐를 읽어 `menu_manager.key_*`를 호출하고, menu_manager는 키를 직접
처리(help 오버레이, 마킹 메뉴, 뒤로/점프)하거나 활성 화면 `self.stack[-1].key_*`로
전달합니다.

| 입력 | 전역 동작 |
| --- | --- |
| `LEFT` | 뒤로: 현재 화면을 스택에서 pop (화면의 `key_left()`가 `False`를 반환하면 유지) |
| `LNG_LEFT` | 메뉴 최상위로 점프(루트로 리셋) |
| `LNG_RIGHT` | 가장 최근 객체의 Object Details로 점프 |
| `LNG_SQUARE` | 현재 화면의 **마킹 메뉴** 토글 |
| `SQUARE` | 마킹 메뉴가 열려 있으면 한 단계 뒤로/닫기, 아니면 화면으로 전달 |
| `UP`/`DOWN`/`RIGHT`/`PLUS`/`MINUS`/숫자/문자 | 활성 화면으로 전달 |
| help 오버레이 열림 | `UP`/`DOWN`은 도움말 이미지 페이지 이동; `LEFT`/`RIGHT`/`SQUARE`/숫자/문자는 닫기. `+`/`-`와 숫자·문자 release 이벤트는 활성 화면으로 전달되거나 무시됨 |
| `ALT_PLUS`/`ALT_MINUS` | 디스플레이 밝기 증가/감소 (전역) |
| `ALT_0` | 스크린샷 |
| `ALT_LEFT` | 카메라 이미지 저장 |
| `ALT_RIGHT` | 전체 디버그 덤프 저장(이미지 + solution + 상태) |

<a id="mf_input_controls_ko--마킹-메뉴-모델-marking_menuspy"></a>
#### 마킹 메뉴 모델 (`marking_menus.py`)

- `LNG_SQUARE`로 열림, 정지된 스크린샷 위에 4분할 파이로 렌더링.
- 네 개의 `MarkingMenuOption`(`up` 기본 `HELP`, `down`, `left`, `right`)을 가짐.
  열려 있는 동안 `LEFT`/`UP`/`DOWN`/`RIGHT`가 해당 옵션을 선택하고, `SQUARE`는 한
  단계 뒤로(스택이 비면 닫힘).
- 옵션은 중첩 마킹 메뉴 열기, HELP 표시, 라벨 메뉴로 `menu_jump`(예:
  `filter_options`, `shutdown`, `camera_gain`), 콜백 실행 중 하나를 함.

<a id="mf_input_controls_ko--죽은미처리-입력-현재-어디서도-동작-없음"></a>
#### 죽은/미처리 입력 (현재 어디서도 동작 없음)

- `LNG_UP` / `LNG_DOWN` (200/201 발생) — `main.py`가 디스패치하지 않고
  `menu_manager.key_long_up/down`은 `pass`. 그 결과
  `UIObjectList.key_long_up/key_long_down`은 도달 불가 죽은 코드.
- `ALT_UP` / `ALT_DOWN` / `ALT_SQUARE` — 키보드가 내보내지만 `main.py`가 처리하지
  않고 화면으로도 전달하지 않음.

<a id="mf_input_controls_ko--3-lcd-페이지별-키맵-적용-범위"></a>
### 3. LCD 페이지별 키맵 적용 범위

모든 LCD 페이지가 같은 키맵을 쓰지는 않습니다. 먼저 §2의 전역 키는 모든 페이지에
공통이고, 그 다음에는 아래 트리처럼 클래스별 공통 맵 또는 화면 고유 맵이 적용됩니다.

```text
LCD 키 입력
├─ 전역 처리 (모든 페이지)
│  ├─ LEFT / LNG_LEFT / LNG_RIGHT / LNG_SQUARE
│  └─ ALT_+ / ALT_- / ALT_0 / ALT_LEFT / ALT_RIGHT
└─ 활성 LCD 페이지
   ├─ 공통 숫자·문자 마운트 맵: GuideKeyMixin
   │  ├─ 일반 UITextMenu, UIObsList, UILocationList, UIEquipment
   │  ├─ UIPreview, UIStatus, UIGPSStatus, UIGPSTimeSyncStatus, UIIndiStatus
   │  └─ Mount Control ON → §7 마운트 맵 / OFF → 숫자·문자 무효
   │     (화살표·SQUARE·+/-는 각 페이지 고유 동작)
   ├─ 기본 UIModule 맵: 고유 핸들러가 없는 보조 페이지
   │  └─ LEFT=뒤로, SQUARE=표시 모드 순환, 나머지는 무효
   └─ 화면 고유 맵
      ├─ 객체: UIObjectList / UIObjectDetails
      ├─ 입력: UITextEntry / UIRADecEntry / Date·Time·Location·값 입력
      ├─ INDI: UIIndiInit / UIIndiGuide / UIIndiMultiPointAlign
      ├─ 정렬: UIAlign / UIAlignDaytime / UIPolarAlign
      └─ 정보·도구: UIChart / UISQM / UILog / UIConsole / UISQMCalibration
```

즉, `GuideKeyMixin`을 상속했다는 사실만으로 모든 키가 같아지는 것은 아닙니다.
믹스인은 **숫자·문자 키만** 공통 마운트 맵으로 처리하며, Object List처럼 그 숫자·문자
처리도 재정의할 수 있습니다. 화살표, `SQUARE`, `+`, `-`는 항상 해당 LCD 페이지의
핸들러가 우선합니다.

<a id="mf_input_controls_ko--공통-맵에서-벗어나는-lcd-페이지"></a>
#### 공통 맵에서 벗어나는 LCD 페이지

| 페이지/그룹 | 공통 맵과 다른 키 정의 |
| --- | --- |
| `UIObjectList` | 숫자=카탈로그 순번 점프, 문자=Name Search 시작. 마운트 조그로 보내지 않음 |
| `UIObjectDetails` | 자체 마운트 맵. `5`=현재 객체 GoTo, `7`=Sync, `2/4/6/8`=방향 이동; `+/-`=FOV 또는 설명 스크롤 |
| `UITextEntry` | 숫자=T9/멀티탭 입력, 문자=직접 텍스트, `+`=공백, `-`=삭제 |
| 좌표·값 입력 (`UIRADecEntry`, `UIDateEntry`, `UITimeEntry`, `UILocationEntry`, `UIIndiBacklash`, `UISQMSweep`) | 숫자가 값 입력에 우선하며 마운트 조그를 하지 않음 |
| 전용 INDI (`UIIndiInit`, `UIIndiGuide`, `UIIndiMultiPointAlign`) | 연결/정렬 단계와 수동 조그를 화면 상태별로 정의. 일반 공통 맵과 동일하다고 가정하지 않음 |
| 정렬 (`UIAlign`, `UIAlignDaytime`, `UIPolarAlign`) | 화살표·숫자·`SQUARE`가 정렬 마법사 단계/별 선택/취소에 사용 |
| 정보/도구 (`UIChart`, `UISQM`, `UILog`, `UIConsole`, `UISQMCalibration`) | 확대·스크롤·등급·개발/보정 기능처럼 화면 콘텐츠 키가 우선 |

이 트리는 "어느 화면에서 공통 키맵을 기대할 수 있는가"를 위한 인덱스입니다. 실제
키별 결과는 §5(표준 메뉴), §6(특수 화면), §7(공통 마운트 맵)을 함께 확인합니다.

<a id="mf_input_controls_ko--4-기본-화면-기본값-uimodule"></a>
### 4. 기본 화면 기본값 (`UIModule`)

화면이 재정의하지 않으면:

| 입력 | 기본값 |
| --- | --- |
| `LEFT` | `True` 반환 -> 화면 pop(뒤로) |
| `RIGHT` / `UP` / `DOWN` | 동작 없음 |
| `SQUARE` | `cycle_display_mode()` (화면 표시 모드 순환) |
| `PLUS` / `MINUS` / 숫자 / 문자 | 동작 없음 |
| 숫자 **press** | `key_number()`로 폴백(탭이 개별 핸들러를 실행); 숫자 **release** = 동작 없음 |

<a id="mf_input_controls_ko--5-표준-메뉴--uitextmenu-object-list-예외"></a>
### 5. 표준 메뉴 — `UITextMenu` (Object List 예외)

`UITextMenu`는 **`GuideKeyMixin`**(§7)을 상속하므로, 표준 메뉴에서 숫자·문자
키는 **마운트 제어가 켜져 있을 때** INDI 마운트 제어로 가로채이고(숫자=공통 마운트
맵, 문자=방향 조그), 그 외에는 동작이 없습니다. 믹스인은 `+`/`-`를 재정의하지
않으므로 표준 메뉴에서 `+`/`-`는 항상 무효입니다.

| 입력 | 동작 |
| --- | --- |
| `UP` / `DOWN` | 하이라이트 스크롤 (`menu_scroll`) |
| `RIGHT` | 선택: 항목 `callback` 실행, 또는 서브메뉴 `class` 진입, 또는 `config_option` 값 설정(아래), 이후 메뉴 `post_callback` |
| `LEFT` | 뒤로(pop) |
| `SQUARE` | `cycle_display_mode` (일반 메뉴에서는 보통 무효) |
| 숫자 / 문자 | **GuideKeyMixin** -> 마운트 제어(마운트 ON: 숫자=공통 마운트 맵, 문자=방향 조그) 또는 무효 |
| `+` / `-` | 무효 (믹스인이 재정의하지 않음) |

config-option 메뉴(`RIGHT`):
- `single`: 값 하나 설정. `filter.*` 옵션은 값이 바뀌면 상위 메뉴로 자동 복귀.
- `multi`: 항목을 선택 집합에 토글; `Select All` / `Select None`은 일괄 토글.

<a id="mf_input_controls_ko--리스트-파생"></a>
#### 리스트 파생

- **`UIObjectList`**: `RIGHT`는 하이라이트된 객체의 Object Details를 엶; `SQUARE`는
  표시 모드 `LOCATE -> NAME -> INFO` 순환; **숫자는 카탈로그 시퀀스를 입력해
  점프**(예: 45 -> M45, `key_number`). 정렬·필터는 마킹 메뉴(`Sort` 중첩 MM,
  `Filter` -> `filter_options`).
- **`UIObsList`**: `RIGHT`는 폴더로 진입하거나 `.skylist`를 로드해 객체 목록으로
  엶; `LEFT` 뒤로.
- **`UILocationList`**: `RIGHT`는 위치별 액션 메뉴(Load / Delete / Rename)를 엶;
  `UP`/`DOWN`으로 이동; `LEFT`는 액션 메뉴 닫기 또는 뒤로.
- **`UIEquipment`** (`GuideKeyMixin` + `UIModule`): `UP`/`DOWN`으로 망원경/아이피스
  행 전환; `RIGHT`로 해당 선택 메뉴 열기.

<a id="mf_input_controls_ko--6-특수-키-동작-화면"></a>
### 6. 특수 키 동작 화면

<a id="mf_input_controls_ko--object-details--uiobjectdetails-커스텀-guidekeymixin-아님"></a>
#### Object Details — `UIObjectDetails` (커스텀, GuideKeyMixin 아님)

| 입력 | 동작 |
| --- | --- |
| `UP` / `DOWN` | 목록의 이전/다음 객체 |
| `LEFT` | 뒤로(최근 목록에 추가) |
| `RIGHT` | **Log** 화면 열기(pointing solution 필요) |
| `SQUARE` | 표시 모드 순환: LOCATE / POSS / DESC / Contrast |
| `PLUS` / `MINUS` | 아이피스 시야(FOV) 순환(DESC 모드에서는 설명 스크롤) — 마운트와 무관 |
| 숫자 **탭** (`key_number`) | 공통 마운트 맵: 2/4/6/8=남/서/동/북 한 번 이동, 5=**타겟 GoTo**, 7=**Sync**, 0=정지, 9/3=슬루 속도 +/- (1 미사용) |
| 숫자 **press/release** (`key_number_press`) | 마운트 ON: 2/4/6/8 **홀드 이동**(떼면 정지); 5=GoTo·7=Sync·0=정지·9/3=슬루 속도는 개별 명령 |
| 문자 (HID) | 8방향 홀드 이동 가이드(대각 포함, q/w/e/a/s/d/z/x/c, s=정지) |

<a id="mf_input_controls_ko--텍스트--숫자-입력"></a>
#### 텍스트 / 숫자 입력

- **`UITextEntry`**: 멀티탭 또는 T9 텍스트 입력. 숫자키가 글자를 순환(멀티탭)하거나
  숫자를 입력(T9/검색). `SQUARE` 글자/기호 세트 토글; `PLUS` 공백 삽입; `MINUS`
  삭제; 길게 `MINUS` 전체 삭제; `LEFT` 확정 또는 뒤로; `RIGHT` 검색 결과 표시;
  HID 문자는 바로 추가.
- **`UIDateEntry`** (위치/GPS 고정 필요): 숫자가 yyyy/mm/dd 칸을 채움(자동 진행);
  `MINUS` 삭제 / 이전 칸; `RIGHT` 진행 / 확정; `LEFT` 이전 칸 또는 취소.
- **`UILocationEntry`**: 숫자가 위도/경도/고도 칸을 채움; `MINUS` 삭제 / 이전 칸;
  `PLUS` 부호 토글(N/S, E/W); `RIGHT` 위도->경도->고도 흐름 진행; `LEFT` 이전 칸
  또는 취소.
- **`UIRADecEntry`**: 숫자가 RA/Dec/EPOCH의 현재 필드를 채우며, `UP`/`DOWN`은 필드
  이동, `MINUS`는 삭제, `PLUS`는 Dec 부호 또는 epoch 전환, `SQUARE`는 좌표 형식 순환,
  `RIGHT`는 대상 생성, `LEFT`는 취소/이전 필드다.

<a id="mf_input_controls_ko--indi-마운트-화면-indipy"></a>
#### INDI 마운트 화면 (`indi.py`)

- **`UIIndiInit`**: 숫자로 개별 1회 명령 — 1=Init 2=위치/시간 Sync 3=Park 4=홈
  설정 5=홈 복귀 6=Unpark 7=Park 설정 8=드라이버 재시작 9=마운트 재부팅;
  `SQUARE` = Init.
- **`UIIndiBacklash`**: 숫자로 선택 축의 백래시 값 입력(0-999, `0`은 입력 초기화);
  `PLUS`는 RA 축, `MINUS`는 DE 축 선택; `RIGHT` 자동 백래시 실행; `SQUARE` 두 축 저장.
- **`UIIndiGuide`**: `0`은 가이드 보정 on/off 토글. `5`와 `1`/`7`은 무효.
  방향 숫자 `2/4/6/8`과 문자는 **press/홀드 이동** 가이드(문자는 대각 포함;
  떼면 정지); 슬루 속도는 `9`(증가)/`3`(감소), 키보드 `,`/`.`도 각각 감소/증가;
  `PLUS`/`MINUS`는 무효; `SQUARE`
  현재 solve로 마운트 Sync.
- **`UIIndiMultiPointAlign`** (`UIIndiGuide` 확장): 단계별 마법사. POINTS 단계에서
  `1-9` 또는 `+`/`-`로 정렬점 수를 정하고, MODE 단계에서 `1`=수동/`2`=자동을
  선택한다. ADJUST 단계에서는 방향 숫자·문자가 홀드 이동 조그이고 `0`은 취소,
  `9`/`3`은 속도 조절이다. `UP`/`DOWN`, `LEFT`/`RIGHT`, `SQUARE`가 마법사 단계
  전환을 담당.

<a id="mf_input_controls_ko--정렬-화면"></a>
#### 정렬 화면

- **`UIAlign`**: `SQUARE` 정렬 모드 토글(나갈 때 정렬 저장); 정렬 모드에서
  `UP`/`DOWN`/`RIGHT`/`LEFT`가 별 선택 이동; `PLUS`/`MINUS` 확대/축소; `1` 레티클
  리셋, `0` 취소(정렬 모드에서만).
- **`UIAlignDaytime`**: `SQUARE` 시작 / 저장; 사분면 숫자 `7 9 1 3`으로 영역 선택;
  화살표는 정밀 모드 전환 및 1px 이동; `0` 취소; `PLUS`/`MINUS` 노출 +/-.
- **`UIPolarAlign`**: `SQUARE` 마법사 진행; `MINUS` 취소/뒤로; `0` 계산(AIM에서
  solve 2개 이상일 때).

<a id="mf_input_controls_ko--정보--유틸-화면"></a>
#### 정보 / 유틸 화면

- **`UILog`**: `RIGHT`는 현재 항목 실행(로그 & 종료 / 평점 순환 / 서브메뉴 /
  아이피스); `UP`/`DOWN` 항목 이동; 숫자는 현재 별점(관측성/매력도) 설정.
- **`UIChart`**: `PLUS`/`MINUS` 확대/축소; `SQUARE` 카메라 시야로 FOV 리셋.
- **`UIPreview`** (`GuideKeyMixin`): `PLUS`/`MINUS`는 **확대/축소**(믹스인은
  `+`/`-`를 건드리지 않음), `SQUARE`는 포커스/HUD 오버레이 토글; 숫자·문자는 마운트
  ON이면 여전히 마운트 제어(숫자=공통 마운트 맵, 문자=방향 조그).
- **`UIConsole`**: `UP`/`DOWN` 로그 스크롤; 숫자는 개발 단축키(0=카메라 디버그
  토글, 아무 숫자나 고정 디버그 시각 설정).
- **수동 상태 화면** (`UIGPSStatus`, `UIGPSTimeSyncStatus`, `UIIndiStatus`): 순수
  `GuideKeyMixin` — 화살표는 로컬 동작, 숫자(공통 마운트 맵)·문자(방향 조그)는 마운트
  ON이면 마운트 제어; `+`/`-`는 무효.

<a id="mf_input_controls_ko--7-guidekeymixin--공통-페이지의-숫자문자-키"></a>
### 7. GuideKeyMixin — 공통 페이지의 숫자·문자 키

`GuideKeyMixin`(`base.py`)은 `key_number`/`key_number_press`/`key_number_release`
(-> 공통 마운트 맵 `_mount_key*`)와 `key_text`/`key_text_press`/`key_text_release`
(-> 방향 조그 `_guide_key_text*`)를 재정의합니다. **`key_plus`/`key_minus`는
재정의하지 않습니다.** `UITextMenu`(따라서 모든 표준 메뉴·리스트), `UIEquipment`,
`UIPreview`, 수동 상태 화면이 상속합니다.

- 숫자 -> 공통 마운트 맵: 2/4/6/8 누르는 동안 남/서/동/북 이동(탭=한 번), 0=정지,
  5=GoTo(타겟이 선택된 화면만), 7=Sync, 9/3=슬루 속도 +/-, 1 미사용.
- 문자 q/w/e/a/s/d/z/x/c -> 8방향 이동(대각 포함), s=정지.
- `+`/`-`는 믹스인이 건드리지 않음(화면 고유 동작 또는 무효).
- 모두 마운트 제어 큐(`_mount_control_queue`/`_guide_mount_queue`)를 거치며,
  `mount_control`이 꺼져 있으면 `None`이라 키는 **무효**. 화살표·`SQUARE`·`+`·`-`는
  믹스인이 건드리지 않음.

믹스인이 `key_number_press`를 공통 마운트 맵으로 보내므로(**`key_number`로 폴백하지
않음**), 자체 `key_number` 동작이 물리 키패드/HID(press/release)에서도 동작해야 하는
서브클래스(예: `UIObjectList` 카탈로그 점프, `UIObjectDetails` GoTo/Sync)는
`key_number_press`/`key_number_release`도 함께 재정의해야 하며, 실제로 그렇게 되어
있습니다.

<a id="mf_input_controls_ko--8-알려진-불일치-수정-후보"></a>
### 8. 알려진 불일치 (수정 후보)

> 2026-07-13 갱신: 이전에 이 목록에 있던 세 항목은 소스에서 해소됨 —
> ① Object Details 개별 마운트 명령이 하드웨어에서 가려지던 문제와
> ② Object List 카탈로그 숫자 점프가 키패드에서 죽던 문제는
> `UIObjectDetails`/`UIObjectList`가 `key_number_press`/`key_number_release`를
> 재정의해 탭이 기기에서도 동작하도록 고쳐졌고,
> ③ `UIIndiBacklash`의 `PLUS`/`MINUS`는 `PLUS`=RA·`MINUS`=DE로 분리됐다.

남아 있는 불일치:

1. **표준 메뉴가 마운트 조이스틱이 됨.** 마운트 ON이면 모든 `UITextMenu`(전 메뉴·
   리스트)의 숫자·문자가 마운트 제어로 바뀌어(믹스인은 `+`/`-`는 건드리지 않음),
   탐색 중 의도치 않게 마운트가 움직이기 쉬움.
2. **개발용 키보드와 기기가 근본적으로 다름**(단발 숫자 vs press/release), 그래서
   `--keyboard local` 테스트와 실제 하드웨어의 동작이 갈림.
3. **죽은 키**: `LNG_UP`/`LNG_DOWN`, `ALT_UP`/`ALT_DOWN`/`ALT_SQUARE`가 발생하지만
   디스패치되지 않음. `LNG_MINUS`(MINUS 길게)는 `keyboard_interface.py`에 키코드가
   없어 어떤 드라이버도 발생시키지 않으므로, `textentry.py`의
   `key_long_minus`(전체 삭제)는 현재 도달 불가.

<a id="mf_input_controls_ko--9-제안-목표-모델-논의용"></a>
### 9. 제안 목표 모델 (논의용)

목표: 키패드와 키보드에서 동일하게 예측 가능한 하나의 체계로, 각 화면이 분기 로직을
재구현하지 않고도 개별 동작과 홀드 이동 가이드를 모두 유지.

- **디스패치 계층에 탭 vs 홀드 레이어 도입**(main.py / 키보드 드라이버): 숫자·문자
  press 시 타이머 시작; 빠른 릴리스(~400 ms 미만)는 단발 **탭**(`key_number(n)` /
  `key_text(c)`)을, 홀드 임계 초과는 **홀드 시작**(`key_number_press`)과 릴리스 시
  **홀드 종료**(`key_number_release`)를 발생. 그러면 키패드와 키보드가 같은 탭/홀드
  이벤트를 공급하고, 개발용 키보드의 단발 숫자도 탭으로 통일됨.
- **하나의 규약 정의:** 탭 = 개별 동작(GoTo/Sync/선택/점프/입력), 홀드 = 마운트
  가이드 / 자동 반복. `GuideKeyMixin`은 홀드 -> 가이드로 매핑하고 탭은 화면의 개별
  핸들러에 맡김(그러면 Object List 점프와 Object Details GoTo가 기기에서도 동작).
- **마운트 가이드를 게이트**해서 일반 탐색 메뉴에서는 화면이 opt-in하지 않는 한
  숫자를 가로채지 않게 함(예: Object Details / Preview / 상태 화면만 가이드, 일반
  메뉴는 아님).
- **죽은 키 정리** — `LNG_UP/DOWN`, `ALT_UP/DOWN`을 실제 동작에 연결하거나 매핑에서
  제거.
- **`UIIndiBacklash`** `PLUS`/`MINUS`를 구분(예: +/-로 값 조정, 또는 하나는 축
  토글·다른 하나는 다른 유용한 동작).
- **`mf_keyboard_mapping`을 최종 동작과 재동기화**.

정확한 탭 임계값과 어떤 화면이 가이드에 opt-in할지 결정한 뒤 이 문서에 맞춰
구현하면 됩니다.


---

<a id="mf_input_keymap_ko"></a>

## mf_input_keymap_ko.md

<a id="mf_input_keymap_ko--mf-pifinder-키패드-우선-입력-체계-그룹별-키맵"></a>
## MF PiFinder 키패드 우선 입력 체계 (그룹별 키맵)

기준: `mf_pifinder` 브랜치, 2026-07-11.

이 문서는 **목표** 입력 설계입니다. 목표는 키패드를 기준으로 하되 **기존 동작과
부드럽게 합쳐지는** 체계입니다 — 현재의 키패드 관습을 보존하고, 입력이 충돌하는
지점만 해소합니다. UI 페이지를 그룹으로 묶고 그룹별 키 매핑을 정의합니다.

*현재* 동작과 이 체계가 해소하는 충돌은 `docs/mf_dev/mf_input_controls_ko.md`를 참고하세요.

<a id="mf_input_keymap_ko--설계-원칙"></a>
### 설계 원칙

1. **키패드 우선.** 모든 동작은 물리 키패드만으로 도달 가능(화살표, `SQUARE`, `+`,
   `-`, `0-9`, 길게 누르기). USB/블루투스 키보드는 문자 키를 더하는 액세서리이며
   키패드가 못 하는 동작을 새로 열어주지 않음.
2. **보존 후 조정.** 기존 동작은 충돌하지 않는 한 그대로 유지. 해당 그룹이 자기
   목적으로 꼭 필요한 곳(객체 선택, 텍스트, 숫자 입력)에서만 키 의미를 바꿈. 변경을
   작게, 느낌을 연속적으로.
3. **INDI 조그가 기본으로 유지** — 숫자·문자를 달리 쓸 일이 없는 화면(일반 메뉴
   [마운트 ON], INDI 화면, Object Details, 상태 화면). 이는 기존 `GuideKeyMixin`
   동작이며 그대로 보존하므로, 마운트를 제어하는 곳에서는 **알파벳이 계속 INDI 수동
   조그를 구동**함.
4. **입력 그룹은 그 기본을 재정의**해 숫자·문자가 제 역할을 하게 함: 객체 선택
   (카탈로그 점프 / 이름 검색), 텍스트 검색(T9 + 영문), 숫자 입력(숫자). 그래서
   **이름을 입력하는 곳에서는 영문 입력이 충돌 없이 동작**함.
5. **전역 키는 어디서나 동일**(아래).

<a id="mf_input_keymap_ko--전역-키-모든-그룹--변경-없음"></a>
### 전역 키 (모든 그룹 — 변경 없음)

| 키 | 동작 |
| --- | --- |
| `LEFT` | 뒤로(현재 화면 pop) |
| `LNG_LEFT` | 홈(메뉴 루트) |
| `LNG_RIGHT` | 가장 최근 객체의 Object Details로 점프 |
| `LNG_SQUARE` | 화면 마킹 메뉴 열기/닫기 |
| `ALT_+` / `ALT_-` | 밝기 증가/감소 |
| `ALT_0` | 스크린샷 |
| `ALT_LEFT` / `ALT_RIGHT` | 이미지 저장 / 디버그 덤프 |

마킹 메뉴가 열려 있으면 `SQUARE`는 한 단계 닫기, 그 외에는 그룹별 콘텐츠 키.

<a id="mf_input_keymap_ko--마운트를-구동하는-숫자-키--공통-맵"></a>
### 마운트를 구동하는 숫자 키 — 공통 맵

**숫자 키**가 INDI 마운트를 제어하는 모든 곳(Object Details, 마운트 ON 일반 메뉴,
상태 화면)에서 하나의 공통 매핑을 사용합니다:

| 키 | 마운트 동작 |
| --- | --- |
| `0` | 이동·마운트 추적·GoTo/Guide 자동 보정 정지 |
| `2` | 남으로 이동 — **누르는 동안** |
| `4` | 서로 이동 — **누르는 동안** |
| `5` | GoTo — **객체가 선택된 화면에서만**(Object Details); 자동 보정 재활성화 |
| `6` | 동으로 이동 — **누르는 동안** |
| `7` | 현재 solve로 Sync |
| `8` | 북으로 이동 — **누르는 동안** |
| `9` | 슬루 속도 증가 |
| `3` | 슬루 속도 감소 |
| `1` | GoTo Type 순환: Off → INDI Mount → PiFinder |

기본 방향 키(`2`/`4`/`6`/`8`)는 **누르는 동안 마운트를 이동**합니다(누르면 시작,
떼면 정지) — 누른 만큼 정확히 이동합니다. `0`(정지)·`7`(Sync)은 개별 1회 명령이며,
`5`(GoTo)는 **객체가 선택된 화면(Object Details)에서만** 동작합니다 — 일반 메뉴·상태
화면엔 타겟이 없으므로 `5`는 미사용입니다. **스텝 크기 설정 없음**(제거), **`1`의
Init/Sync 없음**(제거 — 기동 시 자동 init/sync되며, 실수로 `1`을 누르면 불필요하게
연결이 재시작됨). `0`(정지)은 마운트 추적을 명시적으로 끄고, 누른 방향키의
keepalive와 대기 중인 재타깃·정밀 이동을 취소한다. GoTo/Guide **자동 보정**(트래킹 가이드)도 멈추고 그
타겟을 지워서 즉시 재보정되지 않게 합니다 — 이후 `5`(GoTo)나 새 트래킹 시작 시 다시
활성화됩니다. 슬루 속도(빠르기)는 `9`(증가) / `3`(감소)이며 **`+`/`-`가 아닙니다** —
`+`/`-`는 각 화면 고유의 콘텐츠 동작을 유지합니다. 연속 조그는 키보드 문자
(`q w e / a s d / z x c`, `s` = 정지)에도 있습니다.

`1`은 새 GoTo Type을 적용한 뒤에만 팝업을 표시하므로, 팝업에는 항상 선택 완료된
타입이 보입니다. 이 session 전용 설정은 GoTo를 끄거나, INDI mount로 전달하거나, PiFinder의
GoTo 절차로 실행할지를 결정합니다. 물리 키패드, 외부 키보드, Web Remote의 `1`
버튼은 모두 같은 토글을 사용하며 PiFinder 화면에 같은 완료 팝업을 표시하고
`config.json`을 쓰지 않습니다. Settings 메뉴에서 GoTo Type을 선택하면 persistent
설정을 저장하고 session 전용 선택을 대체합니다.
이 단축키는 공통 마운트 제어 키맵을 쓰는 화면에서만 적용됩니다. 숫자·좌표·날짜/시간·
위치·텍스트 입력 화면에서는 `1`이 일반 입력값이며 GoTo Type을 변경하지 않습니다.

상단 상태바의 GoTo 표시는 `Off`에서는 숨기고, `INDI Mount`에서는 `I`,
`PiFinder`에서는 `P`를 표시합니다. INDI driver가 연결되면 굵은 글자, 연결 중·상태
오래됨·오류 상태이면 얇은 글자로 표시합니다.

<a id="mf_input_keymap_ko--페이지-그룹과-공통-맵-적용-트리"></a>
### 페이지 그룹과 공통 맵 적용 트리

이 문서의 그룹은 키를 똑같이 처리하는 화면의 목록이 아닙니다. G1/G7 일부처럼
`GuideKeyMixin` 공통 맵을 쓰는 페이지가 있고, 같은 그룹 안에서도 Object List처럼
화면 고유 맵으로 숫자·문자를 재정의하는 페이지가 있습니다. 현재 구현의 정확한
적용 범위는 `mf_input_controls_ko.md` §3을 우선합니다.

```text
PiFinder LCD 페이지
├─ G1 메뉴·내비게이션
│  ├─ 공통 숫자·문자 맵: UITextMenu, UIObsList, UILocationList, UIEquipment
│  │  └─ Mount Control ON → 공통 마운트 맵 / OFF → 무효
│  └─ 화살표·SQUARE·+/- → 각 메뉴의 고유 내비게이션 동작
├─ G2 객체
│  ├─ UIObjectList → 예외: 숫자=순번 점프, 문자=이름 검색
│  └─ UIObjectDetails → 자체 마운트 맵 + FOV/설명 스크롤
├─ G3 텍스트/이름 검색 → UITextEntry의 텍스트 입력 맵
├─ G4 숫자/좌표 입력 → UIRADecEntry, UIDateEntry, UITimeEntry,
│                       UILocationEntry, UIIndiBacklash 등의 값 입력 맵
├─ G5 INDI 수동 조작 → UIIndiInit / UIIndiGuide / MultiPoint 단계별 맵
├─ G6 정렬 마법사 → UIAlign / UIAlignDaytime / UIPolarAlign 고유 맵
└─ G7 정보·수동표시
   ├─ 공통 숫자·문자 맵: UIPreview, UIStatus, GPS/INDI Status
   └─ 고유 콘텐츠 맵: UIChart, UISQM, UILog, UIConsole 등
```

트리의 **공통 숫자·문자 맵**은 이 문서의 "마운트를 구동하는 숫자 키 — 공통 맵"을
뜻합니다. 화살표, `SQUARE`, `+`, `-`는 그 공통 맵에 포함되지 않으며 항상 각 LCD
페이지의 정의를 따릅니다.

**객체 선택은 일반 내비게이션(G1)에서 분리된 독립 그룹(G2)입니다.** 별을 찾는 것은
탐색/점프/검색/상세 열기/마운트 구동이 얽힌 별개의 상호작용이라 자체 규칙을 가짐.

---

<a id="mf_input_keymap_ko--g1--메뉴--내비게이션"></a>
### G1 — 메뉴 & 내비게이션

순수 내비게이션. 숫자·문자 키의 INDI 조그 기본값을 포함해 현재 동작을 보존.

| 키 | 동작 |
| --- | --- |
| `UP` / `DOWN` | 하이라이트 이동 |
| `RIGHT` | 선택 / 서브메뉴 진입 / config 값 설정 |
| `LEFT` | 뒤로 |
| `SQUARE` | 표시 모드 순환(일반 메뉴에서는 보통 무효) |
| `0-9` | 마운트 ON이면 **공통 마운트 맵**(2/4/6/8 누른 동안 이동, 0=정지·7=Sync·9/3=슬루 속도; 5/GoTo는 선택 객체 없어 미사용), 아니면 무효 |
| 문자 | 마운트 ON이면 INDI 방향 조그, 아니면 무효 |

메뉴는 지금 그대로 동작하되, 숫자 키만 8방향 방향 가이드 대신 공통 마운트 맵
(누른 동안 이동 방향키 + 0/5/7 + 9/3 슬루 속도)을 사용.

<a id="mf_input_keymap_ko--g2--객체-선택--상세"></a>
### G2 — 객체 (선택 + 상세)

객체 선택은 G1에서 분리. 화면 둘, 역할 둘.

<a id="mf_input_keymap_ko--객체-리스트-선택"></a>
#### 객체 리스트 (선택)

| 키 | 동작 |
| --- | --- |
| `UP` / `DOWN` | 리스트 스크롤 |
| `RIGHT` | 하이라이트된 객체의 Object Details 열기 |
| `LEFT` | 뒤로 |
| `SQUARE` | 리스트 보기 LOCATE -> NAME -> INFO 순환 |
| `0-9` | **카탈로그 시퀀스 점프**(예: `4` `5` -> M45) — 키패드에서 동작 |
| 문자(키보드) | **이름 검색 시작**(입력한 글자로 G3에 넘김) |

조정: 여기서 숫자·문자 키는 *객체 찾기*를 의미하지 마운트 조그가 아님. 그래서
객체 선택 리스트는 INDI 조그 기본값을 재정의함. 이로써 의도된 키패드 점프(현재는
가려짐)를 복원하고 영문 이름 검색을 제공.

<a id="mf_input_keymap_ko--객체-상세-보기--마운트"></a>
#### 객체 상세 (보기 + 마운트)

| 키 | 동작 |
| --- | --- |
| `UP` / `DOWN` | 이전 / 다음 객체 |
| `RIGHT` | Log 화면 열기 |
| `LEFT` | 뒤로 |
| `SQUARE` | 보기 순환: LOCATE / POSS / DESC / Contrast |
| `0-9` (키패드) | **공통 마운트 맵**: 2/4/6/8 = 남/서/동/북 **누른 동안 이동**, 5=**GoTo** 이 객체, 7=**Sync**, 0=정지, 9/3=슬루 속도 증가/감소 (1 미사용) |
| 문자(키보드) | **연속 INDI 조그**(`q w e / a s d / z x c`, `s` = 정지) |
| `+` / `-` | 아이피스 FOV / 설명 스크롤 (마운트와 무관) |

조정: 키패드에서 숫자 키는 **문서화된 개별 명령**을 실행(그래서 GoTo/Sync/스텝이
기기에서 실제로 동작 — 현재는 조그에 가려짐). 연속 홀드 이동 조그는 키보드 문자와
전용 INDI 수동 화면(G5)으로 유지. 알파벳 조그를 깨지 않으면서 Object Details에서
마운트를 제어 가능하게 함.

> 선택 확장(키패드 숫자에서도 홀드 조그를 원할 때만): 탭-vs-홀드 레이어를 추가해
> 같은 숫자에서 빠른 탭 = 개별 명령, 길게 홀드 = 연속 조그. 키패드 우선 기본에는
> 불필요.

<a id="mf_input_keymap_ko--g3--텍스트--이름-검색"></a>
### G3 — 텍스트 / 이름 검색

"필요한 곳의 영문 입력" 그룹. 키패드와 키보드 모두 텍스트를 생성하며, 어느 것도
마운트를 구동하지 않음.

| 키 | 동작 |
| --- | --- |
| `0-9` | 키패드 텍스트 입력(T9 / 멀티탭); 숫자 검색 모드에서는 숫자 그대로 |
| 문자(키보드) | 영문 직접 입력 |
| `SQUARE` | 글자 / 기호 세트 전환 |
| `+` / `-` | 공백 삽입 / 글자 삭제; `LNG_-` 전체 삭제 |
| `RIGHT` | 검색 결과 표시 |
| `LEFT` | 확정 / 뒤로 |

<a id="mf_input_keymap_ko--g4--숫자--좌표-입력"></a>
### G4 — 숫자 / 좌표 입력

| 키 | 동작 |
| --- | --- |
| `0-9` | 현재 칸에 숫자(가득 차면 자동 진행) |
| `-` | 삭제 / 이전 칸 |
| `+` | 부호 토글(N/S, E/W) 또는 다음 칸 |
| `RIGHT` / `LEFT` | 다음-확정 / 이전-취소 |
| 문자(키보드) | 무시 |

`UIIndiBacklash`는 여기서 값을 입력; `+`/`-` 축 토글 충돌은 별도 수정(§조정).

<a id="mf_input_keymap_ko--g5--indi-수동-조작"></a>
### G5 — INDI 수동 조작

전용 수동 구동 화면. `UIIndiGuide`와 `UIIndiMultiPointAlign`(ADJUST)도 이제
**다른 화면과 동일한 숫자 맵**을 따릅니다(2026-07-13에 숫자 키 대각 조그 제거 —
대각 이동은 키보드 문자로 유지). 시각적 키패드 오버레이, keepalive 이동, 화면별
화면별 `0` 명령은 그대로이며, `5`는 현재 가이드 화면에서 동작하지 않는다:

| 키 | 동작 |
| --- | --- |
| `2` `4` `6` `8` | 기본 방향 조그(press-hold, 떼면 정지) |
| `9` / `3` | 슬루 속도 증가 / 감소 |
| `0` | 가이드: 가이드 보정 토글; ADJUST: 취소 |
| `5` | 무효 |
| `1` `7` | 미사용 |
| 문자(키보드) | INDI 방향 조그 — 대각 포함(`q w e / a s d / z x c`, `s` = 정지) |
| `+` / `-` | POINTS 단계에서 정렬점 수 +/−; 그 외 단계에서는 무효 |
| `SQUARE` | 현재 solve로 Sync / 정렬(가이드) / 확정(ADJUST) |

`UIIndiInit`은 연결 관리용 개별 INDI 패널(숫자로 Init/Park/Home 등)을 유지하며
공통 맵 적용 대상이 아님. `UIIndiMultiPointAlign`의 POINTS 단계(`1-9` = 정렬
포인트 개수)도 결정에 따라 적용 범위에서 제외.

<a id="mf_input_keymap_ko--g6--정렬-마법사"></a>
### G6 — 정렬 마법사

키패드 구동, 화면별(유지):

- **`UIAlign`**: `SQUARE` 정렬 모드 토글+저장; 화살표 별 선택; `+`/`-` 확대/축소;
  `1` 레티클 리셋, `0` 취소.
- **`UIAlignDaytime`**: `SQUARE` 시작/저장; `7 9 1 3` 사분면 선택; 화살표 정밀 넛지;
  `0` 취소; `+`/`-` 노출.
- **`UIPolarAlign`**: `SQUARE` 진행; `-` 취소/뒤로; `0` 계산.

문자 무시; 숫자는 마법사 전용.

<a id="mf_input_keymap_ko--g7--정보--수동표시"></a>
### G7 — 정보 / 수동표시

- **`UIChart`**: `+`/`-` 확대/축소, `SQUARE` FOV 리셋.
- **`UIPreview`**: `+`/`-` 확대/축소, `SQUARE` 포커스 오버레이.
- **`UIConsole`**: `UP`/`DOWN` 스크롤.
- **`UILog`**: `RIGHT` 항목 실행, `UP`/`DOWN` 항목 변경, 숫자로 평점 설정.
- **상태 화면**(`UIGPSStatus`, `UIGPSTimeSyncStatus`, `UIIndiStatus`): 마운트 제어
  허용(텍스트 없음) — 숫자 키는 **공통 마운트 맵**(2/4/6/8 누른 동안 이동, 0=정지·
  7=Sync; 5/GoTo는 선택 객체 없어 미사용), 문자는 연속 조그 — 상태를 보며 마운트를
  구동하기 좋은 곳.

<a id="mf_input_keymap_ko--그룹별-요약"></a>
### 그룹별 요약

| 그룹 | 숫자 `0-9` | 문자(키보드) | INDI 조그 |
| --- | --- | --- | --- |
| G1 메뉴/내비 | 공통 마운트 맵(마운트 ON) / 없음 | 방향 조그 / 없음 | 기본 |
| G2 객체 리스트 | 카탈로그 시퀀스 점프 | 이름 검색 시작 | 아니오 |
| G2 객체 상세 | 공통 마운트 맵(누른 동안 이동 + 0/5/7 + 9/3 속도) | 연속 조그 | 예 |
| G3 텍스트/검색 | T9 / 멀티탭 텍스트 | 영문 텍스트 입력 | 아니오 |
| G4 숫자 입력 | 숫자 | 무시 | 아니오 |
| G5 INDI 수동 | 방향키 + 9/3 속도 + 화면별 0 (`5` 무효) | 방향 조그 | 예 |
| G6 정렬 | 마법사 전용 | 무시 | 아니오 |
| G7 정보/표시 | 평점 / 개발 / 없음 (상태: 공통 마운트 맵) | 무시(상태: 조그) | 상태만 |

마운트 접근이 되는 모든 곳(G1 마운트 ON 메뉴, G2 Object Details, G5 전용 컨트롤러,
G7 상태)은 공통 마운트 맵(2/4/6/8 누른 동안 남/서/동/북 이동, 0=정지 7=Sync
9/3=슬루 속도 증가/감소; 5=GoTo는 객체가 선택된 Object Details에서만; 1 미사용)을
사용하고, 대각을 포함한 연속 방향 조그는 키보드 문자에 있음.

<a id="mf_input_keymap_ko--조정-단계-작고-가산적--구현-대상"></a>
### 조정 단계 (작고 가산적 — 구현 대상)

기존 동작과 합쳐지는 범위 한정 변경이며, 통째로 걷어내는 것은 없음.

1. **객체 리스트**: 키패드에서 `0-9`가 카탈로그 시퀀스 점프를 하도록(현재는 INDI
   조그에 가려짐), 문자가 G3 이름 검색을 열도록. 범위: 객체 선택 리스트만.
2. **공통 마운트 숫자 키**(완료): *부수적* 마운트 접근(Object Details, 마운트 ON
   메뉴, 상태 화면)에서 방향키 2/4/6/8은 **누르는 동안** 마운트를 이동(누르면 시작,
   떼면 정지)하고, 0=정지 / 5=GoTo / 7=Sync는 개별 명령. 스텝 크기(3/9)와 Init/Sync(1)는
   **제거** — 누른 만큼 이동하고, 기동 시 이미 init/sync됨. `UIModule`의 공유
   `_mount_key` / `_mount_key_press` / `_mount_key_release`로 구현하고 `GuideKeyMixin`과
   `UIObjectDetails`가 사용.
3. **슬루 속도를 `9`/`3`으로**(2026-07-13 완료): 슬루 속도를 `+`/`-`에서 떼어
   공통 마운트 맵의 `9`(증가) / `3`(감소)에 배치하고 전체에 동일 적용 —
   `UIIndiGuide`·`UIIndiMultiPointAlign`(ADJUST) 포함. 이를 위해 두 화면의 숫자 키
   대각 조그(1/3/7/9)는 제거(대각은 키보드 문자로 유지). MultiPointAlign POINTS
   단계(`1-9` = 포인트 개수)는 적용 범위에서 제외. `+`/`-`는 이제 어디서나 화면
   고유 콘텐츠 동작(FOV, 스크롤, 확대)만 의미.
4. 마운트 화면에서 **연속 조그는 키보드 문자**(`q w e / a s d / z x c`)로 유지 —
   변경 없음.
5. `UIIndiBacklash` `+`/`-`(현재 둘 다 축 토글)를 서로 다른 동작으로 **수정**.
6. **선택**: G2 객체 상세에서 키패드 홀드 조그를 원하면 숫자 키에 탭-vs-홀드 레이어
   추가.
7. 구현 후 `docs/mf_keyboard_mapping_*`와 사용자 가이드 **재동기화**.

검토용 미결정: 일반 메뉴에 INDI 조그를 계속 둘지(또는 전용 "마운트 조그" 화면을
요구할지); 객체 리스트에서 이름 검색을 트리거하는 정확한 문자; 선택적 탭-vs-홀드
레이어 추가 여부.


---

<a id="mf_keyboard_mapping_ko"></a>

## mf_keyboard_mapping_ko.md

<a id="mf_keyboard_mapping_ko--mf_pifinder-키보드-매핑"></a>
## MF_PiFinder 키보드 매핑

이 문서는 `mf_pifinder` 브랜치의 USB/Bluetooth 키보드와 GPIO 키패드 입력
매핑을 간단히 정리한다.

<a id="mf_keyboard_mapping_ko--usbbluetooth-키보드"></a>
### USB/Bluetooth 키보드

| 키 | PiFinder 입력 |
| --- | --- |
| 방향키 | `LEFT`, `UP`, `DOWN`, `RIGHT` |
| Enter / Keypad Enter | `SQUARE` |
| Esc | `LEFT` |
| Backspace | `MINUS` |
| `=` / Keypad `+` | `PLUS` |
| `-` / Keypad `-` | `MINUS` |
| 숫자 `1-9` / Keypad 숫자 | 숫자 press/release |
| `0` / Keypad `0` | 현재 이벤트가 전달되지 않음 |
| Space | 공백 문자 |
| `a-z` | 영문 소문자 |
| `Shift + a-z` | 영문 대문자 |

<a id="mf_keyboard_mapping_ko--alt-조합"></a>
### Alt 조합

| 키 | PiFinder 입력 |
| --- | --- |
| `Alt + 방향키` | `ALT_LEFT`, `ALT_UP`, `ALT_DOWN`, `ALT_RIGHT` |
| `Alt + =` / `Alt + Keypad +` | `ALT_PLUS` |
| `Alt + -` / `Alt + Keypad -` | `ALT_MINUS` |
| `Alt + 0` / `Alt + Keypad 0` | `ALT_0` |
| `Alt + Enter` / `Alt + Keypad Enter` | `ALT_SQUARE` |

<a id="mf_keyboard_mapping_ko--길게-누르기"></a>
### 길게 누르기

1초 이상 누르면 long key로 처리된다.

| 키 | PiFinder 입력 |
| --- | --- |
| 길게 `Left` | `LNG_LEFT` |
| 길게 `Right` | `LNG_RIGHT` |
| 길게 `Enter` / `Keypad Enter` | `LNG_SQUARE` |
| 길게 `Up` | `UP` 반복 |
| 길게 `Down` | `DOWN` 반복 |

호환용으로 `Shift` 또는 `Ctrl`과 함께 `Left`, `Up`, `Down`, `Right`,
`Enter`를 누르면 각각 `LNG_LEFT`, `LNG_UP`, `LNG_DOWN`, `LNG_RIGHT`,
`LNG_SQUARE`로 처리된다.

<a id="mf_keyboard_mapping_ko--gpio-키패드"></a>
### GPIO 키패드

| 키패드 | PiFinder 입력 |
| --- | --- |
| 숫자 키 | 숫자 `0-9` |
| `+` | `PLUS` |
| `-` | `MINUS` |
| 사각/확인 키 | `SQUARE` |
| 방향키 | `LEFT`, `UP`, `DOWN`, `RIGHT` |

GPIO 키패드는 `SQUARE`를 누른 상태에서 방향키, `+`, `-`, `0`을 누르면
해당 `ALT_*` 입력으로 처리된다.

GPIO 키패드의 `0`은 릴리스 때 단발 숫자 입력으로 전달되지만, USB/Bluetooth
키보드의 `0`은 내부에서 "입력 없음" 값과 겹쳐 큐에 전달되지 않는다. 따라서 HID
키보드에서는 `0`에 배정된 화면 동작(예: 마운트 정지)을 사용할 수 없다.

<a id="mf_keyboard_mapping_ko--indi-마운트-제어"></a>
### INDI 마운트 제어

INDI 마운트 제어는 선택 기능이다. 기본 설치는 PiFinder 배포본의 INDI 바이너리
아카이브(`scripts/install_indi_mount_archive.sh`)를 사용한다. INDI 소스나 PiFinder
OnStepX 패치를 수정해야 할 때만 `scripts/install_indi_mount_OnstepX.sh`로 전체 소스
설치·빌드를 수행한다. 설치 후 PiFinder UI에서 다음 설정을 켠 경우에만 동작한다.

```text
Settings > Experimental > Mount Control > On
```

Mount Control이 켜져 있으면 숫자 키는 Object Details 화면, 일반 메뉴, 상태
화면에서 아래 마운트 동작을 보낸다(하나의 공통 맵 — `docs/mf_dev/mf_input_keymap_ko.md`
참고). `1-9`는 USB/Bluetooth 키보드·키패드·GPIO 키패드에서 같은 방식으로
동작하지만, USB/Bluetooth 키보드의 `0`은 위 제한 때문에 동작하지 않는다. 연속 방향 조그는 키보드 문자에도 있고, 전용 INDI Guide 화면도 같은 공통
맵을 쓴다(숫자 키 대각 조그는 제거 — 대각은 키보드 문자로 유지). 객체 리스트에서는
숫자 키가 대신 카탈로그 시퀀스 점프를 입력하고, 문자는 Name Search를 연다.

| 키 | INDI 마운트 동작 |
| --- | --- |
| `0` | 마운트 정지 (GPIO 키패드/개발 키보드만; HID 키보드에서는 미전달) |
| `2` | South 이동 — 키를 누르는 동안 |
| `4` | West 이동 — 키를 누르는 동안 |
| `5` | GoTo — Object Details(선택 객체)에서만 |
| `6` | East 이동 — 키를 누르는 동안 |
| `7` | 현재 PiFinder solve 위치로 마운트 Sync |
| `8` | North 이동 — 키를 누르는 동안 |
| `9` | 슬루 속도 증가 |
| `3` | 슬루 속도 감소 |
| `1` | 미사용 |

기본 방향 키는 누르는 동안 마운트를 이동한다(누르면 시작, 떼면 정지). 누른 만큼
이동한다. `5`(GoTo)는 객체가 선택된 Object Details 화면에서만 동작하며, 일반 메뉴·
상태 화면엔 타겟이 없어 아무 동작도 하지 않는다. step 크기 설정은 없으며, `1`은 더
이상 init/sync하지 않는다 — 기동 시 자동으로 init·sync된다. 이동 속도(슬루
속도)는 `9`(증가) / `3`(감소)으로 정하며, `+`/`-`는 마운트에 관여하지 않는다.

INDI 서버나 마운트 연결에 문제가 있어도 PiFinder 기본 기능은 계속 동작한다.
마운트 연결 상태는 다음 파일에서 확인할 수 있다.

```text
~/PiFinder_data/mount_control_status.json
```


---

<a id="mf_large_catalog_lazy_load_ko"></a>

## mf_large_catalog_lazy_load_ko.md

<a id="mf_large_catalog_lazy_load_ko--mf_pifinder--대형-카탈로그-지연선택-로드-설계"></a>
## MF_PiFinder — 대형 카탈로그 지연/선택 로드 설계

작성일: 2026-07-20 · 상태: **설계안 (구현 전)**

<a id="mf_large_catalog_lazy_load_ko--1-배경과-목표"></a>
### 1. 배경과 목표

메인 UI 프로세스의 실측 메모리(PSS)는 548MB이고, 그 중 **~350-400MB가 카탈로그
인메모리 로드**로 추정된다. 전체 149,329개 천체 중 **WDS가 131,303개(88%)**로
지배적이다. 최종 제품이 2GB RAM이므로:

- **목표**: WDS(및 대형 카탈로그)를 쓰지 않는 세션에서 메인 UI를 ~200-250MB로.
- **제약**: `catalogs.py`는 upstream 파일 — 변경 최소화. 기존 UX(LCD 카탈로그
  탐색, push-to, 검색)는 유지하되, 미로드 카탈로그는 "진입하면 그때 로드"로.

<a id="mf_large_catalog_lazy_load_ko--2-현재-구조-실조사-결과"></a>
### 2. 현재 구조 (실조사 결과)

| 단계 | 동작 | 근거 |
|---|---|---|
| 첫 부팅 (캐시 없음) | M/NGC/IC(~13K)만 동기 로드 → 나머지(WDS 포함 ~136K)는 `CatalogBackgroundLoader` 스레드가 100개/50ms 배치로 로드 → 완료 시 전체를 pickle 캐시로 저장 | catalogs.py:1011 (`priority_catalogs = {"NGC","IC","M"}`), 703-, 855- |
| 재부팅 (캐시 있음) | **45MB pickle 하나를 통째로 동기 로드** → 전부 상주 | catalog_cache.py (`composite_objects.pkl`, 실측 45MB), catalogs.py:866- |
| UI "로딩 중" 처리 | 빈(미로드) 카탈로그는 필터를 건너뛰는 분기가 **이미 존재** | catalogs.py:310-316 |
| `filter.selected_catalogs` | UI 표시 필터일 뿐 — 메모리와 무관 (전부 로드됨) | catalogs.py:129, 298 |

즉 "지연 로드 골격 + 로딩중 UI 인지 + 캐시"가 모두 있으므로, 부족한 것은
**(a) 캐시가 카탈로그별로 분리되어 있지 않다**, **(b) 지연 대상을 영구히
로드하지 않고 버틸 방법이 없다** 두 가지다.

<a id="mf_large_catalog_lazy_load_ko--3-대안-비교"></a>
### 3. 대안 비교

| 안 | 내용 | 절감 | 변경량 | 판정 |
|---|---|---|---|---|
| **A. 선택+지연 로드 (권장)** | 설정으로 지정한 대형 카탈로그는 부팅 시 로드 제외. LCD에서 그 카탈로그에 **진입하는 순간** 카탈로그별 캐시(pkl)를 로드 | WDS 제외 시 ~300-350MB | 중간 (기존 골격 재사용) | ✅ 채택 |
| B. 온디맨드 DB 조회 (비상주) | 웹 카탈로그처럼 SQLite를 페이지 단위 직조회, 메모리 상주 없음 | 최대 | UI 필터/정렬/nearby 파이프라인이 "전체 리스트 상주" 전제라 **대규모 리팩터** | 장기 옵션 |
| C. CompositeObject 슬림화 (`__slots__`, name interning) | 객체당 오버헤드 축소 | 20-30% | upstream 데이터클래스 변경, 파급 큼 | 보조 수단, 보류 |

<a id="mf_large_catalog_lazy_load_ko--4-설계-a안"></a>
### 4. 설계 (A안)

<a id="mf_large_catalog_lazy_load_ko--41-설정"></a>
#### 4.1 설정

```json
"catalogs.deferred_load": ["WDS"]        // 기본값. 2GB 프로파일 후보: ["WDS","SaM","SaR"]
```

- 빈 리스트 = 현재 동작과 동일(전부 로드). upstream 동작이 기본으로 보존되도록
  **default_config.json에는 빈 리스트**, MF 제품 config에서 `["WDS"]`.

<a id="mf_large_catalog_lazy_load_ko--42-카탈로그별-캐시-분할-catalog_cachepy"></a>
#### 4.2 카탈로그별 캐시 분할 (`catalog_cache.py`)

- `composite_objects.pkl`(45MB 단일) → `catalog_<CODE>.pkl` 분할 저장.
  `CACHE_VERSION` bump로 기존 캐시 자동 무효화.
- 부팅 로드: deferred 목록에 없는 카탈로그의 pkl만 로드.
- 진입 시 로드: 해당 카탈로그 pkl 하나만 로드 — **pickle 로드는 수 초**
  (background loader 재빌드는 131K 기준 65초+라 캐시 필수).
  캐시가 없는 첫 부팅만 background loader가 만들고 저장.

<a id="mf_large_catalog_lazy_load_ko--43-로드-흐름"></a>
#### 4.3 로드 흐름

```
부팅:
  캐시 있음 → non-deferred pkl들 로드 (WDS 제외 시 ~18K 객체)
  캐시 없음 → 기존 우선순위/백그라운드 로더 그대로 전체 빌드
              → 완료 시 카탈로그별 pkl 저장 (deferred 대상은 저장 후 메모리에서 해제)

LCD에서 deferred 카탈로그 진입:
  Catalog.get_objects()가 빈 상태 감지 → 로드 요청 (기존 310행 "빈 카탈로그"
  분기가 이미 이 상태를 안전하게 처리)
  → CatalogBackgroundLoader 또는 pkl 로더가 백그라운드 스레드에서 채움
  → 기존 "로딩 중" UI 상태 재사용, 완료 시 목록 갱신
  → 세션 동안 상주 유지 (언로드는 하지 않음 — 복잡도 대비 실익 없음)
```

<a id="mf_large_catalog_lazy_load_ko--44-터치-포인트-원소스-최소-변경-관점"></a>
#### 4.4 터치 포인트 (원소스 최소 변경 관점)

| 파일 | 변경 | 성격 |
|---|---|---|
| `catalog_cache.py` | save/load를 카탈로그별 분할로 확장 | upstream 파일, 함수 시그니처 유지 |
| `catalogs.py` | build()에서 deferred 목록 분기 + Catalog에 `ensure_loaded()` 추가 | upstream 파일, 기존 background 골격 재사용으로 삽입 위주 |
| UI 카탈로그 진입 지점 (object_list 등) | `ensure_loaded()` 호출 1곳 | 삽입 |
| `default_config.json` / menu_structure | 설정 항목 (+ 선택: 설정 메뉴 노출) | 삽입 |

<a id="mf_large_catalog_lazy_load_ko--45-영향위험-분석"></a>
#### 4.5 영향/위험 분석

- **전역 검색·nearby**: 미로드 카탈로그의 천체는 결과에서 빠진다 — 명시적
  트레이드오프. (WDS 이중성이 nearby에 안 뜨는 것은 2GB 절약의 대가로 수용;
  로드 후에는 정상 포함)
- **push-to recent / observed 체크**: observed는 (catalog, sequence) 키 기반
  DB 조회라 무영향. 웹 카탈로그는 SQLite 직조회라 **완전 무영향**.
- **캐시 정합성**: observed 상태는 로드 시점에 obs_db로 재주입(기존 로직 그대로).
- **첫 부팅 시간**: 변화 없음(전체 빌드는 동일, 저장만 분할).
- **재부팅 시간**: 오히려 개선 (45MB → ~8MB 로드).

<a id="mf_large_catalog_lazy_load_ko--46-예상-효과-실측-기반-추정"></a>
#### 4.6 예상 효과 (실측 기반 추정)

| 구성 | 메인 UI PSS |
|---|---|
| 현재 (전체 로드) | 548MB |
| WDS 지연 (기본 제안) | **~220-250MB** |
| WDS+SaM+SaR 지연 (2GB 공격적 프로파일) | ~200MB |

2GB 제품 수지: PiFinder 전체 ~650MB + INDI 50MB + OS 200MB ≈ 0.9GB → 여유 1.1GB.

<a id="mf_large_catalog_lazy_load_ko--5-구현-단계"></a>
### 5. 구현 단계

| 단계 | 내용 | 검증 |
|---|---|---|
| P1 | 캐시 분할 (동작 변화 없음, 버전 bump) | 재부팅 시간·객체 수 동일 확인 |
| P2 | `catalogs.deferred_load` 설정 + 부팅 제외 + 메모리 해제 | PSS 실측 (목표 250MB 이하) |
| P3 | 진입 시 로드 (`ensure_loaded` + 로딩중 UI 재사용) | LCD에서 WDS 진입 → 수 초 내 목록 표시 |
| P4 | (선택) 설정 메뉴 노출 + 2GB 프로파일 기본값 | 2GB 실기기 검증 |

<a id="mf_large_catalog_lazy_load_ko--6-미결-질문-구현-전-확인"></a>
### 6. 미결 질문 (구현 전 확인)

1. 진입 시 로드의 UX 허용치 — pkl 로드 수 초를 "Loading…" 화면으로 수용?
2. deferred 기본값에 WDS만 넣을지, SaM(2,162)·SaR(333)은 작아서 실익 없음 →
   **WDS 단독 권장**.
3. Hipparcos(`hip_main.pkl` 8.2MB, 차트용 별)는 별도 경로 — 이번 범위 제외.


---

<a id="mf_lcd_operation_errors_ko"></a>

## mf_lcd_operation_errors_ko.md

<a id="mf_lcd_operation_errors_ko--lcd-동작-오류-알림"></a>
## LCD 동작 오류 알림

GOTO·동기화·수동이동·추적·INDI 연결 작업의 실패는 콘솔 기록과 별도로 LCD 오류 화면에 표시한다. 오류 화면은 시간이 지나도 사라지지 않으며 표시 중에는 절전으로 화면을 끄지 않는다.

- 오른쪽, 왼쪽 또는 확인키: 알림을 닫고 기존 화면으로 돌아간다.
- 위·아래: 긴 오류 내용을 스크롤한다.
- 확인키는 마운트 수동이동이나 원래 화면의 선택 동작으로 전달하지 않는다.
- 확인은 알림을 닫는 동작이다. 작업을 자동으로 재시도하거나 오류를 해결한 것으로 처리하지 않는다.
- 화면 스택을 바꾸지 않아 이전 화면의 위치와 선택을 유지한다.

마운트 오류는 `operation_error` 구조화 이벤트로 콘솔 큐에 전달한다. 다음 heartbeat가 상태 파일을 덮어써도 오류 이벤트는 남는다. 같은 작업의 같은 오류는 한 번만 알리고, 새 작업에서 다시 발생하면 다시 알린다. 여러 오류가 한꺼번에 발생하면 한 화면 안에서 확인하며 최근 10건을 보관한다.

GOTO 서비스 오류/시간 초과, 추적 복귀 실패, 카메라 좌표를 장시간 기다리는 수동 목표 갱신/외란 복귀도 알린다. 마운트·GOTO 프로세스 비정상 종료 후 기존 자동 재시작 절차가 작동할 때에도 오류 화면을 표시한다. 일시적인 정상 대기와 사용자가 취소한 작업은 실패로 알리지 않는다.

처음 실행한 뒤에는 INDI 서버 접속, 마운트 장치 연결 및 좌표 수신이 성공해 `mount_ready` 이벤트가 도착한 시점부터 LCD 오류 알림을 활성화한다. 부팅 중 연결 대기, 디버깅을 위한 마운트 미연결, 뒤늦게 큐에서 읽힌 초기 오류는 콘솔/상태 기록에만 남긴다. 이후 연결이 끊기거나 프로세스가 재시작되어도 알림을 다시 비활성화하지 않는다. GPS 시각 보정의 영향을 받지 않도록 이벤트 비교에는 단조 증가 시계를 사용한다.

OnStep의 최초 GPS/Location 위치·시간 동기화는 명령 전송뿐 아니라 새 INDI 응답의 위치·시간과 추적 켜짐을 확인한다. 응답 거부, 전송 실패, 8초 내 확인 실패 또는 추적 시작 실패 시 기존 INDI 리셋(`reboot_mount`)을 자동으로 한 번 실행한다. 리셋 후 선택한 위치를 유지하여 시간과 함께 다시 보내고 추적을 확인한다. 복구 중간 오류는 팝업으로 띄우지 않으며, 리셋이나 재검증이 실패하면 `initialization_failed` 오류 화면을 띄운다. 무한 리셋을 막기 위해 자동 리셋은 마운트 프로세스 실행당 한 번만 허용한다. 미연결 상태나 GOTO/수동이동 중에는 자동 리셋을 시작하지 않는다. 직접 LX200 동기화 경로는 기존 명령 응답 검증 후 추적을 확인한다.

구현 경로:
- `operation_errors.ErrorNotifier`: 구조화 이벤트와 작업별 중복 억제
- `operation_errors.MountErrorGate`: 최초 정상 연결 이후 알림 허용
- `UIOperationError` 및 `MenuManager`: 별도 오류 화면, 스크롤, 복귀
- `KeyboardMappingManager`: 알림 확인키와 마운트 단축키 분리
- `mountcontrol_indi`, `indi_goto_guide_service`, `main`: 오류 발생 및 전달

검증: 초기 연결 알림 게이트와 자동 복구를 포함한 관련 테스트 237개 통과, INDI 바인딩이 필요한 2개 건너뜀. 변경 파일의 Ruff 검사와 형식 검사, 전체 207개 소스 파일의 mypy 검사 통과. 앞선 LCD 구현에서는 UI 통합/모듈 등록 검사 5개 통과 및 128·176픽셀 화면 렌더링을 확인했다. 실제 장비 오류 유발 및 자동 리셋 시험은 수행하지 않았다.


---

<a id="mf_location_catalog_ko"></a>

## mf_location_catalog_ko.md

<a id="mf_location_catalog_ko--mf-pifinder-위치-카탈로그"></a>
## MF PiFinder 위치 카탈로그

웹 `Locations > Add New Location` 화면에서 국가, 지역, 군/구, 도시/장소를 선택해 기본 좌표를 입력할 수 있도록 오프라인 위치 카탈로그를 추가했다.

<a id="mf_location_catalog_ko--데이터-출처"></a>
### 데이터 출처

초기 데이터는 GeoNames export dump를 사용한다.

```text
https://download.geonames.org/export/dump/
```

사용 파일:

```text
cities5000.zip
countryInfo.txt
admin1CodesASCII.txt
admin2Codes.txt
KR.zip
```

GeoNames 데이터는 CC BY 4.0 라이선스이며, PiFinder 문서와 데이터 metadata에 출처를 남긴다. 북한은 요청에 따라 국가 코드 `KP`를 제외하고 생성한다. 한국은 전세계 공통 `cities5000` 데이터가 서울/구/동 단위에서 너무 성기기 때문에, GeoNames 국가별 전체 덤프인 `KR.zip`을 추가로 섞어 비교적 자세한 행정구역과 동/장소를 선택할 수 있게 했다.

<a id="mf_location_catalog_ko--포함-파일"></a>
### 포함 파일

```text
python/PiFinder/data/location_catalog.json
python/PiFinder/location_catalog.py
scripts/build_location_catalog.py
python/tests/test_location_catalog.py
```

`location_catalog.json`은 앱 실행 중 인터넷 연결 없이 사용할 수 있는 가공 데이터다. 서버는 전체 JSON을 브라우저로 한 번에 보내지 않고, 선택 단계별 API로 필요한 목록만 반환한다.

<a id="mf_location_catalog_ko--웹-동작"></a>
### 웹 동작

`Add New Location` form에서 다음 순서로 선택한다.

```text
Country > State / Province > County / District > City / Place
```

`City / Place`를 선택하면 기존 수동 입력 필드에 기본값을 채운다.

- Location Name: 사용자가 직접 수정한 이름이 없으면 장소 이름을 입력한다.
- Latitude / Longitude: GeoNames 좌표를 입력한다.
- Altitude: GeoNames elevation 또는 DEM 값을 입력한다.
- Error: 기본 `1000m`로 입력한다. 실제 관측지는 필요에 따라 사용자가 수정한다.
- Source: `GeoNames: country / region / district / place` 형식으로 기록한다.

수동 입력과 DMS 입력 기능은 그대로 유지된다.

<a id="mf_location_catalog_ko--재생성-방법"></a>
### 재생성 방법

```bash
mkdir -p /tmp/pifinder_geonames
curl -L -o /tmp/pifinder_geonames/cities5000.zip https://download.geonames.org/export/dump/cities5000.zip
curl -L -o /tmp/pifinder_geonames/countryInfo.txt https://download.geonames.org/export/dump/countryInfo.txt
curl -L -o /tmp/pifinder_geonames/admin1CodesASCII.txt https://download.geonames.org/export/dump/admin1CodesASCII.txt
curl -L -o /tmp/pifinder_geonames/admin2Codes.txt https://download.geonames.org/export/dump/admin2Codes.txt
curl -L -o /tmp/pifinder_geonames/KR.zip https://download.geonames.org/export/dump/KR.zip

python3 scripts/build_location_catalog.py \
  --source-dir /tmp/pifinder_geonames \
  --output python/PiFinder/data/location_catalog.json
```

재생성 뒤에는 다음을 확인한다.

```bash
python3 -m pytest python/tests/test_location_catalog.py -q
```


---

<a id="mf_stellarium_push_port_analysis_ko"></a>

## mf_stellarium_push_port_analysis_ko.md

<a id="mf_stellarium_push_port_analysis_ko--stellarium-mobile-plus-push-621-mf-선별-이식-분석"></a>
## Stellarium Mobile Plus push (#621) MF 선별 이식 분석

작성일: 2026-09-06. 비교 기준: MF `9dfd3a3f`, upstream #621 `ef7e7928`.
사용자가 선택한 **9번**에 대한 작업 트리 반영 기록이다. 아직 커밋하지 않았다.

<a id="mf_stellarium_push_port_analysis_ko--결론"></a>
### 결론

Stellarium 연결 초기화에 필요한 LX200 응답을 추가하되, upstream의
`pos_server.py` 전체를 교체하지 않았다. MF는 Push-To뿐 아니라 실제 INDI
GoTo·Align·가이드·정지를 담당하므로, upstream의 모터 없는 장비 전제를
그대로 가져오면 정상 동작 중인 경로를 손상할 수 있다.

특히 **좌표 수신(`Sr/Sd`)과 이동 요청(`MS`)의 분리**, 음수 0도 적위,
기존 좌표 epoch 처리, 짧은 TCP 연결의 가이드 이동 유지는 그대로 보존했다.
실제 휴대폰과 마운트 연결 시험을 한 것은 아니므로 현장 호환성을 확정하지 않는다.

<a id="mf_stellarium_push_port_analysis_ko--현재-mf와-upstream의-충돌-분석"></a>
### 현재 MF와 upstream의 충돌 분석

| 항목 | upstream #621 | 현재 MF 및 이번 결정 |
| --- | --- | --- |
| TCP 수신 | `split_frames()`로 수신 문자열을 분리 | MF에는 미완성 프레임을 다음 `recv`까지 보관하는 `_pop_lx200_message()`가 이미 있다. 이를 유지하고 완성 프레임의 명령 처리만 분리했다. |
| 대상 좌표 수신 | `Sd`에서 push를 실행하고 `MS`는 성공 응답 | MF는 `Sr/Sd`를 임시 보관하고 `MS`에서 push/GoTo한다. 그대로 유지해 Align 좌표 설정만으로 이동하거나 한 요청에 중복 GoTo하는 문제를 피했다. |
| 음수 적위 | upstream의 좌표 파싱 경로 | MF가 이미 고친 `-00°` 부호 보존 튜플을 유지했다. `*`/`:` 구분자와 선택적 선행 `#`만 호환 확장했다. |
| 좌표 epoch | SkySafari/Stellarium 별도 처리 및 세차 변환 | MF의 기존 좌표 서비스·J2000 기준 경로를 유지하고 새 변환을 넣지 않았다. 앱의 좌표 epoch 설정과 실제 지향은 현장 확인 대상이다. |
| 이동 상태 `D` | 모터 없는 장비의 비이동 응답 | MF의 실제 이동 상태·이동 직후 유예 처리를 유지했다. Stellarium 연결이라고 비이동으로 고정하지 않는다. |
| 정지 `Q` | 앱 호환 응답 | 기존 `handle_guide_stop()`을 반드시 실행한다. 일반 연결은 무응답, ACK를 보낸 연결에만 upstream 호환 응답 `1`을 보낸다. |
| 연결 종료 | 단순 접속 수명주기 | MF 가이드 버튼은 짧은 연결을 쓸 수 있다. 종료 시 가이드 이동을 멈추거나 keepalive 상태를 초기화하지 않는다. 기존 `Q/Qn/...`, lease와 최대 유지 시간 제한이 정지를 담당한다. |
| 마운트 형식 | ACK에 `P` | ACK 응답만 `P`로 변경한다. `GW`는 MF 설정에 따른 실제 `AT/PT/GT` 상태를 유지한다. ACK는 호환성 판별 신호이지 확실한 앱 식별 정보는 아니다. |
| 사이트·시각 | 연결 초기화 명령 응답 | 클라이언트 사이트는 같은 연결의 조회에만 echo한다. GPS·설정 파일·시스템 시각·마운트 관측지는 바꾸지 않는다. |

<a id="mf_stellarium_push_port_analysis_ko--실제-반영-내용"></a>
### 실제 반영 내용

대상: `python/PiFinder/pos_server.py`.

- `SC/SL/SG` 수신 확인, `GC/GL/GG` 로컬 날짜·시각·UTC 보정값 조회를 추가했다.
  날짜 형식은 locale과 무관하게 `MM/DD/YY`, 시각은 `HH:MM:SS`다.
  날짜 설정 응답은 두 개의 이미 종료된 상태 문자열을 보존한다.
  `GG`는 로컬 시각에 더해서 UTC가 되는 보정값이므로 일반 UTC offset의
  반대 부호다. PiFinder 시각이 없으면 임의 값을 만들지 않고 응답하지 않는다.
- `St/Sg`는 연결 안에서만 저장·조회한다. 설정하지 않았으면 실제 위치를
  분 단위로 반올림해 반환한다. 위도 분 올림과 경도 서경 양수/0~359도
  변환을 포함하며 `360*00`을 반환하지 않는다.
- `Sr/Sd`의 시간·각도 범위를 검증하고 잘못된 값은 `0`으로 거부한다.
  새 RA는 이전 Dec를 지우며, 잘못된 좌표 설정 뒤 `MS`가 이전 임시 좌표로
  이동하지 않도록 했다. 알파벳을 포함한 잘못된 `:Srbad#`도 검증 경로로 보낸다.
- `_format_lx200_response()`는 기존 `0/1`, `AT/PT/GT` 응답 형식을 유지하고,
  이미 `#`로 끝난 복합 응답에 종료 문자를 중복해서 붙이지 않는다.
- `handle_frame()`으로 완성 명령 처리를 분리했다. TCP 조립은 기존 MF 함수를
  재사용한다. 송신은 `sendall()`, 수신은 바이트 보존 Latin-1 처리로 바꿨다.
  미완성 입력 버퍼는 4 KiB로 제한하고, timeout/reset/broken pipe 때 소켓을 정리한다.
- 접속 시작·종료 시 앱 판별과 사이트 echo를 초기화한다. 대상 좌표는 같은
  클라이언트 IP의 연속 연결 사이에 유지한다. SkySafari가 `Sr`, `Sd`, `MS/CM`을
  각각 다른 TCP 연결로 보내기 때문이다. 다른 IP 또는 60초 이상 통신 공백 뒤에는
  대상 좌표도 초기화한다. 마운트의 실제 이동·가이드 상태는 초기화하지 않는다.
- PUSH 객체 설명의 앱 이름을 일반화하고 사용자 문서에 접속·안전 경계를 기록했다.

<a id="mf_stellarium_push_port_analysis_ko--명령-흐름과-안전-경계"></a>
#### 명령 흐름과 안전 경계

1. `Sr` → `Sd`: 대상 좌표만 보관하고 각각 성공/실패를 반환한다. 모터 명령 없음.
2. `MS`: 기존 MF 설정에 따라 Push-To 또는 INDI GoTo 경로를 실행한다.
   명령 한 번당 기존 GoTo 처리 함수를 한 번 호출한다. 클라이언트가 `MS`를
   재전송하는 경우까지 자동 중복 제거하는 기능은 추가하지 않았다.
3. `CM`: 기존 MF Align 라우팅을 사용한다. 좌표를 설정했다는 이유만으로
   `MS`를 대체 실행하지 않는다.
4. `Q` 및 방향별 정지: MF의 기존 정지·가이드 해제 동작을 사용한다.

기존 `SkySafari` 이름의 GoTo/Align 설정은 Stellarium 연결에도 적용된다.
이 이식은 Push-To 전용 별도 서버를 만드는 작업이 아니다. 따라서 마운트 제어가
켜져 있으면 Stellarium의 GoTo도 실제 이동을 요청할 수 있다.

<a id="mf_stellarium_push_port_analysis_ko--검증-근거"></a>
### 검증 근거

- 기존 `tests/test_pos_server.py`의 동작 검증을 유지했다. 소켓 테스트 더블만
  실제 송신 API 변경에 맞춰 `send`에서 `sendall`로 바꿨다.
- `tests/test_pos_server_stellarium.py`를 추가했다. 소켓·큐·설정을 격리하고
  실제 마운트 상태 조회 및 하드웨어 명령을 대체한다.
- ACK와 `Sr/Sd/MS`가 합쳐진 입력을 모든 바이트 분할 위치에서 나눠도
  목표 전달이 한 번 발생하는지 확인한다. 좌표만 수신했을 때 미이동,
  음수 0도 적위, 잘못된 범위·알파벳, 새로운 RA와 이전 Dec의 혼합 방지도 검사한다.
- 실제 이동 상태 응답, MF 마운트 형식 override, 정지 처리 호출과 앱별 응답,
  사이트·시각 초기화 명령의 비변경성, 연결 간 정보 초기화, 송신 실패 및
  과도하게 긴 미완성 입력을 검사한다.
- 기존의 짧은 가이드 연결 유지 테스트가 종료 시 무조건 정지하는 방식과
  충돌함을 확인했다. 그런 동작은 최종 코드에 넣지 않았으며 기존 회귀 테스트를 통과했다.
- 최종 전체 테스트·타입·정적 검사 결과는
  [upstream 패치 기준 문서](maintenance.md#mf_upstream_patch_reference_ko)의 같은 날짜 기록을 참조한다.

<a id="mf_stellarium_push_port_analysis_ko--실기기-확인이-필요한-항목"></a>
### 실기기 확인이 필요한 항목

<a id="mf_stellarium_push_port_analysis_ko--2026-09-06-skysafari-좌표-거부-수정"></a>
#### 2026-09-06 SkySafari 좌표 거부 수정

실기기에서 `대상 좌표들이 유효하지 않다` 오류를 재현했다. 20:56:52 수동
패킷 관찰에서 `Sr19:52:05`는 TCP 송신 포트 59628로 들어와 `1`을 받았지만,
`Sd+08*56:10`은 송신 포트 59636으로 들어와 `0`을 받았다. 접속마다 좌표를
지우는 코드 때문에 적경이 사라져, 정상 범위의 적위가 거부된 것이다.

같은 IP의 연속 연결에서는 좌표를 보존하도록 수정했다. 적경·적위 사이의
`GR/GD` 조회도 좌표를 지우지 않는다. 다른 IP나 60초 이상의 통신 공백 뒤에는
이전 대상을 사용하지 않는다. 두 대의 클라이언트가 번갈아 같은 서버를 제어하는
경우에는 대상을 다시 설정해야 한다. 기존 잘못된 좌표 거부와 새 적경 수신 시
이전 적위 무효화는 유지한다.

실측 좌표 및 음수 0도 적위로 별도 연결 GoTo, 별도 연결 Align, 다른 IP 및
시간 초과 시 대상 초기화를 회귀 테스트에 추가했다. 수정 후 두 프로토콜 테스트
파일의 154개 테스트가 통과했다. 서비스 재시작 후 실제 GoTo 성공 여부는 별도
현장 확인이 필요하다.

<a id="mf_stellarium_push_port_analysis_ko--나머지-현장-확인"></a>
#### 나머지 현장 확인

- 먼저 마운트 제어가 꺼진 상태에서 Mobile Plus의 LX200 TCP 연결
  (`pifinder.local` 또는 IP, 포트 `4030`), 지향 조회, 대상 push와 재접속을 확인한다.
- GPS 시각이 유효한 상태에서 사이트·날짜 초기화가 연결을 막지 않는지 확인한다.
  GPS 시각 미확정 시 무응답 정책은 유지하므로 그때의 앱 동작은 별도 확인 대상이다.
- 알려진 별로 앱/장치 좌표 epoch 설정과 지향 일치를 확인한다. ACK 호환 응답
  `P`와 실제 `GW` 마운트 형식 응답 조합도 사용 중인 앱 버전에서 확인해야 한다.
- 이후 안전한 공간에서 사용 중인 MF GoTo 방식별 이동, Align, 전체/방향별 정지,
  SkySafari 짧은 연결 가이드를 확인한다. 이 작업 중 실제 마운트는 움직이지 않았다.

<a id="mf_stellarium_push_port_analysis_ko--참고-자료"></a>
### 참고 자료

- [upstream #621](https://github.com/brickbots/PiFinder/pull/621) 및 로컬 Git 객체
  `ef7e7928`: 이식 대상 구현. MF와의 차이는 해당 커밋의 파일 내용을 직접 비교했다.
- [Meade Telescope Serial Command Protocol](https://aggregate.org/DIT/CAPTURE/LX200CommandSet.pdf):
  Meade 작성 문서의 미러. `Sr/Sd` 대상 설정, `MS` 이동, `Q` 정지와
  사이트·시간 응답 형식의 근거다. ACK 연결의 `Q` 응답은 이 문서의 표준
  무응답 동작과 구분되는 upstream 앱 호환 처리다.
- [Stellarium Labs의 Mobile Plus 망원경 제어 안내](https://www.stellarium-labs.com/telescope-control-in-stellarium-mobile-plus/):
  LX200 연결 지원의 근거다. 개별 앱 버전의 실제 패킷 순서나 좌표 epoch까지
  보장하는 자료로 사용하지 않았다.


---

<a id="mf_web_catalogs_dev_ko"></a>

## mf_web_catalogs_dev_ko.md

<a id="mf_web_catalogs_dev_ko--mf_pifinder--web-catalogs-페이지-개발-문서"></a>
## MF_PiFinder — Web Catalogs 페이지 개발 문서

> **구현 상태 (2026-07-20)**: P1~P5 구현 완료·실기기 검증 완료.
> 본체 `python/PiFinder/web_catalogs.py`, 템플릿 `views/catalogs/*`,
> `views/css/catalogs.css`, `views/js/catalogs.js`, 테스트 `tests/test_web_catalogs.py`(9개).
> 원소스 변경은 계획대로 server.py 훅 +5줄, base.html 네비 2줄뿐.
> Push 시 트래킹 주파수 연동 포함(정적 천체=sidereal 복원, `offset_arcsec_per_s` 지정 시
> 비항성 주파수 설정 — `mf_web_catalogs` P6/`nonsidereal.py` 참조).
> 미구현: P6(행성/혜성 live 카탈로그).

기기 내장 웹 UI(Flask)에 카탈로그 브라우징 페이지를 추가한다.
디자인 시안: 3화면 구조(카탈로그 홈 → 천체 목록 → 천체 상세), 기존 `--pf-*` 토큰 / Gray·Red Night 테마 그대로 사용.

- 참고 사이트: https://catalogs.pifinder.eu/ (라우트·필터 구조 참고)
- 작성일: 2026-07-19

---

<a id="mf_web_catalogs_dev_ko--1-대원칙-신규-소스-분리--원소스-최소-변경"></a>
### 1. 대원칙: 신규 소스 분리 / 원소스 최소 변경

이 저장소는 upstream(brickbots/PiFinder) 머지를 계속 받아야 하므로, **기능 전체를 신규 파일에 구현**하고
원소스는 "등록 지점"만 건드린다. 선례는 `api_extensions.py`이며 동일한 패턴을 따른다
(`server.py` 말미의 try/except 3줄 훅 → `register_api_routes(app, self, ...)`).

<a id="mf_web_catalogs_dev_ko--11-원소스-변경-지점-전체-목록--이-2곳이-전부"></a>
#### 1.1 원소스 변경 지점 (전체 목록 — 이 2곳이 전부)

| 파일 | 변경 | 내용 |
|---|---|---|
| `python/PiFinder/server.py` | +5줄 | `run()` 직전, 기존 api_extensions 훅(현재 2442행 부근) 바로 아래에 동일 형태의 등록 훅 추가 |
| `python/views/base.html` | +2줄 | 데스크톱 네비 `ul.pf-nav-links` 와 모바일 `ul#nav-mobile` 에 `<li><a href="/catalogs">{{ _('Catalogs') }}</a></li>` 각 1줄 |

server.py 훅 형태 (api_extensions 훅과 동일한 방어적 구조):

```python
try:
    from PiFinder.web_catalogs import register_catalog_routes

    register_catalog_routes(app, self)
except Exception:
    logger.exception("Failed to register web catalog routes")
```

훅이 실패해도 기존 웹 UI는 정상 동작해야 한다(신규 모듈의 import 에러가 서버를 죽이면 안 됨).

<a id="mf_web_catalogs_dev_ko--12-신규-파일-기능-본체"></a>
#### 1.2 신규 파일 (기능 본체)

| 파일 | 역할 |
|---|---|
| `python/PiFinder/web_catalogs.py` | 라우트 등록 + 조회/필터 SQL + 고도 계산 + push 처리. 기능 전부가 여기 모임 |
| `python/views/catalogs/index.html` | ① 카탈로그 홈 (`{% extends "base.html" %}`) |
| `python/views/catalogs/catalog.html` | ② 천체 목록 (필터바 + 테이블 + 페이지네이션) |
| `python/views/catalogs/object.html` | ③ 천체 상세 (facts + 이미지 + 고도곡선 + 액션) |
| `python/views/css/catalogs.css` | 신규 화면 전용 스타일. 기존 `/css/<path>` 정적 라우트가 그대로 서빙하므로 서버 변경 불필요 |
| `python/views/js/catalogs.js` | 필터 갱신·고도곡선 캔버스·push 호출. 기존 `/js/<path>` 라우트로 서빙 |
| `python/tests/test_web_catalogs.py` | 단위 테스트 (`test_api_extensions.py` 선례를 따름) |
| `docs/mf_dev/mf_web_catalogs_dev_ko.md` | 본 문서 |

CSS/JS 로드: `base.html`에는 head 확장 블록이 없으므로, 신규 템플릿의 `{% block content %}` 첫 줄에
`<link rel="stylesheet" href="/css/catalogs.css">` 를 두고 JS는 `{% block scripts %}` 를 사용한다.
→ base.html에 블록을 추가하지 않아도 되므로 원소스 변경이 늘지 않는다.

---

<a id="mf_web_catalogs_dev_ko--2-아키텍처와-데이터-접근"></a>
### 2. 아키텍처와 데이터 접근

웹 서버는 별도 프로세스이지만 `Server` 인스턴스가 이미 다음을 보유한다
(`register_catalog_routes(app, server_instance)` 로 전달받아 사용):

- `server_instance.shared_state` — 위치·시각·ui_state
- `server_instance.ui_queue` — LCD로 명령 전달

<a id="mf_web_catalogs_dev_ko--21-천체-데이터-읽기-전용-sqlite"></a>
#### 2.1 천체 데이터 (읽기 전용 SQLite)

- 대상: `astro_data/pifinder_objects.db` (`utils.pifinder_db`)
  - `objects`(149,329) / `catalog_objects`(151,170) / `catalogs`(21) / `names`(430,288) / `object_images`
- `web_catalogs.py`가 **자체 읽기 전용 커넥션**을 연다:
  `sqlite3.connect(f"file:{utils.pifinder_db}?mode=ro", uri=True, check_same_thread=False)`
  - 기존 `db/objects_db.py`는 목록형 API만 있어 페이지네이션/필터 SQL에 부적합 → 원소스를 고치지 않고
    신규 모듈 안에 전용 쿼리 계층을 둔다.
  - 이 DB는 저장소에 포함된 빌드 산출물이므로 **절대 쓰기 금지** (인덱스 추가도 금지).
    Pi에서 catalog_code 조건의 15만 행 스캔은 수십 ms 수준 — 페이지당 1쿼리면 충분하다.

<a id="mf_web_catalogs_dev_ko--22-필터정렬페이지네이션-wds-131k-대응"></a>
#### 2.2 필터·정렬·페이지네이션 (WDS 131k 대응)

- 전부 **서버측 SQL**: `WHERE catalog_code=? AND obj_type IN (...) AND const=? AND filter_mag<=?`
  + `LIMIT/OFFSET`. `mag`은 JSON 텍스트이므로 `json_extract(mag,'$.filter_mag')` 사용.
- 이름 검색은 `names.common_name LIKE` (통합 검색은 전 카탈로그 대상, LIMIT 50).
  홈 통합 검색은 **카탈로그 홈의 그룹·카탈로그 표시 순서**(`CATALOG_GROUPS`)를
  먼저 따르며, 미등록 카탈로그는 홈의 `Other`와 같이 코드 알파벳순으로 뒤에 둔다.
  같은 카탈로그 안에서는 **q로 시작하는 이름 우선 → 짧은 이름 → 알파벳순**으로
  정렬한다(WHERE는 `%q%`). SQL에서 제한·중복 제거 전에 이 순서를 적용하므로,
  여러 카탈로그에 속한 천체는 화면 순서상 첫 카탈로그의 지정번호로 표시된다.
- "Up now"(현재 고도) 필터/정렬: 페이지 크기(≤200행) 범위에서만 고도를 계산하면 정렬이 왜곡되므로,
  고도 정렬 시에는 **필터 통과 행 전체의 (ra,dec)를 가져와 numpy 일괄 계산 후 정렬 → 페이지 슬라이스**.
  Messier급은 문제없고 WDS는 고도 정렬을 비활성화(시퀀스 정렬 고정)한다 — UI에서 안내 문구 표시.

<a id="mf_web_catalogs_dev_ko--221-홈-통합검색-지정번호-정렬-2026-07-22"></a>
#### 2.2.1 홈 통합검색 지정번호 정렬 (2026-07-22)

홈 검색창(`/catalogs/api/search`, `catalogs_api_search`)은 사용자가 카탈로그
지정번호를 칠 때 이름 검색만으로는 순서가 무의미했다(정렬 없이 `LIKE '%q%'`
120개 → dedup → 50개). 다음으로 개선했다:

- 질의가 `문자+숫자` 패턴(`^([A-Za-z]+)\s*(\d+)$`, 예 `m5`, `ngc1`)이면
  **지정번호 검색**으로 처리: `WHERE co.catalog_code = ? COLLATE NOCASE
  AND CAST(co.sequence AS TEXT) LIKE '숫자%'`,
  `ORDER BY LENGTH(CAST(sequence AS TEXT)), sequence`.
  → 입력 자리수와 같은 이름이 맨 위, 그다음 한 자리 더 긴 것들이 숫자 순:
  `m5` → M 5, M 50, M 51…; `ngc1` → NGC 1, NGC 10, NGC 11…
- 지정번호 결과가 50개 미만이면 이름 검색으로 채운다(2.2의 prefix 우선 정렬).
- 문자가 카탈로그 코드가 아니면 자동으로 이름 검색으로 폴백.
- 테스트: `test_search_api_designation_ordering` (m5/ngc1 순서 검증).

<a id="mf_web_catalogs_dev_ko--222-주변-관측-대상-2026-09-13"></a>
#### 2.2.2 주변 관측 대상 (2026-09-13)

- M·NGC·WDS·PL 등 개별 카탈로그 목록의 `Up now` 옆 `Nearby` 버튼으로
  `/catalogs/api/objects?catalog=코드&sort=nearby` 정렬을 선택한다.
  다시 누르면 기존 정렬로 돌아간다. 홈의 별도 버튼·결과 목록과
  `/catalogs/api/nearby` 전역 조회 API는 제거했다.
- 기준은 pointing coordinate service의 `current` RA/Dec이다. 선택 좌표가
  없으면 같은 서비스가 게시한 `solved` → `imu` 순으로 유효한 좌표를 사용한다.
  솔빙 전 IMUPLUS 상태에서도 주변 조회가 가능하며, 절대 방위 정렬이 없는
  IMU 좌표는 `IMU estimate (heading not aligned)`로 표시한다. 이 조회용
  폴백은 마운트 제어나 SkySafari의 좌표 선택 규칙을 변경하지 않는다.
  모든 좌표가 없으면 안내한다. 위치가 없어도 거리 정렬은 가능하지만
  `Up now`를 함께 쓰려면 관측 위치가 필요하다.
- 해당 카탈로그의 전체 필터 결과를 현재 지향점과의 구면 각거리가 가까운 순으로 정렬한
  뒤 기존 `page`/`page_size` 방식으로 표시한다. 총 개수 제한은 없다.
  기본 페이지 크기 50, 최대 페이지 크기 200과 기존 전체 개수·페이지 수를 유지한다.
  M에서는 M 지정번호, NGC에서는 NGC 지정번호로 표시하며 행성은 PL에만 포함된다.
- `Up now`는 별도 필터로 유지한다. 함께 켜면 고도 > 0°만 남긴다.
  이름·종류·별자리·등급·관측 여부 필터도 그대로 적용된다.
  WDS도 Nearby 모드에서는 `Up now` 계산을 지원한다.
- 기존 테이블에 Nearby 모드일 때만 예상 관측 난이도·각거리 열을 표시한다.
  고도·크기·관측 여부·상세 페이지 이동은 기존 목록과 같다.
- 대형 카탈로그도 좌표·측광 정보로 전체를 먼저 정렬하고 표시 정보는 현재
  페이지에 해당하는 천체만 읽는다. 좌표 없는 행은 거리 없음으로 유지한다.
  DB는 읽기 전용이다.

보틀/SQM 관측 난이도 표시:

- 기존 장치 설정에는 보틀 항목이 없었다. 선택 설정 키 `filter.bortle`가 있으면
  1~9 및 장치의 4.5 등급을 읽는다. 이 기능은 값을 임의로 저장하지 않는다.
- 실측은 `shared_state.sqm()`의 최근 60초 이내 유효한 값만 사용한다.
  장치가 게시하는 로컬 ISO 시각과 시간대가 있는 ISO 시각을 모두 지원한다.
  초기 기본값(측정 시각 없음)은 실측으로 취급하지 않는다.
- 설정값과 실측값이 모두 있으면 더 밝은 하늘, 즉 낮은 SQM을 적용한다.
  SQM↔보틀 구간은 `PiFinder/sky_quality.py`에서 LCD SQM 화면과 공유한다.
  설정 보틀의 대표 SQM은 구간 중간값이며, 범위가 넓은 9등급은 16.5를 쓴다.
- `web_catalog_visibility.py`가 활성 망원경·접안렌즈로 난이도를 추정한다.
  확산 천체는 LCD 상세 화면과 같은 `pydeepskylog.contrast_reserve`를 사용한다.
  CR ≥ 0.5는 Favorable, −0.2 이상은 Challenging, 그 이하는 Unlikely이다.
- 별·다중성·행성은 SQM에서 얻은 맨눈 한계등급에 집광 면적 이득
  `5 log10(min(구경, 배율×7)/7)`을 더하는 근사치를 쓴다(동공 7 mm 가정).
  `filter.magnitude`가 있으면 점광원 한계등급을 그 값 이내로 제한한다.
  한계보다 1등급 이상 밝으면 Favorable, 한계 이내면 Challenging이다.
  이는 검출 우선순위 추정이며 이중성 분리나 행성 세부의 가시성 판정은 아니다.
- 측광·크기가 없거나 모델이 적용되지 않는 대상은 Unknown으로 표시한다.
  관측 난이도는 참고 정보이며 Nearby 정렬 순서에 영향을 주지 않는다.
  유효한 하늘 밝기나 장비 정보가 없으면 난이도 추정이 불가능한 이유를 표시한다.
- 2026-10-09 수정: 난이도를 거리보다 우선하던 정렬로 인해 먼 대상이 앞에
  나오던 현상을 해소했다. 행성에도 같은 거리순을 적용하며 전체 결과를 정렬한
  뒤 페이지를 나눈다. 좌표가 없는 대상은 목록 끝에 둔다.
- 참고: [pydeepskylog](https://pypi.org/project/pydeepskylog/),
  집광 면적과 한계등급의 근사 관계는
  [CAAA 관측 입문 자료](https://caao.ca/wp-content/uploads/2023/02/CAAO-tutorial.pdf).

<a id="mf_web_catalogs_dev_ko--23-고도방위-계산--skyfield-금지-fastaltaz-사용"></a>
#### 2.3 고도/방위 계산 — skyfield 금지, FastAltAz 사용

- `calc_utils.FastAltAz`(`calc_utils.py:23`, `radec_to_altaz`)는 순수 수식이라 가볍다.
  서버 프로세스에서 `Skyfield_utils`(de421.bsp 로드)를 **새로 인스턴스화하지 않는다** (메모리·기동시간).
- 위치·시각은 `shared_state.location()` / `shared_state.datetime()` — pos_server와 동일한 소비 방식.
- 상세 화면의 "오늘 밤 고도 곡선"과 transit: 일몰~일출 구간을 10분 간격 샘플링해 FastAltAz로 계산,
  JSON으로 내려 캔버스에 그린다. GPS 미고정 시 고도 관련 UI는 "위치 대기 중"으로 강등(테이블 자체는 동작).

<a id="mf_web_catalogs_dev_ko--24-이미지"></a>
#### 2.4 이미지

- `cat_images.resolve_image_name(obj, "POSS")` + `BASE_IMAGE_PATH`(=`{utils.data_dir}/catalog_images`) 재사용.
- 신규 라우트가 `send_from_directory` 로 서빙, 파일 없으면 404 → 프런트에서 플레이스홀더 표시.

<a id="mf_web_catalogs_dev_ko--25-관측-이력"></a>
#### 2.5 관측 이력

- `db/observations_db.py` `ObservationsDatabase.get_observed_objects()` 재사용 (읽기 전용).
- 목록의 ✓ 컬럼, "Not observed" 필터, 상세의 "Observed n회"에 사용.

<a id="mf_web_catalogs_dev_ko--26-push-to-pifinder-핵심-액션"></a>
#### 2.6 Push to PiFinder (핵심 액션)

`pos_server.py`의 SkySafari GoTo 처리(1139–1158행)와 **동일한 메커니즘**을 재사용한다:

```python
obj = load_composite_object(object_id)   # DB에서 실제 천체 → LCD에 정식 정보 표시
shared_state.ui_state().add_recent(obj)
shared_state.ui_state().set_new_pushto(True)
ui_queue.put("push_object")              # main.py:896 에서 처리됨
```

- SkySafari 경로와 달리 DB의 실제 `CompositeObject`(catalog_code/sequence/mag/size 포함)를 구성하므로
  LCD에 "PUSH 임시 천체"가 아닌 정식 카탈로그 천체로 표시된다.
- `CompositeObject` 구성 시 `names`/`catalog_objects`를 조인해 LCD 상세 화면과 동일한 필드를 채운다.

<a id="mf_web_catalogs_dev_ko--27-인증"></a>
#### 2.7 인증

- 조회 페이지: 기존 페이지들과 동일하게 비인증 허용.
- **push 등 상태 변경 엔드포인트: `@auth_required`**(`server.py:69`의 기존 데코레이터를 import) 적용.
  로그인은 기존 `/login`(시스템 계정 PAM) 흐름 그대로.

<a id="mf_web_catalogs_dev_ko--28-i18n--테마"></a>
#### 2.8 i18n / 테마

- 템플릿 문자열은 전부 `{{ _('...') }}` — 기존 Babel 설정이 그대로 적용된다.
- 색·간격은 `--pf-*` 토큰만 사용(신규 색상 하드코딩 금지) → Red Night 테마 자동 대응.
  고도곡선 캔버스도 `getComputedStyle`로 토큰을 읽어 그린다.

---

<a id="mf_web_catalogs_dev_ko--3-라우트-설계"></a>
### 3. 라우트 설계

| 메서드/경로 | 응답 | 내용 |
|---|---|---|
| `GET /catalogs` | HTML | ① 홈: `catalogs` 테이블 + 그룹핑(딥스카이/이중성·변광성/리스트) + 통합검색 |
| `GET /catalogs/<code>` | HTML | ② 목록: 첫 페이지는 서버 렌더, 필터 변경은 JSON API 호출 |
| `GET /catalogs/object/<int:object_id>` | HTML | ③ 상세 |
| `GET /catalogs/api/objects` | JSON | 목록 데이터. 파라미터: `catalog, q, types, const, mag_max, observed, up_now, sort, page, page_size(≤200)` |
| `GET /catalogs/api/search?q=` | JSON | 전 카탈로그 검색 (지정번호 우선 + 이름, LIMIT 50 — 2.2.1 참조) |
| `GET /catalogs/api/altitude/<int:object_id>` | JSON | 현재 alt/az + 오늘 밤 곡선 + transit |
| `POST /catalogs/api/push/<int:object_id>` | JSON | **auth_required.** LCD 타겟 전송 (2.6) |
| `GET /catalogs/image/<int:object_id>` | JPEG | POSS 썸네일 |

URL prefix `/catalogs`는 기존 라우트와 충돌 없음(기존 `/locations/catalog/*`와도 무관).

---

<a id="mf_web_catalogs_dev_ko--4-단계별-구현-계획"></a>
### 4. 단계별 구현 계획

각 단계는 독립적으로 배포 가능해야 하며, 원소스 변경은 **1단계에서만** 발생한다.

| 단계 | 내용 | 파일 |
|---|---|---|
| **P1 골격** | 훅 2곳 + `web_catalogs.py` 뼈대 + ① 홈 화면(카탈로그 목록/그룹/카운트) | 원소스 2곳 + 신규 4파일 |
| **P2 목록** | ② 필터/정렬/페이지네이션 + 통합검색 (`/catalogs/api/objects`, `/catalogs/api/search`) | 신규 파일만 |
| **P3 상세** | ③ facts·설명·이미지 서빙·관측 이력 | 신규 파일만 |
| **P4 실시간** | Alt 컬럼·Up now 필터·고도곡선·transit (FastAltAz) | 신규 파일만 |
| **P5 Push** | `POST push` + auth + LCD 연동 검증 | 신규 파일만 |
| **P6 확장(선택)** | 행성/혜성 live 카탈로그, 관측리스트 연동, AstroPlanner export | 별도 설계 후 진행 |

P6 주의: 행성/혜성은 메인 프로세스 메모리에만 있어 서버 프로세스에서 접근 불가.
서버에서 자체 계산하려면 skyfield 로드가 필요하므로(2.3 원칙과 충돌) **요청 시 lazy-load** 방식으로
별도 검토한다. P1~P5 범위에서는 정적 21개 카탈로그만 다룬다.

<a id="mf_web_catalogs_dev_ko--p6-사전-검증-indi-비항성-트래킹-2026-07-19-실기기-검증-완료"></a>
#### P6 사전 검증: INDI 비항성 트래킹 (2026-07-19 실기기 검증 완료)

Push 대상이 행성/혜성일 때 트래킹 속도를 INDI로 넘기는 방안을 OnStepX 10.28q + indi_lx200_OnStepX
실기기에서 검증했다 (실내, 좌표 드리프트 회귀 측정 방식).
**마운트는 Alt/Az 타입**(`:GU#`의 `A` 플래그로 확인)이며 아래 결과는 Alt/Az 기구학이 포함된
실측이다 — 펌웨어가 sky 목표를 항성 시계로 적분해 두 물리축(Az/Alt)을 함께 구동하는 구조라,
시계 스케일 오프셋이 그대로 sky RA 방향 이동으로 나타남을 확인했다.

- **INDI `TELESCOPE_TRACK_RATE`(표준 경로)는 사용 불가** — 드라이버 `SetTrackRate()`가 보내는
  `:RA`/`:RE`를 OnStepX 10.x가 트래킹 명령으로 받지 않음(프로퍼티 Alert).
  주의: 이 명령들은 OnStepX에서 **축 이동(슬루) 레이트 설정**으로 해석돼 `:GU#`의 rate index가
  변한다. 오염 시 `:R6#`(프리셋 재선택)으로 복원.
- **RA 방향 피드포워드는 `Tracking Frequency.trackFreq` 프로퍼티로 가능(검증됨)** —
  드라이버가 `:ST<Hz>#`로 전달. 대상 추적 환산: `Hz = 60.16427 × (1 − dRA/dt ÷ 15.0411)`
  (클럭이 빠르면 포인팅 RA가 감소하므로 동진(+dRA/dt) 대상은 느린 클럭.
  검산: 달 dRA/dt=+0.55″/s → 57.96 Hz = 전통 lunar rate).
  66 Hz(+9.7%) 설정 후 보고 RA 드리프트 실측 -1.542"/s (예상 1.459"/s, RA 15″ 양자화 오차 내)
  → 펌웨어가 실제 축 구동에 반영함을 확인. 수락 범위 실측 54~80 Hz(0.90×~1.33×), 2×(120 Hz)는
  거부 — 달(-3.5%)·혜성(±0.3%)에는 충분.
- **Dec "방향"(sky frame) 피드포워드는 펌웨어 미지원** — Alt/Az라 기계적으로는 두 축이 항상
  함께 움직이지만, 펌웨어가 받는 비항성 입력이 시계 스케일(RA 방향)뿐이고 Dec 방향 sky rate를
  줄 명령이 없다. Dec 방향 성분은 `indi_goto_guide_service`의 pulse guide 폐루프(target 좌표를
  에페메리스로 주기 갱신)로 처리 — 이 폐루프는 본 Alt/Az 마운트에서 이미 실전 검증된 경로다.
- 권장 구조: RA 방향 = trackFreq 피드포워드 + Dec 방향/잔차 = pulse guide 폐루프.
- **goto 후 유지 확인(2026-07-20 실측)**: 66 Hz 설정 → goto(RA +2.5°) → 완료 후 `:GT#` = 66.00000
  그대로 유지. 커스텀 주파수 상태에서 goto도 정상 수락. → goto마다 재적용할 필요 없음.
  재적용이 필요한 시점은 **드라이버 재연결 시**(enable_tracking의 TRACK_SIDEREAL 전환)뿐.
- **복원 방법 주의(실측)**: `TRACK_SIDEREAL=On` 재전송은 스위치가 이미 On이면 no-op라 `:TQ#`가
  전송되지 않음(주파수 안 돌아옴). 복원은 `trackFreq=60.16427` 직접 쓰기로 할 것
  (모드 스위치에 의존하지 말 것).
- 관찰 사항: sidereal 상태에서도 보고 Dec 드리프트 ~+0.2"/s 존재(PiFinder 서비스 정지 상태에서도
  지속). Alt/Az에서는 보고 RA/Dec이 축각+정렬 모델 변환 결과라 실내의 무의미한 정렬 모델 오차가
  sky-frame 드리프트로 보일 수 있음 — 실외 정렬 후 재측정으로 확인할 것.
- 참고: EQ용 "Multi-Axis Tracking" 상태가 N/A인 것은 Alt/Az에서 정상(항상 2축 구동).

<a id="mf_web_catalogs_dev_ko--p6-1-goto-진입점별-트래킹-주파수-정책-2026-07-20"></a>
#### P6-1 GoTo 진입점별 트래킹 주파수 정책 (2026-07-20)

세 진입점이 같은 정책을 공유하되 **대상 판별 방법이 다르다**.

| 진입점 | 판별 근거 | 구현 |
| --- | --- | --- |
| 웹 카탈로그 push | `obj_type == "Pla"` | `web_catalogs._apply_push_track_freq` |
| LCD GoTo(키패드 5) | `obj_type == "Pla"` | `track_freq_policy.track_freq_command_for_target` |
| SkySafari `:MS#` | **좌표 ↔ 에페메리스 대조** | `track_freq_policy.track_freq_command_for_coordinates` |

- 공통: 행성은 feed-forward 주파수를 걸고, 정적 대상은 **활성 비항성 주파수가 있을 때만**
  sidereal로 복원한다(이미 sidereal이면 무동작). 복원은 P6대로 `trackFreq` 직접 쓰기.
- SkySafari는 LX200 프로토콜상 천체 종류를 보내지 않으므로 좌표로 추정할 수밖에 없다.
  허용오차 6′는 LX200 양자화(RA 1s=15″, Dec 1″)와 에페메리스 차이를 흡수하면서
  달 시직경 30′보다 작아 이웃 천체와 충돌하지 않는 값으로 정했다.
- **좌표 추정은 어디까지나 추정이다** — 엄폐/합에서는 행성과 항성이 같은 좌표를 가진다.
  그래서 `skysafari_planet_track_freq`(기본 켜짐, SkySafari Mount Mode 카드)로 끌 수 있고,
  끄면 SkySafari 대상은 전부 sidereal로 처리한다. `obj_type`을 아는 웹/LCD 경로는
  **좌표 추정을 사용하지 않는다** — 선언된 타입이 항상 우선이다.

<a id="mf_web_catalogs_dev_ko--p6-2-해결-skysafari-좌표는-jnow-calc_planets는-j2000-2026-07-20-실측수정"></a>
#### P6-2 해결: SkySafari 좌표는 JNow, `calc_planets()`는 J2000 (2026-07-20 실측·수정)

웹에서 달 GoTo(주파수 정상 적용) → SkySafari에서 금성 GoTo 시 **60.16427 Hz(sidereal)로
리셋**되는 현상. 원인은 **좌표 분점(epoch) 불일치**다.

```
마운트 좌표(SkySafari가 보낸 값):  RA 163.5792  Dec 7.9008
금성 J2000 (calc_planets 반환값):  RA 163.2353  Dec 8.0447   → 분리 22.18′
금성 JNow  (radec(epoch='date')):  RA 163.5840  Dec 7.9027   → 분리  0.31′
```

- SkySafari ↔ OnStep 체인은 **JNow**로 일관되어 있다(그래서 GoTo 자체는 정확히 맞는다).
- `Skyfield_utils.calc_planets()`는 `apparent().radec()`을 인자 없이 호출하므로 **J2000(ICRS)**
  를 반환한다. JNow는 `radec(epoch='date')`로 받아야 한다.
- 세차 오차 22.2′가 허용오차 6′를 넘겨 매칭 실패 → "행성 아님" 판정 → sidereal 리셋.
- **주의: "GoTo가 잘 맞으니 양쪽 다 J2000"은 틀린 추론이다.** 양쪽이 일관되게 JNow였을 뿐이다.

**채택한 수정 (2안)**: `track_freq_policy.planet_positions_of_date()` — 매칭 전용으로
equinox-of-date 위치를 직접 계산한다. `calc_planets()`는 J2000 그대로 두어
카탈로그·차트·플롯 호출자에 회귀가 없다.

`calc_planets()`에 분점 옵션을 추가하는 1안은 호출자 범위가 넓어 채택하지 않았다.

**`mf_coordinate_helper_plan`의 원칙과의 관계**: "요청 좌표를 J2000/JNow 같은 epoch
이름으로 재해석하거나 변환하지 않는다"를 지킨다 — SkySafari가 보낸 좌표는 손대지 않고,
**에페메리스 쪽만 요청 좌표의 프레임으로 맞춘다.** 즉 프레임 경계는 좌표 서비스가 아니라
매칭 함수 안에 둔다.

주의: `planet_positions_of_date()`는 지심이 아닌 **지평 시차 포함 topocentric** 값이므로
관측지 위치가 없거나 틀리면 달이 최대 ~1° 어긋나 허용오차를 벗어난다.

검증 (2026-07-20): 사용자의 실제 금성 GoTo 좌표(RA 163.5792 Dec 7.9008)로 재현 →
`VENUS` 매칭, `set_track_freq 60.00012 Hz` 산출. 현재 하늘의 10개 천체 전부 왕복 통과.
회귀 테스트 `test_matching_uses_equinox_of_date_not_j2000`이 두 프레임의 분리가 허용오차를
넘는지 먼저 확인한 뒤 of-date는 매칭·J2000은 비매칭임을 검사한다.

부수 수정: 진단 로그(`TrackFreqPolicy`)가 INFO라 기본 설정에서 기록되지 않아 정작 실패했을
때 침묵했다. SD 쓰기를 늘리지 않도록 기본(`logconf_default.json`)은 ERROR로 두고,
진단용 `logconf_indi.json`에만 `TrackFreqPolicy: INFO`를 추가했다 — 웹 Logs 페이지에서
"Indi"로 전환하면 매칭 결과와 기각된 근접 후보의 분리 각도가 남는다.

---

<a id="mf_web_catalogs_dev_ko--5-테스트-계획"></a>
### 5. 테스트 계획

`python/tests/test_web_catalogs.py` — `test_api_extensions.py` 선례(Flask test client + `MockSharedState`)를 따른다.

- **P1**: `/catalogs` 200 + 21개 카탈로그 렌더 / 훅 실패 시 기존 라우트 생존(모듈 import 에러 주입)
- **P2**: 필터 조합 SQL 정합성(M 카탈로그 기준 건수 검증), WDS 페이지네이션 응답 시간(< 300ms 목표),
  `page_size` 상한, 잘못된 catalog code → 404
- **P3**: 이미지 존재/부재 경로, observed 조인
- **P4**: FastAltAz 결과를 `test_calc_utils.py` 기준값과 교차 검증, GPS 미고정 시 강등 동작
- **P5**: 비인증 push → 401, 인증 push → `ui_queue`에 `"push_object"` 적재 + `ui_state.add_recent` 호출 확인
- 실기기 수동 검증: Red Night 테마 가독성, 폰(좁은 화면) 레이아웃, LCD에 push 반영

---

<a id="mf_web_catalogs_dev_ko--51-마지막-방문-카탈로그-페이지-복귀-2026-08-08"></a>
### 5.1 마지막 방문 카탈로그 페이지 복귀 (2026-08-08)

GoTo 후 다른 페이지(원격 등)에 갔다가 네비 "Catalogs"로 돌아오면 홈이 아니라
**마지막으로 보던 카탈로그 페이지**(목록 `/catalogs/<code>` 또는 상세
`/catalogs/object/<id>`)로 복귀한다.

- 구현: 목록/상세 렌더 시 쿠키 `pf_last_catalog`(path=/catalogs, 30일)에
  해당 URL 저장(`_remember_catalog_page`). `/catalogs` 진입 시 쿠키가 있고
  **Referer가 카탈로그 섹션이 아니면** 그 URL로 302.
- 홈 접근 경로 보존: 카탈로그 페이지 안에서 홈으로 가는 이동(Referer가
  `/catalogs*`)은 리다이렉트하지 않으며, `?home=1`이 명시적 탈출구.
- 필터/페이지 상태는 URL에 없으므로(2.2, JS 메모리) 복귀 단위는 페이지 URL이다.
- 테스트: `test_catalogs_home_resumes_last_visited_page`,
  `test_catalogs_home_resumes_at_object_detail`.

---

<a id="mf_web_catalogs_dev_ko--6-리스크-및-결정-기록"></a>
### 6. 리스크 및 결정 기록

- **astro_data DB에 쓰기 금지** — 저장소 추적 파일이므로 인덱스 생성도 하지 않는다. 성능은 측정 후 판단.
- **skyfield를 서버 프로세스에 올리지 않는다** — FastAltAz로 충분. P6에서 재검토.
- **WDS 고도 정렬 비활성화** — 13만 행 전체 고도 계산은 페이지 요청당 비용이 과함.
- **base.html head 블록 미추가** — content 블록 안 `<link>`로 대체(HTML 표준 허용). upstream이 나중에
  head 블록을 추가하면 그때 이관.
- 문서/코드의 라인 번호는 2026-07-19 기준이며 upstream 머지로 이동할 수 있음 — 훅은 항상
  "api_extensions 훅 바로 아래"를 기준 위치로 삼는다.
