# MF PiFinder Wi-Fi AP+STA 모드

PiFinder Wi-Fi 모드는 세 가지입니다.

| 모드 | 의미 |
| --- | --- |
| `Client` | `wlan0`이 저장된 Wi-Fi에 STA로 접속합니다. 인터넷 접속과 업데이트에 사용합니다. |
| `AP` | `wlan0`이 `PiFinderAP` access point가 됩니다. 스마트폰/태블릿은 `10.10.10.1`로 접속합니다. |
| `AP+STA` | `wlan0`은 STA로 인터넷에 접속하고, `uap0` 가상 인터페이스가 `PiFinderAP`를 제공합니다. |

## 동작 방식

`AP+STA`는 Raspberry Pi의 내장 Wi-Fi 하나를 STA와 AP로 동시에 사용합니다. 단일 라디오이므로 AP는 STA가 접속한 채널과 같은 채널을 사용해야 합니다.

PiFinder는 `AP+STA` 모드에서 다음을 수행합니다.

- `wlan0`은 기존 `wpa_supplicant` 설정을 사용해 외부 Wi-Fi에 접속합니다.
- `uap0` 가상 AP 인터페이스를 생성합니다.
- `dnsmasq`는 `uap0`에서 `10.10.10.2`부터 `10.10.10.20`까지 DHCP를 제공합니다.
- `hostapd`는 `uap0`에서 PiFinder AP를 제공합니다.
- STA 채널을 감시하고, 채널이 바뀌면 `hostapd` 채널을 갱신한 뒤 재시작합니다.

시작 시에는 STA 채널을 잠깐 기다린 뒤 AP를 시작합니다. STA가 아직 연결되지 않았거나 채널을 알 수 없으면 기본 채널 `7`을 사용합니다. 이후 STA가 연결되어 채널이 확인되면 AP 채널을 STA 채널로 맞춥니다.

## 설정 위치

웹 UI:

```text
Network Setup > Wifi Mode > AP+STA
```

같은 Network 페이지에서 다음 항목도 설정합니다.

- AP 네트워크 이름
- AP IP 주소. 기본값은 `10.10.10.1`이며, 클라이언트는 같은 `/24` 대역에서 DHCP 주소를 받습니다.
- AP 보안 모드: Open 또는 WPA2 Password
- AP 암호: WPA2 선택 시 8-63자
- 저장된 STA 네트워크
- 새 STA 네트워크 추가 시 주변 Wi-Fi 스캔 목록
- AP+STA 인터넷 공유. 기본값은 Off입니다.
- STA 밴드 선호: Auto, Prefer 2.4 GHz, Prefer 5 GHz
- AP 접속 장치 목록. 현재 연결된 station 상태와 DHCP lease를 함께 보여줍니다.

### 저장과 적용의 분리 (2026-08-07)

Network 페이지의 편집은 **저장(설정 파일 기록)**과 **적용(네트워크 재구성)**이
분리되어 있습니다. STA 목록 추가/삭제/우선순위 변경과 밴드 선호 변경은 저장만
되고, 주황색 "Apply Now" 배너 버튼을 눌러야 NetworkManager 프로파일 동기화와
`wpa_cli reconfigure`가 실행됩니다(이 단계에서만 STA 링크가 잠시 끊길 수
있습니다). 모드/AP 설정 폼도 "Save Settings"(저장만)와 "Apply &
Restart"(저장+모드 전환+재시작)로 나뉩니다. 수시 끊김과 재접속 실패를 막기
위한 구조입니다.

### STA 우선순위와 수동 접속

- 저장된 STA 목록은 접속 우선순위 순으로 표시되며, 행의 ▲/▼로 순서를
  바꿉니다. 우선순위는 `wpa_supplicant`의 `priority=`(높을수록 선호)와
  NetworkManager `connection.autoconnect-priority`에 함께 기록됩니다(적용 시).
- 행의 Wi-Fi 아이콘은 해당 SSID로 **지금 즉시** 접속을 전환합니다(nmcli
  `con up`; 명시적 사용자 액션이라 적용 대기 없이 실행). 해당 SSID의
  NetworkManager 프로파일이 아직 없으면 먼저 Apply가 필요합니다.
- **전파 범위 사전 검사(2026-08-08)**: 전환 전에 Wi-Fi 스캔으로 대상 SSID가
  보이는지 확인하고, 안 보이면 현재 링크를 건드리지 않고 즉시 오류를
  돌려줍니다("not in range"). 안 보이는 SSID로 `con up`을 실행하면
  NetworkManager가 현재 링크부터 끊고 타임아웃까지 기다린 뒤 자동접속으로
  다른 저장 네트워크에 붙어, 웹 세션이 죽고 "다른 Wi-Fi로 접속된" 것처럼
  보였기 때문입니다(현장 관찰). `con up`에는 25초 대기 상한(`-w 25`)을
  둡니다. 스캔 자체가 실패(빈 결과)하면 차단하지 않고 진행하며, 그
  트레이드오프로 다른 네트워크가 보이는 동안 숨김 SSID로는 전환할 수
  없습니다.
- **현재 접속 표시(2026-08-08)**: 목록에서 현재 접속된 SSID
  행(`get_connected_ssid()` 일치)은 녹색 "Connected" 체크 표시가 붙고, 접속
  버튼 대신 녹색 Wi-Fi 아이콘(비활성)이 표시됩니다.
- **비동기 전환 + 결과 배너(2026-08-08)**: 검증 통과 후 실제 `con up`은
  HTTP 응답을 먼저 내보낸 뒤 백그라운드 스레드에서 1초 지연 후 실행합니다.
  전환을 인라인으로 하면 응답을 실어 나르는 링크가 먼저 끊겨 사용자는
  성공/실패 어느 쪽의 피드백도 못 받았습니다("버튼 반응 없음"으로 관찰).
  응답에는 "전환 중, 이 페이지 연결이 끊길 수 있음" 안내가 나가고, 전환
  결과는 `get_last_connect_result()`에 남아 다음 페이지 로드 때 배너로
  표시됩니다(성공=녹색, 실패=적색).

기기 UI:

```text
Settings > WiFi Mode > AP+STA Mode
```

변경 후에는 시스템 재시작이 필요합니다.

## STA 네트워크 가져오기

Raspberry Pi OS Trixie을 처음 설치할 때 Raspberry Pi Imager에서 설정한 Wi-Fi는 `/etc/wpa_supplicant/wpa_supplicant.conf`가 아니라 NetworkManager 프로파일에 저장될 수 있습니다.

PiFinder는 설치 및 업데이트 마이그레이션 과정에서 이 OS 기본 Wi-Fi 프로파일을 가져와 저장된 STA 네트워크 목록에 표시되도록 합니다. 웹 UI도 가능한 경우 NetworkManager 프로파일을 직접 읽으므로, 아직 `wpa_supplicant`로 옮겨지기 전의 초기 OS Wi-Fi도 목록에 보일 수 있습니다.

웹 UI에서 새 STA 네트워크를 추가할 때는 주변 Wi-Fi를 스캔해 SSID를 선택할 수 있습니다. 숨김 네트워크나 스캔 실패 상황을 위해 수동 SSID 입력도 유지됩니다.

편집 대상인 `/etc/wpa_supplicant/wpa_supplicant.conf`는 PiFinder 서비스 사용자 소유의 `600` 권한으로 유지합니다. 따라서 PiFinder는 저장된 STA 네트워크를 수정할 수 있지만 Wi-Fi 암호가 모든 로컬 사용자에게 노출되지는 않습니다.

## AP 접속 장치 목록

Network 페이지에서는 PiFinder AP에서 보이는 장치 목록을 확인할 수 있습니다. `Connected`로 표시되는 항목은 현재 hostapd에 실제로 연결된 AP station입니다. `Lease only`로 표시되는 항목은 DHCP lease 기록은 남아 있지만 현재 AP station으로는 보이지 않는 장치입니다.

## AP 보안

AP 보안 설정은 `/etc/hostapd/hostapd.conf`를 공통으로 사용하므로 `AP` 모드와 `AP+STA` 모드에 모두 적용됩니다.

지원 모드:

- `Open`: AP 암호 없음
- `WPA2 Password`: hostapd에 `wpa=2`, `wpa_key_mgmt=WPA-PSK`, `rsn_pairwise=CCMP`를 설정

AP 보안 방식이나 암호를 변경한 뒤에는 재시작해야 클라이언트가 새 설정으로 다시 접속할 수 있습니다.

AP IP 주소를 변경한 뒤에도 재시작이 필요합니다. 재시작 후에는 `10.10.10.1` 대신 새 AP IP 주소로 접속해야 합니다. `gw.wlan` DNS 별칭도 선택한 AP IP로 갱신됩니다.

## AP+STA 인터넷 공유

AP+STA 모드에서는 선택적으로 STA 쪽 인터넷 연결을 PiFinder AP에 접속한 클라이언트에 공유할 수 있습니다. 이 기능은 IPv4 forwarding과 PiFinder 전용 `nft` masquerade table을 사용합니다.

기본값은 Off입니다. 이 기능은 Pi에 라우팅 부하를 추가하고 속도가 느릴 수 있으므로 필요한 경우에만 켜는 것을 권장합니다. 특히 PiFinder가 촬영, plate solving, 웹 UI 처리를 동시에 수행하는 중에는 더 느려질 수 있습니다.

PiFinder는 AP+STA 모드가 활성화되어 있고 STA 인터페이스에 default route가 있을 때만 인터넷 공유를 켭니다. STA 인터넷이 사용할 수 없는 상태이면 NAT table을 제거하며, 이 경우에도 PiFinder AP 제어 기능은 그대로 사용할 수 있습니다.

## STA 밴드 선호

같은 SSID가 2.4 GHz와 5 GHz를 동시에 제공하는 경우, Network 페이지에서 STA 접속 밴드를 선택할 수 있습니다.

옵션:

- `Auto`: STA 스캔 주파수를 제한하지 않습니다.
- `Prefer 2.4 GHz`: STA 스캔을 일반적인 2.4 GHz 채널로 제한합니다.
- `Prefer 5 GHz`: STA 스캔을 일반적인 5 GHz 채널로 제한합니다.

AP+STA 모드에서는 AP가 STA 채널을 따라가야 하므로 이 설정이 중요합니다. OnStep처럼 AP 클라이언트가 2.4 GHz만 지원한다면 STA 밴드를 `Prefer 2.4 GHz`로 설정하고 PiFinder를 2.4 GHz를 제공하는 STA 네트워크에 연결하세요.

선택한 밴드가 저장된 STA SSID에서 실제로 제공되어야 합니다. 선택한 밴드가 없으면 `Auto`로 되돌리거나 사용 가능한 밴드로 바꾸기 전까지 STA 연결이 실패할 수 있습니다.

## 관련 파일

```text
switch-apsta.sh
scripts/pifinder_apsta.sh
scripts/import_initial_wifi_networks.py
/etc/pifinder_apsta_nat.conf
pi_config_files/dhcpcd.conf.apsta
pi_config_files/pifinder_apsta_prepare.service
pi_config_files/pifinder_apsta_monitor.service
```

## Pi 4 / Pi 5 호환성

Pi 4와 Pi 5 모두 기본 Wi-Fi 인터페이스는 `wlan0`으로 사용합니다. AP+STA 모드는 `wlan0` 위에 `uap0` 가상 AP 인터페이스를 추가하므로 GPS UART 보드 프로파일과는 독립적으로 동작합니다.

Pi 5에서도 동일한 `wlan0`/`uap0` 구성을 사용합니다. 단, STA가 5 GHz 채널에 연결되면 AP도 같은 5 GHz 채널로 재시작될 수 있으므로 접속하는 스마트폰/태블릿이 해당 채널을 지원해야 합니다.
