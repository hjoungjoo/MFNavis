# Cedar 없는 테스트 환경

이 checkout은 `test/cedar-free-20260915` 전용이다. 운영 `/home/pifinder/PiFinder`
및 부팅 서비스 경로는 유지한다. 테스트 코드에서 기본 데이터 경로는
`/home/pifinder/PiFinder_test_data`, runtime은 `/dev/shm/pifinder_test`다.

- [작업 전 계획](docs/test_cedar_free_20260915/PLAN_ko.md)
- [1단계 결과](docs/test_cedar_free_20260915/STAGE1_ko.md)
- [최종 비교 결과와 한계](docs/test_cedar_free_20260915/RESULTS_ko.md)

마운트 미연결 상태이므로 현재 테스트 설정의 `mount_control`과
`indi_tracking_guide_enabled`는 껐다. 운영 설정은 변경하지 않았다.

## 오프라인 실행

```bash
cd /home/pifinder/PiFinder_test
bash scripts/ensure_tetra3_link.sh .
make -C /home/pifinder/mf_detect_star_test -j2
PYTHONPATH=python python3 python/scripts/replay_star_preprocess_ab.py \
  /home/pifinder/PiFinder_test_data/corpora/20260915_fixed_lights \
  --lens manual --manual-focal 10.3889 \
  --output /home/pifinder/PiFinder_test_data/results/sep_repeat.csv
```

`PIFINDER_DETECTOR=sep`가 기본이다. `PIFINDER_DETECTOR=mf`로 자체 검출기를
선택한다. MF는 response 순서/2×2 binning/최대 48개가 기본이고
원본 재측정은 꺼져 있다. `.so`는 `MF_DETECT_LIBRARY`로 지정할 수 있다. 원본 영상·캐시는
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
