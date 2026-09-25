# MFNavis 홈 자료 통합 — 2026-09-25

운영 서비스가 `/home/pifinder/MFNavis`와 `/home/pifinder/MFNavis_data`를 직접
사용하는 것을 확인한 뒤, 홈 최상위의 이전 PiFinder 경로를 정리했다.

| 이전 경로 | 현재 경로·처리 |
|---|---|
| `/home/pifinder/PiFinder_main` | `/home/pifinder/MFNavis_data/legacy_source_20260925`로 이동. 이전 Git 기록과 무시된 산출물을 그대로 보존했다. 이전 HEAD와 원격 `main`은 모두 MFNavis `main`의 조상이다. |
| `/home/pifinder/PiFinder_test_data` | `/home/pifinder/MFNavis_data/test_data`로 이동. `cache`, `corpora`, `releases`, `results`, `work`, 테스트 설정·DB를 함께 보존했다. |
| `/home/pifinder/PiFinder`, `/home/pifinder/PiFinder_data` | 각각 MFNavis 경로를 가리키던 심볼릭 링크를 제거했다. |

과거 현장 보고서에 적힌 절대 경로는 당시 기록으로 유지한다. 현재 파일을 찾을
때는 위 경로 대응표를 적용한다. MFNavis 저장소의 테스트 실행 스크립트와 실험
도구는 새 자료 경로를 사용한다. 두 개발 가상환경의 실행 파일·활성화 스크립트에
남은 이전 절대 경로 119곳도 새 경로로 바꿨다.

이동 후 이전 소스 저장소의 작업 트리는 깨끗했고, 홈 최상위에 PiFinder 이름의
경로는 남지 않았다. `mfnavis.service` 재시작 후 `active/running`, 웹 HTTP 200을
확인했다. 실험 자료의 과거 릴리스 스냅샷에는 이동 전부터 대상 파일이 없는
상대 심볼릭 링크 21개가 포함되어 있으며, 원본 기록을 보존했다.
