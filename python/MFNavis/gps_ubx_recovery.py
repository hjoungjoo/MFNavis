"""Device selection and one-shot recovery of stalled UBX navigation."""

import json
import logging
import re

logger = logging.getLogger("GPS.parser.recovery")

NAV_STALE_SECONDS = 60.0
MAX_TEXT_BYTES = 8192
MON_VER_HEX = "b5620a0400000e34"
NMEA_SENTENCE = re.compile(
    rb"\$[A-Z]{2}(?:RMC|GGA|GSA|GSV|GLL|VTG|ZDA),[ -~]*\*[0-9A-Fa-f]{2}"
)


class UBXRecovery:
    """Observe text outside UBX frames; never scan binary payloads as NMEA.

    A single supported local device is required before sending a poll.
    Only decoded NAV messages rearm an automatic recovery attempt.
    """

    def __init__(self, started_at=0.0):
        self.text = bytearray()
        self.device = None
        self.last_ubx = None
        self.last_navigation = started_at
        self.probed = False

    def feed_text(self, data, now):
        """Return whether complete, checksum-valid navigation NMEA arrived."""
        self.text.extend(data)
        seen = False
        while b"\n" in self.text:
            line, _, rest = self.text.partition(b"\n")
            self.text = bytearray(rest)
            if len(line) > MAX_TEXT_BYTES:
                continue
            line = line.rstrip(b"\r")
            if line.startswith(b"{"):
                self._device_report(line)
            elif len(line) <= 256 and NMEA_SENTENCE.fullmatch(line):
                checksum = 0
                for value in line[1:-3]:
                    checksum ^= value
                if checksum != int(line[-2:], 16):
                    continue
                seen = True
        if len(self.text) > MAX_TEXT_BYTES:
            self.text.clear()
        return seen

    def _device_report(self, line):
        try:
            report = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            return
        if not isinstance(report, dict) or report.get("class") != "DEVICES":
            return
        # Clear a previous target if gpsd now advertises an ambiguous pool.
        self.device = None
        devices = report.get("devices")
        if not isinstance(devices, list) or len(devices) != 1:
            return
        device = devices[0]
        if not isinstance(device, dict):
            return
        path = device.get("path")
        if (
            isinstance(path, str)
            and path.startswith("/dev/")
            and device.get("driver") in ("NMEA0183", "u-blox")
            and not device.get("readonly", False)
        ):
            self.device = path

    def observe_ubx(self, now):
        """Any checksum-valid UBX frame proves binary communication is alive."""
        self.text.clear()
        self.last_ubx = now

    def observe_navigation(self, now):
        """Only decoded NAV traffic rearms recovery, never a version or ACK."""
        if self.probed:
            logger.warning(
                "Navigation traffic resumed after MON-VER recovery on %s",
                self.device,
            )
        self.last_navigation = now
        self.probed = False

    def needs_probe(self, now):
        return not self.probed and now - self.last_navigation >= NAV_STALE_SECONDS

    def version_command(self):
        if self.device is None:
            return None
        command = {"path": self.device, "hexdata": MON_VER_HEX}
        return (
            "?DEVICE=" + json.dumps(command, separators=(",", ":")) + ";\n"
        ).encode()
