# MFNavis 제품명 적용 결과 — 2026-09-23

제품 브랜드는 **MFNavis**, 수정 제작자는 **MagicFly**, 판매·배포자는 **FNPD 한국**이다.

## 적용 범위

- 기기 제목, 시작 화면, 부팅 스플래시, 도움말, INDI 상태·오류·동작 설명
- 웹 제목·메뉴·제품 설명·PWA·로고·아이콘 및 다국어 제품 문자열
- 백업 다운로드 `MFNavis_backup.zip`, 새 실행 로그 `mfnavis.log`, 관측 목록 내보내기 제작자 표기
- 기본 AP 이름 `MFNavisAP`, 저장된 NetworkManager 연결 프로필의 제품명 접두사
- 정식 서비스 `mfnavis.service`, `mfnavis_splash.service`, `mfnavis_apsta_prepare.service`, `mfnavis_apsta_monitor.service` 및 선택적 GPS 시간 서비스 템플릿
- 제품 문서 진입점과 제품 안내. 기존 매뉴얼은 원작 자료임을 명시한 별도 진입점으로 보존

로고는 `images/MFNavis logo.png` 원본을 사용한다. 예전 이미지 경로는 새 로고를 가리키며 원작 아트워크는 `docs/history/upstream-branding/`에 보관했다. 도움말의 제품명 포함 이미지 두 장은 텍스트 기반 제품 안내로 교체했다.

## 유지한 이름과 이유

원작 PiFinder의 저작권·라이선스·출처·원본 하드웨어 도면·역사 자료는 보존했다.

기존 설치와 데이터의 호환성을 위해 Python `PiFinder` 패키지, `pifinder` 계정, `/home/pifinder/PiFinder` 및 `PiFinder_data` 경로, 환경변수·설정 키·IPC 식별자·파일 형식·기존 URL은 유지한다. 따라서 저장소 전체 문자열을 무조건 치환한 작업은 아니다. 기존 서비스 이름은 새 서비스를 가리키는 별칭으로 남겨 업데이트·복구 스크립트가 작동하도록 했다. 기존 로그와 백업도 계속 읽을 수 있다.

## 실제 기기 적용

`scripts/apply_product_branding.py --apply`를 실행했다. 설치된 unit의 실제 실행 옵션을 보존한 채 새 이름과 별칭을 구성하고 실행 중인 서비스를 재시작했다. 저장된 Wi-Fi 프로필 두 개는 연결 이름만 변경했으며 UUID·접속 대상 SSID·암호는 유지했다. hostapd를 재시작해 `MFNavisAP`를 적용했다.

원래 설정 백업: `/var/backups/mfnavis-branding-20260923T024348Z`.

재실행 계획은 변경할 unit 0개, 프로필 0개, SSID 변경 없음으로 확인됐다.

## 확인 결과

- 관련 pytest 309개 통과: sys_utils, INDI GoTo, Wi-Fi 서비스 구성, 웹 테마·장비 폼, 관측 목록 형식, 위치 서버
- 변경한 Python 파일 Ruff 검사 및 Python 컴파일 통과, `git diff --check` 통과
- Sphinx 문서 빌드 경고 없이 통과
- 도움말 두 장 × 두 글꼴 × 세 입력 크기 총 12가지 렌더링 확인; 로고 세 화면 크기 확인
- 실제 주 서비스 active/running, 재시작 횟수 0; 이전 `pifinder.service` 조회도 동일 새 unit으로 연결
- 주 서비스·스플래시·AP 보조 서비스의 부팅 자동 시작 enabled 확인
- 기기 화면 캡처에서 MFNavis 제목 확인
- TCP 4030 `:GVP#` 응답 `MFNavis#` 확인
- 로컬 웹 HTTP 200 및 MFNavis 제목 확인; 웹 로고 바이트 SHA256이 제공된 원본과 동일

AP에 연결하던 기기는 새 네트워크 이름 `MFNavisAP`를 선택해야 한다. 실제 전원 재부팅은 수행하지 않았다. 판매용 MFDS 패키지의 발행·고정 및 최종 이미지 배포는 별도 릴리즈 절차이며, 이번 브랜드 적용으로 기존 개발용 설치가 판매용 이미지로 바뀌는 것은 아니다.
