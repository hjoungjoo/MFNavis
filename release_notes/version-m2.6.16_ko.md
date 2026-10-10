# MFNavis m2.6.16 — Nox 프로세스 종료 검사 수정 패키지 반영

MFDS **v0.4.3** 정식 패키지를 고정합니다. 부모 프로세스 종료 검사에서
`/proc/<pid>/stat`를 열고 읽는 사이에 worker가 종료되면 발생하는
`ProcessLookupError`를 정상 종료로 처리합니다. 살아 있는 worker에 대한
2초 종료 제한은 유지합니다. m2.6.15 release CI에서 발생한 간헐적
Nox 3.11 테스트 실패의 재발 방지 수정이 설치 패키지에도 포함됩니다.

일반 및 process-only 판매용 lock의 소스 커밋·ARM64/x86_64 패키지와
manifest SHA256을 실제 빌드 결과로 갱신합니다. 검출 알고리즘·C ABI 1과
MFDS1 프로토콜은 유지됩니다. SkySafari 좌표 갱신, LCD `0` 키 추적 정지와
중복 제목 수정 등 m2.6.15의 변경도 포함합니다.

## 설치

Raspberry Pi OS **Trixie 64-bit / Python 3.13**에서 설치 계정으로 실행합니다.

```bash
wget -O /tmp/mfnavis-m2.6.16-setup.sh https://raw.githubusercontent.com/hjoungjoo/MFNavis/m2.6.16/mfnavis_setup.sh &&
MFNAVIS_INSTALL_BRANCH=m2.6.16 bash /tmp/mfnavis-m2.6.16-setup.sh
```

완료 후 재부팅하세요. 상세 절차는 [Trixie 설치 안내](../docs/history/development/setup.md#mf_trixie_install_ko)를 따릅니다.
이번 배포는 소프트웨어 소스와 설치 자료입니다.

[전체 변경 비교](https://github.com/hjoungjoo/MFNavis/compare/m2.6.15...m2.6.16)
