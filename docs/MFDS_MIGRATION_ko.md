# MFDS 공개 저장소 전환 — 2026-09-16

사용자 요청으로 최종 MF 소스·전처리·통합 코드·집계 자료를 공개 저장소
`hjoungjoo/MFDS`로 옮기고 PiFinder가 이를 사용하도록 변경한다.
이관 전 원본은 mf_detect_star `2f556b448aa21782c478cd47215ab54899055cf7`,
새 고정 커밋은 `2be2336635384e350fb50f9fcc91f501c00a4dde`다. MFDS PUBLICATION.json에 파일별 출처 해시를 보존한다.

## 계획과 변경

- 새 공개 저장소는 최종 추적 소스 149개에서 시작한다. 비공개 전체 이력·장비
  원본은 공개하지 않는다. 기존 비공개 이력은 로컬 보존 기록으로 남긴다.
- native FSL 5년 조건과 LICENSE 원문, 통합·전처리 GPL 및 과거 MIT 고지를
  유지한다. 공개 상태나 저장소 이름 변경이 새 라이선스 허락을 만들지 않는다.
- submodule URL과 GitHub Actions checkout을 MFDS로 바꾸고 개인 SSH 키 입력을
  제거한다. `.gitmodules`의 이름/경로와 프로그램 ABI는 호환성을 위해 유지한다.
- 새 소스·자료와 설치·CI·운영 확인 후 기존 mf_detect_star 원격 저장소를 삭제한다.
- m2.6.3 태그는 이동하지 않고 m2.6.4를 정식 릴리즈한다. 이전 버전의 원격
  submodule은 저장소 삭제 후 접근할 수 없으므로 신규 설치는 m2.6.4를 사용한다.

## 기존 m2.6.3 설치의 수동 전환

서브모듈 URL 변경은 의도적으로 일반 코드 갱신기의 자동 적용 대상이 아니다.
설정과 관측 자료를 보존하고 깨끗한 체크아웃에서 다음과 같이 전환한다.

```bash
git -c fetch.recurseSubmodules=false fetch origin release
git merge --ff-only origin/release
git submodule sync -- python/mf_detect_star
git submodule update --init -- python/mf_detect_star
bash scripts/ensure_tetra3_link.sh .
bash scripts/setup_mf_detect_star.sh
```

이 절차는 새 소스와 빌드를 준비한다. 이번 전환은 native 실행 코드가 동일해
운영 장비를 재시작하지 않는다. 이후 실행 코드가 달라지는 업데이트에서는
빌드 완료 후 해당 버전의 서비스 전환 지침을 따른다.
GitHub 자동 소스 ZIP/tar.gz에는 submodule이 포함되지 않으므로 Git clone을 사용한다.

## 검증 범위

원본과 MFDS의 실행 코드·테스트·빌드·라이선스 해시 동일성을 확인했다.
MFDS 공개 CI와 인증 없는 clone/build, native 6/6 및 라이선스/레이아웃 검사를
통과했다. PiFinder는 전체 검사 2,435개가 통과했고 기존 URL 기대값 1개를
갱신한 뒤 관련 회귀 59개를 통과했다. lint/포맷 427파일, 타입 검사 206소스를
통과했다. 최종 원격 CI와 삭제 결과는 릴리즈 본문 및 로컬 이관 기록에 남긴다.
마운트 전원 OFF 조건이며 이번 저장소 전환으로 검출 성능이나 GoTo 이동을
새롭게 측정한 것은 아니다. 사용자 완료 기준 90초각 설정을 유지한다.
