# MFNavis 설치·업데이트 경로 점검

## 수정 사항

- `pifinder_setup.sh`: 기존 서비스명을 먼저 이관한 뒤 MFNavis 서비스 템플릿을 설치한다. 기존 AP 설정을 덮어쓰지 않아 사용자 SSID·암호가 보존된다. 기본 PiFinderAP만 MFNavisAP로 변경된다.
- `pifinder_post_update.sh`: 명시적인 시스템 업데이트에서는 MFDS 설치 검증 후 브랜드 이관을 실행한다. 실패 시 중단하도록 설정했다. 코드 전용 업데이트는 기존처럼 시스템 변경 없이 조기 종료한다.
- `migration_source/v1.x.x.sh`: 이전 서비스 파일을 무조건 삭제·재설치하던 부분을 수정했다. 이관된 실제 실행 옵션을 보존하고 없는 MFNavis 서비스만 생성한다. splash 파일 검사 오타도 제거했다.
- `migration_source/mf_apsta_wifi.sh`: 새 AP 보조 서비스를 MFNavis 이름으로 설치·활성화한다.
- `scripts/install_gps_time_sync_helper.sh`: MFNavis 서비스명을 사용한다. 기존 GPS 서비스만 선택적으로 이관하며 다른 서비스와 네트워크는 변경하지 않는다. 일반 모드 활성화 시 기존 별칭 경로의 dry-run 설정도 제거한다.
- `scripts/apply_product_branding.py`: 선택적 서비스 이관, 네트워크 제외 모드, NetworkManager 미설치 환경을 지원한다. 변경이 없으면 백업이나 재시작 없이 종료한다.
- 업데이트 완료 안내와 판매용 service drop-in 설치 문서의 이름을 MFNavis로 정리했다.

## 업데이트 방식과 판매용 보호

`pifinder_update.sh` → `transactional_update.py` → 후보 checkout 준비 → 검증 후 활성화의 흐름을 유지한다. 코드 업데이트는 서비스 재시작·OS 패키지 설치·네트워크 설정 변경을 하지 않는다. `pi_config_files` 또는 `migration_source` 변경은 별도 시스템 설치가 필요하다는 오류로 중단한다. 따라서 이번 서비스 이름 전환은 일반 코드 업데이트만으로 적용하는 변경이 아니다.

`/etc/mfnavis-commercial`이 있는 이미지에서는 후보 준비와 최종 MFDS 설치가 모두 판매용 lock을 요구한다. 해당 lock이 없거나 일반 개발용 패키지라면 거부한다. 현재 정식 판매용 lock·패키지 발행은 별도 릴리즈 작업이며, 이 점검에서 개발 패키지를 판매용으로 승인하지 않았다.

내부 계정·패키지·데이터 경로, 원격 저장소 URL, 기존 설치 스크립트 파일명은 호환성을 위해 유지한다.

## 검증

관련 셸 스크립트 구문 검사, 변경한 Python의 Ruff 검사, diff 공백 검사 수행. 서비스 이관·기존 옵션 보존·별칭·반복 실행·시작 실패 시 복구·GPS 한정 이관·NetworkManager 없는 환경을 모의 파일시스템에서 검증했다. 코드 업데이트 및 판매용 설치 회귀 테스트를 포함해 **37개가 통과**했다. 후처리 스크립트의 실패 시 중단 설정 추가 후 업데이트 관련 **21개를 다시 실행해 통과**했다.

실제 전체 설치, 원격 업데이트, GPS 보조 서비스 활성화 또는 기기 재부팅은 실행하지 않았다. 설치 스크립트 전체의 새 OS 이미지 실증 테스트는 별도로 필요하다.
