# GPSD 안정 버전 설치

2026-09-20에 확인한 공식 최신 안정 릴리스는 **3.27.5**다.
[공식 릴리스 태그](https://gitlab.com/gpsd/gpsd/-/tags)와
[공식 배포 파일](https://download-mirror.savannah.gnu.org/releases/gpsd/)을 사용한다.
개발 브랜치나 PyPI의 Python 클라이언트 버전을 설치 기준으로 사용하지 않는다.

`pifinder_setup.sh`는 GPS 설정을 생성한 다음 안정 버전 설치기를 실행한다.
기존 장비의 GPSD만 업데이트하려면 일반 사용자로 실행한다.

```bash
cd ~/PiFinder
bash scripts/install_gpsd_stable.sh
```

설치기는 SHA-256으로 소스를 검증하고 빌드 및 `scons check`를 수행한다.
실패하면 서비스 전환 전에 중단한다. `/var/tmp`에서 빌드하므로 디스크
공간과 인터넷 연결이 필요하다. 설치 과정에서 GPSD가 잠시 재시작된다.
`/etc/default/gpsd`의 장치·통신 속도 설정은 보존한다.

실행 파일은 `/opt/pifinder/gpsd-3.27.5`에 설치하고 systemd의
`/etc/systemd/system/gpsd.service.d/50-pifinder-stable.conf`로 선택한다.
Debian 패키지의 서비스·소켓·클라이언트 라이브러리는 유지한다.
따라서 `/usr/sbin/gpsd -V`는 배포판 버전을 표시하며, 실제 서비스 버전은
다음과 같이 확인한다.

```bash
/opt/pifinder/gpsd-3.27.5/sbin/gpsd -V
systemctl status gpsd --no-pager
/opt/pifinder/gpsd-3.27.5/bin/gpspipe -w -n 5
```

서비스 시작 실패 시 기존 drop-in을 복원한다. 수동으로 Debian GPSD로
되돌릴 때는 아래 명령을 실행한다.

```bash
sudo rm /etc/systemd/system/gpsd.service.d/50-pifinder-stable.conf
sudo systemctl daemon-reload
sudo systemctl restart gpsd
```

후속 안정 버전 적용 시 설치기의 `version`과 `sha256`을 함께 갱신하고
자체 회귀 테스트 및 실제 GPS 수신을 확인한다.

## 2026-09-20 장비 적용 검증

- Debian 12 arm64에서 빌드 및 `scons check` 통과. 데이터 재생 회귀 테스트
  194건 성공. 설치하지 않는 그래픽 도구의 선택 의존성 경고만 남았다.
- GPSD 서비스가 3.27.5를 실행하고 JSON `VERSION`도 3.27.5를 반환했다.
- `/dev/ttyAMA2`, 115200 설정 보존, u-blox 수신기 인식 확인.
- PiFinder와 동일한 `gpsdclient`에서 `convert_datetime=True`로 TPV/SKY
  파싱 성공. PiFinder 서비스 active, gpsd.socket enabled 확인.
- 검증 시점에는 TPV mode 1, 사용 위성 0개로 위치 고정이 없었다.
  실제 위치·시각 정확도는 위성 고정 후 별도로 확인해야 한다.
- 설치 스크립트 `bash -n` 및 `git diff --check` 통과.
