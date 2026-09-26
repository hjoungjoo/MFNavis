"""Read and write mount limits through INDI, without owning the serial port."""

import math
import socket
import time
import xml.etree.ElementTree as ET


LIMIT_FIELDS = {
    "horizon": ("Slew elevation Limit", "minAlt", -30, 30),
    "overhead": ("Slew elevation Limit", "maxAlt", 60, 90),
    "meridian_east": ("Minutes Past Meridian", "East", -180, 180),
    "meridian_west": ("Minutes Past Meridian", "West", -180, 180),
}


def limit_values(properties, device_name):
    """Missing/invalid telemetry stays empty instead of inventing defaults."""
    result = {}
    connected = properties.get(f"{device_name}.CONNECTION.CONNECT") == "On"
    for key, (vector, element, low, high) in LIMIT_FIELDS.items():
        try:
            value = float(properties[f"{device_name}.{vector}.{element}"])
            if not connected or not math.isfinite(value) or not low <= value <= high:
                raise ValueError
            result[key] = value
        except (KeyError, TypeError, ValueError):
            result[key] = ""
    return result


def validate_limits(values):
    result = {}
    for key, (_, _, low, high) in LIMIT_FIELDS.items():
        try:
            value = float(values.get(key, ""))
        except (TypeError, ValueError):
            raise ValueError(
                f"{key}: a whole number between {low} and {high} is required"
            )
        if (
            not math.isfinite(value)
            or not value.is_integer()
            or not low <= value <= high
        ):
            raise ValueError(
                f"{key}: a whole number between {low} and {high} is required"
            )
        result[key] = int(value)
    return result


class _LimitConnection:
    def __init__(self, host, port, device):
        self.socket = socket.create_connection((host, port), timeout=3)
        self.socket.settimeout(0.2)
        self.device = device
        self.parser = ET.XMLPullParser(events=("end",))
        self.parser.feed("<indi>")

    def send(self, element):
        self.socket.sendall(ET.tostring(element, encoding="utf-8"))

    def events(self):
        try:
            data = self.socket.recv(65536)
        except socket.timeout:
            return []
        if not data:
            raise RuntimeError("INDI server disconnected while applying limits")
        self.parser.feed(data)
        result = []
        for _, element in self.parser.read_events():
            if element.tag.endswith("Vector") or element.tag == "message":
                if element.get("device") == self.device:
                    result.append(element)
        return result

    def close(self):
        self.socket.close()


def apply_limits(values, *, server_host, server_port, device_name, timeout=8.0):
    """Send complete vectors and verify driver responses.

    A write echo alone is insufficient: this driver can publish Ok even after
    a controller rejection. For elevation wait for a later poll and preserve
    error messages. Meridian firmware polls only run in GEM mode; its write
    acknowledgement does not claim firmware readback in Alt/Az mode.
    Partial changes are reported; no automatic rollback overwrites other clients.
    """
    values = validate_limits(values)
    connection = _LimitConnection(server_host, server_port, device_name)
    applied = []
    try:
        connection.send(ET.Element("getProperties", version="1.7", device=device_name))
        definitions = {}
        connected = False
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for event in connection.events():
                if event.get("name") == "CONNECTION":
                    connected = any(
                        c.get("name") == "CONNECT" and (c.text or "").strip() == "On"
                        for c in event
                    )
                if event.tag == "defNumberVector":
                    definitions[event.get("name")] = event
            if connected and all(
                v in definitions for v, _, _, _ in LIMIT_FIELDS.values()
            ):
                break
        if not connected:
            raise RuntimeError("Connect the INDI mount before applying limits")
        for vector in dict.fromkeys(v for v, _, _, _ in LIMIT_FIELDS.values()):
            definition = definitions.get(vector)
            expected = {
                element: values[key]
                for key, (name, element, _, _) in LIMIT_FIELDS.items()
                if name == vector
            }
            if (
                definition is None
                or definition.get("perm") != "rw"
                or not set(expected).issubset({c.get("name") for c in definition})
            ):
                raise RuntimeError(f"INDI driver does not provide writable {vector}")
        for vector in dict.fromkeys(v for v, _, _, _ in LIMIT_FIELDS.values()):
            expected = {
                element: values[key]
                for key, (name, element, _, _) in LIMIT_FIELDS.items()
                if name == vector
            }
            command = ET.Element("newNumberVector", device=device_name, name=vector)
            for name, value in expected.items():
                ET.SubElement(command, "oneNumber", name=name).text = str(value)
            connection.send(command)
            sent = time.monotonic()
            deadline = sent + timeout
            verified = False
            while time.monotonic() < deadline:
                for event in connection.events():
                    if event.get("name") == "CONNECTION" and any(
                        c.get("name") == "CONNECT" and (c.text or "").strip() == "Off"
                        for c in event
                    ):
                        raise RuntimeError(
                            "INDI mount disconnected while applying limits"
                        )
                    if event.tag == "message" and "[ERROR]" in event.get("message", ""):
                        raise RuntimeError(event.get("message"))
                    if event.tag != "setNumberVector" or event.get("name") != vector:
                        continue
                    if event.get("state") == "Alert":
                        raise RuntimeError(f"INDI driver rejected {vector}")
                    if event.get("state") not in {"Ok", "Idle"}:
                        continue
                    # Elevation is polled every second. Meridian is only polled
                    # in GEM mode, so require the explicit write acknowledgement.
                    if vector == "Slew elevation Limit" and time.monotonic() - sent < 2:
                        continue
                    if vector == "Minutes Past Meridian" and event.get("state") != "Ok":
                        continue
                    try:
                        readback = {c.get("name"): float(c.text) for c in event}
                    except (TypeError, ValueError):
                        continue
                    if all(readback.get(k) == v for k, v in expected.items()):
                        verified = True
                if verified:
                    break
            if not verified:
                raise RuntimeError(
                    f"Could not verify {vector} from INDI mount readback"
                )
            applied.append(vector)
        return values
    except (OSError, ET.ParseError, UnicodeError, RuntimeError) as exc:
        suffix = (
            f"; already verified: {', '.join(applied)}"
            if applied
            else "; some values may have changed; refresh to check"
        )
        raise RuntimeError(f"{exc}{suffix}") from exc
    finally:
        connection.close()
