# 카메라·노출·광학·LiveCam

기준: 2026-10-10 작업 트리. 용어는 [Camera CONTEXT](../ax/camera/CONTEXT.md),
측광 계약은 [SQM CONTEXT](../ax/sqm/CONTEXT.md)를 따른다.

## 촬영과 노출 제어

카메라 backend는 RAW와 실제 노출·gain 메타데이터를 게시한다.
수동 제어, native 자동 노출, MFNavis 자동 제어의 소유권을 구분한다.
매치 수 기반 `ExposurePIDController`, 검출 별 수 기반 `ExposureStarCountController`,
Pi 카메라의 프레임 단위 Auto(Star) v2는 서로 다른 피드백 경로다.

Pi backend의 framewise 경로는 `camera_auto_star_framewise`, 컨트롤러 존재,
star-count 선택, MFNavis AE 활성, 비-SNR·비-native AE 조건이 모두 맞을 때 활성화된다.
매 캡처 RAW의 공간 통계를 실제 `ExposureTime`/`AnalogueGain`과 함께 측정하고,
새 exposure/gain 요청과 센서 적용 지연을 추적한다. 이 기능을 지원하지 않는 backend는
기본 인터페이스의 framewise 활성값이 false이고 기존 선택 경로를 사용한다.
솔빙 결과의 지연과 센서 제어 적용 지연을 같은 프레임으로 오해하지 않는다.

Focus 화면의 token 기반 임시 노출 hold는 카메라 프로세스에서 처리한다.
명시적 노출·gain·AE·Stop 입력이 들어오면 hold를 해제한다.
지연된 이전 화면 명령이 새 사용자 설정을 다시 가져가지 않도록 token을 검사한다.

## 센서와 제품 기본 광학

새 설정의 기본은 color, manual 렌즈 8.2409 mm다. 활성 왜곡 프로파일의 camera/lens/
crop fingerprint를 확인하며, 기존 사용자의 저장 설정이 제품 기본값보다 우선한다.
mono/color 변형은 단순 센서 ID만으로 자동 판별하지 않고 사용자 설정과 프로파일에 반영한다.
색이 없는 영상에 임의의 Bayer 색 보정을 적용하지 않는다.
기본 계수를 다른 렌즈의 실측값으로 취급하지 않는다.

## FOV·렌즈 측정·왜곡

렌즈 선택과 수동 초점거리로 FOV를 계산하고 optics 계약을 솔빙과 화면에 전달한다.
`Lens → Auto (Measure)`와 `Distortion → Measure Sky`는 명시적으로 요청한 측정 경로다.
활성 계수와 기하가 바뀌면 해당 전처리/솔빙·추적 기준도 갱신한다.

왜곡 보정은 영상을 remap하는 대신 검출 centroid를 Tetra3에 넣기 전에 변환하는 경로다.
표시 overlay로 되돌릴 때 좌표 변환을 일관되게 적용한다.
수동 TV distortion 사양과 하늘 실측 계수를 구분하고, 부호·정의·센서 반경을 확인한다.
이전 타일 복구 설계의 구현 상태를 현행 centroid 보정의 전제로 삼지 않는다.

## LiveCam과 RAW 스택

`RawLiveStackProcessor`는 선택한 입력/출력, mean/max 등 정규화된 설정과
프레임 한도를 관리한다. 같은 frame ID를 반복 누적하지 않고, 입력 크기와 source 변경을
처리하며 accepted/rejected 수와 원인을 상태로 제공한다.
웹 표시 이미지의 누적과 광학 solver의 성공 관측은 별개의 상태다.
스택 출력이 선명하다는 이유로 최신 plate solve가 있다고 판정하지 않는다.
별 대응/기준 재고정/누적 drift 개선을 제안한 안정화 조사는 구현 전체 완료를 뜻하지 않는다.

SQM은 RAW 측광, 센서 프로파일과 mono/color 판정을 사용한다.
도시광·구름·포화가 있는 특정 실측의 노출/gain 최적값을 모든 하늘의 기본값으로 복사하지 않는다.

## 소스와 회귀

- [카메라 인터페이스](../../python/MFNavis/camera_interface.py), [Pi 촬영](../../python/MFNavis/camera_pi.py), [프레임 AE](../../python/MFNavis/auto_exposure_framewise.py).
- [광학](../../python/MFNavis/optics.py), [렌즈 측정](../../python/MFNavis/lens_measurement.py), [RAW 스택](../../python/MFNavis/raw_live_stack.py).
- [프레임 AE 검사](../../python/tests/test_auto_exposure_framewise.py), [렌즈 검사](../../python/tests/test_lens_measurement.py), [광학 검사](../../python/tests/test_optics.py), [스택 검사](../../python/tests/test_raw_live_stack.py).

방법 조사·튜닝·측정값·미구현 제안은 [카메라 이력](../history/development/camera.md),
실측 결과는 [보고서](../mf_report/README.md)를 참조한다. 카메라 장착과 IMX678 준비는 [설치](setup_ko.md)에 통합했다.
