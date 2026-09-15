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

## 서비스 전환 결과

22:08 KST에 운영 `/home/pifinder/PiFinder` main을 `27c6a3a6`으로 갱신했다.
PiFinder PID 46938이 기존 unit 경로에서 실행되고 MF native worker가 솔버의
자식 프로세스로 실행됐다. `pifinder.service`는 enabled/active,
`cedar_detect.service`는 disabled/inactive다. systemd drop-in은 없다.
Cedar unit 파일은 자동 승인 검토가 삭제를 거절해 복구용으로 보존했다.
옛 Tetra3/Cedar 작업 디렉터리와 설정·로그·unit은 로컬 배포 백업으로 옮겼다.
이 장비의 파일시스템 전체를 Cedar 없는 판매 이미지로 인증한 것은 아니다.

재시작 직후 목표가 초기화됐으며 사용자가 이어서 실행한 GoTo는
22:10:36에 제어기 오차 1.28분각으로 완료됐다. 이후 수동 이동과 SkySafari
정렬이 기록됐다. 설정 차이는 해당 정렬에 따른 `target_pixel` 갱신뿐이었으며
테스트 도구가 노출·gain·정렬 값을 변경하지 않았다.

22:10:48–22:12:47의 120개 상태 샘플에서 목표 오차 중앙값은 0.67분각,
p95 1.00분각, 최대 2.89분각이었다. 이는 제어기 추정 오차이며 독립 광학
정답 오차는 아니다. 102개 서로 다른 solver frame 상태 중 sync 72 / async 30,
RAW solved 68 / accepted 39가 관측됐다. 채택된 39개 광학 좌표의 RMSE는
중앙값 22.8초각 / p95 25.6초각, 매칭 별 중앙값은 20개였다.
전체 상태 샘플은 CAM 43 / CAM_FAILED 77이므로 계속되는 RAW 채택이나
모든 프레임 성공을 의미하지 않는다. 실패·확인 구간은 전처리 동기 복구를 사용했다.
전체 솔버 처리시간은 p50 1032ms / p95 1262ms / 최대 1599ms였다.

`sep_*`는 기존 통합 경로 이름으로 MF 추출 결과에도 사용된다. 이름만으로
SEP가 주 검출기라고 판단하지 않으며, 이번 기록은 개별 SEP fallback 전수 집계가 아니다.
원본 상태·좌표·로그는 `PiFinder_test_data/work/main_finalization`에만 보존했다.

## 원격 CI의 비공개 submodule 인증

MF main CI는 성공했다. 첫 PiFinder main CI는 기본 GITHUB_TOKEN으로 다른
비공개 MF 저장소를 읽지 못해 checkout 단계에서 실패했다. 이를 위해 MF에
읽기 전용 deploy key를 등록하고 PiFinder Actions의 `MF_DETECT_STAR_READ_KEY`에
연결했다. 저장소 공개 범위나 코드 쓰기 권한은 변경하지 않았다.
checkout composite action이 부모의 gitlink SHA를 읽어 정확한 MF 커밋을 받는다.
개인 토큰을 공유하지 않으며 작업 종료 후 checkout의 SSH 인증은 남기지 않는다.
CI 수정은 실행 중인 검출·솔빙 코드의 변경이 아니다.
