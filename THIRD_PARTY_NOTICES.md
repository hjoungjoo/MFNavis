# MFNavis — third-party notices / 제3자 고지

제품: **MFNavis** · 판매·배포: **FNPD 한국** · 제작·수정: **MagicFly**

MFNavis는 PiFinder에서 파생된 제품이다. PiFinder는 원 프로젝트의 명칭이며
제품명이나 원 프로젝트의 공식 판매·보증을 뜻하지 않는다. 원저작자 고지는
유지하고 MagicFly의 변경 부분을 구분한다. GPL 부분은 GPL에 따라 사용·수정·
재배포할 수 있으며, 제품 판매 조건으로 이 권리를 제한하지 않는다.
각 라이선스의 무보증 조항은 해당 원문을 따른다.

| 구성요소 | 출처·권리자 | 조건 / 동봉 원문 |
|---|---|---|
| PiFinder / MF_PiFinder 및 파생 변경 | PiFinder 원저작자·기여자, MagicFly의 변경 부분 | [GPLv3](LICENSES/GPL-3.0.txt); 파일별 원래 고지 유지 |
| MFDS native | MagicFly 자체 작성·수정 부분, 그 밖의 원래 고지 | 설치된 `python/MFDS/LICENSE`, `LICENSING.md`의 FSL 5년 후 MIT 정책 |
| MFDS의 PiFinder integration·전처리 | PiFinder 기여자 및 각 파일 작성자 | GPLv3; FSL 상용 제한을 적용하지 않음 |
| MFDS legacy MIT | 원문상의 PiFinder contributors | [MIT 원문](LICENSES/MIT-MFDS-legacy.txt); 이전 허락 유지 |
| Tetra3 및 포함된 파생 solver | `python/PiFinder/tetra3/VENDORED.md`와 각 원본 파일의 작성자 | [Apache-2.0](LICENSES/Apache-2.0-Tetra3.txt); 원본 attribution 유지 |
| SEP 1.4.1 | [SEP authors](LICENSES/SEP-AUTHORS.md); 포함된 SExtractor 코드의 원래 저작자 | LGPL-3.0-or-later: [LGPLv3](LICENSES/LGPL-3.0.txt) + GPLv3; 수정·교체 가능한 배포와 대응소스 제공 |
| Python 의존성과 포함된 하위 라이브러리 | 설치 패키지별 원저작자 | 판매 이미지에서 수집한 `OPEN_SOURCE_LICENSES/python/`의 원문·NOTICE·METADATA |
| Debian/Raspberry Pi OS 및 native 의존성 | 설치 패키지별 원저작자 | `OPEN_SOURCE_LICENSES/os/`의 copyright 원문 및 패키지 목록 |
| 웹 JS/CSS·폰트, 천문 카탈로그, 사진·하드웨어 설계 | 각 파일의 원래 출처 | 소프트웨어 라이선스와 별도로 원본 고지·사용 조건 확인 |

NumPy/SciPy의 bundled BLAS 등은 상위 패키지 이름만으로 고지를 대신하지 않는다.
빌드에 실제로 설치된 의존성의 원문을 `scripts/collect_product_licenses.py`로 수집한다.
라이선스 파일이 없는 패키지는 미확인 목록에 기록하며 해결 전 출하하지 않는다.
이 문서는 OS 전체 및 데이터·폰트까지 자동으로 승인한 완결된 법률 감사가 아니다.

대응소스 동봉 방식과 수정판 설치 절차는
[판매·소스 제공 문서](docs/MFNAVIS_RELEASE_ko.md)를 따른다.
