# IMUPLUS 상대 지자계 보정 계획 — 무효화 기록

- 상태: **무효화 — 구현하지 않음**
- 결정일: 2026-09-17 (KST)
- 검토 기준: `main` / `352e2abe`, 설치된 Adafruit BNO055 드라이버 `5.4.22`
- 결정: IMUPLUS에서 내장 자력계의 새 측정값을 사용할 수 없음을 재확인했으며,
  사용자의 조건부 취소 요청에 따라 이번 계획을 무효화한다.

## 검토 대상

BNO055의 IMUPLUS 동작과 별도 사용자 캘리브레이션 없는 사용성을 유지하면서,
같은 센서의 지자계 벡터 변화와 IMU 회전을 비교해 PiFinder에서 yaw drift를
보정하려던 계획이다. 아래 하드웨어 전제가 성립하지 않으므로 설계 확장을 중단한다.

## 재확인 근거

Bosch BNO055 데이터시트 revision 1.8 (October 2021):

| 위치 | 확인 내용 |
|---|---|
| p.21, §3.3, Table 3-3 | IMU 모드의 Accel/Gyro/상대 자세는 제공되지만 Mag는 `-` |
| p.21, 표 바로 아래 설명 | 선택 모드에 필요하지 않은 센서는 suspend 상태로 전환 |
| p.22, Table 3-5 | IMU 모드 값은 `0x08`, 드라이버의 IMUPLUS와 동일 |
| p.33, §3.6.3, Table 3-14 | IMU 모드의 자력계 입력·출력은 `NA` |

출처: [Bosch 공식 데이터시트](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bno055-ds000.pdf).
페이지 번호는 문서에 인쇄된 번호다.

설치된 `/usr/local/lib/python3.11/dist-packages/adafruit_bno055.py`와
[Adafruit 공식 소스](https://docs.circuitpython.org/projects/bno055/en/latest/_modules/adafruit_bno055.html)의
`magnetic` getter도 모드 `0x08`에서 `(None, None, None)`을 반환한다.
이는 제조사 동작 명세와 일치한다.

따라서 자력계를 fusion 계산에서만 제외하고 별도 측정을 계속하는 모드로 해석하면
안 된다. 레지스터 주소에 접근할 수 있다는 것과 새로운 유효 측정값이 갱신된다는
것은 다르며, 드라이버 검사만 우회해도 이번 계획에 필요한 입력을 얻을 수 없다.

## 종료 범위

- 작성 중이던 설계 초안을 이 무효화 기록으로 대체했다.
- 코드, 센서 모드, 사용자 설정, 실행 중 서비스는 변경하지 않았다.
- 외부 센서 추가나 다른 fusion 모드 전환으로 작업을 확대하지 않는다.
- 실기기 레지스터 측정 실험은 하지 않았다. 결론은 제조사 명세와 드라이버 재확인에 근거한다.
- 기존 [IMU 현재 동작 분석](mf_imu_current_behavior_analysis_ko.md)과
  [선택형 NDOF calibration 안내](mf_imu_compass_calibration_ko.md)는 그대로 유효하다.
