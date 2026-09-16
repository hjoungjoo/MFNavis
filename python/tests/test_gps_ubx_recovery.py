"""GPS recovery, manual version queries and mixed-stream regression tests."""

import asyncio
import json
from queue import Queue

import pytest

from PiFinder.gps_ubx_parser import UBXParser
from PiFinder.gps_ubx_recovery import MAX_TEXT_BYTES, MON_VER_HEX, UBXRecovery

pytestmark = pytest.mark.unit


def nmea(body="GNRMC,183045.20,V,,,,,,,080926,,,N,V"):
    checksum = 0
    for value in body.encode():
        checksum ^= value
    return f"${body}*{checksum:02X}\r\n".encode()


def devices(*paths, driver="NMEA0183", **extra):
    return (
        json.dumps(
            {
                "class": "DEVICES",
                "devices": [{"path": p, "driver": driver, **extra} for p in paths],
            }
        )
        + "\r\n"
    ).encode()


def frame(cls=1, msg_id=0x61, payload=b"\0" * 4):
    return UBXParser(None)._generate_ubx_message(cls, msg_id, payload)


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


class Reader:
    def __init__(self, clock, chunks):
        self.clock = clock
        self.chunks = iter(chunks)

    async def read(self, _size):
        self.clock.now, data = next(self.chunks, (self.clock.now, b""))
        if data is None:
            raise asyncio.TimeoutError
        return data


class Writer:
    def __init__(self):
        self.writes = []
        self.closed = False

    def is_closing(self):
        return self.closed

    def write(self, data):
        self.writes.append(data)

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass


@pytest.fixture(autouse=True)
def no_throttle(monkeypatch):
    async def no_sleep(_delay):
        pass

    monkeypatch.setattr("PiFinder.gps_ubx_parser.asyncio.sleep", no_sleep)


def run_stream(chunks, *, writer=None, replay=False, handshake=False, manual=False):
    clock = Clock()
    writer = writer if writer is not None else Writer()
    parser = UBXParser(
        None,
        reader=Reader(clock, chunks),
        writer=writer,
        file_path="recording.ubx" if replay else None,
        clock=clock,
    )
    parser.command_queue = Queue()
    parser.result_queue = Queue()
    if manual:
        parser.command_queue.put("get_version")

    async def collect():
        if handshake:
            await parser._handle_initial_messages()
        return [m["class"] async for m in parser.parse_messages()]

    return asyncio.run(collect()), writer, parser


def nmea_stream(end=100, path="/dev/ttyAMA2"):
    return [(0, devices(path))] + [(t, nmea()) for t in range(end + 1)]


def version_frame():
    return frame(
        10,
        4,
        b"ROM SPG 5.10".ljust(30, b"\0")
        + b"000A0000\0\0"
        + b"FWVER=SPG 5.10".ljust(30, b"\0")
        + b"PROTVER=34.10".ljust(30, b"\0"),
    )


def polls(writer):
    return [w for w in writer.writes if w.startswith(b"?DEVICE=")]


def test_watchdog_once_per_outage_and_only_nav_rearms():
    recovery = UBXRecovery()
    assert not recovery.needs_probe(59.99)
    assert recovery.needs_probe(60)
    recovery.probed = True
    recovery.observe_ubx(61)
    assert not recovery.needs_probe(3600)
    recovery.observe_navigation(3601)
    assert not recovery.needs_probe(3660)
    assert recovery.needs_probe(3661)


def test_parser_recovers_then_keeps_navigation_messages(caplog):
    chunks = nmea_stream(60)
    chunks += [
        (61, devices("/dev/ttyAMA3")),
        (62, version_frame()),
        (63, frame()),
        (64, frame()),
    ]
    events, writer, parser = run_stream(chunks, handshake=True)
    assert events[-3:] == ["MON-VER", "NAV-EOE", "NAV-EOE"]
    assert "?NMEA" in events
    assert writer.writes[0].startswith(b"?WATCH=")
    assert len(writer.writes) == 3
    assert json.loads(polls(writer)[0][8:-2]) == {
        "path": "/dev/ttyAMA3",
        "hexdata": MON_VER_HEX,
    }
    assert not parser._recovery.probed
    assert "Navigation traffic resumed" in caplog.text


def test_handshake_keeps_coalesced_device_report_and_first_ubx():
    events, writer, parser = run_stream(
        [(0, devices("/dev/ttyAMA2") + frame())], handshake=True
    )
    assert events == ["NAV-EOE"]
    assert parser._recovery.device == "/dev/ttyAMA2"
    assert len(writer.writes) == 1  # WATCH only


@pytest.mark.parametrize("split", range(1, 12))
def test_fragmented_ubx_header_and_payload_are_preserved(split):
    packet = frame()
    events, writer, _ = run_stream([(0, packet[:split]), (1, packet[split:])])
    assert events == ["NAV-EOE"]
    assert not writer.writes


def test_fragmented_json_and_nmea_are_detected():
    report = devices("/dev/ttyAMA2")
    sentence = nmea()
    chunks = [(0, report[:25]), (0, report[25:])]
    for t in range(11):
        chunks.extend([(t, sentence[:12]), (t, sentence[12:])])
    events, writer, _ = run_stream(chunks)
    assert events.count("?NMEA") == 11
    assert not writer.writes


def test_recent_ubx_suppresses_probe_even_after_nmea_in_same_chunk():
    chunks = [(0, devices("/dev/ttyAMA2"))]
    chunks += [(t, nmea() + frame()) for t in range(101)]
    events, writer, _ = run_stream(chunks)
    assert events.count("NAV-EOE") == 101
    assert not writer.writes


def test_nmea_inside_ubx_payload_does_not_trigger_probe():
    chunks = [(0, devices("/dev/ttyAMA2"))]
    chunks += [(t, frame(0x0A, 0xFF, nmea())) for t in range(59)]
    events, writer, _ = run_stream(chunks)
    assert set(events) == {"?0AFF"}
    assert not writer.writes


@pytest.mark.parametrize("payload", [b"garbage\r\n", b"$GNRMC,invalid*00\r\n", b"{}\n"])
def test_noise_and_invalid_nmea_trigger_one_long_outage_probe(payload):
    chunks = [(0, devices("/dev/ttyAMA2"))] + [(t, payload) for t in range(61)]
    chunks += [(61, devices("/dev/ttyAMA2")), (300, payload)]
    events, writer, _ = run_stream(chunks)
    assert events == []
    assert len(polls(writer)) == 1


def test_corrupt_ubx_stays_a_checksum_marker_and_does_not_rearm():
    corrupt = frame()[:-1] + b"\xff"
    chunks = [(t, corrupt) for t in range(61)]
    chunks += [(61, devices("/dev/ttyAMA2")), (62, corrupt), (600, corrupt)]
    events, writer, _ = run_stream(chunks)
    assert set(events) == {"?CKSUM"}
    assert len(polls(writer)) == 1


def test_silent_reader_is_polled_once_without_waiting_for_navigation():
    events, writer, _ = run_stream(
        [
            (59, None),
            (60, None),
            (61, devices("/dev/ttyAMA2")),
            (62, None),
            (300, None),
            (600, None),
        ]
    )
    assert events == []
    assert len(polls(writer)) == 1


@pytest.mark.parametrize(
    "report",
    [
        b"",
        devices(),
        devices("/dev/ttyAMA2", "/dev/ttyUSB0"),
        devices("tcp://remote:1234"),
        devices("/dev/ttyAMA2", driver="SiRF"),
        devices("/dev/ttyAMA2", readonly=True),
        b'{"class":"DEVICES","devices":[null]}\n',
        b'{"class":"DEVICES","devices":null}\n',
    ],
)
def test_unidentified_ambiguous_or_unsupported_device_never_receives_poll(report):
    events, writer, _ = run_stream(
        [(0, report + nmea()), (60, nmea()), (61, report + nmea()), (70, nmea())]
    )
    assert "?NMEA" in events
    assert not polls(writer)


def test_changed_device_pool_clears_previous_poll_target():
    recovery = UBXRecovery()
    recovery.feed_text(devices("/dev/ttyAMA2"), 0)
    recovery.feed_text(devices("/dev/ttyAMA2", "/dev/ttyUSB0"), 1)
    assert recovery.version_command() is None


def test_file_replay_never_sends_commands_even_if_it_contains_gpsd_json():
    events, writer, _ = run_stream(nmea_stream(), replay=True)
    assert "?NMEA" in events
    assert not writer.writes


def test_closed_writer_never_sends_commands():
    writer = Writer()
    writer.closed = True
    _, writer, _ = run_stream(nmea_stream(), writer=writer)
    assert not writer.writes


def test_failed_drain_does_not_retry_automatically(caplog):
    class SlowWriter(Writer):
        async def drain(self):
            raise asyncio.TimeoutError

    _, writer, parser = run_stream(nmea_stream(), writer=SlowWriter())
    assert len(writer.writes) == 1
    assert parser._recovery.probed
    assert caplog.text.count("command drain timed out") == 1


def test_broken_connection_closes_instead_of_repeating_probe():
    class BrokenWriter(Writer):
        def write(self, data):
            super().write(data)
            raise BrokenPipeError

    _, writer, parser = run_stream(nmea_stream(), writer=BrokenWriter())
    assert len(writer.writes) == 1
    assert parser._recovery.probed
    assert writer.closed


def test_version_reply_does_not_rearm_automatic_recovery():
    chunks = [
        (60, None),
        (61, devices("/dev/ttyAMA2")),
        (62, version_frame()),
        (300, version_frame()),
        (600, None),
    ]
    _, writer, parser = run_stream(chunks)
    assert len(polls(writer)) == 1
    assert parser._recovery.probed


def test_no_new_probe_immediately_after_ubx_disappears():
    recovery = UBXRecovery()
    recovery.feed_text(devices("/dev/ttyAMA2"), 0)
    recovery.observe_navigation(100)
    assert not recovery.needs_probe(159)
    assert recovery.needs_probe(160)


def test_manual_version_works_during_normal_navigation_and_reports_result():
    chunks = [
        (0, devices("/dev/ttyAMA2") + frame()),
        (1, version_frame()),
        (2, frame()),
    ]
    events, writer, parser = run_stream(chunks, manual=True)
    assert "MON-VER" in events
    assert len(polls(writer)) == 1
    assert parser.result_queue.get_nowait() == (
        "version_status",
        "SPG 5.10\nPROT 34.10",
    )
    assert parser.result_queue.empty()


def test_manual_version_timeout_and_missing_device_are_reported():
    _, writer, parser = run_stream(
        [(0, devices("/dev/ttyAMA2")), (6, None)], manual=True
    )
    assert len(polls(writer)) == 1
    assert parser.result_queue.get_nowait() == (
        "version_status",
        "GPS VER\nNo response",
    )
    _, writer, parser = run_stream([(6, None)], manual=True)
    assert not polls(writer)
    assert parser.result_queue.get_nowait() == ("version_status", "GPS VER\nNo device")


def test_manual_is_allowed_after_automatic_budget_is_used():
    clock = Clock()
    writer = Writer()
    parser = UBXParser(None, writer=writer, clock=clock)
    parser._recovery.probed = True
    parser.command_queue = Queue()
    for _ in range(4):
        parser.command_queue.put("get_version")

    async def check():
        await parser._service_requests()
        parser._recovery.feed_text(devices("/dev/ttyAMA2"), 0)
        await parser._service_requests()
        await parser._service_requests()

    asyncio.run(check())
    assert len(polls(writer)) == 1


def test_unterminated_text_buffer_is_bounded_and_recovers():
    recovery = UBXRecovery()
    recovery.feed_text(b"x" * (MAX_TEXT_BYTES + 1), 0)
    assert len(recovery.text) <= MAX_TEXT_BYTES
    assert recovery.feed_text(nmea(), 1)
