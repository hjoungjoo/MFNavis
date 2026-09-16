# MFDS 라이선스 표기 정리 패치 릴리즈

## 계획

MFDS 자체 정책으로 라이선스 설명과 식별자를 정리하고 MFDS v0.2.1 / PiFinder m2.6.6으로 정식 릴리즈한다. 과거 태그·버전별 기산일·저작권 고지·라이선스 조건·검출 동작은 유지한다.

## 변경과 검증

- 현재 식별자는 `LicenseRef-MFDS-FSL-1.1-MIT-5year`. LICENSE·LICENSING·상용 사용 안내, README, native SPDX와 식별자 파일·검사 도구·MFDS 라이선스 설명을 정리했다.
- PiFinder 통합 안내를 MFDS 자체 native 정책으로 수정하고 submodule을 `7a772cfd022ed6072018f934271c58e7c33dea7e`로 고정한다.
- Functional Source License 본문 해시 `8f822494dbb1e4ef5f655245257cc449b81450e59dd122f6f9197e1d7622b8c9`는 그대로다. native C++/헤더/테스트는 SPDX 고지 다음 코드가 v0.2.0과 동일함을 확인했다.
- native 7/7, 라이선스·레이아웃·버전 검사·검사 도구 Ruff 통과. 외부 소스의 원래 고지와 과거 비교·이관 기록은 별도의 출처 기록으로 보존한다.
- 고정 submodule의 process/ctypes·통합 경로·출처 기록 관련 51개 테스트, Ruff·포맷·운영 잔여 검사 통과. PiFinder Python 실행 코드는 m2.6.5와 동일하다.
- 최종 CI와 배포 확인은 [MFDS v0.2.1](https://github.com/hjoungjoo/MFDS/releases/tag/v0.2.1) 및 [PiFinder m2.6.6](https://github.com/hjoungjoo/MF_PiFinder/releases/tag/m2.6.6)의 게시 본문에 기록한다.
