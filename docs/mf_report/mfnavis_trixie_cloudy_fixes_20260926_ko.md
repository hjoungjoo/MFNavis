# Trixie 구름 많은 하늘·고정 장비 점검 후 수정 — 2026-09-26

대상은 [직전 현장 점검](mfnavis_trixie_cloudy_fixed_20260926_ko.md)에서 발견한
혜성 계산·번역·테스트 간 간섭·웹 기대값 불일치다. 직전 보고서는 당시 기록으로 보존한다.
Raspberry Pi 5 / Trixie / Python 3.13.5의 기존 작업 트리에 수정했다.
수정·최종 검증은 2026-09-26 밤부터 2026-09-27 새벽까지 진행했다.

## 수정

- **혜성 계산:** Skyfield 1.55의 `propagate()`는 내부적으로 여러 궤도를 계산한 뒤
  출력 형태에서 궤도 축을 잃는다. 해당 함수를 `MFNavis/comet_propagation.py`에
  별도로 유지하며 출력 형태에 궤도 축을 보존했다. 기존 Skyfield 설치·전역 함수는
  변경하지 않는다. 기존 궤도 생성·회전·J2000 좌표 계산과 느린 예외 복구 경로를
  유지한다. 원본 MIT 고지와 출처를 소스 및 제3자 고지에 포함했다.
- **한국어 번역:** 네트워크 적용·재시작 준비·장비 권한 실패·네트워크 적용 실패
  메시지 4개를 추가하고 `messages.mo`도 다시 생성했다.
- **테스트 간 간섭:** `test_ui_modules.py`의 데이터·시스템 명령·sleep·네트워크
  모의 객체와 관련 자원을 session 범위에서 module 범위로 변경했다. 메뉴 순회가
  끝나면 원래 객체로 복구되어 INDI 웹 테스트에 MagicMock이 남지 않는다.
- **웹 검사:** 데스크톱·모바일의 언어 선택기, 브라우저별 언어 쿠키, 현재 CSS
  cache key `v=11`을 확인하도록 오래된 기대값을 갱신했다.
- **로그 종료:** 추가 회귀 실행에서 여러 프로세스의 로그 중 일부가 사라지는
  문제도 확인했다. 첫 큐의 종료 표시만 보고 끝내지 않고 등록된 모든 큐를
  각각 비운 뒤 로그 수집 프로세스를 종료한다. 다른 큐에 대기 중인 로그가
  있을 때의 종료를 재현하는 검사를 추가했다. 또한 수집기가 멈춘 뒤에도
  부모 프로세스가 같은 큐에 로그를 보내면 큐 feeder의 종료 대기가 끝나지 않는다.
  `join()`에서 해당 QueueHandler를 제거하고 큐도 닫아 이 문제를 해결했다.
  핸들러 해제 검사를 추가했다. 임시 카탈로그 타이머 종료 hook은 원인 확인 후 제거했다.

혜성 계산의 원본 구현은
[Skyfield keplerlib](https://github.com/skyfielders/python-skyfield/blob/master/skyfield/keplerlib.py)이며,
수정본은 설치된 1.55에서 가져왔다. 출력 축 외 계산식은 그대로 유지한다.

## 계산 실측

운영 `.venv-trixie`에서 실제 카탈로그 959개를 같은 시각·관측 위치로 계산했다.

| 항목 | 결과 |
| --- | --- |
| 수정한 일괄 계산 | 0.0502초 |
| 혜성별 기준 계산 | 25.3093초 |
| 가시 혜성 목록 | 두 방식 모두 동일한 8개 |
| 최대 RA/Dec 차이 | 약 `1.35e-13`도 |

이는 해당 실행의 계산 시간이다. 운영 서비스와 회귀 검사도 실행 중이었으므로
독립 벤치마크의 절대 성능 보증으로 해석하지 않는다.
기존 혜성 검사 외에 여러 궤도·여러 시각의 위치와 속도가 Skyfield의 독립적인
궤도별 결과와 일치하는 검사 2개를 추가했다.

## 운영 반영

2026-09-26 23:50:09 KST에 `mfnavis.service`를 한 번 재시작했다.
주 프로세스는 PID 1382에서 48767로 바뀌었고 새 서비스는 active/running이다.
추가 로그 종료 수정도 반영하기 위해 2026-09-27 00:04:30 KST에 다시 시작했으며,
최종 PID는 63184, active/running이다.

이번 현장 조건은 마운트 미연결이므로 사용자 설정에서 `mount_control=false`,
`indi_tracking_guide_enabled=false`로 변경했다. 카메라·렌즈·화면·위치 등
나머지 값은 보존했다. 원본 설정은 아래 원자료 경로의
`config-before-fixed-test.json`에 0600 권한으로 백업했다.
향후 실제 마운트 연결 시험에서는 연결 프로필을 준비하고 두 설정을 다시 선택해야 한다.

마운트 이동·Sync·GoTo·가이딩을 실행하지 않았다. 인증 필요한 실물 웹 페이지의
제한과 이동·장시간 안정성 검사 범위는 직전 보고서와 동일하다.

## 최종 확인

- 전체 비-Selenium 회귀: **3530 passed, 3 skipped**, 실패 0개.
  최종 실행은 175.09초였고 결과 출력 후 프로세스도 **exit code 0**으로 정상 종료했다.
- 별도 IMU 모의 검사: **3 passed**. 중복 제외 합계 **3533 passed, 3 skipped**.
- 수정 관련 독립 회귀: **93 passed**. 위 전체 결과와 중복되므로 합산하지 않는다.
  추가 로그 종료 검사 10개도 통과했다.
- Ruff lint, format 405개 파일 검사와 `git diff --check` 통과.
- 앞서 발견한 혜성 5개·INDI 웹 10개·한국어 번역 1개·웹 테마 2개 실패가 모두 해소됐다.
- 재시작 후 약 88초간 30개 표본에서 GPS lock·IMU healthy·전처리 ready가 모두 30/30.
  전처리 frame ID 30개가 모두 달랐고 별도 RAW 이미지 비교에서도 영상 갱신을 확인했다.
- `/`, `/api/camera/raw`, `/api/screen` HTTP 200. 실제 장비 화면이 메인 메뉴로 복귀했다.
- 수집한 재시작 이후 journal에 혜성 계산 오류·마운트 설정 오류·Traceback·ERROR 0건.
- 새 프로세스의 자동 재시작 횟수 `NRestarts=0`.

최종 로그 수정 반영 후에도 1분간 12개 표본에서 GPS·IMU·전처리가 모두 12/12 정상,
전처리 frame ID 12개가 서로 달랐다. 최신 솔빙 상태는 성공 7개·실패 5개였으며
**실제 솔빙 성공을 재확인했다**. 이 비율은 전체 시도별 성공률이 아니다.
해당 최종 시작 이후 수집 journal에도 ERROR·Traceback·혜성 계산 예외가 없었다.

최초 재시작 후 약 88초 표본에서는 검출 별 수가 0으로 성공하지 못했지만,
이후 최종 재시작 검증에서는 성공을 관측했다. LiveCam 자체 처리 옵션은 비활성 상태이므로 미리보기 `frame=null`은
정상 응답이며, 솔버 전처리 frame ID와 실제 RAW 응답으로 촬영 갱신을 확인했다.

## 재현 및 원자료

로그·실측·설정 백업은 `/home/mfnavis/trixie-fixed-cloudy-20260926/fixes/`에 보존한다.
위치와 설정이 포함된 원자료는 Git에 추가하지 않는다.

```bash
cd /home/mfnavis/MFNavis
source scripts/activate_dev_trixie.sh
python -m pytest tests --ignore=tests/website \
  --ignore=tests/test_imu_runtime.py -q --tb=short
python -m pytest tests/test_imu_runtime.py -q --tb=short
```

IMU 파일의 모의 검사에는 import 시 GPIO 접근이 필요하다. 실제 센서 초기화·
보정·이동을 실행하는 검사는 아니다.

원자료: `verified-final-tests.log`, `verified-final.xml`,
`full-final-tests.log`, `full-final.xml`, `full-clean-exit-tests.log`,
`full-clean-exit.xml`, `imu-tests.log`,
`targeted-final.log`, `logging-tests.log`, `comets-runtime-benchmark.json`,
`runtime-after.jsonl`, `runtime-after-summary.json`, `journal-after.log`,
`runtime-final.jsonl`, `runtime-final-summary.json`, `journal-final.log`,
`service-final.txt`, `logging-exit-final.log`,
`service-after.txt`, `screen-after.png`, `config-changes.json`, `ruff.log`,
`format.log`, `graft-build.log`.
