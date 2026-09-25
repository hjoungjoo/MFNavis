# Cedar-free 병합·배포 준비

작업 전 계획(2026-09-15): 테스트 브랜치 병합 후 신규 설치와 기존 갱신이
Cedar 미포함 소스를 유지하도록 경로를 고정하고, 검토되지 않은 옛 소스로의
갱신을 거부한다. native submodule을 고정 커밋으로 빌드한다. CI와 오프라인
이미지 검사를 추가하며 운영 장비의 서비스·부팅 설정은 지금 변경하지 않는다.

병합은 배포가 아니다. Git merge만으로 기존 OS의 서비스 파일이나 과거 작업
디렉터리가 없어지지 않으므로, 배포 단계의 이미지 검사가 별도로 필요하다.

## 준비한 동작

- 신규 설치 기본은 병합된 `main`이다. 검증 설치는 `MFNAVIS_INSTALL_BRANCH`로
  명시한다. 설치는 Cedar-free marker/파일 목록을 검사하고 pinned MF를 빌드한다.
- 기존 설치/갱신은 설치된 브랜치를 유지한다. detached HEAD와 추적 파일의
  로컬 변경은 거부하며, fast-forward만 허용한다. `release`로 자동 이동하지 않는다.
- updater는 checkout 전에 FETCH_HEAD의 marker, 알려진 Cedar 파일, MF gitlink를
  검사한다. 설치 재실행도 fast-forward 전 marker를 요구하며 이후 전체 목록을 검사한다.
- `scripts/setup_mfds.sh`로 고정 submodule을 빌드/검사한다.
- 과거 설치 백업은 실행 파일 위치에서 `docs/history/pifinder_setup_legacy.txt`로
  이동했다. 이력 문서이며 설치 진입점이 아니다.
- PR 및 main/release의 기존 nox CI에 `check_cedar_free.py` 검사를 추가했다.
  GitHub 브랜치 보호의 필수 체크 지정은 별도 저장소 설정이며 이번에 변경하지 않았다.

## 병합 때 수행할 순서

1. [MF 판매용 제품 사용 정책](../python/MFDS/docs/test_cedar_free_20260915/MF_COMMERCIAL_POLICY_ko.md)에
   따라 MF의 별도 승인 조건과 PiFinder의 기존 GPL을 유지할 배포 근거를 마련한다.
   독립 저작물 구성 또는 유효한 GPL 연결 예외를 검토하고 해당 버전을 gitlink로
   고정한다. MF에 GPL 선택권을 추가하는 대안은 사용자 요구에 맞지 않아 제외한다.
   FSL은 유지하며 테스트 기본은 독립 native worker+memfd다. ctypes는 명시적
   비교 모드로 남긴다. 프로세스 분리의 구현만으로 결합 배포의 법률 검토가
   완료됐다는 뜻은 아니다.
2. main 병합 후보에서 CI와 다음 명령을 실행한다. release를 배포한다면 같은
   변경을 release에도 포함해야 한다. `pifinder_setup.sh` 전체를 검사용으로 실행하지 않는다.

   ```bash
   python3 scripts/check_cedar_free.py --repo .
   bash scripts/setup_mfds.sh
   ```

3. 판매 이미지는 별도 staging 이미지에서 만든다. 현재 운영 SD 전체나 개발
   홈 디렉터리를 그대로 복사하지 않는다. 새 source snapshot과 pinned submodule,
   빌드 결과 및 라이선스 고지만 넣고 원본 관측 데이터/이전 checkout/Git 이력은 분리한다.
4. 기존 OS를 갱신하는 경우 **별도 배포 작업 시간**에 PiFinder를 정지하고 MF
   준비를 확인한 뒤, 해당 제품의 `cedar_detect.service`를 disable/stop한다.
   이전 Cedar 실행 파일, client/proto/pb2, `/etc`·`/lib`·`/usr/lib/systemd/system`의
   옛 unit/enable symlink/drop-in을 확인해 제거한다. 백업은 판매 이미지 밖에 둔다.
   테스트 override를 제거하고 운영 경로의 PiFinder unit을 확인한 뒤 재시작한다.
   이 서비스 변경 절차는 지금 실행하지 않았다.
5. 정지된 최종 이미지의 파일시스템을 별도 디렉터리에 마운트하고 검사한다.

   ```bash
   python3 scripts/check_cedar_free.py --repo . --image-root /mnt/mf-product-image
   ```

   검사는 읽기 전용이며 `/`을 거부한다. 알려진 바이너리/client/proto 이름,
   Cedar를 가리키는 systemd 설정·symlink, `.git` 잔여물을 찾는다. 심볼릭 링크를
   따라 호스트를 탐색하지 않는다. 이름을 바꾼 바이너리나 모든 외부 패키지의
   출처를 증명하는 SBOM/법률 검사는 아니다. native submodule 내용과 의존성도
   승인된 버전과 대조한다.
6. 실제 장비에서 냉부팅 후 PiFinder 실행 경로, MF 로딩, RAW/전처리 솔빙,
   마운트/GOTO를 확인한다. 그 결과와 최종 PiFinder/MF 커밋, 이미지 해시,
   대응 소스/설치 정보, 라이선스 고지를 배포 기록으로 남긴다.

## 검증

로컬 임시 Git 저장소로 정상 fast-forward, 브랜치 보존, Cedar 재유입 차단,
dirty/detached 거부를 실행했다. 모의 이미지에서 옛 unit, symlink, Git 이력을
탐지하는9개 테스트가 통과했다. 전체 단위 테스트는2335통과, 2skip,
723deselected, 기존 경고8개였다. shell 문법과 변경 Python lint 검사도 통과했다.
테스트의 post-update는 무해한 fixture이므로
운영 systemd·카메라·마운트 설정을 실행하지 않는다. 최종 수치는 작업 보고에 기록한다.
