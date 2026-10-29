"""Small transactional file store for the A0 8KiB FM24CL64B.

Two 4KiB banks contain compressed directory snapshots. Each file has its own
SHA-256; metadata and the complete bank payload have a separate SHA-256.
Writes commit the inactive bank last, retaining the previous valid directory.
"""

import base64
import binascii
from contextlib import contextmanager
import fcntl
import hashlib
import json
from pathlib import Path
import struct
import time
import zlib

ADDRESS = 0x50
SIZE = 8192
SLOT_SIZE = SIZE // 2
MAGIC = b"MFNFS01!"
PREFIX = struct.Struct(">BQII")
HEADER_SIZE = len(MAGIC) + PREFIX.size + 32
MAX_JSON = 262144


def canonical(settings):
    if not isinstance(settings, dict) or not all(isinstance(k, str) for k in settings):
        raise ValueError("Settings must be a JSON object with string keys")
    return json.dumps(
        settings,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def decode_slot(data):
    if len(data) != SLOT_SIZE or data[:8] != MAGIC:
        return None
    try:
        prefix = data[8 : 8 + PREFIX.size]
        version, generation, packed_size, raw_size = PREFIX.unpack(prefix)
        if (
            version != 1
            or generation < 1
            or not 0 < packed_size <= SLOT_SIZE - HEADER_SIZE
        ):
            return None
        if not 0 < raw_size <= MAX_JSON:
            return None
        payload = data[HEADER_SIZE : HEADER_SIZE + packed_size]
        digest = data[8 + PREFIX.size : HEADER_SIZE]
        if hashlib.sha256(prefix + payload).digest() != digest:
            return None
        decoder = zlib.decompressobj()
        raw = decoder.decompress(payload, raw_size + 1)
        if (
            len(raw) != raw_size
            or not decoder.eof
            or decoder.unused_data
            or decoder.unconsumed_tail
        ):
            return None
        settings = json.loads(raw)
        if canonical(settings) != raw:
            return None
        return {
            "generation": generation,
            "settings": settings,
            "sha256": digest.hex(),
            "packed_bytes": packed_size,
        }
    except (ValueError, TypeError, UnicodeError, zlib.error, struct.error):
        return None


class FRAMStore:
    def __init__(self, bus):
        self.bus = bus

    @contextmanager
    def locked(self):
        deadline = time.monotonic() + 1
        while not self.bus.try_lock():
            if time.monotonic() >= deadline:
                raise TimeoutError("FRAM I2C lock timed out")
            time.sleep(0.001)
        try:
            yield self
        finally:
            self.bus.unlock()

    def read(self, offset, length):
        if offset < 0 or length < 0 or offset + length > SIZE:
            raise ValueError("FRAM read outside memory")
        data = bytearray(length)
        for start in range(0, length, 128):
            chunk = bytearray(min(128, length - start))
            self.bus.writeto_then_readfrom(
                ADDRESS, (offset + start).to_bytes(2, "big"), chunk
            )
            data[start : start + len(chunk)] = chunk
        return bytes(data)

    def write(self, offset, data):
        if offset < 0 or offset + len(data) > SIZE:
            raise ValueError("FRAM write outside memory")
        for start in range(0, len(data), 128):
            self.bus.writeto(
                ADDRESS, (offset + start).to_bytes(2, "big") + data[start : start + 128]
            )

    def latest(self):
        candidates = []
        for slot in range(2):
            record = decode_slot(self.read(slot * SLOT_SIZE, SLOT_SIZE))
            if record is not None:
                candidates.append({**record, "slot": slot})
        return max(candidates, key=lambda r: r["generation"]) if candidates else None

    def save(self, settings):
        raw = canonical(settings)
        payload = zlib.compress(raw, 9)
        if len(raw) > MAX_JSON or len(payload) > SLOT_SIZE - HEADER_SIZE:
            raise ValueError(
                f"Settings exceed FRAM slot capacity: {len(payload)} compressed bytes"
            )
        old = self.latest()
        if old and old["settings"] == settings:
            return old
        generation = old["generation"] + 1 if old else 1
        prefix = PREFIX.pack(1, generation, len(payload), len(raw))
        digest = hashlib.sha256(prefix + payload).digest()
        slot = 1 - old["slot"] if old else 0
        offset = slot * SLOT_SIZE
        self.write(offset, bytes(8))  # invalidate destination before touching its data
        self.write(offset + HEADER_SIZE, payload)
        self.write(offset + 8, prefix + digest)
        expected = bytes(8) + prefix + digest + payload
        if self.read(offset, len(expected)) != expected:
            raise OSError("FRAM backup readback failed before commit")
        self.write(offset, MAGIC)  # commit only after complete payload readback
        saved = decode_slot(self.read(offset, SLOT_SIZE))
        if saved is None or saved["settings"] != settings:
            raise OSError("FRAM backup verification failed after commit")
        return {**saved, "slot": slot}


FS_FORMAT = "MFNavis-FRAMFS-1"


class CorruptFileError(ValueError):
    pass


def file_name(name):
    if not isinstance(name, str) or not name.startswith("/"):
        raise ValueError("FRAM file names must be absolute paths")
    if len(name.encode("utf-8")) > 128 or any(
        p in ("", ".", "..") for p in name[1:].split("/")
    ):
        raise ValueError("Invalid FRAM file name")
    if "\x00" in name:
        raise ValueError("Invalid FRAM file name")
    return name


def file_entry(data):
    if not isinstance(data, bytes):
        raise TypeError("FRAM file contents must be bytes")
    # Text stays text so JSON configuration compresses efficiently. Binary
    # files use base64; both encodings are reversible and hash the original bytes.
    try:
        encoded = data.decode("utf-8")
        encoding = "utf-8"
    except UnicodeDecodeError:
        encoded = base64.b64encode(data).decode("ascii")
        encoding = "base64"
    return {
        "data": encoded,
        "encoding": encoding,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


class FRAMFileSystem:
    def __init__(self, store, lock_path):
        self.store = store
        self.lock_path = Path(lock_path)

    @contextmanager
    def transaction(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                with self.store.locked():
                    yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _directory(self):
        record = self.store.latest()
        if record is None:
            return {}, None
        document = record["settings"]
        if document.get("format") == FS_FORMAT and isinstance(
            document.get("files"), dict
        ):
            return dict(document["files"]), record
        # Read the earlier configuration-only record without discarding it.
        # It becomes /config.json on the next successful filesystem write.
        if "format" not in document:
            return {"/config.json": file_entry(canonical(document))}, record
        raise ValueError("Unsupported FRAM filesystem format; preserving stored data")

    def read_file(self, name):
        name = file_name(name)
        with self.transaction():
            directory, _ = self._directory()
            if name not in directory:
                raise FileNotFoundError(name)
            entry = directory[name]
            try:
                if entry.get("encoding", "base64") == "utf-8":
                    data = entry["data"].encode("utf-8")
                elif entry.get("encoding", "base64") == "base64":
                    data = base64.b64decode(entry["data"], validate=True)
                else:
                    raise CorruptFileError(f"Unknown file encoding: {name}")
                if (
                    len(data) != entry["size"]
                    or hashlib.sha256(data).hexdigest() != entry["sha256"]
                ):
                    raise CorruptFileError(f"FRAM file hash mismatch: {name}")
                return data
            except (
                KeyError,
                AttributeError,
                TypeError,
                ValueError,
                binascii.Error,
            ) as exc:
                raise CorruptFileError(f"Invalid FRAM file: {name}") from exc

    def write_file(self, name, data):
        name = file_name(name)
        entry = file_entry(data)
        with self.transaction():
            directory, _ = self._directory()
            directory[name] = entry
            saved = self.store.save({"format": FS_FORMAT, "files": directory})
            return {
                k: saved[k] for k in ("generation", "slot", "packed_bytes", "sha256")
            }

    def delete_file(self, name):
        name = file_name(name)
        with self.transaction():
            directory, _ = self._directory()
            if name not in directory:
                raise FileNotFoundError(name)
            del directory[name]
            self.store.save({"format": FS_FORMAT, "files": directory})

    def list_files(self):
        with self.transaction():
            directory, _ = self._directory()
            return {
                name: {"size": entry["size"], "sha256": entry["sha256"]}
                for name, entry in sorted(directory.items())
            }

    def stat(self):
        with self.transaction():
            directory, record = self._directory()
            used = record["packed_bytes"] if record else 0
            return {
                "physical_bytes": SIZE,
                "bank_bytes": SLOT_SIZE,
                "payload_capacity": SLOT_SIZE - HEADER_SIZE,
                "packed_bytes": used,
                "free_packed_bytes": SLOT_SIZE - HEADER_SIZE - used,
                "files": len(directory),
                "generation": record["generation"] if record else 0,
            }


def open_filesystem():
    """Open the A0 file store with the application's shared transaction lock."""
    from PiFinder import utils
    from PiFinder.i2c_bus import get_i2c

    return FRAMFileSystem(FRAMStore(get_i2c()), utils.runtime_dir / "fram-storage.lock")
