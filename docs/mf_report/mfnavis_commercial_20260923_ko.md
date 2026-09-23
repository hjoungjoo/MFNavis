# MFNavis 판매 구성 정리 결과 — 2026-09-23

## 반영

- 제품 MFNavis, 판매·배포 FNPD 한국, 제작·수정 MagicFly.
- 웹 제목·텍스트 로고·PWA·메뉴·부팅/콘솔 화면·프로토콜 제품명과 번역을 변경했다.
  Python import·서비스명·기존 경로는 호환성을 위해 보존했다.
- 원본 README는 `README.upstream*.md`로 보관하고 제품 안내와 분리했다.
- `THIRD_PARTY_NOTICES.md`, `LICENSES/`, GPL 소스 동봉·수정판 설치 기준,
  박스 공통 표기와 이미지별 해시 기록 도구를 추가했다.
- MFDS는 자체 native 기여, PiFinder GPL integration, legacy MIT의 권리 범위를
  분리했다. MagicFly의 자체 기여 표기이며 기존 코드의 단독 소유·권리 양도를
  추정하지 않았다. FSL 본문 및 과거 MIT 원문은 보존했다.
- `make commercial`은 worker만 포함한다. MFDS detector, GPU/NEON 전처리의
  `.so` 및 Python 로더 코드를 판매 패키지에서 제거한다. 개발 소스의 비교 기능은
  유지한다. 판매용 설치기는 일반 profile·dirty 소스·추가 payload를 거절한다.
- release-assets CI는 다음 실행부터 두 아키텍처의 commercial 패키지를 함께 만든다.
  이번 작업에서 CI 실행·업로드·정식 릴리스 발행은 하지 않았다.

## 실제 검증

- ARM64 commercial 패키지 생성 성공. 파일 목록·AST 검사에서 MF native 로더 및
  공유 라이브러리 없음. 환경변수 ctypes 선택 거절, 별도 PID worker 검출 성공.
- 새 commercial 검증 테스트 11개 통과(패키지 5개, 설치 정책 6개).
- 관련 기존 위치 서버·웹 폼/좌표 테스트 91개와 설치 테스트 5개를 함께 실행하여
  당시 96개 통과. 이후 추가한 판매 이미지 marker 테스트까지 설치 6개 재검증.
- smoke 7개 통과. 실제 commercial 패키지의 CPU 전처리 테스트 20개 통과.
  독립 MFDS 테스트 실행에서 pytest `unit` marker 미등록 경고 1개만 발생했다.
- 변경 Python의 Ruff lint/format, 두 저장소 `git diff --check` 통과.
- 고지 제공 URL, 경로 이탈 차단, SVG MIME 확인. 다섯 언어 번역 컴파일 성공.
- 라이선스 scope 검사 통과. 기존 FSL 본문 SHA256
  `8f822494dbb1e4ef5f655245257cc449b81450e59dd122f6f9197e1d7622b8c9` 유지.

## 산출물 및 출하 전 남은 사항

후보 패키지: `/home/pifinder/MFDS/dist/commercial/MFDS-0.4.0-linux-aarch64-commercial.tar.gz`

후보 정확한 해시·base commit·dirty 표시는
`/home/pifinder/PiFinder_test_data/results/mfnavis_20260923/CANDIDATE.json`에 기록했다.
변경된 작업 트리의 검토 후보이므로 기존 v0.4.0 공식 바이너리와 동일한 릴리스로
표시하지 않는다. 소스 commit/tag 확정, 양 아키텍처 정식 패키지와 판매용 lock,
전체 OS 이미지·대응소스 매체 및 실제 수정판 설치 검증은 아직 수행하지 않았다.
운영 서비스·현재 설치된 MFDS·기존 일반 lock은 변경하지 않았다.

현재 개발 장비의 고지 수집 결과는 같은 결과 디렉터리의 `OPEN_SOURCE_LICENSES/`에
보관했다. Python 패키지 145개 중 원문 파일 미확인 18개, OS copyright 미확인
8개가 있다. 개발 도구도 포함된 목록이며 실제 판매 이미지의 확정 목록이 아니다.
실제 이미지에서 불필요한 개발 도구를 제외하고 남은 패키지 원문/대응소스를 확보한다.

Python 미확인: adafruit-extended-bus, docutils, pam, pygame, pyserial,
python-libinput, selenium, sep, sphinxcontrib-applehelp, sphinxcontrib-devhelp,
sphinxcontrib-htmlhelp, sphinxcontrib-jquery, sphinxcontrib-qthelp,
sphinxcontrib-serializinghtml, types-pytz, types-requests, types-tqdm, types-urllib3.
SEP는 LGPLv3 및 AUTHORS를 기본 고지에 별도로 동봉했으나 정확한 배포 소스의
개별 저작권 고지·대응소스 확보는 출하 기록에서 확인해야 한다.

OS 미확인: libliftoff-rpi, libwidevinecdm0, pi-package, pi-package-data,
pi-package-session, raspberrypi-net-mods, sense-hat, systemd-timesyncd.
웹 자산·폰트·천문 데이터·케이스/CAD·실제 박스의 권리 및 로고도 별도 확인 대상이다.
