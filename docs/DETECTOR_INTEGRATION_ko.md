# 검출기 통합 관리

소스 수정과 빌드는 공개 [MFDS](https://github.com/hjoungjoo/MFDS)에서 수행한다.
PiFinder의 `python/MFDS`는 `deployment/mfds.lock.json`에 고정된 MFDS 릴리즈 패키지다.
Python 연동 모듈·지원 도구도 MFDS 패키지에서 공급하며 기존 `PiFinder.*` import와 scripts/tests 링크를 유지한다.

## 설치와 사용

```bash
bash scripts/setup_mfds.sh
PYTHONPATH=python python3 -m PiFinder.detector_profiles mf4p
PYTHONPATH=python python3 python/scripts/field_compare.py --help
```

설치는 아키텍처·버전·해시를 검증하고 패키지 링크를 교체한다. MFDS 소스 clone·submodule·make는 사용하지 않는다.
기본 서버는 패키지의 `build/mf_detect_star_server`이며 스레드별 worker와 memfd 공유 메모리로 RAW/전처리 병렬성을 유지한다.
`MF_DETECT_SERVER`, `MF_DETECT_LIBRARY`, `MF_DETECT_TRANSPORT` 비교용 설정은 유지한다. 기본값은 별도 프로세스다.
기존 native 라이선스 조건과 GPL Python 연동 코드 고지를 패키지에 포함한다.

[설치·소스 버전 전환·롤백 안내](MFDS_BINARY_DISTRIBUTION_ko.md)와
[MFDS 프로세스 프로토콜](https://github.com/hjoungjoo/MFDS/blob/v0.3.0/docs/PROCESS_PROTOCOL.md)을 참고한다.

## 검색 속도 비교

Tetra3의 해시 일괄 계산과 충돌 조회 최적화는 기본 활성화된다. 후보/검색 순서,
1000ms 솔빙 제한, 품질 기준과 전처리 대기 정책은 유지한다.
`TETRA3_SEARCH_OPTIMIZED=0`으로 새 프로세스를 실행하면 이전 검색 연산으로
비교할 수 있다. 운영 서비스 전환은 별도 작업 요청 때만 수행한다.

```bash
PYTHONPATH=python python3 python/MFDS/integrations/pifinder/scripts/compare_search_speed.py CORPUS CACHE NEW_RESULT.json --frames 120
```

이 도구는 검출 좌표를 공유하고 검색 캐시는 방식별로 분리해 실행 순서를
교대한다. 전처리 생성 시간을 제외한 검출+솔빙 지연을 측정한다. 상세 좌표와
영상은 로컬에 두고 집계만 공유한다. Tetra3는 두 검출기가 공통으로 사용하는
PiFinder 소스이며, 이 최적화는 MF native 검출기 자체의 변경이 아니다.

## 달·도심 조명 노출 실측

[중앙 하단 달 노출 비교 결과](https://github.com/hjoungjoo/MFDS/blob/2be2336635384e350fb50f9fcc91f501c00a4dde/docs/test_cedar_free_20260915/MOON_LOWER_EXPOSURE_RESULTS_ko.md)
는 정본 MF 저장소에서 관리한다. 달이 보이던 336장과 이후 별도 40장을 기록했다.
RAW MF2/전체 영역 우선 탐색과 MF4p 전처리의 비교는 수동 하늘 마스크를 사용한
재생 실험이다. 운영 검색 순서·기본 프로파일·서비스·부팅 경로는 유지했으며,
수동 노출 실험 후 원래 `auto_star`와 gain `profile`로 복원했다.
원본 영상·관측 좌표·장비 설정은 로컬 보관하고 도구·문서·집계만 공유한다.

## 토성 GoTo 후 추적 실측

[토성 추적 결과](https://github.com/hjoungjoo/MFDS/blob/2be2336635384e350fb50f9fcc91f501c00a4dde/docs/test_cedar_free_20260915/SATURN_GOTO_RESULTS_ko.md)
는 정본 MF 저장소에서 관리한다. RAW 240장과 별도 추적 상태 180초를 기록하고,
32장에 RAW/전처리 MF4p·MF2를 비교했다. 실제 추적은 기존 Cedar 운영 서비스,
MF는 오프라인 재생이므로 MF로 GoTo 제어를 검증한 결과는 아니다.
RAW 기록 출력은 복원했고 노출·gain·부팅·운영 경로는 유지했다.
수집 시 `capture_detector_corpus.py --conditions`에 실제 환경을 적을 수 있다.
참조 갱신 후 통합 배치 검사 `test_detector_integration_layout.py` 3개와
수집 도구 Ruff lint/format 검사를 통과했다.

MFDS 공개 이관(m2.6.4): [공개 저장소](https://github.com/hjoungjoo/MFDS)에서
당시 고정 소스를 인증 없이 받도록 전환했다. 현재는 바이너리 릴리즈 패키지를 사용한다. [이관 기록](MFDS_MIGRATION_ko.md)을 참고한다.

## 운영 패키지와 비교 도구

`bash scripts/setup_mfds.sh`는 서버·CLI·공유 라이브러리와 GPL Python 지원 도구가 포함된 패키지를 설치한다.
이전 `--runtime` 및 `--with-tools` 옵션은 호환용으로 받아들이지만 PiFinder에서 빌드하지 않는다.

`solver_cedar_fullframe`과 `solver_cedar_ff_gates`는 더 이상 사용하지 않는다.
MFDS의 전체 RAW 입력은 항상 게시하며 품질 필터는 `star_detect`가 적용한다.
기존 설정 파일에 남은 Cedar 키는 무시한다. `solver_preprocess_mode=auto`가
기본이며 옛 `solver_preprocess_async` 키는 모드가 없는 설정의 호환 판독만
유지한다. `sep_*` 솔빙 경로와 과거 진단 필드명은 기록 호환용이므로 실제
검출기는 `detector_backend`로 구분한다. NixOS 경로는 이번 정리에서 유지한다.
