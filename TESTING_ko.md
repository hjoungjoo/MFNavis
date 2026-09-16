# Cedar 없는 테스트 환경

누적 실측을 종합한 선택과 메모리 범위는
[현재 테스트 기본값](docs/test_cedar_free_20260915/CURRENT_DEFAULTS_ko.md),
재부팅 후 추가 개선은
[통합 최적화 결과](docs/test_cedar_free_20260915/INTEGRATED_OPTIMIZATION_RESULTS_ko.md)를 참조한다.

검출기·전처리·비교 도구·실험 문서의 정본은 `python/MFDS` submodule이다.
[통합 관리 안내](docs/DETECTOR_INTEGRATION_ko.md)와
[라이선스 범위](https://github.com/hjoungjoo/mf_detect_star/blob/test/cedar-free-20260915/LICENSING.md)를 따른다.

이 checkout은 `test/cedar-free-20260915` 전용이다. 운영 `/home/pifinder/PiFinder`
및 부팅 서비스 경로는 유지한다. 테스트 코드에서 기본 데이터 경로는
`/home/pifinder/PiFinder_test_data`, runtime은 `/dev/shm/pifinder_test`다.

- [확정 기본값·실측 비교·관측 좌표 저장](https://github.com/hjoungjoo/mf_detect_star/blob/test/cedar-free-20260915/docs/test_cedar_free_20260915/FIELD_GUIDE_ko.md)
- [이번 검증 결과](https://github.com/hjoungjoo/mf_detect_star/blob/test/cedar-free-20260915/docs/test_cedar_free_20260915/FIELD_RESULTS_ko.md)
- [Cedar Detect와 MF4p 직접 비교](https://github.com/hjoungjoo/mf_detect_star/blob/test/cedar-free-20260915/docs/test_cedar_free_20260915/CEDAR_AB_RESULTS_ko.md)
- [검색 속도 개선·전체 재검증](https://github.com/hjoungjoo/mf_detect_star/blob/test/cedar-free-20260915/docs/test_cedar_free_20260915/SPEED_RESULTS_ko.md)
- [Cedar 라이선스·소스 배포 점검과 미해결 사항](https://github.com/hjoungjoo/mf_detect_star/blob/test/cedar-free-20260915/docs/test_cedar_free_20260915/LICENSE_AUDIT_ko.md)
- [병합·설치·갱신·이미지 정리 절차](docs/CEDAR_FREE_MERGE_ko.md)
- [FSL/GPL 배포 선택안 상세](https://github.com/hjoungjoo/mf_detect_star/blob/test/cedar-free-20260915/docs/test_cedar_free_20260915/GPL_FSL_OPTIONS_ko.md)
- [MF만 판매용 제품 사용 승인: 정책과 미해결 사항](https://github.com/hjoungjoo/mf_detect_star/blob/test/cedar-free-20260915/docs/test_cedar_free_20260915/MF_COMMERCIAL_POLICY_ko.md)
- [원본 PiFinder의 Cedar 상용 허락·별도 서버 구조 확인](https://github.com/hjoungjoo/mf_detect_star/blob/test/cedar-free-20260915/docs/test_cedar_free_20260915/UPSTREAM_LICENSE_DISTRIBUTION_ko.md)
- [MF 독립 프로세스·공유 메모리 적용 및 실측 결과](https://github.com/hjoungjoo/mf_detect_star/blob/test/cedar-free-20260915/docs/test_cedar_free_20260915/PROCESS_RESULTS_ko.md)
- [MF 내부 전처리 추가의 라이선스·출처 검토](https://github.com/hjoungjoo/mf_detect_star/blob/test/cedar-free-20260915/docs/test_cedar_free_20260915/PREPROCESS_LICENSE_REVIEW_ko.md)
- [작업 전 계획](https://github.com/hjoungjoo/mf_detect_star/blob/test/cedar-free-20260915/docs/test_cedar_free_20260915/PLAN_ko.md)
- [1단계 결과](https://github.com/hjoungjoo/mf_detect_star/blob/test/cedar-free-20260915/docs/test_cedar_free_20260915/STAGE1_ko.md)
- [최종 비교 결과와 한계](https://github.com/hjoungjoo/mf_detect_star/blob/test/cedar-free-20260915/docs/test_cedar_free_20260915/RESULTS_ko.md)
- [추가 실험: 다단계 해상도·별 주변 ROI 비교](https://github.com/hjoungjoo/mf_detect_star/blob/test/cedar-free-20260915/docs/test_cedar_free_20260915/PYRAMID_RESULTS_ko.md)
- [현재 MF 우선 정책과 RAW/전처리 비교](https://github.com/hjoungjoo/mf_detect_star/blob/test/cedar-free-20260915/docs/test_cedar_free_20260915/MF_PRIMARY_RESULTS_ko.md)
- [동기 예외를 유지한 실행 구조](https://github.com/hjoungjoo/mf_detect_star/blob/test/cedar-free-20260915/docs/test_cedar_free_20260915/MF_PRIMARY_FLOW_ko.md)
- [별도 실험: 항상 병렬 전처리 기준점과 RAW 변화량](https://github.com/hjoungjoo/mf_detect_star/blob/test/cedar-free-20260915/docs/test_cedar_free_20260915/ANCHOR_RESULTS_ko.md)

마운트 미연결 상태이므로 현재 테스트 설정의 `mount_control`과
`indi_tracking_guide_enabled`는 껐다. 운영 설정은 변경하지 않았다.

## 오프라인 실행

```bash
cd /home/pifinder/PiFinder_test
bash scripts/ensure_tetra3_link.sh .
bash scripts/setup_mfds.sh
PYTHONPATH=python python3 python/scripts/replay_star_preprocess_ab.py \
  /home/pifinder/PiFinder_test_data/corpora/20260915_fixed_lights \
  --lens manual --manual-focal 10.3889 \
  --output /home/pifinder/PiFinder_test_data/results/mf_repeat.csv
```

`PIFINDER_DETECTOR=mf`가 기본이다. RAW와 전처리 모두 전체4×4 축소 탐색 후
후보 주변2×2 정밀화, response 순서/최대48개를 사용한다. 필터 후 후보5개
미만 또는 native 실행 오류일 때만 SEP를 보조로 호출한다. 후보가 충분한
솔빙 실패에서는 SEP를 재호출하지 않고 기존 전처리 복구 경로를 따른다.
순수 MF 비교는 `MF_DETECT_SEP_FALLBACK=0`, 기존 전체1/2 방식은
`MF_DETECT_BINNING=2 MF_DETECT_PYRAMID=0`으로 재현한다.
`PIFINDER_DETECTOR=sep`는 별도 비교용이다. 원본 재측정은 꺼져 있다.
기본은 `MF_DETECT_TRANSPORT=process`이며 `MF_DETECT_SERVER`로 서버를 지정한다.
직접 호출 비교는 `MF_DETECT_TRANSPORT=ctypes`, `.so` override는
`MF_DETECT_LIBRARY`다. 프로세스 오류에 직접 호출로 자동 전환하지 않는다.
동일 RAW/전처리 A/B는 `python/scripts/compare_detector_transport.py`를 사용한다.
전처리 실행 위치와 캐시 개선 비교는
`python/scripts/benchmark_preprocess_placement.py`를 사용한다.
[실측 계획](docs/test_cedar_free_20260915/PREPROCESS_PLACEMENT_PLAN_ko.md)과
[결과·재현 절차](docs/test_cedar_free_20260915/PREPROCESS_PLACEMENT_RESULTS_ko.md)를
참조한다. 통합 프로세스는 성능 비교용이며 서비스 선택 모드가 아니다.
원본 영상·캐시는
Git에 추가하지 않으며 공유할 집계 결과와 재현 절차만 문서화한다.

## 서비스를 명시적으로 전환할 때

아래 명령은 사용자가 서비스 전환 작업을 요청했을 때만 실행한다.

```bash
sudo scripts/test_runtime.sh start sep
sudo scripts/test_runtime.sh start mf
sudo scripts/test_runtime.sh restore
scripts/test_runtime.sh status
```

`start`는 `/run/systemd/system/pifinder.service.d/90-detector-test.conf`만
추가한다. `restore`는 이 파일만 제거하고 운영 서비스를 다시 시작한다.
enable/disable이나 `/etc`·`/lib`의 영구 unit을 변경하지 않는다. 재부팅하면
runtime override가 사라져 운영 소스가 실행된다. 이 작업에서는 스위치 스크립트를
구문 검사만 했으며 실제 서비스 전환은 실행하지 않았다.
