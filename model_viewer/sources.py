"""Read-only corpus index. Physical source selection is never precedence.

Index every DV2 recursively, including root patches. Metadata guards detect
ordinary drift, not adversarial same-metadata rewrites; export rehashes used
archives before accepting cached identities.
"""
from dataclasses import dataclass
import hashlib
from pathlib import Path

from tools.dv2_archive.src.dv2lib import DV2Session
from .package import Source, logical_path, MAX_MEMBER


class SourceError(ValueError):
    pass


@dataclass(frozen=True)
class Occurrence:
    archive: str
    path: str
    size: int


def stamp(path):
    s = path.stat()
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def hash_file(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


class Corpus:
    def __init__(self, root, progress=None):
        self.root = Path(root).resolve(strict=True)
        self.sessions, self.stamps, self.entries, self.identities = {}, {}, {}, {}
        self.archives = self._inventory()
        if not self.archives:
            raise SourceError('no DV2 archives found')
        for number, path in enumerate(self.archives):
            before = stamp(path)
            session = DV2Session(path)
            if stamp(path) != before:
                raise SourceError('archive changed while indexing')
            archive = path.relative_to(self.root).as_posix()
            self.sessions[archive] = session
            self.stamps[archive] = before
            local = set()
            for entry in session.list_entries():
                name = logical_path(entry.path)
                key = name.casefold()
                if key in local:
                    raise SourceError('duplicate normalized path inside archive')
                local.add(key)
                self.entries.setdefault(key, []).append(Occurrence(archive, name, entry.logical_size))
            if progress:
                progress(number + 1, len(self.archives), archive)
        self.check()

    def _inventory(self):
        if not self.root.is_dir():
            raise SourceError('corpus root must be a directory')
        paths = sorted((p for p in self.root.rglob('*') if p.is_file() and p.suffix.casefold() == '.dv2'),
                       key=lambda p: p.as_posix().casefold())
        for path in paths:
            if not path.resolve().is_relative_to(self.root):
                raise SourceError('archive symlink escapes corpus root')
        return tuple(paths)

    def check(self):
        if self._inventory() != self.archives:
            raise SourceError('archive inventory changed; rebuild index')
        for archive, session in self.sessions.items():
            self._check_one(archive, session)

    def _check_one(self, archive, session):
        if stamp(session.path) != self.stamps[archive]:
            raise SourceError('archive changed; rebuild index: ' + archive)

    def occurrences(self, path):
        return tuple(self.entries.get(logical_path(path).casefold(), ()))

    def select(self, path, archive=None):
        rows = self.occurrences(path)
        if archive is not None:
            rows = tuple(r for r in rows if r.archive == archive)
        if len(rows) != 1:
            raise SourceError('resource missing or ambiguous; choose physical archive: ' + path)
        return rows[0]

    def read(self, occurrence, *, fresh_hash=False, dependencies=(), unresolved=()):
        if occurrence not in self.occurrences(occurrence.path):
            raise SourceError('occurrence does not belong to index')
        session = self.sessions[occurrence.archive]
        self._check_one(occurrence.archive, session)
        if fresh_hash or occurrence.archive not in self.identities:
            identity = hash_file(session.path)
            if occurrence.archive in self.identities and identity != self.identities[occurrence.archive]:
                raise SourceError('archive identity changed; rebuild index')
            self.identities[occurrence.archive] = identity
        raw = session.read_entry_bytes(occurrence.path, maximum_size=MAX_MEMBER)
        self._check_one(occurrence.archive, session)
        return Source(occurrence.path, occurrence.archive, self.identities[occurrence.archive], raw,
                      tuple(dependencies), tuple(unresolved))

    def candidates(self, reference):
        """UI suggestions only: exact logical identity, else same filename.

        An absolute authoring filename is NOT a physical path to read. Filename
        matches must be explicitly selected by the user/verified asset rule.
        """
        normalized = reference.replace('\\', '/')
        exact = self.entries.get(normalized.casefold())
        if exact:
            return tuple(exact)
        filename = normalized.rsplit('/', 1)[-1].casefold()
        return tuple(row for key in sorted(self.entries) if key.rsplit('/', 1)[-1] == filename
                     for row in self.entries[key])

    def texture_candidates(self, reference):
        """Same-stem NIF wrapper suggestions; explicit approval still required."""
        filename = reference.replace('\\', '/').rsplit('/', 1)[-1]
        stem = filename.rsplit('.', 1)[0]
        return self.candidates(stem + '.nif')
