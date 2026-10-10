# 기능 체크리스트 테스트 세션 — 자동 검증분 (2026-08-05)

> [mf_feature_review_checklist_ko.md](../history/development/validation.md#mf_feature_review_checklist_ko)
> (2026-08-05 기준선) 전체 재테스트의 **자동/원격 검증 가능분** 실행 기록.
> 조건: 실내, 하늘 불량(솔빙 불가), 마운트 미연결 — 야간/실외/마운트 항목은
> 수동 테스트로 남김(§하단). 실행: Claude (자동화), 결과 기록 양식 준수.

```text
Date: 2026-08-05 03:40–04:40 KST
Device: PiFinder Pi4, imx462, SSD1351
OS: Bookworm 64-bit
Branch / commit: main / 49856ba4 (+당일 수정 3건)
Network mode: AP+STA
Mount / driver: 미연결
GPS state: 실내 미락 (위치 미로드 — 설계상 정상, 아래 참고)
```

## 결과 요약

| 영역 | 결과 |
|---|---|
| 정적 검사 (compileall, bash -n ×4, lint, format, mypy 170파일) | **전부 통과** |
| 전체 테스트 스위트 | **1,117건 통과** (당일 회귀 테스트 3건 포함) |
| 라이브 서비스 API | 통과 (하단 상세) |
| 헤드리스 UI (Focus 4모드, Software 화면) | 통과 (스크린샷 검증) |
| **발견 결함** | **3건 발견 → 3건 수정+테스트** (하단) |

## 발견/수정된 결함 (이 세션의 핵심 산출물)

테스트 중 실제 크래시로 드러난 결함 3건을 즉시 수정했다:

1. **Software 화면 RIGHT 키가 미제안 업데이트를 실행** (P1 심각).
   "Release info unavailable"/"No Update needed" 상태에서 RIGHT 한 번에
   `pifinder_update.sh`(git checkout release)가 실행됐고, release 브랜치가
   없어 실패하면서 —
2. **업데이트 스크립트 실패 예외가 UI 메인 루프를 관통** — 앱 전체가
   죽었다(헤드리스에서 실측 재현; 실기기였다면 systemd 재시작으로 관측
   상태 소실). 수정: `key_right()`에 `_go_for_update` 게이트,
   `sys_utils.update_software()` 예외 격리(실패→False→"Error on Upd" 표시).
3. **`imu_fake.imu_monitor` 시그니처 불일치** — main이 4인자(나침반 보정
   명령 큐 포함)를 넘기는데 fake는 3인자라, `-fh`(fake hardware) 실행마다
   IMU 프로세스가 TypeError로 즉사했다(실기기 무영향, 개발/헤드리스 전용).
   수정: `command_queue=None` 수용.

각각 회귀 테스트 추가(`test_software.py` 2건, 시그니처 바인딩 1건).
수정 후 헤드리스 재기동에서 IMU 프로세스 생존(TypeError 0건) 확인.

## 체크리스트 항목별 결과

### 통과 — 자동 검증

- **§1 플랫폼**: pifinder/cedar_detect/chrony 서비스 active, 부팅 정상.
- **§2 Focus 화면**: 4모드 전부 렌더(Stars 4타일+HFD 오버레이 5.4 /
  Single 판독 / Image 별 필드 / Stats: FWHM 2.0px·Stars 41·Gain 10),
  SQUARE 순환, 마킹메뉴 EXPOSURE·HELP·GAIN 표시. (주간 raw 경로는 유닛
  테스트로 커버 — 실외 확인은 수동 항목)
- **§5/§21 웹**: `/`·`/login` 200, 보호 페이지 6종 302(인증 게이트 정상).
- **§6 AP+STA**: 활성 (Software 화면 "Wifi Mode: AP+STA" 표기 확인).
- **§8 시간 동기화**: chrony stratum 3, 시스템 시계 오차 0.35ms,
  NTPSynchronized=yes.
- **§12 IMU(실기기)**: quat 발행, imuplus, gyro 보정 3.
- **§17 솔버 파이프라인**: 시도 지속(24초 전 시도), `solve_path=cedar_ff`,
  T_extract 발행 — 실내라 검출 0은 예상 동작. (솔브율은 야간 수동 항목)
- **§19 SQM**: Radiometer 13.10 발행(실내 상식값), imx462 상수 zero point는
  유닛 151건으로 커버.
- **§20 LiveCam**: 라이브 image/jpeg 0.37s, 다운로드 image/png(설정 그대로),
  TIFF 16-bit 4.1MB, `/api/camera/controls` 응답 — 전부 정상.
  (검증용 processing 플래그는 원복)
- **§23 업데이트 채널**: 실기 화면으로 확인 — Current **m2.6.0** /
  Release **Unknown** / **"Release info unavailable"** 표시, Update Now
  없음. 포크 URL 404 확인.
- **§25 설치 스크립트**: bash -n 4종 통과, `test_wifi_apsta_static` 통과.

### 참고 — 회귀 아님으로 판정

- **위치 소스 None**: 재시작 후 `CONFIG: HOME`이 사라진 것은 회귀가 아니라
  설계 — 저장 위치는 UI/웹에서 Load할 때만 shared state에 적용되고,
  기본값 플래그는 LX200/INDI 관측자 폴백(`_configured_default_location`)이
  소비한다. 실내 GPS 미락과 겹쳐 None으로 보였을 뿐. 재현: 위치 목록에서
  HOME Load 시 즉시 복원.

### 남은 수동 항목 (조건 필요)

- 야간: §17 솔브율/solve_path, §19 bias 238 재검증+SQM 위저드(스윕은 #561
  적용 후라 유효), §2 실별 초점
- 주간 실외: §2 Image 모드 주간 정렬 경로
- 마운트 연결 시: §9–§11 INDI/OnStepX/SkySafari 전체, §2 가이드 키
- 실물 확인: §4 BT 키보드 페어링(WiFi off 절차), §22 조이스틱,
  §24 SSD1333 실패널(입수 시)
- 릴리즈 컷 후: §23 업데이트 전체 흐름
