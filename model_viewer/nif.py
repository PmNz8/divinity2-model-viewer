"""Bounded NIF 20.3.0.9 envelope and explicit geometry decoding.

Original payload remains authoritative. Unknown blocks are retained, not
interpreted. This module implements no native model writer.
"""
from dataclasses import dataclass
import hashlib
import math
import struct


class NifError(ValueError):
    pass


class Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def read(self, size):
        if size < 0 or size > len(self.data) - self.pos:
            raise NifError(f'truncated range at {self.pos}: {size} bytes')
        out = self.data[self.pos:self.pos + size]
        self.pos += size
        return out

    def unpack(self, fmt):
        return struct.unpack('<' + fmt, self.read(struct.calcsize('<' + fmt)))

    def one(self, fmt):
        return self.unpack(fmt)[0]

    def count(self, limit=1_000_000):
        n = self.one('I')
        if n > limit:
            raise NifError(f'count {n} exceeds {limit}')
        return n

    def string(self):
        raw = self.read(self.count(1 << 20))
        try:
            return raw.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise NifError('unsupported non-UTF8 string') from exc

    def flag(self):
        n = self.one('B')
        if n not in (0, 1):
            raise NifError(f'invalid boolean {n} at {self.pos - 1}')
        return bool(n)

    def vectors(self, count, width):
        values = self.unpack(f'{count * width}f')
        if not all(math.isfinite(x) for x in values):
            raise NifError('nonfinite vector component')
        return tuple(values[i:i + width] for i in range(0, len(values), width))

    def finish(self):
        if self.pos != len(self.data):
            raise NifError(f'unconsumed bytes: {len(self.data) - self.pos}')


@dataclass(frozen=True)
class Block:
    index: int
    type: str
    start: int
    end: int


@dataclass(frozen=True)
class Document:
    payload: bytes
    user_version: int
    strings: tuple[str, ...]
    groups: tuple[int, ...]
    blocks: tuple[Block, ...]
    roots: tuple[int, ...]
    footer_start: int

    @property
    def sha256(self):
        return hashlib.sha256(self.payload).hexdigest()

    def body(self, index):
        if not 0 <= index < len(self.blocks):
            raise NifError(f'block index out of range: {index}')
        b = self.blocks[index]
        return self.payload[b.start:b.end]

    def sidecar(self):
        return dict(sha256=self.sha256, size=len(self.payload),
                    user_version=self.user_version, strings=self.strings,
                    groups=self.groups, roots=self.roots, footer_start=self.footer_start,
                    blocks=[dict(index=b.index, type=b.type, start=b.start, end=b.end,
                                 sha256=hashlib.sha256(self.body(b.index)).hexdigest())
                            for b in self.blocks])


def parse(data: bytes) -> Document:
    if len(data) > 256 * 1024 * 1024:
        raise NifError('payload exceeds 256 MiB limit')
    r = Reader(data)
    line = b'Gamebryo File Format, Version 20.3.0.9\n'
    if r.read(len(line)) != line:
        raise NifError('unsupported header line')
    version, endian, user = r.unpack('IBI')
    if version != 0x14030009 or endian != 1 or user != 0x30000:
        raise NifError('unsupported version/endian/user version')
    count = r.count(16384)
    if not count:
        raise NifError('empty block table')
    types = tuple(r.string() for _ in range(r.one('H')))
    indices = r.unpack(f'{count}H')
    if any(i >= len(types) for i in indices):
        raise NifError('invalid block type index')
    sizes = r.unpack(f'{count}I')
    nstrings, maxlen = r.count(65536), r.count(1 << 20)
    strings = tuple(r.string() for _ in range(nstrings))
    if any(len(s.encode('utf-8')) > maxlen for s in strings):
        raise NifError('string exceeds declared maximum')
    groups = r.unpack(f'{r.count(16384)}I')
    blocks = []
    for i, size in enumerate(sizes):
        start = r.pos
        r.read(size)
        blocks.append(Block(i, types[indices[i]], start, r.pos))
    footer = r.pos
    roots = r.unpack(f'{r.count(16384)}i')
    if any(i < 0 or i >= count for i in roots):
        raise NifError('invalid footer root')
    r.finish()
    return Document(data, user, strings, groups, tuple(blocks), roots, footer)


def geometry(doc: Document, index: int):
    if doc.blocks[index].type != 'NiTriShapeData':
        raise NifError('unsupported geometry class')
    r = Reader(doc.body(index))
    group, n, keep, compress = r.unpack('iHBB')
    vertices = r.vectors(n, 3) if r.flag() else ()
    flags = r.one('H')
    normals = r.vectors(n, 3) if r.flag() else ()
    tangents = r.vectors(n, 3) if normals and flags & 4096 else ()
    bitangents = r.vectors(n, 3) if tangents else ()
    div2 = r.vectors(n, 1) if r.flag() else ()
    sphere = r.vectors(1, 4)[0]
    corners = r.one('H')
    aabb = r.vectors(2, 3)
    colors = r.vectors(n, 4) if r.flag() else ()
    uv_start = r.pos
    uv = tuple(r.vectors(n, 2) for _ in range(flags & 63))
    consistency, additional, ntri, npoints = r.unpack('HiHI')
    has_triangles = r.flag()
    if npoints != 3 * ntri:
        raise NifError('triangle counts disagree')
    if additional != -1 and not 0 <= additional < len(doc.blocks):
        raise NifError('invalid additional data reference')
    triangles = tuple(r.unpack('3H') for _ in range(ntri)) if has_triangles else ()
    if any(v >= n for t in triangles for v in t):
        raise NifError('triangle index out of range')
    matches = tuple(r.unpack(f'{r.one("H")}H') for _ in range(r.one('H')))
    if any(v >= n for group_indices in matches for v in group_indices):
        raise NifError('match-group index out of range')
    r.finish()
    warnings = []
    if any(abs(v) > 100 for uvset in uv for pair in uvset for v in pair):
        warnings.append('extreme_uv_values_not_interpreted')
    return dict(block=index, vertices=vertices, normals=normals, tangents=tangents,
                bitangents=bitangents, div2_floats=div2, sphere=sphere,
                aabb_corners=corners, aabb=aabb, colors=colors, uv_sets=uv,
                uv_start=doc.blocks[index].start + uv_start, triangles=triangles,
                declared_triangles=ntri, match_groups=matches, flags=flags,
                group_id=group, keep_flags=keep, compress_flags=compress,
                consistency=consistency, additional_data=additional, warnings=warnings)
