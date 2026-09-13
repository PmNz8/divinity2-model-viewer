#!/usr/bin/env python3
"""Independent synthetic DV2 archive constructor for tests.

Deliberately does NOT use dv2lib's writer: archives are assembled directly
with struct/zlib so that backend round-trip success is independent evidence
that both sides agree on the documented layout.

Layout produced (mirrors the format facts encoded by the reference parser):
  header  <IIIBBII>  (22 bytes)
  path table           NUL-terminated ASCII paths, backslash separated
  u32 count
  count * <III>        (relative_offset, packed_size, unpacked_size)
  payloads             starts aligned to 0x8000 in layout mode 0, packed in
                       mode 1; offsets relative to the declared data offset
  final padding to a 32 KiB multiple unless ``final_padding=False``.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

HEADER = struct.Struct("<IIIBBII")
ENTRY = struct.Struct("<III")
BLOCK_SIZE = 0x8000


def align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def build_synthetic(
    entries: list[tuple[str, bytes, str]],
    layout_mode: int,
    *,
    version: int = 5,
    unknown_04: int = 1,
    unknown_08: int = 4,
    compression_mode: int = 1,
    final_padding: bool = True,
    extra_header_gap: int = 0,
    mode0_sequential: bool = False,
    head_filler: bytes = b"",
    gap_filler: bytes = b"",
    tail_content: bytes = b"",
) -> bytes:
    """Assemble a synthetic archive.

    ``entries``: list of (path, logical_payload, storage_mode) in placement
    order.  ``extra_header_gap`` inserts additional zero bytes between the
    entry table and the data area (a non-canonical variant the reader still
    accepts; useful when measuring forced-rebuild differences).
    ``mode0_sequential`` places layout-mode-0 payloads back-to-back WITHOUT
    per-entry 0x8000 alignment (the runtime-accepted sequential-offset
    variant); the declared data offset stays aligned as usual.
    ``head_filler`` fills the beginning of the [entry_table_end, data_offset)
    gap with nonzero bytes; ``gap_filler`` inserts nonzero bytes between the
    first and second payload; ``tail_content`` overwrites the beginning of the
    final padding with nonzero bytes.  All three simulate UNINDEXED residue.
    """
    if layout_mode not in (0, 1):
        raise ValueError("layout_mode must be 0 or 1")
    for path, _payload, mode in entries:
        if mode not in ("raw", "zlib"):
            raise ValueError("mode must be raw or zlib")
        if mode == "zlib" and len(_payload) == 0:
            raise ValueError("zlib mode cannot represent an empty payload")
        path.encode("ascii")

    path_table = b"".join(path.encode("ascii") + b"\0" for path, _p, _m in entries)
    entry_table_offset = HEADER.size + len(path_table)
    entry_table_end = entry_table_offset + 4 + len(entries) * ENTRY.size

    if layout_mode == 0:
        data_offset = align_up(entry_table_end, BLOCK_SIZE) + extra_header_gap
    else:
        data_offset = entry_table_end + extra_header_gap

    out = bytearray()
    out += HEADER.pack(
        version, unknown_04, unknown_08, layout_mode, compression_mode, data_offset, len(path_table)
    )
    out += path_table
    out += struct.pack("<I", len(entries))
    out += bytes(len(entries) * ENTRY.size)
    gap_len = data_offset - len(out)
    if gap_len < 0:
        raise ValueError("data_offset precedes end of entry table")
    if head_filler:
        if len(head_filler) > gap_len:
            raise ValueError("head_filler does not fit into the pre-data gap")
        out += head_filler + bytes(gap_len - len(head_filler))
    else:
        out += bytes(gap_len)

    records: list[tuple[int, int, int]] = []
    cursor = 0
    for entry_index, (_path, payload, mode) in enumerate(entries):
        if layout_mode == 0 and not mode0_sequential:
            aligned = align_up(cursor, BLOCK_SIZE)
            out += bytes(aligned - cursor)
            cursor = aligned
        if mode == "zlib":
            stored = zlib.compress(payload, 9)
            unpacked_field = len(payload)
        else:
            stored = payload
            unpacked_field = 0
        records.append((cursor, len(stored), unpacked_field))
        out += stored
        cursor += len(stored)
        if gap_filler and entry_index == 0 and len(entries) >= 2:
            # Non-indexed inter-payload residue between first and second entry.
            out += gap_filler
            cursor += len(gap_filler)

    if final_padding:
        pad_len = align_up(len(out), BLOCK_SIZE) - len(out)
        if tail_content:
            if len(tail_content) > pad_len:
                raise ValueError("tail_content does not fit into the final padding")
            out += tail_content + bytes(pad_len - len(tail_content))
        else:
            out += bytes(pad_len)

    table_at = entry_table_offset + 4
    for index, (rel, packed, unpacked) in enumerate(records):
        struct.pack_into("<III", out, table_at + index * ENTRY.size, rel, packed, unpacked)

    return bytes(out)


def write_synthetic(directory: Path, name: str, *args, **kwargs) -> Path:
    path = Path(directory) / name
    path.write_bytes(build_synthetic(*args, **kwargs))
    return path


SAMPLE_PAYLOADS = {
    "small": b"hello divinity payload",
    "binary": bytes(range(256)) * 40,
    "compressible": b"REPEAT" * 5000,
}
