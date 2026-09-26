# MFNavis 오프라인 캐시 다운로드 가이드

[English](mf_cache_download_en.md) | [한국어](mf_cache_download_ko.md)

## 목적과 범위

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

## 실행 전 준비

- MFNavis가 인터넷에 연결되어 있어야 한다. AP 모드로 휴대기기만 연결한
  상태는 인터넷 연결이 아닐 수 있다.
- 전원과 저장 공간이 충분한 상태에서 실행한다. 기존 배포 이미지의
  13,000개 이상 카탈로그 이미지는 약 5GB 수준이므로, 전체 POSS+SDSS
  다운로드에는 **최소 6GB 이상의 여유 공간**을 권장한다. 실제 크기는
  서베이 응답과 현재 카탈로그에 따라 달라질 수 있다.
- 관측 중에는 실행하지 않는 것이 좋다. 다운로드와 카탈로그 생성이 CPU,
  네트워크 및 SD 카드 I/O를 사용한다.

## 기본 실행

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

## 필요한 범위별 실행

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

## 진행 상태와 완료 확인

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

## 중단과 재실행

네트워크가 끊기거나 작업을 멈춰야 하면 `Ctrl-C`로 종료한 뒤, 인터넷이
가능해졌을 때 같은 명령을 다시 실행한다. 이미 완성된 이미지 파일은
`gen_images`가 건너뛰고, 유효한 런타임 캐시는 다시 사용한다.

정적 캐시를 만드는 동안에는 행성·혜성 갱신 타이머와 혜성 자료 다운로드를
시작하지 않는다. 이미지도 완전히 저장된 뒤에만 최종 JPEG 경로로 옮긴다.
다운로드 실패가 있으면 명령은 실패 코드로 끝나며, 같은 명령을 다시 실행할 수
있다. SDSS 범위 밖의 천체는 `unavailable`로 집계하고 실패로 보지 않는다.
이전 버전에서 남은 손상 이미지는 해당 JPEG만 삭제한 뒤 다시 실행한다.
사용자 설정·관측 기록은 삭제하지 않는다.

## 문제 해결

| 증상 | 확인 및 조치 |
| --- | --- |
| 이미지가 전혀 늘지 않음 | MFNavis 자체가 인터넷에 연결되어 있는지, DNS와 HTTPS 연결이 가능한지 확인한다. |
| 저장 공간 부족 | `--images poss`로 SDSS를 제외하거나 더 큰 SD 카드/저장소를 사용한다. |
| 다운로드가 너무 느림 | `--workers`를 4~10 범위에서 조절한다. 네트워크가 불안정하면 낮은 값이 더 안정적일 수 있다. |
| 웹 상세 화면에 여전히 사진이 없음 | 해당 천체가 POSS 서베이 이미지가 없을 수 있다. 캐시가 있으면 웹 서버는 로컬 파일을 우선 사용한다. |

## 구현 참조

- 실행 스크립트: `scripts/warm_mfnavis_caches.py`
- 이미지 생성기: `python/MFNavis/gen_images.py`
- 웹 카탈로그 이미지 제공 경로: `python/MFNavis/web_catalogs.py`
- 캐시 위치 정의: `python/MFNavis/utils.py`
