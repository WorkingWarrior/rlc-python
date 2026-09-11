"""RealLive Seen.txt archive creation."""

from __future__ import annotations

import os
import re
import struct
import tempfile
from collections.abc import Iterable
from pathlib import Path

ENTRY_COUNT = 10_000
ENTRY_SIZE = 8
INDEX_SIZE = ENTRY_COUNT * ENTRY_SIZE
SCENARIO_NAME = re.compile(r"^SEEN(?P<number>\d{4})\.TXT$", re.IGNORECASE)
COMPRESSED_REALLIVE_HEADER = b"\xd0\x01\x00\x00"


def scenario_number(path: Path) -> int:
    """Return the archive slot encoded in a SEENxxxx.TXT file name."""
    match = SCENARIO_NAME.fullmatch(path.name)
    if match is None:
        raise ValueError(f"invalid scenario file name: {path.name}")
    return int(match.group("number"))


def read_seen_archive(path: Path) -> dict[int, bytes]:
    """Read and validate the populated entries in a RealLive Seen.txt archive."""
    data = Path(path).read_bytes()
    if len(data) < INDEX_SIZE:
        raise ValueError(f"invalid RealLive archive (index is truncated): {path}")

    scenarios = {}
    for number in range(ENTRY_COUNT):
        offset, length = struct.unpack_from("<II", data, number * ENTRY_SIZE)
        if offset == 0 and length == 0:
            continue
        if offset < INDEX_SIZE or length == 0 or offset + length > len(data):
            raise ValueError(f"invalid RealLive archive entry {number:04d}: {path}")
        scenarios[number] = data[offset : offset + length]
    return scenarios


def pack_seen_archive(scenarios: Iterable[Path], destination: Path) -> int:
    """Add compressed scenarios to a RealLive Seen.txt archive.

    Entries already present in ``destination`` are retained unless replaced,
    matching RLDev's ``kprl -a`` behaviour. A missing destination starts a new
    archive.
    """
    destination = Path(destination)
    payloads = read_seen_archive(destination) if destination.exists() else {}
    additions: dict[int, bytes] = {}
    for source in scenarios:
        source = Path(source)
        number = scenario_number(source)
        if number in additions:
            raise ValueError(f"duplicate scenario number: {number:04d}")
        payload = source.read_bytes()
        if payload[:4] != COMPRESSED_REALLIVE_HEADER:
            raise ValueError(f"scenario is not compressed RealLive bytecode: {source}")
        additions[number] = payload

    if not additions:
        raise ValueError("no scenarios to archive")

    payloads.update(additions)
    destination.parent.mkdir(parents=True, exist_ok=True)
    index = bytearray(INDEX_SIZE)
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+b",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as archive:
            temporary_name = archive.name
            archive.write(index)
            offset = INDEX_SIZE
            for number, payload in sorted(payloads.items()):
                struct.pack_into("<II", index, number * ENTRY_SIZE, offset, len(payload))
                archive.write(payload)
                offset += len(payload)
            archive.seek(0)
            archive.write(index)
        os.replace(temporary_name, destination)
    except Exception:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
        raise

    return len(payloads)
