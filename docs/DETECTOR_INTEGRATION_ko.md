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
변경하지 않는다. 기본 라이브러리는 submodule의 `build/libmf_detect_star.so`다.
임의의 형제 checkout을 암묵적으로 읽지 않으며 `MF_DETECT_LIBRARY`만 명시적
override로 허용한다. submodule이 없으면 먼저 setup을 실행해야 한다.

수정은 mf_detect_star 정본에서 수행하고 검사·커밋·푸시한다. 이후 PiFinder에서
승인된 커밋을 checkout하고 `git add python/mf_detect_star`로 참조 버전을 갱신한다.
`git submodule update --remote`를 부팅/실행 시 호출하지 않는다.
소스 배포는 submodule까지 포함한 recursive clone 또는 전체 source bundle로 제공한다.

[실측 기본값·비교 절차](https://github.com/hjoungjoo/mf_detect_star/blob/test/cedar-free-20260915/docs/test_cedar_free_20260915/FIELD_GUIDE_ko.md),
[라이선스 적용 범위](https://github.com/hjoungjoo/mf_detect_star/blob/test/cedar-free-20260915/LICENSING.md)를 참고한다.
Cedar의 native 라이선스 조건(5년 MIT 전환)과 기존 PiFinder 통합 코드의 GPL을
구분한다. PiFinder 카메라/solver 스케줄/서비스 orchestration은 본 저장소에서
계속 관리한다. 이번 변경은 파일 위치와 참조 경로의 통합이며 검출 정책 변경이 아니다.
