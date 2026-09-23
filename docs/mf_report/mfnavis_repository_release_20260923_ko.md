# MFNavis 저장소 이전 및 m2.6.10 릴리즈

새 정식 저장소는 https://github.com/hjoungjoo/MFNavis 이다. 기존 MF_PiFinder에서 Git 이력을 계승하고 main 및 release 브랜치와 m2.6.10 태그를 게시한다. 기존 저장소는 삭제하거나 이력을 변경하지 않는다.

- 설치기의 신규 clone 주소 및 README의 설치·릴리즈 링크 전환
- 기기의 버전 조회와 migration gate 조회 주소를 새 저장소의 release 브랜치로 전환
- 기존 설치기의 origin이 이전 MF_PiFinder 주소인 경우 새 주소로 변경; 사용자 지정 원격 주소는 보존
- 원작 PiFinder 출처·라이선스, 과거 문서·보고서의 역사적 주소는 보존
- 내부 Python 패키지, 서비스 호환 별칭, 사용자 데이터 경로는 유지
- MFDS 저장소·패키지·고정 lock은 변경하지 않음

이번 릴리즈는 MFNavis 소프트웨어 소스 릴리즈이며 판매용 OS 이미지가 아니다. MFDS 판매용 clean package·commercial lock·대응소스 및 설치 정보 제공 요건을 완료한 판매 이미지와 구별한다.

기존 기기에서 원격 주소만 수동으로 전환할 경우:

```bash
git -C ~/PiFinder remote set-url origin https://github.com/hjoungjoo/MFNavis.git
```

이 명령 자체는 소스나 사용자 데이터를 변경하지 않는다. 코드 업데이트가 서비스/OS 변경을 감지하면 별도 시스템 설치가 필요하다고 중단하는 기존 정책을 유지한다.
