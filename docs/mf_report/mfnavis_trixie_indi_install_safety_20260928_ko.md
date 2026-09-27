# Trixie INDI 설치 안전성 수정 및 검증

2026-09-28, `a9a08126` 기반 로컬 수정.

Trixie INDI 설치가 아카이브의 `0775` 디렉터리 권한을 `/`, `/usr`, `/usr/bin`,
`/usr/lib`에 덮어쓰던 문제를 수정했다. 기존 `/lib` 링크 파손 방지 기능은 유지하고,
아카이브 경로 제한, 디스크 여유 공간 검사, 설치 실패 시 복원과 영구 진단 로그를 추가했다.

## 수정한 동작

- 설치 tar에 `--no-overwrite-dir`을 추가해 기존 디렉터리의 권한·소유자를 보존한다.
  생성·설치 staging의 디렉터리는 `0755`로 정규화한다. 이전 아카이브도 수정된
  설치 코드로 설치하면 기존 시스템 디렉터리 metadata를 덮어쓰지 않는다.
- rootfs는 INDI 실행 파일, INDI 데이터·헤더, 확인된 지원 라이브러리와 udev 규칙만
  허용한다. `bash`, `sudo`, `rm`, `python3`, `systemctl`, libc, 로더 등 다른 시스템
  파일과 privileged mode, 과도한 압축 확장을 거부한다.
- 패키징 manifest의 상대 경로·`..` 경로와 staging 안의 심볼릭 링크를 경유하는
  쓰기를 거부한다. 생성된 아카이브도 checksum·플랫폼·payload 검증 후 분할한다.
- 손상된 `/lib`, `/bin`, `/sbin` 링크는 설치 전에 거부한다. 시스템 디렉터리를
  `rm -rf`로 삭제해서 복구하는 기존 루프는 제거했다.
- 재조립·압축 해제·native 배치·백업·가상환경 패키지 교체 공간을 단계별로 검사한다.
  같은 파일시스템의 요구 공간은 합산하고 256 MiB 여유분을 확보한다.
- 파일 교체 직전에 기존 native 파일, 전체 선택 가상환경, `ld.so.cache`,
  Web Manager unit 및 enable 링크, chrony 설정을 백업한다. 일반 오류와
  SIGINT/SIGTERM은 파일과 Python 환경을 복원한 뒤 기존 서비스를 시작한다.
  복원이나 runtime 갱신이 실패하면 서비스를 멈춘 채 백업과 복구 명령을 남긴다.
- 같은 체크아웃에서 동시에 두 설치가 실행되지 않게 잠금을 사용한다.
- INDI 설치 stdout/stderr는 `MFNavis_data/logs/indi-install-*.log`, 전체 setup은
  첫 apt 단계 전부터 `setup-*.log`에 기록한다. 전체 setup은 system journal을
  `Storage=persistent`, `SystemMaxUse=64M`, `RuntimeMaxUse=32M`,
  `SyncIntervalSec=30s`로 설정한다. `/tmp/indiserver.log`는 RAM 로그를 유지한다.
- Bookworm 아카이브의 Web Manager 의존성도 가상환경에 설치한다. 기존 v1의
  PyIndi/indiweb 파일 배치는 유지하며 Web Manager wrapper는 선택 가상환경의
  Python으로 실행한다.

## 갱신한 배포 파일

`dist/mfnavis-indi-trixie-arm64-v2.2.3.1-current.tar.gz`와 분할 파일 4개,
`.sha256`을 갱신했다. INDI 재빌드는 수행하지 않았다. 기존 native 파일과
Python wheel 453개는 바이트 단위 SHA-256이 동일하다.

변경된 내용은 디렉터리 metadata, 설치 도구, 재패키징 시각과 설치 안내다.
모든 아카이브 디렉터리 권한은 `0755`이고 동봉 도구는 현재 수정한 소스와 일치한다.
새 `indi_archive_transaction.py`도 동봉했다. 기존 native 소스·패치 provenance는 보존했다.

새 SHA-256:
`7179e8da0d433ae0560055b95bb5b6919d64f110fb00a7f6f3e4a0aed7c37d55`.

전체 압축 파일 크기는 193,952,159 bytes다. 분할 파일은 앞 세 개 각각
49,283,072 bytes, 마지막 파일은 46,102,943 bytes다.
분할 파일을 이어 붙인 SHA-256도 동일하다.

## 검증

- 관련 테스트 103개 통과. INDI 검증·플랫폼·setup·transaction·실제 설치 스크립트
  흐름과 기존 설치·이미지 캐시 테스트를 함께 실행했다.
- 실제 설치 스크립트의 시스템 작업을 임시 루트로 연결해 Python 설치 실패,
  import 실패, Web Manager 시작 실패, chrony 재시작 실패를 주입했다.
  네 가지 모두 native 파일·Python 파일·설정 복원이 서비스 재시작보다 먼저 수행됐다.
- 성공 경로에서는 새 INDI 파일이 설치되고 기존 디렉터리의 사용자 지정 `0750`이
  유지됐다. 핵심 실행 파일 표식도 유지됐다.
- 서비스 정지 전 preflight 실패, 복원 실패 시 백업 보존과 서비스 정지,
  동시 설치 거부를 검증했다.
- 현재 Trixie와 기존 Bookworm 배포본 모두 강화한 payload 검증을 통과했다.
- 새 전체 파일, 분할 파일, 동봉 도구의 `--verify-only` 검사를 현재
  aarch64/Python 3.13 환경에서 실행했다. sandbox 검증 중 mktemp만 사용자 디스크
  경로로 연결했고 apt·서비스 변경은 수행하지 않았다.
- Ruff 검사·형식 검사, 셸 구문 검사, `git diff --check` 통과. Graft graph 갱신 완료.

## 적용 범위와 복구 한계

로컬 소스와 배포 아카이브를 수정했다. GitHub에 push하지 않았고 현재 운영 시스템에
INDI를 재설치하거나 서비스를 변경하지 않았다. 현재 장비의 journal 영구 저장 설정도
전체 setup을 다음에 실행할 때 적용된다.

apt로 설치한 OS 의존성과 전체 MFNavis setup의 다른 변경은 INDI transaction의
복원 범위가 아니다. 전원 차단이나 SIGKILL은 EXIT trap을 실행할 수 없으므로,
설치 로그에 남은 `/var/tmp/mfnavis-indi.*/rollback` snapshot을 사용해 수동으로 복구한다.
복구 전에 MFNavis·Web Manager를 정지하고, helper 복원 후 `ldconfig`와
`systemctl daemon-reload`를 수행한 뒤 원래 사용하던 서비스를 시작한다.

새 장비의 당시 설치본·실패 단계와 로그가 없어 원래 먹통의 원인은 확정하지 못했다.
이번 수정은 점검에서 재현된 권한 변경과 확인된 설치 보호·진단의 부족을 해결한다.
