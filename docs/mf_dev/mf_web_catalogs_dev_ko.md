# MF_PiFinder — Web Catalogs 페이지 개발 문서

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

## 1. 대원칙: 신규 소스 분리 / 원소스 최소 변경

이 저장소는 upstream(brickbots/PiFinder) 머지를 계속 받아야 하므로, **기능 전체를 신규 파일에 구현**하고
원소스는 "등록 지점"만 건드린다. 선례는 `api_extensions.py`이며 동일한 패턴을 따른다
(`server.py` 말미의 try/except 3줄 훅 → `register_api_routes(app, self, ...)`).

### 1.1 원소스 변경 지점 (전체 목록 — 이 2곳이 전부)

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

### 1.2 신규 파일 (기능 본체)

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

## 2. 아키텍처와 데이터 접근

웹 서버는 별도 프로세스이지만 `Server` 인스턴스가 이미 다음을 보유한다
(`register_catalog_routes(app, server_instance)` 로 전달받아 사용):

- `server_instance.shared_state` — 위치·시각·ui_state
- `server_instance.ui_queue` — LCD로 명령 전달

### 2.1 천체 데이터 (읽기 전용 SQLite)

- 대상: `astro_data/pifinder_objects.db` (`utils.pifinder_db`)
  - `objects`(149,329) / `catalog_objects`(151,170) / `catalogs`(21) / `names`(430,288) / `object_images`
- `web_catalogs.py`가 **자체 읽기 전용 커넥션**을 연다:
  `sqlite3.connect(f"file:{utils.pifinder_db}?mode=ro", uri=True, check_same_thread=False)`
  - 기존 `db/objects_db.py`는 목록형 API만 있어 페이지네이션/필터 SQL에 부적합 → 원소스를 고치지 않고
    신규 모듈 안에 전용 쿼리 계층을 둔다.
  - 이 DB는 저장소에 포함된 빌드 산출물이므로 **절대 쓰기 금지** (인덱스 추가도 금지).
    Pi에서 catalog_code 조건의 15만 행 스캔은 수십 ms 수준 — 페이지당 1쿼리면 충분하다.

### 2.2 필터·정렬·페이지네이션 (WDS 131k 대응)

- 전부 **서버측 SQL**: `WHERE catalog_code=? AND obj_type IN (...) AND const=? AND filter_mag<=?`
  + `LIMIT/OFFSET`. `mag`은 JSON 텍스트이므로 `json_extract(mag,'$.filter_mag')` 사용.
- 이름 검색은 `names.common_name LIKE` (통합 검색은 전 카탈로그 대상, LIMIT 50).
  이름 검색 자체도 **q로 시작하는 이름 우선 → 짧은 이름 → 알파벳순**으로 정렬한다
  (`ORDER BY (common_name LIKE 'q%') DESC, LENGTH, common_name`, WHERE는 `%q%`).
- "Up now"(현재 고도) 필터/정렬: 페이지 크기(≤200행) 범위에서만 고도를 계산하면 정렬이 왜곡되므로,
  고도 정렬 시에는 **필터 통과 행 전체의 (ra,dec)를 가져와 numpy 일괄 계산 후 정렬 → 페이지 슬라이스**.
  Messier급은 문제없고 WDS는 고도 정렬을 비활성화(시퀀스 정렬 고정)한다 — UI에서 안내 문구 표시.

### 2.2.1 홈 통합검색 지정번호 정렬 (2026-07-22)

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

### 2.2.2 주변 관측 대상 (2026-09-13)

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
- 해당 카탈로그의 전체 필터 결과를 관측 난이도 → 구면 각거리 순으로 정렬한
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

보틀/SQM 정렬:

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
- 측광·크기가 없거나 모델이 적용되지 않는 대상은 Unknown으로 뒤에 둔다.
  난이도가 같으면 가까운 순이다. 현재 페이지만 재정렬하지 않는다.
  유효한 하늘 밝기나 장비 정보가 없으면 거리순으로 돌아가며 이유를 표시한다.
- 참고: [pydeepskylog](https://pypi.org/project/pydeepskylog/),
  집광 면적과 한계등급의 근사 관계는
  [CAAA 관측 입문 자료](https://caao.ca/wp-content/uploads/2023/02/CAAO-tutorial.pdf).

### 2.3 고도/방위 계산 — skyfield 금지, FastAltAz 사용

- `calc_utils.FastAltAz`(`calc_utils.py:23`, `radec_to_altaz`)는 순수 수식이라 가볍다.
  서버 프로세스에서 `Skyfield_utils`(de421.bsp 로드)를 **새로 인스턴스화하지 않는다** (메모리·기동시간).
- 위치·시각은 `shared_state.location()` / `shared_state.datetime()` — pos_server와 동일한 소비 방식.
- 상세 화면의 "오늘 밤 고도 곡선"과 transit: 일몰~일출 구간을 10분 간격 샘플링해 FastAltAz로 계산,
  JSON으로 내려 캔버스에 그린다. GPS 미고정 시 고도 관련 UI는 "위치 대기 중"으로 강등(테이블 자체는 동작).

### 2.4 이미지

- `cat_images.resolve_image_name(obj, "POSS")` + `BASE_IMAGE_PATH`(=`{utils.data_dir}/catalog_images`) 재사용.
- 신규 라우트가 `send_from_directory` 로 서빙, 파일 없으면 404 → 프런트에서 플레이스홀더 표시.

### 2.5 관측 이력

- `db/observations_db.py` `ObservationsDatabase.get_observed_objects()` 재사용 (읽기 전용).
- 목록의 ✓ 컬럼, "Not observed" 필터, 상세의 "Observed n회"에 사용.

### 2.6 Push to PiFinder (핵심 액션)

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

### 2.7 인증

- 조회 페이지: 기존 페이지들과 동일하게 비인증 허용.
- **push 등 상태 변경 엔드포인트: `@auth_required`**(`server.py:69`의 기존 데코레이터를 import) 적용.
  로그인은 기존 `/login`(시스템 계정 PAM) 흐름 그대로.

### 2.8 i18n / 테마

- 템플릿 문자열은 전부 `{{ _('...') }}` — 기존 Babel 설정이 그대로 적용된다.
- 색·간격은 `--pf-*` 토큰만 사용(신규 색상 하드코딩 금지) → Red Night 테마 자동 대응.
  고도곡선 캔버스도 `getComputedStyle`로 토큰을 읽어 그린다.

---

## 3. 라우트 설계

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

## 4. 단계별 구현 계획

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

### P6 사전 검증: INDI 비항성 트래킹 (2026-07-19 실기기 검증 완료)

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

### P6-1 GoTo 진입점별 트래킹 주파수 정책 (2026-07-20)

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

### P6-2 해결: SkySafari 좌표는 JNow, `calc_planets()`는 J2000 (2026-07-20 실측·수정)

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

## 5. 테스트 계획

`python/tests/test_web_catalogs.py` — `test_api_extensions.py` 선례(Flask test client + `MockSharedState`)를 따른다.

- **P1**: `/catalogs` 200 + 21개 카탈로그 렌더 / 훅 실패 시 기존 라우트 생존(모듈 import 에러 주입)
- **P2**: 필터 조합 SQL 정합성(M 카탈로그 기준 건수 검증), WDS 페이지네이션 응답 시간(< 300ms 목표),
  `page_size` 상한, 잘못된 catalog code → 404
- **P3**: 이미지 존재/부재 경로, observed 조인
- **P4**: FastAltAz 결과를 `test_calc_utils.py` 기준값과 교차 검증, GPS 미고정 시 강등 동작
- **P5**: 비인증 push → 401, 인증 push → `ui_queue`에 `"push_object"` 적재 + `ui_state.add_recent` 호출 확인
- 실기기 수동 검증: Red Night 테마 가독성, 폰(좁은 화면) 레이아웃, LCD에 push 반영

---

## 5.1 마지막 방문 카탈로그 페이지 복귀 (2026-08-08)

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

## 6. 리스크 및 결정 기록

- **astro_data DB에 쓰기 금지** — 저장소 추적 파일이므로 인덱스 생성도 하지 않는다. 성능은 측정 후 판단.
- **skyfield를 서버 프로세스에 올리지 않는다** — FastAltAz로 충분. P6에서 재검토.
- **WDS 고도 정렬 비활성화** — 13만 행 전체 고도 계산은 페이지 요청당 비용이 과함.
- **base.html head 블록 미추가** — content 블록 안 `<link>`로 대체(HTML 표준 허용). upstream이 나중에
  head 블록을 추가하면 그때 이관.
- 문서/코드의 라인 번호는 2026-07-19 기준이며 upstream 머지로 이동할 수 있음 — 훅은 항상
  "api_extensions 훅 바로 아래"를 기준 위치로 삼는다.
