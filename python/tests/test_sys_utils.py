from __future__ import annotations
import threading
from types import SimpleNamespace

import pytest

try:
    from PiFinder import board_config
    from PiFinder import sys_utils

    # These two cover coordinate and time formatting, not device-name
    # resolution, so they pass device_name explicitly. Left to default it,
    # resolve_indi_device_name() reads the machine's real INDI profile
    # (~/.indi/profiles.db) and names the telescope driver found there --
    # "Telescope Simulator" on a stock install -- and only falls back to
    # DEFAULT_ONSTEP_DEVICE_NAME when no profile exists. That made the
    # assertions pass on a bare dev box and fail on any configured device.
    @pytest.mark.unit
    def test_build_indi_location_time_properties_uses_input_time_and_offset():
        device = sys_utils.DEFAULT_ONSTEP_DEVICE_NAME
        properties = sys_utils.build_indi_location_time_properties(
            latitude=37.52704,
            longitude=127.10936,
            elevation=30,
            utc_datetime="2026-06-30T13:45:12",
            utc_offset_hours=9,
            device_name=device,
        )

        assert f"{device}.GEOGRAPHIC_COORD.LAT=37.52704" in properties
        assert f"{device}.GEOGRAPHIC_COORD.LONG=127.10936" in properties
        assert f"{device}.GEOGRAPHIC_COORD.ELEV=30.0" in properties
        assert f"{device}.TIME_UTC.UTC=2026-06-30T13:45:12" in properties
        assert f"{device}.TIME_UTC.OFFSET=9.00" in properties

    @pytest.mark.unit
    def test_build_indi_location_time_properties_converts_west_longitude():
        device = sys_utils.DEFAULT_ONSTEP_DEVICE_NAME
        properties = sys_utils.build_indi_location_time_properties(
            latitude=34,
            longitude=-118.25,
            utc_datetime="2026-06-30T13:45:12Z",
            utc_offset_hours=-7,
            device_name=device,
        )

        assert f"{device}.GEOGRAPHIC_COORD.LONG=241.75" in properties
        assert f"{device}.TIME_UTC.OFFSET=-7.00" in properties

    @pytest.mark.unit
    def test_apply_indi_usb_connection_sets_selected_baud(monkeypatch):
        calls = []

        def fake_run(args, timeout=5.0):
            calls.append(list(args))
            stdout = ""
            if "indi_getprop" in args:
                if any("CONNECTION_MODE" in item for item in args):
                    stdout = (
                        "LX200 OnStepX.CONNECTION_MODE.CONNECTION_SERIAL=On\n"
                        "LX200 OnStepX.CONNECTION_MODE.CONNECTION_TCP=Off\n"
                        "LX200 OnStepX.DEVICE_PORT.PORT=/dev/ttyUSB0\n"
                        "LX200 OnStepX.DEVICE_BAUD_RATE.460800=On\n"
                    )
                else:
                    stdout = "LX200 OnStepX.CONNECTION.CONNECT=On\n"
            return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

        monkeypatch.setattr(sys_utils, "_run_indi_command", fake_run)
        monkeypatch.setattr(sys_utils.time, "sleep", lambda _seconds: None)

        result = sys_utils.apply_indi_onstep_connection(
            connection_type="usb",
            serial_port="/dev/ttyUSB0",
            serial_baud=460800,
            device_name="LX200 OnStepX",
        )

        assert result["ok"] is True
        flattened = [arg for call in calls for arg in call]
        assert "LX200 OnStepX.DEVICE_PORT.PORT=/dev/ttyUSB0" in flattened
        assert "LX200 OnStepX.DEVICE_BAUD_RATE.460800=On" in flattened

    @pytest.mark.unit
    def test_list_onstep_serial_ports_deduplicates_aliases_by_realpath(monkeypatch):
        paths_by_pattern = {
            "/dev/serial/by-id/*": ["/dev/serial/by-id/onstep"],
            "/dev/serial/by-path/*": ["/dev/serial/by-path/onstep"],
            "/dev/ttyUSB*": ["/dev/ttyUSB0"],
            "/dev/ttyACM*": [],
        }
        monkeypatch.setattr(
            sys_utils.glob,
            "glob",
            lambda pattern: list(paths_by_pattern[pattern]),
        )
        monkeypatch.setattr(
            sys_utils.os.path,
            "realpath",
            lambda path: (
                "/dev/ttyUSB0"
                if path
                in {
                    "/dev/serial/by-id/onstep",
                    "/dev/serial/by-path/onstep",
                    "/dev/ttyUSB0",
                }
                else path
            ),
        )

        assert sys_utils.list_onstep_serial_ports() == [
            {
                "path": "/dev/serial/by-id/onstep",
                "label": "/dev/serial/by-id/onstep (/dev/ttyUSB0)",
                "resolved": "/dev/ttyUSB0",
            }
        ]

    @pytest.mark.unit
    def test_list_onstep_serial_ports_keeps_distinct_targets_and_tty_fallback(
        monkeypatch,
    ):
        paths_by_pattern = {
            "/dev/serial/by-id/*": ["/dev/serial/by-id/onstep"],
            "/dev/serial/by-path/*": [],
            "/dev/ttyUSB*": ["/dev/ttyUSB0", "/dev/ttyUSB1"],
            "/dev/ttyACM*": ["/dev/ttyACM0"],
        }
        resolved_paths = {
            "/dev/serial/by-id/onstep": "/dev/ttyUSB0",
            "/dev/ttyUSB0": "/dev/ttyUSB0",
            "/dev/ttyUSB1": "/dev/ttyUSB1",
            "/dev/ttyACM0": "/dev/ttyACM0",
        }
        monkeypatch.setattr(
            sys_utils.glob,
            "glob",
            lambda pattern: list(paths_by_pattern[pattern]),
        )
        monkeypatch.setattr(
            sys_utils.os.path,
            "realpath",
            lambda path: resolved_paths.get(path, path),
        )

        assert [item["path"] for item in sys_utils.list_onstep_serial_ports()] == [
            "/dev/serial/by-id/onstep",
            "/dev/ttyACM0",
            "/dev/ttyUSB1",
        ]

    @pytest.mark.unit
    def test_list_onstep_serial_ports_excludes_gps_alias_by_realpath(monkeypatch):
        paths_by_pattern = {
            "/dev/serial/by-id/*": [
                "/dev/serial/by-id/gps",
                "/dev/serial/by-id/onstep",
            ],
            "/dev/serial/by-path/*": [],
            "/dev/ttyUSB*": ["/dev/ttyUSB0", "/dev/ttyUSB1"],
            "/dev/ttyACM*": [],
        }
        resolved = {
            "/dev/serial/by-id/gps": "/dev/ttyUSB0",
            "/dev/serial/by-id/onstep": "/dev/ttyUSB1",
        }
        monkeypatch.setattr(
            sys_utils.glob, "glob", lambda pattern: list(paths_by_pattern[pattern])
        )
        monkeypatch.setattr(
            sys_utils.os.path, "realpath", lambda path: resolved.get(path, path)
        )

        ports = sys_utils.list_onstep_serial_ports(
            excluded_paths=["/dev/serial/by-id/gps"]
        )

        assert [port["path"] for port in ports] == ["/dev/serial/by-id/onstep"]

    @pytest.mark.unit
    def test_probe_onstep_serial_port_requires_product_and_version():
        class FakeSerial:
            def __init__(self, *_args, **_kwargs):
                self.replies = iter((b"On-Step#", b"10.24c#"))
                self.writes = []

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def reset_input_buffer(self):
                return None

            def reset_output_buffer(self):
                return None

            def write(self, payload):
                self.writes.append(payload)

            def flush(self):
                return None

            def read_until(self, _terminator, _size):
                return next(self.replies)

        result = sys_utils.probe_onstep_serial_port(
            "/dev/ttyUSB0",
            115200,
            settle_seconds=0,
            serial_factory=FakeSerial,
        )

        assert result["status"] == "verified"
        assert result["product"] == "On-Step"
        assert result["version"] == "10.24c"

    @pytest.mark.unit
    def test_serial_without_modem_control_suppresses_lines_and_hangup(monkeypatch):
        import termios

        calls = []
        applied = []

        class FakeSerial:
            def __init__(self):
                self.fd = 23

            def _reconfigure_port(self, *_args, **_kwargs):
                calls.append("configured")

            def _update_dtr_state(self):
                calls.append("dtr")

            def _update_rts_state(self):
                calls.append("rts")

        initial_iflag = termios.IXON | termios.IXOFF | getattr(termios, "IXANY", 0)
        initial_cflag = termios.HUPCL | getattr(termios, "CRTSCTS", 0)
        monkeypatch.setattr(
            termios,
            "tcgetattr",
            lambda _fd: [initial_iflag, 0, initial_cflag, 0, 0, 0, []],
        )
        monkeypatch.setattr(
            termios,
            "tcsetattr",
            lambda fd, when, settings: applied.append((fd, when, settings)),
        )

        safe_serial = sys_utils._serial_class_without_modem_control(FakeSerial)()
        safe_serial._update_dtr_state()
        safe_serial._update_rts_state()
        safe_serial._reconfigure_port()

        assert calls == ["configured"]
        assert len(applied) == 1
        settings = applied[0][2]
        assert settings[0] & (termios.IXON | termios.IXOFF) == 0
        assert settings[2] & termios.HUPCL == 0
        assert settings[2] & getattr(termios, "CRTSCTS", 0) == 0
        assert settings[2] & termios.CLOCAL

    @pytest.mark.unit
    def test_probe_onstep_serial_port_product_only_is_not_verified():
        class FakeSerial:
            def __init__(self, *_args, **_kwargs):
                self.replies = iter((b"On-Step#", b"not-a-version#"))

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def write(self, _payload):
                return None

            def flush(self):
                return None

            def read_until(self, _terminator, _size):
                return next(self.replies)

        result = sys_utils.probe_onstep_serial_port(
            "/dev/ttyUSB0",
            9600,
            settle_seconds=0,
            serial_factory=FakeSerial,
        )

        assert result["status"] == "probable"
        assert result["error"] == "invalid_version"

    @pytest.mark.unit
    def test_discover_onstep_serial_uses_baud_pass_and_unique_verified_device():
        calls = []
        ports = [
            {"path": "/dev/onstep", "resolved": "/dev/ttyUSB0"},
            {"path": "/dev/other", "resolved": "/dev/ttyUSB1"},
        ]

        def fake_probe(path, baud):
            calls.append((path, baud))
            if path == "/dev/onstep" and baud == 115200:
                return {
                    "status": "verified",
                    "path": path,
                    "baud": baud,
                    "product": "On-Step",
                    "version": "10.24c",
                }
            return {"status": "rejected", "path": path, "baud": baud}

        result = sys_utils.discover_onstep_serial(
            preferred_bauds=[115200], ports=ports, probe=fake_probe
        )

        assert result["ok"] is True
        assert result["selected"]["stable_path"] == "/dev/onstep"
        assert result["selected"]["baud"] == 115200
        assert calls[:2] == [
            ("/dev/onstep", 115200),
            ("/dev/other", 115200),
        ]
        assert calls.count(("/dev/onstep", 115200)) == 1
        assert not any(path == "/dev/onstep" and baud != 115200 for path, baud in calls)

    @pytest.mark.unit
    def test_discover_onstep_serial_does_not_choose_multiple_verified_devices():
        ports = [
            {"path": "/dev/one", "resolved": "/dev/ttyUSB0"},
            {"path": "/dev/two", "resolved": "/dev/ttyUSB1"},
        ]

        result = sys_utils.discover_onstep_serial(
            preferred_bauds=[9600],
            ports=ports,
            probe=lambda path, baud: {
                "status": "verified",
                "path": path,
                "baud": baud,
                "product": "On-Step",
                "version": "10.24c",
            },
        )

        assert result["ok"] is False
        assert result["state"] == "ambiguous"
        assert result["verified_count"] == 2

    @pytest.mark.unit
    def test_apply_connection_does_not_save_mismatched_readback(monkeypatch):
        calls = []

        def fake_run(args, timeout=5.0):
            calls.append(list(args))
            stdout = ""
            if "indi_getprop" in args:
                if any("CONNECTION_MODE" in item for item in args):
                    stdout = (
                        "LX200 OnStepX.CONNECTION_MODE.CONNECTION_SERIAL=On\n"
                        "LX200 OnStepX.CONNECTION_MODE.CONNECTION_TCP=Off\n"
                        "LX200 OnStepX.DEVICE_PORT.PORT=/dev/ttyUSB0\n"
                        "LX200 OnStepX.DEVICE_BAUD_RATE.9600=On\n"
                    )
                else:
                    stdout = "LX200 OnStepX.CONNECTION.CONNECT=On\n"
            return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

        monkeypatch.setattr(sys_utils, "_run_indi_command", fake_run)
        monkeypatch.setattr(sys_utils.time, "sleep", lambda _seconds: None)

        result = sys_utils.apply_indi_onstep_connection(
            connection_type="usb",
            serial_port="/dev/ttyUSB0",
            serial_baud=115200,
            device_name="LX200 OnStepX",
        )

        assert result["ok"] is False
        assert "readback does not match" in result["stderr"]
        assert not any(
            "CONFIG_PROCESS.CONFIG_SAVE" in item for call in calls for item in call
        )

    @pytest.mark.unit
    def test_normalize_ignores_invalid_inactive_transport_values():
        usb = sys_utils.normalize_onstep_connection_config(
            {
                "connection_type": "usb",
                "serial_port": "/dev/ttyUSB0",
                "serial_baud": 115200,
                "network_port": "not-used",
            }
        )
        network = sys_utils.normalize_onstep_connection_config(
            {
                "connection_type": "network",
                "network_host": "10.0.0.2",
                "network_port": 9999,
                "serial_baud": "not-used",
            }
        )

        assert usb["network_port"] == 9999
        assert network["serial_baud"] == 9600

    @pytest.mark.unit
    def test_apply_indi_usb_connection_rejects_unsupported_baud():
        with pytest.raises(ValueError, match="Unsupported USB serial baud rate"):
            sys_utils.apply_indi_onstep_connection(
                connection_type="usb",
                serial_port="/dev/ttyUSB0",
                serial_baud=12345,
                device_name="LX200 OnStepX",
            )

    @pytest.mark.unit
    def test_parse_live_indi_usb_connection():
        device = "LX200 OnStepX"
        properties = {
            f"{device}.CONNECTION_MODE.CONNECTION_SERIAL": "On",
            f"{device}.CONNECTION_MODE.CONNECTION_TCP": "Off",
            f"{device}.DEVICE_PORT.PORT": "/dev/serial/by-id/onstep",
            f"{device}.DEVICE_BAUD_RATE.9600": "Off",
            f"{device}.DEVICE_BAUD_RATE.115200": "On",
        }

        connection = sys_utils.parse_indi_onstep_connection_properties(
            properties, device_name=device
        )

        assert connection == {
            "connection_type": "usb",
            "serial_port": "/dev/serial/by-id/onstep",
            "serial_baud": 115200,
            "network_host": "",
            "network_port": 9999,
            "source": "indi_live",
            "verified": True,
        }

    @pytest.mark.unit
    def test_parse_live_indi_network_connection():
        device = "LX200 OnStepX"
        properties = {
            f"{device}.CONNECTION_MODE.CONNECTION_SERIAL": "Off",
            f"{device}.CONNECTION_MODE.CONNECTION_TCP": "On",
            f"{device}.DEVICE_ADDRESS.ADDRESS": "10.10.10.12",
            f"{device}.DEVICE_ADDRESS.PORT": "9998",
        }

        connection = sys_utils.parse_indi_onstep_connection_properties(
            properties, device_name=device
        )

        assert connection["connection_type"] == "network"
        assert connection["network_host"] == "10.10.10.12"
        assert connection["network_port"] == 9998

    @pytest.mark.unit
    def test_read_saved_indi_usb_connection(tmp_path):
        xml_path = tmp_path / "onstep.xml"
        xml_path.write_text(
            """<INDIDriver>
            <newSwitchVector name="CONNECTION_MODE">
              <oneSwitch name="CONNECTION_SERIAL">On</oneSwitch>
              <oneSwitch name="CONNECTION_TCP">Off</oneSwitch>
            </newSwitchVector>
            <newTextVector name="DEVICE_PORT">
              <oneText name="PORT">/dev/serial/by-id/onstep</oneText>
            </newTextVector>
            <newSwitchVector name="DEVICE_BAUD_RATE">
              <oneSwitch name="115200">On</oneSwitch>
            </newSwitchVector>
            </INDIDriver>""",
            encoding="utf-8",
        )

        connection = sys_utils.read_saved_indi_onstep_connection_config(
            device_name="LX200 OnStepX", config_path=xml_path
        )

        assert connection["connection_type"] == "usb"
        assert connection["serial_port"] == "/dev/serial/by-id/onstep"
        assert connection["serial_baud"] == 115200
        assert connection["source"] == "indi_xml"

    @pytest.mark.unit
    def test_connection_match_compares_only_active_transport():
        left = {
            "connection_type": "usb",
            "serial_port": "/dev/ttyUSB0",
            "serial_baud": 460800,
            "network_host": "old-host",
            "network_port": 1,
        }
        right = {
            "connection_type": "usb",
            "serial_port": "/dev/ttyUSB0",
            "serial_baud": 460800,
            "network_host": "different-host",
            "network_port": 65535,
        }

        assert sys_utils.onstep_connection_configs_match(left, right)

    @pytest.mark.unit
    def test_apply_connection_fails_when_indi_config_save_fails(monkeypatch):
        def fake_run(args, timeout=5.0):
            is_get = "indi_getprop" in args
            is_save = any("CONFIG_PROCESS.CONFIG_SAVE" in item for item in args)
            if is_get and any("CONNECTION_MODE" in item for item in args):
                stdout = (
                    "LX200 OnStepX.CONNECTION_MODE.CONNECTION_SERIAL=On\n"
                    "LX200 OnStepX.CONNECTION_MODE.CONNECTION_TCP=Off\n"
                    "LX200 OnStepX.DEVICE_PORT.PORT=/dev/ttyUSB0\n"
                    "LX200 OnStepX.DEVICE_BAUD_RATE.115200=On\n"
                )
            elif is_get:
                stdout = "LX200 OnStepX.CONNECTION.CONNECT=On\n"
            else:
                stdout = ""
            return SimpleNamespace(
                returncode=1 if is_save else 0,
                stdout=stdout,
                stderr="save failed" if is_save else "",
            )

        monkeypatch.setattr(sys_utils, "_run_indi_command", fake_run)
        monkeypatch.setattr(sys_utils.time, "sleep", lambda _seconds: None)

        result = sys_utils.apply_indi_onstep_connection(
            connection_type="usb",
            serial_port="/dev/ttyUSB0",
            serial_baud=115200,
            device_name="LX200 OnStepX",
        )

        assert result["ok"] is False
        assert result["stderr"] == "save failed"

    @pytest.mark.unit
    def test_apply_connection_can_defer_config_save_until_telemetry(monkeypatch):
        calls = []

        def fake_run(args, timeout=5.0):
            calls.append(list(args))
            if "indi_getprop" in args and any(
                "CONNECTION_MODE" in item for item in args
            ):
                stdout = (
                    "LX200 OnStepX.CONNECTION_MODE.CONNECTION_SERIAL=On\n"
                    "LX200 OnStepX.CONNECTION_MODE.CONNECTION_TCP=Off\n"
                    "LX200 OnStepX.DEVICE_PORT.PORT=/dev/ttyUSB0\n"
                    "LX200 OnStepX.DEVICE_BAUD_RATE.115200=On\n"
                )
            elif "indi_getprop" in args:
                stdout = "LX200 OnStepX.CONNECTION.CONNECT=On\n"
            else:
                stdout = ""
            return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

        monkeypatch.setattr(sys_utils, "_run_indi_command", fake_run)
        monkeypatch.setattr(sys_utils.time, "sleep", lambda _seconds: None)

        result = sys_utils.apply_indi_onstep_connection(
            connection_type="usb",
            serial_port="/dev/ttyUSB0",
            serial_baud=115200,
            device_name="LX200 OnStepX",
            save_config=False,
        )

        assert result["ok"] is True
        assert not any(
            "CONFIG_PROCESS.CONFIG_SAVE" in item for call in calls for item in call
        )

    @pytest.mark.unit
    def test_format_onstep_location_display_matches_onstep_web_sign():
        degree = "\N{DEGREE SIGN}"
        assert (
            sys_utils.format_onstep_location_display(
                37.53333333333333,
                127.11666666666666,
                0,
            )
            == f"+37{degree}32'00\", -127{degree}07'00\" / 0m"
        )

    @pytest.mark.unit
    def test_onstep_location_display_uses_cached_seconds_for_coarse_indi_readback():
        degree = "\N{DEGREE SIGN}"
        onstep_props = {
            "LX200 OnStep.GEOGRAPHIC_COORD.LAT": "37.51666666666665719",
            "LX200 OnStep.GEOGRAPHIC_COORD.LONG": "127.0999999999999432",
            "LX200 OnStep.GEOGRAPHIC_COORD.ELEV": "0",
        }
        cache = {
            "latitude": 37.52704,
            "longitude": 127.10936,
            "elevation": 30,
        }

        assert sys_utils.onstep_location_readback_matches(
            onstep_props["LX200 OnStep.GEOGRAPHIC_COORD.LAT"],
            onstep_props["LX200 OnStep.GEOGRAPHIC_COORD.LONG"],
            cache["latitude"],
            cache["longitude"],
        )
        assert (
            sys_utils.format_onstep_location_display_with_cache(onstep_props, cache)
            == f"+37{degree}31'37\", -127{degree}06'34\" / 30m"
        )

    @pytest.mark.unit
    def test_parse_onstep_home_park_state_splits_at_home_from_parked():
        state = sys_utils.parse_onstep_home_park_state(
            status_text="At Home and UnParked",
            park_switch="Off",
            unpark_switch="On",
            raw_status="nNpHAo160",
        )

        assert state["home_state"] == "At Home"
        assert state["park_state"] == "Unparked"
        assert state["driver_status"] == "At Home and UnParked"
        assert state["raw_status"] == "nNpHAo160"

    @pytest.mark.unit
    def test_parse_onstep_home_park_state_uses_switch_fallback():
        state = sys_utils.parse_onstep_home_park_state(
            status_text="",
            park_switch="On",
            unpark_switch="Off",
        )

        assert state["home_state"] == "Unknown"
        assert state["park_state"] == "Parked"

    @pytest.mark.unit
    def test_onstep_location_display_uses_cached_elevation_for_exclusive_sync():
        degree = "\N{DEGREE SIGN}"
        onstep_props = {
            "LX200 OnStep.GEOGRAPHIC_COORD.LAT": "37.31666666666669983",
            "LX200 OnStep.GEOGRAPHIC_COORD.LONG": "126.8166666666666288",
            "LX200 OnStep.GEOGRAPHIC_COORD.ELEV": "0",
        }
        cache = {
            "latitude": 37.32361,
            "longitude": 126.82194,
            "elevation": 15,
        }

        assert (
            sys_utils.format_onstep_location_display_with_cache(onstep_props, cache)
            == f"+37{degree}19'25\", -126{degree}49'19\" / 15m"
        )

    @pytest.mark.unit
    def test_effective_onstep_location_prefers_cached_synced_coordinates():
        onstep_props = {
            "LX200 OnStep.GEOGRAPHIC_COORD.LAT": "37.31666666666669983",
            "LX200 OnStep.GEOGRAPHIC_COORD.LONG": "126.8166666666666288",
            "LX200 OnStep.GEOGRAPHIC_COORD.ELEV": "0",
        }
        cache = {
            "latitude": 37.32361,
            "longitude": 126.82194,
            "elevation": 15,
        }

        effective = sys_utils.effective_onstep_location(onstep_props, cache)

        assert effective["latitude"] == pytest.approx(37.32361)
        assert effective["longitude"] == pytest.approx(126.82194)
        assert effective["elevation"] == pytest.approx(15)
        assert effective["source"] == "MFNavis synced location"
        assert effective["driver_readback_matched"] is True
        assert (
            sys_utils.format_effective_onstep_location(onstep_props, cache)
            == "37.32361, 126.82194 / 15m"
        )

    @pytest.mark.unit
    def test_effective_onstep_location_falls_back_to_driver_readback():
        onstep_props = {
            "LX200 OnStep.GEOGRAPHIC_COORD.LAT": "34.25",
            "LX200 OnStep.GEOGRAPHIC_COORD.LONG": "241.75",
            "LX200 OnStep.GEOGRAPHIC_COORD.ELEV": "100",
        }

        effective = sys_utils.effective_onstep_location(onstep_props, {})

        assert effective["latitude"] == pytest.approx(34.25)
        assert effective["longitude"] == pytest.approx(-118.25)
        assert effective["elevation"] == pytest.approx(100)
        assert effective["source"] == "INDI driver readback"

    @pytest.mark.unit
    def test_build_onstep_lx200_location_time_commands_use_onstep_longitude_sign():
        commands = sys_utils.build_onstep_lx200_location_time_commands(
            latitude=37.32361,
            longitude=126.82194,
            elevation=15,
            utc_datetime="2026-06-30T14:15:06+00:00",
            utc_offset_hours=9,
        )

        assert commands[0] == ":St+37*19:25#"
        assert commands[1] == ":Sg-126*49:19#"
        assert commands[2] == ":Sv15#"
        assert commands[3] == ":SG-09:00#"
        assert commands[4] == ":SL23:15:06#"
        assert commands[5] == ":SC06/30/26#"

    @pytest.mark.unit
    def test_build_onstep_lx200_location_time_commands_use_western_offset_sign():
        commands = sys_utils.build_onstep_lx200_location_time_commands(
            latitude=34,
            longitude=-118.25,
            utc_datetime="2026-06-30T13:45:12Z",
            utc_offset_hours=-7,
        )

        assert commands[1] == ":Sg+118*15:00#"
        assert commands[2] == ":SG+07:00#"
        assert commands[3] == ":SL06:45:12#"

    @pytest.mark.unit
    def test_wpa_supplicant_parsing():
        # This could be read from a file or passed from another function
        wpa_supplicant_example = """
        ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
        update_config=1
        country=US

        network={
            ssid="My Home Network"
            psk="password123"
            key_mgmt=WPA-PSK
        }

        network={
            ssid="Work Network"
            psk="compl3x=p@ssw0rd!"
            key_mgmt=WPA-PSK
        }
        """
        wpa_list = [
            line.strip()
            for line in wpa_supplicant_example.strip().split("\n")
            if line.strip()
        ]
        result = sys_utils.Network._parse_wpa_supplicant(wpa_list)
        assert result[1]["psk"] == "compl3x=p@ssw0rd!"

        example2 = """
        ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
        update_config=1

















        network={
                ssid="testytest"
                psk="oesrucoeahu1234"
                key_mgmt=WPA-PSK
        }

        network={
                ssid="00xx33"
                psk="1234@===!!!"
                key_mgmt=WPA-PSK
        }
        """
        wpa_list = [line for line in example2.split("\n") if line.strip()]
        result = sys_utils.Network._parse_wpa_supplicant(wpa_list)
        assert result[1]["psk"] == "1234@===!!!"

    @pytest.mark.unit
    def test_parse_wpa_supplicant_reads_priority():
        wpa_list = [
            "network={",
            'ssid="low"',
            "key_mgmt=NONE",
            "}",
            "network={",
            'ssid="high"',
            "key_mgmt=NONE",
            "priority=5",
            "}",
        ]
        result = sys_utils.Network._parse_wpa_supplicant(wpa_list)
        assert result[0]["priority"] is None
        assert result[1]["priority"] == "5"

    @pytest.mark.unit
    def test_move_wifi_network_reorders_and_marks_dirty(monkeypatch, tmp_path):
        wpa_path = tmp_path / "wpa_supplicant.conf"
        wpa_path.write_text(
            "update_config=1\n"
            'network={\n\tssid="first"\n\tkey_mgmt=NONE\n}\n'
            'network={\n\tssid="second"\n\tkey_mgmt=NONE\n}\n'
        )
        monkeypatch.setattr(sys_utils, "WPA_SUPPLICANT_PATH", str(wpa_path))
        monkeypatch.setattr(sys_utils, "BOOT_WPA_SUPPLICANT_PATHS", [])
        monkeypatch.setattr(
            sys_utils, "NETWORKMANAGER_CONNECTION_GLOB", str(tmp_path / "none/*")
        )
        network = sys_utils.Network.__new__(sys_utils.Network)
        network.sta_dirty = False
        network.populate_wifi_networks()
        assert [n["ssid"] for n in network.get_wifi_networks()] == [
            "first",
            "second",
        ]

        network.move_wifi_network(1, "up")  # "second" to the top
        assert network.sta_dirty is True
        assert [n["ssid"] for n in network.get_wifi_networks()] == [
            "second",
            "first",
        ]
        # priorities persisted: top of the list wins after a re-parse
        contents = wpa_path.read_text()
        assert "priority=2" in contents and "priority=1" in contents
        # non-network preamble survives the rewrite
        assert "update_config=1" in contents

    @pytest.mark.unit
    def test_add_and_delete_are_saved_only(monkeypatch, tmp_path):
        wpa_path = tmp_path / "wpa_supplicant.conf"
        wpa_path.write_text('network={\n\tssid="keep"\n\tkey_mgmt=NONE\n}\n')
        monkeypatch.setattr(sys_utils, "WPA_SUPPLICANT_PATH", str(wpa_path))
        monkeypatch.setattr(sys_utils, "BOOT_WPA_SUPPLICANT_PATHS", [])
        monkeypatch.setattr(
            sys_utils, "NETWORKMANAGER_CONNECTION_GLOB", str(tmp_path / "none/*")
        )

        def forbidden(*_a, **_k):
            raise AssertionError("edits must not touch nmcli/wpa_cli")

        monkeypatch.setattr(sys_utils.Network, "_nmcli", staticmethod(forbidden))
        monkeypatch.setattr(sys_utils, "wpa_cli", forbidden)

        network = sys_utils.Network.__new__(sys_utils.Network)
        network._wifi_mode = sys_utils.WIFI_MODE_CLIENT
        network.sta_dirty = False
        network.populate_wifi_networks()

        network.add_wifi_network("added", "NONE")
        assert network.sta_dirty is True
        network.delete_wifi_network(0)
        ssids = [n["ssid"] for n in network.get_wifi_networks()]
        assert "added" in ssids and "keep" not in ssids

    @pytest.mark.unit
    def test_populate_wifi_networks_missing_wpa_file(monkeypatch):
        real_open = open

        def fake_open(path, *args, **kwargs):
            if path == "/etc/wpa_supplicant/wpa_supplicant.conf":
                raise FileNotFoundError(path)
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr("builtins.open", fake_open)
        network = sys_utils.Network.__new__(sys_utils.Network)
        network.populate_wifi_networks()

        assert network.get_wifi_networks() == []

    @pytest.mark.unit
    def test_networkmanager_connection_parsing_hex_ssid():
        nmconnection = """
        [connection]
        id=Home WiFi
        type=wifi

        [wifi]
        mode=infrastructure
        ssid=486f6d652057694669

        [wifi-security]
        key-mgmt=wpa-psk
        psk=secretpass
        """

        result = sys_utils.Network._parse_networkmanager_connection(nmconnection)

        assert result["ssid"] == "Home WiFi"
        assert result["psk"] == "secretpass"
        assert result["key_mgmt"] == "WPA-PSK"

    @pytest.mark.unit
    def test_dedupe_wifi_networks_reassigns_ids():
        networks = sys_utils.Network._dedupe_wifi_networks(
            [
                {"id": 99, "ssid": "Home", "psk": "secretpass", "key_mgmt": "WPA-PSK"},
                {"id": 1, "ssid": "Home", "psk": "otherpass", "key_mgmt": "WPA-PSK"},
                {"id": 2, "ssid": "Open", "key_mgmt": "NONE"},
            ]
        )

        assert networks == [
            {"id": 0, "ssid": "Home", "psk": "secretpass", "key_mgmt": "WPA-PSK"},
            {"id": 1, "ssid": "Open", "psk": None, "key_mgmt": "NONE"},
        ]

    @pytest.mark.unit
    def test_connect_wifi_network_refuses_out_of_range_ssid(monkeypatch):
        network = sys_utils.Network.__new__(sys_utils.Network)
        network._wifi_networks = [
            {"id": 0, "ssid": "lab", "key_mgmt": "WPA-PSK"},
            {"id": 1, "ssid": "home", "key_mgmt": "WPA-PSK"},
        ]
        monkeypatch.setattr(
            sys_utils.Network, "_networkmanager_active", staticmethod(lambda: True)
        )
        monkeypatch.setattr(
            sys_utils.Network,
            "_networkmanager_wifi_profiles",
            staticmethod(lambda: [{"name": "MFNavis lab", "ssid": "lab"}]),
        )
        monkeypatch.setattr(network, "scan_wifi_networks", lambda: ["home", "other"])

        def forbidden(*_a, **_k):
            raise AssertionError("must not touch the link for an unreachable SSID")

        monkeypatch.setattr(sys_utils.Network, "_nmcli", staticmethod(forbidden))

        ok, message = network.connect_wifi_network(0)

        assert ok is False
        assert "not in range" in message

    @pytest.mark.unit
    def test_connect_wifi_network_proceeds_when_ssid_visible(monkeypatch):
        network = sys_utils.Network.__new__(sys_utils.Network)
        network._wifi_networks = [{"id": 0, "ssid": "lab", "key_mgmt": "WPA-PSK"}]
        monkeypatch.setattr(
            sys_utils.Network, "_networkmanager_active", staticmethod(lambda: True)
        )
        monkeypatch.setattr(
            sys_utils.Network,
            "_networkmanager_wifi_profiles",
            staticmethod(lambda: [{"name": "MFNavis lab", "ssid": "lab"}]),
        )
        monkeypatch.setattr(network, "scan_wifi_networks", lambda: ["lab", "home"])
        calls = []

        def fake_nmcli(args):
            calls.append(args)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(sys_utils.Network, "_nmcli", staticmethod(fake_nmcli))

        network._last_connect_result = None
        ok, message = network.connect_wifi_network(0, async_switch=False)

        assert ok is True
        assert calls == [["-w", "25", "con", "up", "MFNavis lab"]]
        result = network.get_last_connect_result()
        assert result is not None and result["ok"] is True
        assert "lab" in message

    @pytest.mark.unit
    def test_connect_wifi_network_proceeds_on_scan_failure(monkeypatch):
        # An empty scan (driver hiccup) must not block a legitimate switch.
        network = sys_utils.Network.__new__(sys_utils.Network)
        network._wifi_networks = [{"id": 0, "ssid": "lab", "key_mgmt": "WPA-PSK"}]
        monkeypatch.setattr(
            sys_utils.Network, "_networkmanager_active", staticmethod(lambda: True)
        )
        monkeypatch.setattr(
            sys_utils.Network,
            "_networkmanager_wifi_profiles",
            staticmethod(lambda: [{"name": "MFNavis lab", "ssid": "lab"}]),
        )
        monkeypatch.setattr(network, "scan_wifi_networks", lambda: [])
        monkeypatch.setattr(
            sys_utils.Network,
            "_nmcli",
            staticmethod(
                lambda args: SimpleNamespace(returncode=0, stdout="", stderr="")
            ),
        )

        network._last_connect_result = None
        ok, _message = network.connect_wifi_network(0, async_switch=False)

        assert ok is True

    @pytest.mark.unit
    def test_connect_wifi_network_async_returns_before_switch(monkeypatch):
        # The HTTP response must leave before the link can drop: async mode
        # returns immediately with a switching notice and runs nmcli in a
        # background thread.
        network = sys_utils.Network.__new__(sys_utils.Network)
        network._wifi_networks = [{"id": 0, "ssid": "lab", "key_mgmt": "WPA-PSK"}]
        network._last_connect_result = None
        monkeypatch.setattr(
            sys_utils.Network, "_networkmanager_active", staticmethod(lambda: True)
        )
        monkeypatch.setattr(
            sys_utils.Network,
            "_networkmanager_wifi_profiles",
            staticmethod(lambda: [{"name": "MFNavis lab", "ssid": "lab"}]),
        )
        monkeypatch.setattr(network, "scan_wifi_networks", lambda: ["lab"])
        monkeypatch.setattr(sys_utils.time, "sleep", lambda _s: None)
        done = threading.Event()

        def fake_nmcli(args):
            done.set()
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(sys_utils.Network, "_nmcli", staticmethod(fake_nmcli))

        ok, message = network.connect_wifi_network(0)

        assert ok is True
        assert "Switching to lab" in message
        assert done.wait(5.0)

    @pytest.mark.unit
    def test_iw_scan_parsing_dedupes_ssids():
        output = """
        BSS 00:11:22:33:44:55(on wlan0)
                SSID: Cafe
        BSS 66:77:88:99:aa:bb(on wlan0)
                SSID: Cafe
        BSS cc:dd:ee:ff:00:11(on wlan0)
                SSID:
        BSS 22:33:44:55:66:77(on wlan0)
                SSID: Observatory
        """

        assert sys_utils.Network._parse_iw_scan(output) == ["Cafe", "Observatory"]

    @pytest.mark.unit
    def test_hostapd_security_rewrite_adds_wpa2_and_removes_pairwise():
        lines = [
            "interface=wlan0\n",
            "ssid=PiFinderAP\n",
            "channel=7\n",
            "wpa_pairwise=TKIP\n",
        ]

        result = sys_utils.Network._rewrite_key_value_lines(
            lines,
            {
                "wpa": "2",
                "wpa_passphrase": "observing",
                "wpa_key_mgmt": "WPA-PSK",
                "rsn_pairwise": "CCMP",
            },
            {"wpa_pairwise"},
        )

        assert "wpa_pairwise=TKIP\n" not in result
        assert "wpa=2\n" in result
        assert "wpa_passphrase=observing\n" in result
        assert "wpa_key_mgmt=WPA-PSK\n" in result
        assert "rsn_pairwise=CCMP\n" in result

    @pytest.mark.unit
    def test_hostapd_security_rewrite_removes_wpa_for_open_ap():
        lines = [
            "interface=wlan0\n",
            "ssid=PiFinderAP\n",
            "wpa=2\n",
            "wpa_passphrase=observing\n",
            "wpa_key_mgmt=WPA-PSK\n",
            "rsn_pairwise=CCMP\n",
        ]

        result = sys_utils.Network._rewrite_key_value_lines(
            lines,
            {},
            {"wpa", "wpa_passphrase", "wpa_key_mgmt", "rsn_pairwise"},
        )

        assert result == ["interface=wlan0\n", "ssid=PiFinderAP\n"]

    @pytest.mark.unit
    def test_ap_dhcp_range_avoids_ap_ip():
        assert sys_utils.Network._ap_dhcp_range("10.10.10.1") == (
            "10.10.10.2",
            "10.10.10.20",
        )
        start, end = sys_utils.Network._ap_dhcp_range("10.10.10.2")
        assert start == "10.10.10.1"
        assert end == "10.10.10.20"

    @pytest.mark.unit
    def test_ap_ip_validation_rejects_public_and_link_local():
        with pytest.raises(ValueError):
            sys_utils.Network._validate_ap_ip("8.8.8.8")
        with pytest.raises(ValueError):
            sys_utils.Network._validate_ap_ip("169.254.1.1")

    @pytest.mark.unit
    def test_dhcpcd_static_ip_rewrite_for_ap_interface():
        contents = "interface wlan0\n    static ip_address=10.10.10.1/24\n"
        result = sys_utils.Network._rewrite_dhcpcd_static_ip(
            contents, "wlan0", "192.168.50.1"
        )

        assert "interface wlan0\n" in result
        assert "static ip_address=192.168.50.1/24" in result
        assert "10.10.10.1" not in result

    @pytest.mark.unit
    def test_dnsmasq_ap_network_rewrite():
        contents = (
            "interface=uap0 # Listening interface\n"
            "dhcp-range=10.10.10.2,10.10.10.20,255.255.255.0,24h\n"
            "address=/gw.wlan/10.10.10.1\n"
        )
        result = sys_utils.Network._rewrite_dnsmasq_ap_network(contents, "192.168.50.1")

        assert "interface=uap0 # Listening interface\n" in result
        assert "dhcp-range=192.168.50.2,192.168.50.20,255.255.255.0,24h\n" in result
        assert "address=/gw.wlan/192.168.50.1\n" in result

    @pytest.mark.unit
    def test_apsta_nat_config_parse_defaults_off():
        assert not sys_utils.Network._parse_apsta_nat_config("")
        assert not sys_utils.Network._parse_apsta_nat_config(
            "PIFINDER_APSTA_SHARE_INTERNET=0\n"
        )
        assert sys_utils.Network._parse_apsta_nat_config(
            "PIFINDER_APSTA_SHARE_INTERNET=1\n"
        )

    @pytest.mark.unit
    def test_sta_band_preference_rewrites_scan_freq():
        contents = (
            "ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev\n"
            "\nnetwork={\n"
            '\tssid="DualBand"\n'
            '\tpsk="secretpass"\n'
            "\tkey_mgmt=WPA-PSK\n"
            "}\n"
        )

        result = sys_utils.Network._rewrite_wpa_supplicant_band_preference(
            contents, "2.4"
        )

        assert "scan_freq=2412 2417" in result
        assert 'ssid="DualBand"' in result

    @pytest.mark.unit
    def test_sta_band_auto_removes_scan_freq():
        contents = (
            "network={\n"
            '\tssid="DualBand"\n'
            "\tscan_freq=2412 2417 2422\n"
            "\tkey_mgmt=NONE\n"
            "}\n"
        )

        result = sys_utils.Network._rewrite_wpa_supplicant_band_preference(
            contents, "auto"
        )

        assert "scan_freq=" not in result
        assert "key_mgmt=NONE" in result

    @pytest.mark.unit
    def test_sta_band_preference_normalization():
        assert sys_utils.Network._normalize_sta_band_preference("2.4GHz") == "2.4"
        assert sys_utils.Network._normalize_sta_band_preference("5g") == "5"
        assert sys_utils.Network._normalize_sta_band_preference("") == "auto"
        with pytest.raises(ValueError):
            sys_utils.Network._normalize_sta_band_preference("6")

    @pytest.mark.unit
    def test_dnsmasq_lease_parsing():
        leases = sys_utils.Network._parse_dnsmasq_leases(
            "1782816834 06:43:af:65:75:9b 10.10.10.15 phone 01:06:43\n"
            "1782815524 da:4f:d2:62:87:74 10.10.10.14 * 01:da:4f\n"
        )

        assert leases["06:43:af:65:75:9b"]["hostname"] == "phone"
        assert leases["da:4f:d2:62:87:74"]["hostname"] == ""
        assert leases["da:4f:d2:62:87:74"]["ip"] == "10.10.10.14"

    @pytest.mark.unit
    def test_iw_station_dump_parsing():
        output = """
        Station da:4f:d2:62:87:74 (on uap0)
            inactive time:  20 ms
            rx bitrate:     72.2 MBit/s
            tx bitrate:     65.0 MBit/s
            authorized:     yes
        """

        stations = sys_utils.Network._parse_iw_station_dump(output)

        assert stations["da:4f:d2:62:87:74"]["connected"]
        assert stations["da:4f:d2:62:87:74"]["rx_bitrate"] == "72.2 MBit/s"
        assert stations["da:4f:d2:62:87:74"]["tx_bitrate"] == "65.0 MBit/s"

    @pytest.mark.unit
    def test_ip_neighbor_parsing_by_mac_and_failed_ip():
        neighbors = sys_utils.Network._parse_ip_neigh(
            "10.10.10.15 lladdr 06:43:af:65:75:9b REACHABLE\n" "10.10.10.14 FAILED\n"
        )

        assert neighbors["06:43:af:65:75:9b"]["neighbor_state"] == "REACHABLE"
        assert neighbors["10.10.10.14"]["neighbor_state"] == "FAILED"

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("model", "profile", "gps_device", "uart_overlay"),
        [
            (
                "Raspberry Pi 5 Model B Rev 1.0",
                "pi5_class",
                "/dev/ttyAMA2",
                "dtoverlay=uart2-pi5",
            ),
            (
                "Raspberry Pi Compute Module 5 Rev 1.0",
                "pi5_class",
                "/dev/ttyAMA2",
                "dtoverlay=uart2-pi5",
            ),
            (
                "Raspberry Pi 4 Model B Rev 1.5",
                "pi4",
                "/dev/ttyAMA3",
                "dtoverlay=uart3",
            ),
            (
                "Raspberry Pi 3 Model B Plus Rev 1.3",
                "legacy",
                "/dev/ttyAMA1",
                "dtoverlay=uart3",
            ),
        ],
    )
    def test_board_profile_by_model(model, profile, gps_device, uart_overlay):
        board_profile = board_config.get_board_profile(model)

        assert board_profile.name == profile
        assert board_profile.gps_device == gps_device
        assert board_profile.uart_overlay == uart_overlay

    @pytest.mark.unit
    def test_resolve_gpsd_device_uses_board_default(monkeypatch):
        monkeypatch.setattr(
            sys_utils, "get_default_gpsd_device", lambda: "/dev/ttyAMA3"
        )

        assert sys_utils.resolve_gpsd_device(None) == "/dev/ttyAMA3"
        assert sys_utils.resolve_gpsd_device("auto") == "/dev/ttyAMA3"
        assert sys_utils.resolve_gpsd_device("/dev/ttyACM0") == "/dev/ttyACM0"

    @pytest.mark.unit
    def test_rewrite_hosts_standard_line():
        contents = (
            "127.0.0.1\tlocalhost\n"
            "::1\t\tlocalhost ip6-localhost ip6-loopback\n"
            "127.0.1.1\tpifinder\n"
        )
        result = sys_utils.Network._rewrite_hosts(contents, "pf-rich")
        assert "127.0.1.1\tpf-rich\n" in result
        assert "pifinder" not in result
        assert "127.0.0.1\tlocalhost\n" in result

    @pytest.mark.unit
    def test_rewrite_hosts_preserves_aliases_and_spacing():
        contents = "  127.0.1.1   pifinder pifinder.local  # primary\n"
        result = sys_utils.Network._rewrite_hosts(contents, "pf-rich")
        assert result == "  127.0.1.1   pf-rich pifinder.local  # primary\n"

    @pytest.mark.unit
    def test_rewrite_hosts_appends_when_missing():
        contents = "127.0.0.1\tlocalhost\n"
        result = sys_utils.Network._rewrite_hosts(contents, "pf-rich")
        assert result.endswith("127.0.1.1\tpf-rich\n")
        assert "127.0.0.1\tlocalhost\n" in result

    @pytest.mark.unit
    def test_rewrite_hosts_appends_with_missing_trailing_newline():
        contents = "127.0.0.1\tlocalhost"
        result = sys_utils.Network._rewrite_hosts(contents, "pf-rich")
        assert result == "127.0.0.1\tlocalhost\n127.0.1.1\tpf-rich\n"

    @pytest.mark.unit
    def test_rewrite_hosts_ignores_commented_line():
        contents = "# 127.0.1.1 oldname\n127.0.0.1\tlocalhost\n"
        result = sys_utils.Network._rewrite_hosts(contents, "pf-rich")
        # commented line is untouched; a real 127.0.1.1 entry is appended
        assert "# 127.0.1.1 oldname\n" in result
        assert result.endswith("127.0.1.1\tpf-rich\n")

    @pytest.mark.unit
    def test_ensure_uhid_loaded_skips_modprobe_when_present(monkeypatch):
        calls = []
        monkeypatch.setattr(sys_utils.os.path, "exists", lambda p: True)
        monkeypatch.setattr(
            sys_utils.subprocess, "run", lambda *a, **k: calls.append(a)
        )
        assert sys_utils.ensure_uhid_loaded() is True
        assert calls == []  # no modprobe needed

    @pytest.mark.unit
    def test_ensure_uhid_loaded_modprobes_when_missing(monkeypatch):
        seen = {"exists": 0}
        run_cmds = []

        def fake_exists(_path):
            # missing on the first check, present after modprobe
            seen["exists"] += 1
            return seen["exists"] > 1

        monkeypatch.setattr(sys_utils.os.path, "exists", fake_exists)
        monkeypatch.setattr(
            sys_utils.subprocess, "run", lambda cmd, **k: run_cmds.append(cmd)
        )
        assert sys_utils.ensure_uhid_loaded() is True
        assert run_cmds == [["sudo", "-n", "modprobe", sys_utils.UHID_MODULE]]

    @pytest.mark.unit
    def test_pause_wifi_for_bt_pairing_silences_radio_and_arms_watchdog(monkeypatch):
        run_cmds = []
        popen_cmds = []
        monkeypatch.setattr(sys_utils, "ensure_uhid_loaded", lambda: True)
        monkeypatch.setattr(sys_utils, "bt_pairing_needs_wifi_pause", lambda: True)
        monkeypatch.setattr(sys_utils, "_capture_wlan_connection", lambda: None)
        monkeypatch.setattr(
            sys_utils.subprocess, "run", lambda cmd, **k: run_cmds.append(cmd)
        )
        monkeypatch.setattr(
            sys_utils.subprocess, "Popen", lambda cmd, **k: popen_cmds.append(cmd)
        )
        assert sys_utils.pause_wifi_for_bt_pairing(safety_timeout=42) is True
        # radio is turned off (both client wifi and the AP interface)
        assert [
            "sudo",
            "-n",
            sys_utils.NMCLI_COMMAND,
            "radio",
            "wifi",
            "off",
        ] in run_cmds
        assert [
            "sudo",
            "-n",
            "ip",
            "link",
            "set",
            sys_utils.BT_PAIRING_AP_INTERFACE,
            "down",
        ] in run_cmds
        # a detached watchdog is armed that restores wifi after the timeout
        assert len(popen_cmds) == 1
        watchdog = popen_cmds[0]
        assert watchdog[:4] == ["sudo", "-n", "setsid", "bash"]
        assert "sleep 42" in watchdog[-1]
        assert "radio wifi on" in watchdog[-1]

    @pytest.mark.unit
    def test_pause_wifi_skipped_when_no_2_4ghz_link(monkeypatch):
        """5GHz-only WiFi does not contend with 2.4GHz-only Bluetooth: the
        pause is skipped, nothing is executed, and callers must not resume."""
        run_cmds = []
        monkeypatch.setattr(sys_utils, "ensure_uhid_loaded", lambda: True)
        monkeypatch.setattr(sys_utils, "bt_pairing_needs_wifi_pause", lambda: False)
        monkeypatch.setattr(
            sys_utils.subprocess, "run", lambda cmd, **k: run_cmds.append(cmd)
        )
        monkeypatch.setattr(
            sys_utils.subprocess, "Popen", lambda cmd, **k: run_cmds.append(cmd)
        )
        assert sys_utils.pause_wifi_for_bt_pairing() is False
        assert run_cmds == []

    def _iw_info_runner(freq_by_interface):
        """Fake `iw dev <iface> info` runner; None value = command fails."""

        def fake_run(cmd, **_kwargs):
            interface = cmd[2]
            freq = freq_by_interface.get(interface)

            class Result:
                returncode = 1 if freq is None else 0
                stdout = (
                    ""
                    if freq is None
                    else f"\tchannel 100 ({freq} MHz), width: 80 MHz\n"
                    if freq
                    else "\ttype managed\n"
                )

            return Result()

        return fake_run

    @pytest.mark.unit
    def test_bt_pairing_pause_needed_only_with_a_2_4ghz_link(monkeypatch):
        cases = [
            # (wlan0 freq, uap0 freq, expected) -- None: iface absent, 0: no link
            (5765, 5765, False),  # STA + AP both 5GHz
            (5765, None, False),  # 5GHz STA only
            (0, 0, False),  # no active link at all
            (2437, None, True),  # 2.4GHz STA
            (5765, 2437, True),  # 5GHz STA but 2.4GHz AP
        ]
        for sta, ap, expected in cases:
            monkeypatch.setattr(
                sys_utils.subprocess,
                "run",
                _iw_info_runner({"wlan0": sta, "uap0": ap}),
            )
            assert sys_utils.bt_pairing_needs_wifi_pause() is expected, (sta, ap)

    @pytest.mark.unit
    def test_bt_pairing_pause_conservative_when_iw_fails(monkeypatch):
        def raise_run(cmd, **_kwargs):
            raise OSError("iw missing")

        monkeypatch.setattr(sys_utils.subprocess, "run", raise_run)
        assert sys_utils.bt_pairing_needs_wifi_pause() is True

    @pytest.mark.unit
    def test_resume_wifi_after_bt_pairing_restores_radio(monkeypatch):
        run_cmds = []
        monkeypatch.setattr(
            sys_utils.subprocess, "run", lambda cmd, **k: run_cmds.append(cmd)
        )
        sys_utils.resume_wifi_after_bt_pairing()
        assert len(run_cmds) == 1
        restore = run_cmds[0]
        assert restore[:4] == ["sudo", "-n", "bash", "-c"]
        assert "radio wifi on" in restore[-1]
        assert f"set {sys_utils.BT_PAIRING_AP_INTERFACE} up" in restore[-1]

    @pytest.mark.unit
    def test_clean_bluetoothctl_output_strips_readline_markers():
        # bluetoothctl wraps colored agent prompts in readline markers
        # (\x01/\x02) that land between "Passkey:" and the digits. If they
        # survive cleaning, passkey detection fails and the code never shows.
        raw = "[agent]\x01\x1b[0m\x02 Passkey: \x01\x02189795\n"
        cleaned = sys_utils._clean_bluetoothctl_output(raw)
        assert "\x01" not in cleaned and "\x02" not in cleaned
        assert "Passkey: 189795" in cleaned


except ImportError:
    pass
