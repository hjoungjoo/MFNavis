# 검출기 통합 관리

MF native 검출기, Python 전처리/검출 연결/프로필/anchor 실험/SEP 보조,
비교 스크립트와 관련 테스트·실험 문서의 정본은
[`mf_detect_star`](../python/mf_detect_star/README.md) 저장소다.
PiFinder의 `python/mf_detect_star` submodule은 사용할 정확한 커밋을 고정한다.
기존 `PiFinder.*` import 및 scripts/tests 경로는 상대 심볼릭 링크로 유지한다.

## 설치와 사용

```bash
bash scripts/setup_mf_detect_star.sh
PYTHONPATH=python python3 -m PiFinder.detector_profiles mf4p
PYTHONPATH=python python3 python/scripts/field_compare.py --help
```

setup은 고정 커밋 checkout과 빌드/검사만 한다. 서비스 전환이나 카메라·부팅 설정은
변경하지 않는다. 기본은 submodule의 `build/mf_detect_star_server`를 별도
프로세스로 실행하는 `MF_DETECT_TRANSPORT=process`다. 스레드별 worker와 memfd
공유 메모리를 재사용하여 RAW/전처리 병렬성을 유지한다. `MF_DETECT_SERVER`는
명시적 서버 경로 override다. `MF_DETECT_TRANSPORT=ctypes`와
`MF_DETECT_LIBRARY`는 기존 직접 호출 비교용이다. 서버 실패 시 자동으로 ctypes를
로드하지 않고 기존 SEP 보조 정책을 따른다. 임의의 형제 checkout을 암묵적으로
읽지 않는다. submodule이 없으면 먼저 setup을 실행해야 한다.

[프로토콜·종료·timeout 정책](../python/mf_detect_star/docs/PROCESS_PROTOCOL.md)을
참고한다. 별도 systemd 서비스 설치는 필요하지 않으며 호출 프로세스가 worker를
관리한다. 기본 요청 timeout은 500ms, 최초 시작 대기는 최소 2초다.

수정은 mf_detect_star 정본에서 수행하고 검사·커밋·푸시한다. 이후 PiFinder에서
승인된 커밋을 checkout하고 `git add python/mf_detect_star`로 참조 버전을 갱신한다.
`git submodule update --remote`를 부팅/실행 시 호출하지 않는다.
소스 배포는 submodule까지 포함한 recursive clone 또는 전체 source bundle로 제공한다.

[실측 기본값·비교 절차](https://github.com/hjoungjoo/mf_detect_star/blob/test/cedar-free-20260915/docs/test_cedar_free_20260915/FIELD_GUIDE_ko.md),
[라이선스 적용 범위](https://github.com/hjoungjoo/mf_detect_star/blob/test/cedar-free-20260915/LICENSING.md)를 참고한다.
Cedar의 native 라이선스 조건(5년 MIT 전환)과 기존 PiFinder 통합 코드의 GPL을
구분한다. PiFinder 카메라/solver 스케줄/서비스 orchestration은 본 저장소에서
계속 관리한다. 프로세스 전환에서도 기존 MF 우선/SEP 보조, RAW/전처리 스케줄,
정렬·보정 중 동기 대기 정책은 유지한다. 분리만으로 법적 적합성을 확정하지 않는다.

[라이선스 적용·통합 검증 완료 기록](https://github.com/hjoungjoo/mf_detect_star/blob/test/cedar-free-20260915/docs/CONSOLIDATION_RESULTS_ko.md)
은 정본 저장소에서 관리한다.

## 검색 속도 비교

Tetra3의 해시 일괄 계산과 충돌 조회 최적화는 기본 활성화된다. 후보/검색 순서,
1000ms 솔빙 제한, 품질 기준과 전처리 대기 정책은 유지한다.
`TETRA3_SEARCH_OPTIMIZED=0`으로 새 프로세스를 실행하면 이전 검색 연산으로
비교할 수 있다. 운영 서비스 전환은 별도 작업 요청 때만 수행한다.

```bash
PYTHONPATH=python python3 python/mf_detect_star/integrations/pifinder/scripts/compare_search_speed.py CORPUS CACHE NEW_RESULT.json --frames 120
```

이 도구는 검출 좌표를 공유하고 검색 캐시는 방식별로 분리해 실행 순서를
교대한다. 전처리 생성 시간을 제외한 검출+솔빙 지연을 측정한다. 상세 좌표와
영상은 로컬에 두고 집계만 공유한다. Tetra3는 두 검출기가 공통으로 사용하는
PiFinder 소스이며, 이 최적화는 MF native 검출기 자체의 변경이 아니다.

## 달·도심 조명 노출 실측

[중앙 하단 달 노출 비교 결과](https://github.com/hjoungjoo/mf_detect_star/blob/test/cedar-free-20260915/docs/test_cedar_free_20260915/MOON_LOWER_EXPOSURE_RESULTS_ko.md)
는 정본 MF 저장소에서 관리한다. 달이 보이던 336장과 이후 별도 40장을 기록했다.
RAW MF2/전체 영역 우선 탐색과 MF4p 전처리의 비교는 수동 하늘 마스크를 사용한
재생 실험이다. 운영 검색 순서·기본 프로파일·서비스·부팅 경로는 유지했으며,
수동 노출 실험 후 원래 `auto_star`와 gain `profile`로 복원했다.
원본 영상·관측 좌표·장비 설정은 로컬 보관하고 도구·문서·집계만 공유한다.
