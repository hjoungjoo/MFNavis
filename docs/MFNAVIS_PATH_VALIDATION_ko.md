# MFNavis m2.6.11 경로 이전 검증

2026-09-23, Raspberry Pi 실기기에서 적용했다.

- 코어 회귀: 2,992 통과 / 4 건너뜀 (`python/`에서 웹·UI 테스트 제외)
- UI 회귀: 296 통과 / 2 건너뜀
- 배포·경로 이전 집중 검사: 30 통과
- MyPy: 210 소스 파일 오류 없음
- 커밋 전 필수 Nox type_hints / smoke_tests 검사 통과
- Ruff 검사·포맷 검사 및 셸 스크립트 35개 구문 검사 통과
- Sphinx 문서 빌드: 경고를 오류로 처리하여 통과
- Selenium 브라우저 테스트는 이번 검사에 포함하지 않음
- 코어 검사는 통과 요약 출력 후 multiprocessing 큐 정리에서 대기하여 SIGINT로 종료했다. 테스트 단언 실패는 없었으나 실행기 종료 대기는 남은 제한이다.

실기기 `mfnavis.service`는 `/home/pifinder/MFNavis/python`에서
`python -m MFNavis.main`으로 실행 중이다. 웹 홈에서 MFNavis와 m2.6.11을
확인하고, TCP 4030의 제품명 응답 `MFNavis#`를 확인했다.
주 서비스·AP 도우미·INDI 웹 매니저·Samba가 활성 상태이며 이전 후 오류 로그는 없다.
실제 별을 이용한 야간 관측 검증은 이번 경로 변경 검사에 포함하지 않는다.

설정 백업: `/var/backups/mfnavis-paths-20260923T042343Z`.
데이터 디렉터리와 config.json의 inode·소유자가 이동 전후 동일하다.
이전 도구를 재실행하면 이동·설정 변경 대상이 없는 것으로 확인했다.
로그인 계정과 홈은 그대로이며 기존 제품 경로는 호환 링크다.

MFDS 잠금 파일 SHA256:
`8b8e84986b3bdb26874237199262e0d0333dfebfbdd4e0aca1a2f7633c5cc1e2`.
설치된 PACKAGE.json SHA256:
`b3ea73acf2b93b0f696507a59f199af336d5dc2d6c888248085663cd3a437a35`.
MFDS 저장소의 기존 작업 상태도 변경하지 않았다.
