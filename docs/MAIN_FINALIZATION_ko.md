# 메인 병합과 최종 서비스 전환 — 2026-09-15

사용자 요청에 따라 검증된 테스트 브랜치를 main에 병합하고 운영 서비스도
최종 소스로 전환한다. 확정 구성은 MF4p RAW + MF4p 전처리, auto 스케줄,
native process/memfd, 전처리 3작업자/5프레임, SEP 검출 실패 보조다.
[MF 정본 결정](../python/mf_detect_star/docs/MAIN_FINALIZATION_ko.md)에 근거를 정리했다.

## 작업 전 계획과 변경 범위

- 기존 main `c1101d9f`와 테스트 `e72a747c`를 별도 main 작업 디렉터리에서 병합한다.
- MF main `c76a1ed`를 고정하고 `.gitmodules`의 참고 브랜치를 main으로 변경한다.
  설치/실행은 항상 gitlink 커밋을 사용하며 floating update를 하지 않는다.
- 테스트에서 바뀐 기본 데이터·상태 경로를 `~/PiFinder_data`, `/dev/shm/pifinder`로
  복원한다. `PIFINDER_DATA_DIR`/`PIFINDER_RUNTIME_DIR` 명시적 테스트 override는 유지한다.
- Cedar 바이너리·unit·client 없는 소스, pinned MF 빌드, 갱신 사전 검사와
  rollback 절차를 main에 포함한다. 설치 스크립트 전체를 운영 장비에서 실행하지 않는다.
- 원본 README의 upstream 소개와 현재 포크의 MF 구성을 구분한다.
- 전체 단위/smoke, lint/format/type, native, 설치/갱신·기본 경로 검사를 실행한다.
- 현재 설정·운영 로그·옛 service unit·소스 커밋을 로컬에 보존한 뒤 PiFinder를
  정지하고 운영 checkout을 fast-forward한다. MF 빌드와 import를 확인한 후
  Cedar unit을 해제하고 기존 PiFinder unit의 운영 경로에서 재시작한다.
- MF worker, RAW/전처리 solve, 좌표 갱신과 마운트 연결 상태를 기록한다.
  실패하면 이전 소스·unit으로 복구한다. 새 GoTo/Sync 명령은 보내지 않는다.

노출·gain·사용자 정렬/장비 설정은 바꾸지 않는다. 서비스 전환은 코드와 검출기
변경이며 현재 설정을 유지한다. 재부팅은 실행하지 않고 이후 부팅도 기존
PiFinder unit이 갱신된 운영 소스를 읽도록 한다.

## 병합 검증 결과

- 단위/smoke: 2420 통과, 2 skip, 706 deselected. 기존 NumPy 경고 12개.
- 기본 데이터·상태 경로 및 submodule 연결 추가 검사: 5 통과.
- Python 전체 lint 통과, 428개 format 통과, MyPy 206개 소스 통과.
- pinned MF 빌드와 native 합성 회귀 6/6, 라이선스 원문·정본 배치 검사 통과.
- main 커밋의 Cedar artifact/gitlink 검사와 설치·갱신 shell 문법 검사 통과.
- 알고리즘은 실측한 테스트 소스를 유지한다. 배포 준비에서 경로 기본값과
  문서/submodule 브랜치 정보를 정리했고, vendored 주석의 끝 공백 하나를 제거했다.

MF main: `c76a1ed`. PiFinder 이력 보존 병합: `78f9bae4`.
서비스 전환 결과는 전환 후 별도 절에 기록한다. 실물 판매 이미지와 냉부팅은
이번 검사에 포함하지 않는다.
