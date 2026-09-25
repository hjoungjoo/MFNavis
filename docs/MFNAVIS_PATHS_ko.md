# MFNavis 제품 경로 (m2.6.11)

설치 계정과 홈 경로는 장비마다 다를 수 있으며, 아래 기본 경로는 해당 계정의 홈을 기준으로 한다.

| 용도 | 기본 경로 |
| --- | --- |
| 설치 저장소 | `~/MFNavis` |
| 애플리케이션 | `~/MFNavis/python/MFNavis` |
| 설정·관측·캡처·보정 데이터 | `~/MFNavis_data` |
| 임시 상태·로그 | `/dev/shm/mfnavis` |
| AP/STA 설정 | `/etc/mfnavis_apsta_nat.conf`, `/etc/mfnavis_sta_band.conf` |

신규 설치는 `mfnavis_setup.sh`, 코드 업데이트는 `mfnavis_update.sh`를 사용한다.
MFNavis 설치·업데이트 스크립트는 `~/MFNavis`만 대상으로 한다. 아래 경로 이전
도구는 과거 제품 설치본의 수동 이전을 위한 기록이며, 현재 설치 흐름에서는 실행하지 않는다.

```bash
python3 scripts/migrate_product_paths.py --home /home/pifinder
sudo python3 scripts/migrate_product_paths.py --home /home/pifinder --apply
```

첫 명령은 계획만 출력한다. 적용 명령은 관련 서비스를 정지한 뒤 기존 디렉터리를
이동하고 systemd·Samba 경로를 변경하며 이전에 실행 중이던 서비스를 재시작한다.
기존 경로는 호환 심볼릭 링크로 남는다. Python `PiFinder` import와 구형 스크립트
이름도 호환용으로 남지만 주 서비스는 `MFNavis.main`으로 실행한다.
두 경로에 별도 데이터가 이미 있으면 자동 병합하지 않고 중단한다.

시스템 설정 원본과 이동 기록은 `/var/backups/mfnavis-paths-<UTC시각>`에 저장된다.
적용 중 일반 오류가 발생하면 경로·설정을 되돌린다. 전원 차단처럼 복구 코드가 실행되지
못한 경우에는 해당 `journal.json`과 설정 사본을 이용해 수동 복구해야 한다.
이 기록은 사용자 데이터의 별도 백업을 대신하지 않는다.

`MFNAVIS_DATA_DIR` / `MFNAVIS_RUNTIME_DIR`로 경로를 지정할 수 있다.
사용자 지정 디렉터리는 이동하지 않는다. 기본 데이터 경로는
`~/MFNavis_data`이다.

새 ZIP 백업은 홈 경로를 포함하지 않는다. 이전 `PiFinder_data` 또는 `MFNavis_data`
경로를 담은 백업도 현재 데이터 디렉터리로 복원한다. MFDS 저장소·패키지·잠금 파일과
기존 원작 저작권 고지는 변경하지 않는다.
