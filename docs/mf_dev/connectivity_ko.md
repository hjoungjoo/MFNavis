# INDI 연결·GPS·시각·네트워크

기준: 2026-10-10 작업 트리. 설치는 [Trixie 안내](setup_ko.md), 이동·취소·한계 정책은
[마운트 제어](mount_control_ko.md)를 따른다.

## INDI Serial/Ethernet과 복구

웹 INDI 설정은 서버 주소·장치·전송 방식과 실제 드라이버 속성을 대조한다.
Serial Auto는 후보 포트 식별, 동일 장치 경로 중복 제거와 OnStep 읽기 전용 probe를 사용한다.
기존 INDI가 포트를 점유할 때에는 장치 DISCONNECT 응답을 확인한 뒤 탐색한다.
probe 성공, 설정 적용, 재연결 성공은 서로 다른 단계이며 실패 원인과 적용 결과를 남긴다.
단순 USB 재삽입과 연결 중 통신 이상을 구분하고, 구 연결의 명령/응답을 새 연결의 증거로 재사용하지 않는다.
재연결 자체가 사용자의 한계 정지 해제나 취소된 타겟 복원을 뜻하지 않는다.
포트와 속도를 바꾼 뒤 연결 상태·site/time·프로토콜 응답을 확인한다.

## 보드와 I2C/UART

Pi 4의 GPS는 `uart3`/`/dev/ttyAMA3`, Pi 5·CM5는 `uart2-pi5`/`/dev/ttyAMA2`를 사용한다.
Pi 5 계열의 UART 선택은 OLED GPIO8/9 충돌을 피한다.
부트 설정은 `/boot/firmware/config.txt`, SPI 표시는 선택한 보드/디스플레이 경로에 따른다.
BNO055 I2C clock-stretching 대응은 보드 프로파일과 설치 설정을 확인한다.
다른 보드에서 과거 핀 설정을 그대로 복사하지 않는다.

## GPS와 시간 소유권

Linux system clock은 chronyd가 관리한다. gpsd는 GPS와 NTP SHM을 공급하고
MFNavis는 Chrony/GPS 상태를 관찰하며 선택적 RTC helper 요청을 처리한다.
현재 앱의 수동 시각은 앱 시각의 세션 우선값이며 system clock 직접 쓰기와 구분한다.
`Time Sync`와 `Chrony Source`, `GPS Source`, 선택적 `RTC Sync`의 관찰 상태를 확인한다.

신뢰 전이와 시각 점프는 mount site/time 재전송에 반영한다. 큰 점프나 수동 시각 변경은
관련 추적 타겟을 해제한다. 일반 연결 초기화는 잠정 시간을 전송할 수 있으나
다중 정렬은 별도의 신뢰 게이트를 적용한다. GPS 위치 잠금, 시각 신뢰와 mount 연결은 독립 상태다.

gpsd 설치기는 릴리즈와 checksum을 고정해 빌드/검증한다.
이전 문서의 “최신 안정 버전”은 해당 조사 날짜의 결과이며 자동 최신 정책을 뜻하지 않는다.
현재 설치 값은 `scripts/install_gpsd_stable.sh`를 따른다.

상태 확인 예:

```bash
chronyc tracking
chronyc sources -v
systemctl status gpsd gpsd.socket --no-pager
```

앱 상태와 helper 경로는 선택한 `utils.runtime_dir`·데이터 루트를 기준으로 확인한다.
하드코딩된 이전 `/home/pifinder/PiFinder` 경로를 현재 개발 환경에 적용하지 않는다.

## Wi-Fi AP·STA·AP+STA

Client는 STA 인터넷 접속, AP는 현장 접속, AP+STA는 `wlan0` STA와 `uap0` AP를 함께 쓴다.
기본 AP 주소는 `10.10.10.1`이다. 웹 Network Setup에서 모드·AP 주소·보안·STA 목록·
밴드 선호와 선택적 인터넷 공유를 관리한다. 저장과 실제 적용/재시작은 별도 동작이다.

단일 라디오의 AP는 STA 채널을 따라간다. 2.4 GHz만 지원하는 마운트가 연결될 경우
STA 밴드도 장치 호환 채널로 설정한다. Imager/NetworkManager의 초기 네트워크는
설치·마이그레이션 가져오기를 통해 반영하며, AP station 연결과 DHCP lease-only 표시를 구분한다.

## 구현·검증 근거

- [마운트 연결](../../python/MFNavis/mountcontrol_indi.py), [시스템 도우미](../../python/MFNavis/sys_utils.py), [네트워크 구현](../../python/MFNavis/sys_utils.py).
- [Serial Auto 검사](../../python/tests/test_server_serial_auto.py), [시각 검사](../../python/tests/test_gps_time_sync.py).
- [gpsd 설치기](../../scripts/install_gpsd_stable.sh), [AP+STA 제어](../../scripts/pifinder_apsta.sh).

시리얼 probe의 상세 transaction, GPS aiding 계획, I2C 실측과 네트워크 장애 분석은
[연결 이력](../history/development/connectivity.md)에 통합했다. 장비별 성공 기록은 [실측 보고서](../mf_report/README.md)에서 확인한다.
