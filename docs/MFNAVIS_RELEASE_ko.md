# MFNavis 판매·소스 제공 기준 — 2026-09-23

## 제품 정체성

제품명은 **MFNavis**, 판매·배포 주체는 **FNPD 한국**(대한민국 소재 FNPD),
제작·수정자는 **MagicFly**다. 제품 UI·박스·상품 페이지에서 PiFinder를
제품명으로 사용하지 않는다. 출처 및 라이선스 설명에는 원 프로젝트 이름을 보존한다.
내부 Python 패키지, 서비스명, 경로, 저장소 주소는 호환성을 위해 유지한다.
상표 등록 또는 PiFinder 원 프로젝트의 공식 제품이라는 표현을 하지 않는다.

박스·상품 페이지 공통 문구:

> MFNavis — 천체 탐색·플레이트 솔빙 시스템
> 판매·배포: FNPD 한국 | 제작·수정: MagicFly
> 오픈소스 구성요소, 라이선스와 수정판 설치 안내는 동봉 자료를 참고하세요.

## GPL 대응소스 제공 방식

물리적 제품 판매는 **GPLv3 §6(a)** 방식으로, 기기와 함께 일반적으로 사용하는
내구성 있는 소스 매체(예: 별도 USB 저장장치)를 동봉한다. GitHub 링크만으로
이를 대체하지 않는다. 소스 매체에는 해당 이미지와 정확히 일치하는 PiFinder
파생 소스, MFDS GPL integration의 실제 변환된 소스, 빌드·설치 스크립트,
필요한 인터페이스 정의, GPL/LGPL 의존성의 해당 버전 대응소스와 변경분,
라이선스·NOTICE 및 수정판 설치 정보를 포함한다. 적용 가능한 System Library
예외는 구성요소별로 판단하고 단순히 OS 패키지라는 이유로 일괄 제외하지 않는다.

다운로드로 이미지를 배포하는 경우에는 **§6(d)**에 맞게 동일 장소에 동등하게
접근 가능한 대응소스를 추가 비용 없이 제공한다. 별도의 §6(b) 서면 제안만을
기본 방식으로 선택하지 않는다. MFDS native에 대한 권한 범위와 결합 배포 검토는
별도이며, IPC 사용만으로 GPL 적용 범위가 자동 확정되는 것은 아니다.
근거: https://www.gnu.org/licenses/gpl (원문 §6 및 User Product Installation Information).

## 수정판 설치 안내

1. 제품의 사용자 소유 SD 카드를 백업한다. 판매 이미지에 맞는 OS/아키텍처와
   Python 버전, 패키지 목록은 동봉 manifest와 의존성 목록을 사용한다.
2. 소스 매체의 PiFinder 소스를 사용자 홈 `~/PiFinder`에 복사한다. `~/PiFinder_data`
   설정·관측 자료는 별도로 보존한다. 원본 경로를 바꾸면 systemd 서비스의
   WorkingDirectory/ExecStart도 맞춘다.
3. 동봉 빌드·설치 스크립트와 고정된 의존성으로 환경을 재현한다. 정식 설치
   스크립트가 최신 브랜치를 가져오지 않도록 동봉 버전과 오프라인 아카이브를 쓴다.
4. 사용자가 원하는 GPL 소스를 수정하고 Python 환경에서 실행하거나
   `pifinder.service`의 ExecStart를 수정한 소스로 지정한다. 소유자 계정의
   서비스 관리 권한과 실제 unit 파일을 함께 제공한다.
5. GPL/LGPL 라이브러리를 ABI 호환 수정판으로 교체·재빌드할 수 있어야 한다.
   공급자의 서명만 허용하는 잠금이나 비공개 설치 키가 있다면 필요한 설치
   정보·권한을 제공해야 한다. 현재 제품에 없는 키가 있다고 가정하지 않는다.

위 절차는 출하 이미지에서 빈 SD 복원 및 수정판 실행으로 확인하고, 실제 계정명,
서비스 파일, 실행 명령과 결과를 출하 기록에 첨부한다. 아직 실기기 복원 검증을
마친 출하용 매뉴얼이라는 뜻은 아니다.

## 이미지별 고정 및 출하 확인

`deployment/mfds.lock.json`은 일반 MFDS 0.4.1 배포를 고정한다. 이 파일의
바이너리는 ctypes 포함 개발 패키지이므로 그대로 판매 이미지로 간주하지 않는다.
`make commercial`로 만든 새 패키지는 다른 해시를 갖는다. 판매용 lock은
`profile: commercial-process-only`를 요구하고 일반 패키지는 거절해야 한다.

각 이미지별 기록에는 다음 실측값을 넣는다. 예시 버전을 실제 출시로 선언하지 않는다.

- 제품 firmware 버전, 제품 이미지 파일명·SHA256
- MF_PiFinder tag와 전체 commit, 깨끗한 소스 트리 여부
- MFDS version·전체 commit, commercial profile, 아키텍처
- MFDS 아카이브 및 PACKAGE.json SHA256, 내부 파일 해시
- 동봉 대응소스 파일명·SHA256, 설치 정보와 고지 묶음의 해시
- Python/OS 패키지 실제 버전과 고지 누락 해결 기록

출하 전 `THIRD_PARTY_NOTICES.md`, `LICENSES/`, 수집한 `OPEN_SOURCE_LICENSES/`,
소스 매체 및 설치 매뉴얼을 함께 검사한다. 웹 자산·폰트·카탈로그·OS 펌웨어·
하드웨어/케이스·박스에 남은 원래 로고도 확인한다. 역사적 이미지나 CAD에 남은
PiFinder 표기는 현재 소프트웨어 브랜드 변경만으로 제거되었다고 보지 않는다.

판매용 설치 검사는 다음처럼 실행한다. 이 명령은 실제로 패키지를 활성화하므로
빌드/출하 준비 환경에서만 사용한다. 기존 일반 lock이나 미커밋 후보는 거절된다.

```sh
python3 scripts/install_mfds.py --commercial --lock deployment/mfds-commercial.lock.json --archive /path/to/MFDS-<version>-linux-<arch>-commercial.tar.gz
python/.venv/bin/python scripts/collect_product_licenses.py --output OPEN_SOURCE_LICENSES
```

`deployment/mfds-commercial.lock.json`은 MFDS v0.4.1 양 아키텍처의 정식
상용 패키지와 실제 해시를 고정한다. 기존 lock의 schema·version·source_commit·assets 구조에
`"profile": "commercial-process-only"`를 추가하고 URL/두 SHA256을 실제 파일로
계산했다. 이후 갱신에서도 없는 릴리스 URL이나 해시를 미리 만들어 배포하지 않는다.
고지 수집기의 종료 코드 1은 원문 누락 검토가 남았다는 뜻이다.

판매 이미지의 서비스에는 `deployment/mfnavis/20-commercial.conf`를
`mfnavis.service.d/20-commercial.conf`로 설치한다. 패키지 자체가 로더를
제외하므로 환경변수만 바꾸어 ctypes를 되살릴 수 없다. bytecode 생성을 꺼서
설치된 commercial 캐시의 파일 목록이 manifest와 일치하도록 유지한다.

이미지와 대응소스 묶음이 완성되면 아래 도구로 실제 파일 해시를 기록한다.
깨끗한 PiFinder 트리·HEAD와 일치하는 tag·clean commercial MFDS 패키지가
아니면 실패하며 기존 기록을 덮어쓰지 않는다. 소스 묶음의 완전성과 설치 가능성은
위 출하 검증으로 별도 확인한다.

```sh
python3 scripts/record_product_release.py --firmware-version <제품버전> \
  --pifinder-tag <실제태그> --image /path/to/MFNavis.img \
  --source-archive /path/to/corresponding-source.tar.gz \
  --mfds-archive /path/to/MFDS-<version>-linux-<arch>-commercial.tar.gz \
  --output /path/to/PRODUCT_RELEASE.json
```

판매 이미지는 `/etc/mfnavis-commercial` 표시 파일도 포함한다. 이 파일이 있으면
일반 setup/update에서 `--commercial`을 생략해도 판매용 lock과 패키지만 허용한다.
따라서 후속 업데이트가 일반 ctypes 포함 패키지로 조용히 되돌아가지 않는다.
이 작업에서는 운영 장비에 표시 파일이나 서비스 설정을 설치하지 않았다.

현재 구현·검증과 미완료 출하 항목은 [작업 결과](mf_report/mfnavis_commercial_20260923_ko.md)를 참고한다.


## 제품 로고

원본은 `images/MFNavis logo.png`(1254×1254 PNG)다. 원본 파일은 수정하지 않는다.
`PiFinder.branding.welcome_image()`가 화면 비율을 유지하고 상태 표시줄 아래에
맞춰 부팅 splash 서비스와 메인 서비스의 시작 콘솔에 표시한다.
웹 공통 헤더·로그인 화면·favicon·홈 화면 앱 아이콘은
`python/views/images/mfnavis-logo.png` 상대 심볼릭 링크로 같은 원본을 사용한다.
배포 시 원본 PNG와 이 링크를 함께 포함한다. 실행 중인 서비스가 로드한 Python
코드는 다음 서비스 시작부터 반영되며 부팅 화면은 다음 부팅에서 표시된다.
