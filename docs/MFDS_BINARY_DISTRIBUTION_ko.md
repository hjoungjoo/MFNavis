# MFDS 빌드 산출물 사용

## 관리 원칙

검출기·전처리·연동 모듈의 수정과 빌드는 [MFDS](https://github.com/hjoungjoo/MFDS)에서 수행한다. PiFinder는 MFDS 소스 서브모듈을 갖지 않고 `deployment/mfds.lock.json`에 고정된 정식 릴리즈 패키지를 설치한다. 현재 패키지는 MFDS v0.3.2이다.

패키지에 포함되는 것은 native 서버·공유 라이브러리·CLI 빌드 결과, 해석 실행에 필요한 GPL Python 연동 모듈과 지원 파일·문서·라이선스 고지다. C++ 원본·헤더·Makefile·Git 저장소는 설치하지 않는다. Python 파일을 PiFinder에서 수정하지 말고 MFDS에서 수정하고 새 패키지로 배포한다.

## 신규 설치

```bash
git clone https://github.com/hjoungjoo/MF_PiFinder.git PiFinder
cd PiFinder
bash scripts/setup_mfds.sh
bash scripts/ensure_tetra3_link.sh .
python/MFDS/build/mf_detect_star_server --version
```

MFDS용 `git submodule update`나 `make`는 필요 없다. `python/MFDS`는 다운로드한 패키지를 가리키는 심볼릭 링크다. 패키지는 `python/.mfds/<archive-SHA256>`에 저장된다. 두 경로 모두 PiFinder의 Git 추적에서 제외된다. 사용자 설정·부팅 설정은 설치 스크립트가 변경하지 않는다. Linux aarch64/x86_64와 glibc 2.36 이상을 지원한다. 기존 NixOS 관련 기능은 제거하지 않으며 이 바이너리를 NixOS native 환경에서 실행하는 것은 이번 검증 범위 밖이다.

## 기존 소스 설치의 전환

이번 전환은 `.gitmodules` 삭제가 포함되므로 기존 코드 전용 자동 갱신기는 별도 설치가 필요하다고 안내한다. 서비스 중지 상태에서 기존 MFDS 체크아웃의 변경 사항이 없는지 확인하고, 기존 `python/MFDS` 또는 더 오래된 검출기 폴더를 저장소 밖의 복구 위치로 이동한 후 새 코드를 적용하고 setup을 실행한다. 두 이름의 소스 폴더를 새 설치와 함께 사용하지 않는다.

설치 스크립트는 남아 있는 소스 폴더를 자동 삭제하지 않는다. 새 패키지와 동작을 확인한 뒤 이전 소스 복제본을 정리한다. 과거 설치 명령 `setup_mf_detect_star.sh`는 새 패키지 설치로 연결되는 호환 진입점이다.

## 검증과 업데이트

PiFinder는 버전·소스 커밋·아키텍처별 다운로드 URL·아카이브 SHA-256·패키지 manifest SHA-256을 고정한다. 다운로드 이후 해시, 경로 안전성, 모든 패키지 파일의 해시 및 서버 버전을 검사한 다음 링크를 교체한다. 최신 버전을 부팅 시 자동으로 조회하지 않는다. 재설치는 검증된 로컬 패키지를 재사용한다.

오프라인 설치도 동일한 고정 해시를 요구한다.

```bash
python3 scripts/install_mfds.py --archive /path/to/MFDS-0.3.2-linux-aarch64.tar.gz
```

이후 코드 업데이트는 후보 체크아웃에서 새 패키지를 먼저 설치·검증하고 기존 소스와 패키지 링크를 기록한다. 다운로드·검증 실패는 운영 링크를 바꾸지 않으며 활성화 이후 오류가 발생하면 이전 PiFinder 커밋과 MFDS 패키지 링크로 복구한다. 이전 버전 패키지는 복구용으로 캐시에 유지한다.

MFDS를 올릴 때는 MFDS 새 버전을 빌드·시험하고 같은 태그 릴리즈에 두 플랫폼의 tar.gz/sha256을 게시한 다음, PiFinder의 lock을 갱신하고 통합 테스트 후 배포한다. MFDS 소스에서의 직접 수정을 PiFinder 소비 경로에 적용하지 않는다. 캡처 provenance에는 MFDS 원본 커밋, 버전, 패키지 manifest 해시, 실제 실행 파일 해시가 기록된다.
