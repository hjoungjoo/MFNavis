# 카메라 mono/color 변형 선택 계획 (IMX296 · IMX462)

> 상태: **구현됨(2026-08-08)** · 작성 2026-08-05 · 구현 후기는 §8
> 관련: [mf_mono_sqm_colour_guard_20260805_ko.md](../mf_report/mf_mono_sqm_colour_guard_20260805_ko.md)(모노 실측·#560 가드),
> `docs/mf_dev/mf_sep_fullframe_impl_ko.md` §6.4(위상 실측), ADR 0026(색 기반 zero point)

> **2026-09-26 제품 기본값 변경:** 새 설치에서 IMX462 Color, 수동 렌즈
> 8.2661 mm, 해당 광학 조합의 하늘 측정 왜곡 계수 `k1=-0.05`를 기본으로
> 사용한다. 아래의 mono 기본값은 2026-08 초기 설계 기록이다. 기기별 저장
> 설정과 이미 선택한 카메라 오버레이는 유지되며, 렌즈가 다르면 재측정한다.

## 1. 배경과 목표

IMX296과 IMX462는 각각 mono/color 두 변형이 존재하지만 실리콘·레지스터
맵이 동일하고 CFA는 I2C로 읽을 수 없는 광학층이라 **런타임에 변형을
판별할 방법이 없다**(실측으로만 판별 가능 —
[colour guard 리포트](../mf_report/mf_mono_sqm_colour_guard_20260805_ko.md) §배경).
현재 코드는 세 프로파일(imx296/imx462/imx290)에 `mono=True`를
하드코딩해 두었다(`python/PiFinder/sqm/camera_profiles.py:238,280,328`).

기기당 카메라는 고정이므로, **설정에서 mono/color를 1회 선택**하게 하고
선택값이 파이프라인 전체(raw 저장, SQM 색보정 게이트, LiveCam 디베이어)에
일관되게 반영되도록 한다.

## 2. 현행 구조 분석

### 2.1 `CameraProfile.mono` 플래그와 소비처

| 소비처 | 위치 | mono=True 동작 | mono=False 동작 |
|---|---|---|---|
| raw TIFF 저장 | `camera_pi.py:386` (`capture_raw_file`) | 접미사 없음(휘도 데이터) | `_RGGB` 접미사 → 후처리 디베이어 유도 |
| SQM 색보정 게이트 | `sqm/radiometer.py:57` (`_mosaic_phase_is_rggb`) | 색 필드 미수집 → zero point 상수 유지 | upstream #560 색 연동 zero point 활성 |
| LiveCam RAW 프리뷰/다운로드 | `raw_live_stack.py:154,608` | 디베이어 생략(2×2 비닝 프리뷰만) | Bayer 포맷이면 디베이어 프리뷰 |

주의: **`extract_photometry_image`(`sqm/radiometer.py:18`)는 mono가 아니라
`format` 라벨(SRGGB*)로 분기**한다. imx462는 mono=True여도 SRGGB12
라벨이라 그린 위상 평균(half-res)을 쓰며, 스텔라 SQM 반경 스케일과
캘리브레이션 전체가 이 추출 방식 기준으로 적합되어 있다. 변형 선택이
이 경로를 건드리면 안 된다(→ 결정 D1).

### 2.2 camera_type 전파 경로

```
Picamera2.camera.id → detect_camera_type() (camera_profiles.py:419)
  → CameraPI.camera_type / self.profile (camera_pi.py:46-47)
  → camType "PI imx462" (camera_pi.py:59)
  → shared_state.set_camera_type("imx462") (camera_interface.py:378-379)
  → solver(solver.py:855) · sqm UI · api_extensions · sep_shadow · sep_warm_map이
    각자 get_camera_profile(camera_type)로 재조회
```

즉 **프로파일은 카메라 프로세스 밖에서도 camera_type 문자열로 여러 번
독립 조회**된다. 카메라 프로세스 안에서만 profile을 패치하면 solver/웹
쪽 조회와 어긋난다 — 변형 정보는 camera_type 문자열에 실려야 전 프로세스에
공짜로 전파된다(→ 결정 D2).

### 2.3 설정 메뉴 현행

- Settings → Advanced → **Camera Type** (`ui/menu_structure.py:1316-1337`):
  imx477/imx296/imx462 3항목. 선택 시 `callbacks.switch_cam_*`
  (`ui/callbacks.py:423-438`) → `switch_camera.py`가 boot config의
  `dtoverlay=`를 바꾸고 `restart_system()`(시스템 재부팅).
- 체크마크는 `callbacks.get_camera_type`(`ui/callbacks.py:441-456`)이
  boot config의 `dtoverlay=imx*` 행을 읽어 결정. config.json이 아니라
  **부트 설정이 카메라 종류의 소유자**다.

## 3. 설계 결정

### D1. dtoverlay는 건드리지 않는다 (변형은 순수 소프트웨어 선택)

RPi 오버레이(imx296/imx290/imx462)에는 수동 `mono` 파라미터가 있지만
사용하지 않는다. 근거:

- 현행 imx462 캘리브레이션 전체(bias 238, 그린 위상 추출, 반경 스케일,
  SQM 상수)가 **컬러 바인딩의 SRGGB12 라벨** 위에 적합되어 있다. 오버레이
  mono 파라미터는 포맷 라벨을 바꿔 이 체인을 전부 흔든다.
- 라벨과 무관하게 실측 사실(`profile.mono`)이 동작을 결정한다는 것이
  colour guard 사건에서 확립한 이 포크의 원칙이다.

따라서 mono/color 선택은 boot config가 아니라 **config.json + 프로파일**
차원에서만 이뤄진다. (imx296 color의 포맷 라벨 이슈는 §6 V1 참조.)

### D2. 변형 표현 = 파생 프로파일 이름 (`imx296_color`, `imx462_color`)

두 안을 비교했다:

| | A. 파생 프로파일 이름 (권장) | B. config를 읽는 profile override |
|---|---|---|
| 방식 | `CAMERA_PROFILES`에 `imx296_color`/`imx462_color` 항목 추가(`dataclasses.replace` 파생). 카메라 프로세스가 시작 시 variant를 붙여 camera_type을 확정 | `get_camera_profile()`이 호출 시마다 config에서 variant를 읽어 `replace(mono=...)` |
| 전파 | camType→shared_state로 **전 프로세스 자동 전파**, 추가 배선 0 | solver/sqm/api/스크립트 등 모든 호출부가 각자 config에 접근해야 함 |
| 오프라인 스크립트·테스트 | 프로파일 이름만으로 결정적(archive replay 스크립트가 이미 `row["profile"]` 문자열 사용) | config.json 상태에 따라 결과가 달라져 재현성 훼손 |
| 부작용 | camera_type 문자열 등가비교 1곳 수정 필요(아래) | camera_profiles가 config 모듈에 의존(계층 역전) |

**A를 채택한다.** 색 변형은 사실상 다른 기기이므로 이름이 다른 것이
오히려 정확하다(웜픽셀 맵도 camera_type으로 그룹되므로 색 변형 기기는
자동으로 별도 맵을 갖는다 — 바람직).

파생 항목 정의(모두 `replace()`로 mono 항목에서 파생, 단일 소스 유지):

```python
CAMERA_PROFILES["imx462_color"] = replace(
    CAMERA_PROFILES["imx462"], mono=False
)   # SRGGB12 유지: 진짜 CFA면 #560 색보정이 원래 의도대로 동작
CAMERA_PROFILES["imx296_color"] = replace(
    CAMERA_PROFILES["imx296"], mono=False, format=<V1 실측값>
)   # R10은 mono 전용 라벨 — 실기 포맷 확인 필요(§6 V1)
```

`detect_camera_type()`은 하드웨어 id 감지 그대로 두고, 변형 적용은 별도
헬퍼로 분리한다:

```python
def apply_variant(camera_type: str, variant: str) -> str:
    """variant("mono"|"color")를 프로파일 이름에 반영. hq 등 무관 카메라는 그대로."""
```

`camera_pi.py:46` 이후 `self.camera_type = apply_variant(detected, cfg.get_option("camera_variant"))`.
이후 camType `"PI imx462_color"` → `camera_interface.py:378`의
`split(" ")[1]` 파싱을 그대로 통과해 전 프로세스에 전파된다.

수정 필요한 등가비교: `camera_pi.py:302-308`(`capture_bias`)의
`camera_type == "imx296"` 등 3곳 → `startswith` 또는 (더 좋게) 이미 있는
`profile.crop_and_rotate` 사용으로 정리. 전수 grep 결과 등가비교는 이
한 함수뿐이다(`main.py:1449`는 "pi"/"debug"/"asi" 구분이라 무관).

### D3. 설정 키: `camera_variant` = `"mono"` | `"color"`, 기본 `"mono"`

- `default_config.json`에 `"camera_variant": "mono"` 추가. 기본값 mono =
  현행 동작과 비트 동일(기존 기기 무영향).
- 이름을 `camera_variant`로 하는 이유: LiveCam에 이미 표시용
  `color_mode`(theme/color/**mono**, `livecam_config.py:52-57`)가 있어
  "color mode"류 이름은 충돌한다. 이것은 표시 모드가 아니라 **하드웨어
  변형 선언**이다.
- hq(imx477)는 항상 컬러이므로 이 키를 무시한다(`apply_variant`가 통과).
- imx290은 imx462 프로파일 계열이므로 동일하게 적용된다.

### D4. UI: 기존 Camera Type 메뉴를 변형 포함 5항목으로 확장

별도 토글 메뉴 대신 **Camera Type 메뉴 항목 자체를 늘린다**
(`menu_structure.py:1316-1337`):

```
v2 - imx477          → dtoverlay imx477,            camera_variant 무관
v3 - imx296 Mono     → dtoverlay imx296  + variant "mono"
v3 - imx296 Color    → dtoverlay imx296  + variant "color"
v3 - imx462 Mono     → dtoverlay imx462  + variant "mono"
v3 - imx462 Color    → dtoverlay imx462  + variant "color"
```

근거: 변형은 센서 선택의 일부이지 독립 옵션이 아니다. 별도 토글이면
"imx477인데 variant=color" 같은 무의미 조합 상태가 UI에 남고, 사용자가
두 메뉴를 오가야 한다. 5항목이면 한 번의 선택으로 조합이 항상 유효하다.

- 항목 value는 `"imx477" | "imx296_mono" | "imx296_color" | "imx462_mono" | "imx462_color"`.
- 콜백: 기존 `switch_cam_*` 3개를 (cam, variant) 인자를 받는 형태로
  통합하거나 5개로 확장. 동작 =
  ① `config_object.set_option("camera_variant", ...)`
  ② dtoverlay가 실제로 바뀌는 경우에만 `sys_utils.switch_cam_*` + `restart_system()`(재부팅),
  ③ **variant만 바뀐 경우 `restart_pifinder()`(서비스 재시작)로 충분** —
  boot config 무변경이므로 재부팅은 낭비다.
- 체크마크: `get_camera_type()`(`callbacks.py:441`)이 boot config의
  dtoverlay id에 config의 `camera_variant`를 합성해
  `"imx462_mono"`식 값을 반환하도록 수정(imx290→imx462 별칭 처리 유지).
- 신규 문자열은 `_()` 래핑 + babel 파이프라인(`nox -s babel`) 통과.

## 4. 선택에 따른 동작 변화 매트릭스

mono(기본, 현행 유지) 대비 **color 선택 시**:

| 영역 | 변화 | 비고 |
|---|---|---|
| raw TIFF 저장 (`capture_raw_file`) | `_RGGB` 접미사 부여 → 후처리 디베이어 안내 | 기존 mono 플래그 분기 그대로 활용, 코드 수정 없음 |
| SQM radiometer (#560) | 색 필드 수집 + 하늘색 연동 zero point 활성 | imx462_color에서는 upstream이 컬러 실기로 적합한 slope 5.544가 **의도대로** 동작. colour guard(`radiometer.py:57`)는 mono 프로파일에만 계속 발동 |
| LiveCam RAW | Bayer 디베이어 프리뷰 활성 | `raw_live_stack.py`는 profile.mono를 이미 스레딩, 수정 없음 |
| 솔빙 (cedar/SEP) | 변화 없음 — 두 경로 모두 raw 모자이크에서 검출하며 hq(컬러)도 같은 방식으로 이미 동작 중 | |
| 스텔라 SQM 추출 | 변화 없음(format 키, §2.1) | imx462_color=SRGGB12라 동일 경로 |
| 웜픽셀 맵 | camera_type이 달라져 별도 맵 그룹 | 물리적으로 다른 기기이므로 올바른 동작 |
| SQM 캘리브레이션 상수 | 승계하되 **미검증 표기** | mono 실기에서 적합한 값. color 실기 확보 전까지 프로파일 주석에 "inherited from mono unit, unverified" 명기 |

## 5. 구현 단계

### P1 — 프로파일·전파 (핵심)
1. `camera_profiles.py`: `imx296_color`/`imx462_color` 파생 항목 +
   `apply_variant()` 헬퍼 + docstring에 변형 판별 불가 사실 기록.
2. `camera_pi.py`: `get_images()`의 `cfg`를 `CameraPI(exposure_time, cfg)`로
   전달, `__init__`에서 `apply_variant` 적용. `capture_bias`의 등가비교
   정리.
3. `default_config.json`: `"camera_variant": "mono"`.

### P2 — 설정 UI
4. `menu_structure.py`: Camera Type 5항목 확장(+`_()` 래핑).
5. `callbacks.py`: switch 콜백에 variant 저장·조건부 재시작,
   `get_camera_type` 합성값 반환. `sys_utils_fake.py` 대응 확인.

### P3 — 테스트·품질
6. `test_radiometer.py`: `imx462_color`가 색 게이트를 **통과**함을
   단언(기존 `replace(mono=False)` 우회와 별개로 출하 프로파일 자체 검증),
   `test_shipped_colour_profiles_hold_the_phase_invariants`에 color 항목
   편입, mono 회귀 핀(`test_measured_mono_imx462_keeps_the_constant_zero_point`)
   유지 확인.
7. 신규: `apply_variant` 단위 테스트(hq 통과, imx290 별칭,
   미지 variant 방어), `get_camera_type` 합성 테스트, 메뉴 value 정합
   테스트(`test_ui_modules.py` 계열).
8. `nox -s lint / format / type_hints / smoke_tests / unit_tests`, babel.
9. 헤드리스 UI로 메뉴 왕복 확인(pifinder-remote 스킬).

### P4 — 문서
10. 본 문서 상태 갱신(plan → 구현), `mf_change_history_ko/en`,
    docs 인덱스, 사용자 가이드(`docs/source/`)의 카메라 설정 절 갱신.
    colour guard 리포트에 "설정 선택화됨" 후기 각주.

## 6. 하드웨어 검증 항목 (구현과 병행)

- **V1 (imx296_color 포맷 라벨, P1 전 필수)**: color IMX296(RPi Global
  Shutter 카메라 등) 실기 또는 자료로 libcamera 보고 포맷을 확정한다
  (`rpicam-hello --list-cameras`, picamera2 `sensor_modes`). 현행 프로파일
  `R10`은 mono 라벨이므로 color 실기에서는 다를 가능성이 높다(SBGGR10
  추정 — **미확인, 코드에 넣기 전 실측**). 포맷이 SRGGB가 아니면
  `extract_photometry_image`가 full-res 경로로 빠지고 색 게이트도 닫히는데,
  이는 안전한(보수적) 폴백이므로 1차 구현에서 허용한다.
- **V2 (imx296 자동 감지 가능성)**: imx296 드라이버가 mono/color를 스스로
  구분해 다른 포맷을 보고한다면, imx296에 한해 variant를 보고 포맷에서
  자동 유도할 수 있다(감지값과 설정 불일치 시 로그 경고). 확인 전까지는
  수동 선택이 정본. imx462는 오버레이 수동 파라미터의 존재가 자동 감지
  불가의 방증이므로 항상 수동.
- **V3 (imx462_color 실기 부재)**: 이 포크에 color 실기가 없으므로 색
  경로는 시뮬레이션 테스트(6번 항목)로만 검증하고, 프로파일 주석에 상수
  미검증을 명기한다.

## 7. 리스크·열린 질문

- **잘못된 선택의 피해 방향**: mono 실기에 color를 선택하면 colour guard가
  무력화되어 SQM이 ~+0.74 mag 이동한다(리포트 실측). 메뉴 설명/문서에
  "실측 없이는 Mono 유지"를 명시하고, 기본값 mono가 안전측임을 유지한다.
  장기적으로 위상 평균 자가진단(주·야 프레임 R/G·B/G≈1 검사)을 진단
  화면이나 콘솔 명령으로 노출하는 것을 후속 과제로 남긴다.
- **camera_type 문자열을 파싱하는 외부 소비자**: 웹 API(`api_extensions.py:221`)가
  `"imx462_color"`를 그대로 노출하게 된다 — 표시 문자열로만 쓰이는지 확인
  필요(P2에서 grep 전수).
- **debug 카메라**: `camera_debug.py:35`의 `"Debug imx296"`은 mono 프로파일
  경로를 타며 현행 유지. 필요 시 후속으로 variant 반영.

## 8. 구현 후기 (2026-08-08)

P1–P4를 설계대로 구현했다 (`camera_profiles.py`의 파생 프로파일 +
`apply_variant`, `camera_pi.py`의 cfg 전달과 `capture_bias` 크롭 사다리의
`profile.crop_and_rotate` 대체, Camera Type 5항목 메뉴와 변형-전용
서비스 재시작, `sys_utils_fake.switch_cam_imx462` 보강 포함).

하드웨어 검증 항목 결과:

- **V1 (해소)**: 커널 드라이버 소스(`drivers/media/i2c/imx296.c`)로 확정 —
  mono는 `Y10`, colour는 SBGGR10 계열(플립 설정에 따라 4종). `imx296_color`
  프로파일은 `SBGGR10`으로 출하하며, 실기 라벨 검증 전까지는 non-SRGGB
  라벨이라 색 게이트가 닫힌 보수 폴백으로 동작한다(계획 §6 V1의 허용 범위).
- **V2 (소스로 확인)**: imx296 드라이버는 compatible 문자열 또는 센서 정보
  레지스터로 mono/color를 자가 감지할 수 있다. imx296에 한한 variant 자동
  유도(감지값-설정 불일치 경고 포함)는 후속 과제로 유지; 수동 선택이 정본.
- **V3 (해소)**: 컬러 imx462 실기가 이 포크에 확보되어 전파 경로를 실기
  검증했다 — `camera_variant=color` 설정 후 카메라 프로세스가
  `imx462_color`로 기동(SRGGB12 스트림 정상), 웹 API `camera_type`이
  `imx462_color`를 반환. **SQM 상수는 여전히 mono 승계 미검증** — 야간
  실측(색 필드 수집과 #560 zero point 거동) 전까지 §4의 "inherited from
  mono unit, unverified" 상태가 유지된다.
