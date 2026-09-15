# MFDS v0.2.0 / PiFinder m2.6.5 릴리즈

## 작업 계획

- MFDS `VERSION`을 빌드 기준으로 사용해 CLI·서버·C API 버전을 표시한다. 릴리즈 태그, 변경 기록, 실행 파일 버전 일치를 CI에서 검사한다.
- immutable MFDS v0.2.0 태그를 정식 릴리즈하고 PiFinder는 해당 커밋을 고정한다. PiFinder m2.6.5도 별도 태그로 정식 릴리즈한다.
- 관측 캡처에 MFDS 소스 버전 및 버전 파일 해시를 추가한다. 기존 실행 바이너리 해시와 함께 비교한다.
- native·통합·정적 검사와 원격 CI 후 배포한다. 서비스와 실제 솔빙을 짧게 확인하고 결과를 기록한다. 알고리즘·NixOS·부팅 서비스·90초각 사용자 설정은 유지한다.

## 결과

- MFDS v0.2.0, 고정 커밋 `15da1f813893e54d302e8a8bd23f2c6d2c50720c`를 정식 게시했다. [릴리즈](https://github.com/hjoungjoo/MFDS/releases/tag/v0.2.0).
- MFDS native 7/7, process/ctypes 통합 46개, CLI·서버·C API 버전 일치 및 잘못된 태그 거부 검사 통과. 소스 아카이브는 Git 정보 없이 빌드했다. [CI 35004445500](https://github.com/hjoungjoo/MFDS/actions/runs/35004445500)의 sanitizer·누수 검사·libpng 없는 빌드도 통과했다.
- PiFinder m2.6.5는 위 MFDS 커밋을 submodule로 고정한다. unit/smoke 2,452개 통과, 2개 skip. Ruff·포맷·MyPy(205개 파일)·Cedar 운영 잔여 검사 통과.
- 기록 manifest의 `environment.detector_runtime.mf_source_version`에 `0.2.0`과 VERSION 파일 해시가 추가된다. 실행 파일의 출처는 기존 running_workers 해시와 함께 확인한다.
- 알고리즘은 직전 323/323 실측의 코드와 동일하다. 이번 변경은 버전 표시·검사 및 출처 기록이다.
- 최종 태그 커밋·원격 CI·운영 서비스 확인은 [m2.6.5 정식 릴리즈 본문](https://github.com/hjoungjoo/MF_PiFinder/releases/tag/m2.6.5)에 기록한다. 원본 테스트 데이터·장비 설정은 공개하지 않는다.

