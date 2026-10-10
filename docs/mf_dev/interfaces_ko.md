# 입력·화면·웹·카탈로그

기준: 2026-10-10 작업 트리. 용어는 [UI CONTEXT](../ax/ui/CONTEXT.md)와
[Catalog CONTEXT](../ax/catalog/CONTEXT.md)를 따른다.

## 입력 이벤트와 사용자 매핑

GPIO 키패드, 실제 USB/Bluetooth HID, 개발용 local 키보드는 입력 생성 방식이 다르다.
숫자/문자 단발 이벤트와 press/release를 구분한다. 홀드 이동은 release·keepalive·
연결/제어 epoch를 함께 처리한다. 개발용 단발 키 시험만으로 하드웨어 홀드를 검증하지 않는다.

현재 HID 경로에는 `KeyboardMappingManager`와 `KeyboardDispatcher`가 있다.
물리 키 ID와 press/release가 담긴 이벤트를 받고, 키 캡처·사용자 매핑을 먼저 처리한 뒤
남은 UI keycode만 화면으로 전달한다. 사용자 매핑이 있는 경우 이전 고정 키표와 다를 수 있다.
`keyboard_mapping` 기본값은 빈 객체다. 오류 창 활성 시 held motion과 캡처를 중단하는
별도 경로를 사용한다. 예전 HID `0` 미전달 분석을 모든 사용자 매핑의 제한으로 일반화하지 않는다.

## LCD 공통 마운트 조작

`GuideKeyMixin`을 쓰는 페이지와 Object Details의 마운트 조작은 아래 기본 의도를 공유한다.
입력 화면·정렬 마법사·전용 INDI 패널은 화면 고유 키가 우선한다.

| 숫자 | 기본 의미 |
|---|---|
| `2/4/6/8` | 남/서/동/북 press-hold, 해제하면 축 이동 종료 |
| `0` | 일반 마운트 제어에서 전체 Stop과 추적/자동 보정 중단 |
| `5` | 타겟을 선택한 페이지의 GoTo |
| `7` | 해당 화면의 Sync/정렬 요청 |
| `9/3` | 슬루 속도 증가/감소 |
| `1` | 공통 맵 적용 화면에서 GoTo Type 세션 순환 |

문자 방향 조그와 대각 조작도 화면·매핑 정책에 따른다. `+/-`는 확대·스크롤·값 입력 등
콘텐츠 기능이며 공통 슬루 속도 키로 설명하지 않는다. Backlash의 `0` 입력 지우기처럼
같은 키가 다른 뜻인 입력 화면에서는 공통 Stop 표를 그대로 적용하지 않는다.
GoTo 진행 중 솔빙 없는 정렬 요청은 [사용자 도착 확인](mount_control_ko.md)으로 처리한다.

## 오류 알림

`operation_errors.py`와 LCD 오류 화면은 작업 실패 원인과 이동 한계 초과를 표시한다.
오류 창 닫기와 마운트 재시작은 서로 다른 동작이다.
한계 정지는 실제 위반 해소 및 명시적 사용자 Tracking On 조건을 따른다.
표시 문자열·번역·원인 코드와 현재 정지 latch를 함께 검증한다.

## 웹 카탈로그와 외부 Push

`web_catalogs.py`는 홈·목록·상세·검색/필터·천체 Push를 Flask에 등록한다.
저장 카탈로그와 행성/혜성의 시간 의존 좌표를 구분한다. 근처 탐색은 좌표 서비스의
신뢰 가능한 샘플을 우선하고 IMU fallback 사용 시 그 성격을 표시한다.
Push/GoTo는 공통 명령 큐로 전달하고 대상 종류에 따른 tracking-rate 정책을 적용한다.
웹 경로만으로 독립적인 마운트 보정 루프를 만들지 않는다.
Locations는 관측 위치와 표준 카탈로그를 관리하며 장소 변경은 포인팅·마운트 site/time에 반영한다.

SkySafari/LX200와 Stellarium 좌표 경로의 frame·단위·정렬 라우팅은
[포인팅 계약](positioning_ko.md)을 따른다. 웹 언어 설정은 [웹 언어 안내](../WEB_LANGUAGE_ko.md)를 참조한다.

## 소스와 회귀

- [물리 키 매핑](../../python/MFNavis/keyboard_mapping.py), [하드웨어 입력](../../python/MFNavis/keyboard_pi.py), [공통 화면](../../python/MFNavis/ui/base.py).
- [웹 카탈로그](../../python/MFNavis/web_catalogs.py), [API 확장](../../python/MFNavis/api_extensions.py), [작업 오류](../../python/MFNavis/operation_errors.py).
- [키 매핑 검사](../../python/tests/test_keyboard_mapping.py), [카탈로그 검사](../../python/tests/test_web_catalogs.py), [오류 검사](../../python/tests/test_operation_errors.py).

이전 고정 키맵 목표·페이지별 조사와 캐시 설계의 이력은 [인터페이스 이력](../history/development/interfaces.md)을 참조한다.

## 오프라인 캐시 다운로드와 문제 해결

[English](interfaces_ko.md) | [한국어](interfaces_ko.md)

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

### 실행 전 준비

- MFNavis가 인터넷에 연결되어 있어야 한다. AP 모드로 휴대기기만 연결한
  상태는 인터넷 연결이 아닐 수 있다.
- 전원과 저장 공간이 충분한 상태에서 실행한다. 기존 배포 이미지의
  13,000개 이상 카탈로그 이미지는 약 5GB 수준이므로, 전체 POSS+SDSS
  다운로드에는 **최소 6GB 이상의 여유 공간**을 권장한다. 실제 크기는
  서베이 응답과 현재 카탈로그에 따라 달라질 수 있다.
- 관측 중에는 실행하지 않는 것이 좋다. 다운로드와 카탈로그 생성이 CPU,
  네트워크 및 SD 카드 I/O를 사용한다.

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

### 문제 해결

| 증상 | 확인 및 조치 |
| --- | --- |
| 이미지가 전혀 늘지 않음 | MFNavis 자체가 인터넷에 연결되어 있는지, DNS와 HTTPS 연결이 가능한지 확인한다. |
| 저장 공간 부족 | `--images poss`로 SDSS를 제외하거나 더 큰 SD 카드/저장소를 사용한다. |
| 다운로드가 너무 느림 | `--workers`를 4~10 범위에서 조절한다. 네트워크가 불안정하면 낮은 값이 더 안정적일 수 있다. |
| 웹 상세 화면에 여전히 사진이 없음 | 해당 천체가 POSS 서베이 이미지가 없을 수 있다. 캐시가 있으면 웹 서버는 로컬 파일을 우선 사용한다. |

### 구현 참조

- 실행 스크립트: `scripts/warm_mfnavis_caches.py`
- 이미지 생성기: `python/MFNavis/gen_images.py`
- 웹 카탈로그 이미지 제공 경로: `python/MFNavis/web_catalogs.py`
- 캐시 위치 정의: `python/MFNavis/utils.py`
