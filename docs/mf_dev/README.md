# MFNavis 개발 문서

**현재 동작은 아래 주제별 기준 문서에서 확인한다.** 기준일은 2026-10-10이며,
이전 GoTo·솔빙 실패·이동 한계 수정이 포함된 작업 트리를 기준으로 했다.
계획과 구현을 섞어 설명하던 개별 문서, 반복된 소스 구조 설명과 번역 사본은 통합했다.

| 작업 영역 | 현재 기준 문서 | 합친 내용 |
|---|---|---|
| 설치·개발 | [설치와 개발 환경](setup_ko.md) · [English installation](setup_en.md) | Trixie 설치, 개발 venv/Nox, IMX678 준비 |
| 마운트·GoTo | [GoTo와 추적 보정](mount_control_ko.md) · [English summary](mount_control_en.md) | 서비스/실행기, 시작→도착→보정, 솔빙 실패 두 경우, 사용자 취소·한계 정지 |
| 정렬·백레시 | [정렬과 측정](alignment_ko.md) | LCD/웹/SkySafari 정렬, 다중 포인트, 광학 백레시 |
| 선택형 추적 | [추적 종류와 제어권](tracking_ko.md) | 기본 guide, smooth active/shadow, visual shadow, 타겟 통합 상태 |
| 좌표·IMU | [포인팅 계약](positioning_ko.md) | 실제 관측/추정, 좌표 선택, 이동 중 융합, 외부 프로토콜 |
| 솔빙 | [MFDS와 전처리](solver_ko.md) | MF 주 경로, 마지막 SEP 복구, 동기/비동기, 품질·frame pairing |
| 카메라·영상 | [노출과 광학](camera_ko.md) | Auto(Star) framewise, 센서 변형, FOV·왜곡, RAW LiveCam/SQM |
| 입력·웹 | [화면과 카탈로그](interfaces_ko.md) | HID 사용자 매핑, LCD 조작, 오류 알림, 카탈로그, 오프라인 캐시 |
| 장치 연결 | [연결과 시간](connectivity_ko.md) | INDI Serial Auto/복구, UART/I2C, GPS/Chrony, AP+STA |
| 검증 | [검사와 현장 확인](validation_ko.md) | 자동 검사, GoTo 수락 기준, 실장 미검증 항목, 기록 양식 |

## 문서 역할과 갱신 규칙

- 현재 구현·제약은 해당 주제 기준 문서 한 곳에서 갱신한다. 날짜별 별도 계획 파일을 추가해 같은 동작을 중복 정의하지 않는다.
- 용어와 bounded context는 [CONTEXT-MAP](../../CONTEXT-MAP.md)와 `docs/ax/*/CONTEXT.md`를 따른다. 주제 문서는 이를 대체하는 새 용어집이 아니다.
- 결정의 이유는 [ADR](../adr/), 날짜·장비에 종속된 관측과 실측은 [보고서](../mf_report/README.md)에 남긴다.
- 완료된 계획·옛 수치·미구현 제안은 [통합 이력](../history/development/README.md)에서 읽는다. 과거 “living/현재” 표시는 원문 작성 당시의 표현이다.
- 현재 문서의 구현 위치와 회귀 파일을 함께 갱신하며 자동 검사와 실장 검증을 구분한다.
- 배포·경로·검출기 패키지의 독립 계약, 공개 사용자 매뉴얼, 라이선스와 하드웨어 자료는 각 기존 문서를 유지한다.

## 문서 정리 내역

구 개발 파일명별 새 기준과 이력 위치는 [이전 경로 대응표](../history/development/README.md)에 있다.
한국어 원문은 주제별 이력으로 합쳤고 중복 영문 개별 파일은 제거했다.
영문 설치와 GoTo 요약은 현재 기준으로 유지하며 다른 영문 번역의 원문은 Git 이력에서 조회할 수 있다.
저장소 내부 링크는 현재 안내에는 새 기준, 과거 보고서·ADR의 근거 인용에는 원문 보관 위치로 연결한다.
