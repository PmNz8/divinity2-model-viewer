"""Versioned source-preserving package; v2 retains original and edited natives.

ZIP members are content-addressed originals. No extraction is necessary for
verification. Scene semantics/dependency discovery are supplied by the asset
layer; this module never guesses that an unresolved graph is complete.
"""
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import zipfile
from .nif import parse, NifError

SCHEMA = 'divinity2.model-source-package/1'
EDIT_SCHEMA = 'divinity2.model-source-package/2'
MAX_MEMBER = 256 * 1024 * 1024
MAX_PACKAGE = 512 * 1024 * 1024


class PackageError(ValueError):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def logical_path(value):
    if not isinstance(value, str):
        raise PackageError('logical path must be text')
    path = value.replace('\\', '/')
    if not path or any(c in path for c in ':\x00') or path.startswith('/'):
        raise PackageError('unsafe logical path')
    if any(part in ('', '.', '..') for part in path.split('/')):
        raise PackageError('unsafe logical path component')
    return path


@dataclass(frozen=True)
class Source:
    logical_path: str
    archive_name: str
    archive_sha256: str
    payload: bytes
    # Explicit, justified edge targets, not string-table guesses.
    dependencies: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()
    original_payload: bytes | None = None


def _json(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _sha(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise PackageError('identity must be lowercase SHA-256')


def _structure(raw):
    try:
        return parse(raw).sidecar()
    except NifError:
        return None


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PackageError('duplicate JSON key')
        result[key] = value
    return result


def build(sources, primary, *, assembly=None):
    sources = tuple(sources)
    edited = any(s.original_payload is not None for s in sources)
    primary = logical_path(primary)
    records, members, keys = [], {}, set()
    for source in sorted(sources, key=lambda s: logical_path(s.logical_path).casefold()):
        path = logical_path(source.logical_path)
        if path.casefold() in keys:
            raise PackageError('ambiguous/duplicate logical resource')
        keys.add(path.casefold())
        if len(source.payload) > MAX_MEMBER:
            raise PackageError('resource too large')
        _sha(source.archive_sha256)
        if not isinstance(source.archive_name, str) or not source.archive_name:
            raise PackageError('archive name required')
        if not isinstance(source.unresolved, (tuple, list)) or any(not isinstance(v, str) or not v for v in source.unresolved):
            raise PackageError('unresolved must contain descriptions')
        sha = digest(source.payload)
        member = ('resources/' if edited else 'originals/') + sha + '.bin'
        members[member] = source.payload
        structure = _structure(source.payload)
        records.append(dict(logical_path=path, archive_name=source.archive_name,
                            archive_sha256=source.archive_sha256, sha256=sha,
                            size=len(source.payload), member=member, structure=structure,
                            dependencies=sorted({logical_path(p) for p in source.dependencies}),
                            unresolved=list(source.unresolved)))
        if edited:
            original = source.original_payload if source.original_payload is not None else source.payload
            if len(original) > MAX_MEMBER:
                raise PackageError('original resource too large')
            original_sha = digest(original)
            original_member = 'originals/' + original_sha + '.bin'
            members[original_member] = original
            records[-1].update(original_sha256=original_sha,original_size=len(original),
                               original_member=original_member,original_structure=_structure(original))
            from .editing import validate_native_edit
            try: rules=validate_native_edit(original,source.payload)
            except NifError as exc: raise PackageError(str(exc)) from exc
            if rules: records[-1]['normalization']=rules
    if primary.casefold() not in keys:
        raise PackageError('primary resource absent')
    for r in records:
        if any(p.casefold() not in keys for p in r['dependencies']):
            raise PackageError('resolved dependency absent from package')
    if sum(map(len, members.values())) > MAX_PACKAGE:
        raise PackageError('package too large')
    manifest = dict(schema=EDIT_SCHEMA if edited else SCHEMA, primary=primary, resources=records, assembly=assembly,
                    fidelity='originals_and_edited_resources_preserved' if edited else 'original_bytes_preserved',
                    edit_support='fixed_topology/1' if edited else 'none',
                    dependency_status='unresolved' if any(r['unresolved'] for r in records) else 'declared_edges_present')
    members['manifest.json'] = _json(manifest)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED) as z:
        for name, payload in sorted(members.items()):
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_STORED
            entry.external_attr = 0o600 << 16
            z.writestr(entry, payload)
    result = stream.getvalue()
    verify(result)
    return result


def verify(payload):
    if len(payload) > MAX_PACKAGE + 16 * 1024 * 1024:
        raise PackageError('package too large')
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            infos = z.infolist()
            names = [i.filename for i in infos]
            if len(names) != len(set(names)) or len(names) > 10001:
                raise PackageError('duplicate/excessive members')
            if any(i.compress_type != zipfile.ZIP_STORED or i.file_size > (MAX_PACKAGE if i.filename=='model.d2model' else MAX_MEMBER) for i in infos):
                raise PackageError('unsupported compression or oversized member')
            if sum(i.file_size for i in infos) > MAX_PACKAGE + 16 * 1024 * 1024:
                raise PackageError('oversized contents')
            if z.getinfo('manifest.json').file_size > 16 * 1024 * 1024:
                raise PackageError('oversized manifest')
            manifest = json.loads(z.read('manifest.json'), object_pairs_hook=_object)
            if isinstance(manifest,dict) and manifest.get('schema') in ('divinity2.model-source-package/3','divinity2.model-source-package/4'):
                raise PackageError('Visual-only tools accept v1/v2 packages only. Re-export the model without attachments using Model Viewer.')
            if not isinstance(manifest, dict) or not isinstance(manifest.get('resources'), list):
                raise PackageError('invalid manifest shape')
            edited = manifest['schema'] == EDIT_SCHEMA
            if ((manifest['schema'],manifest['edit_support'],manifest['fidelity']) not in
                ((SCHEMA,'none','original_bytes_preserved'),
                 (EDIT_SCHEMA,'fixed_topology/1','originals_and_edited_resources_preserved'))):
                raise PackageError('unsupported contract')
            keys, expected, originals = set(), {'manifest.json'}, []
            for row in manifest['resources']:
                if not isinstance(row, dict):
                    raise PackageError('invalid resource record')
                _sha(row['archive_sha256'])
                if not isinstance(row['archive_name'], str) or not row['archive_name']:
                    raise PackageError('archive name required')
                if type(row['size']) is not int or row['size'] < 0:
                    raise PackageError('invalid resource size')
                for key in ('dependencies', 'unresolved'):
                    if not isinstance(row[key], list) or any(not isinstance(v, str) or not v for v in row[key]):
                        raise PackageError('invalid dependency list')
                path = logical_path(row['logical_path'])
                if path.casefold() in keys:
                    raise PackageError('duplicate logical identity')
                keys.add(path.casefold())
                sha = row['sha256']
                _sha(sha)
                member = ('resources/' if edited else 'originals/') + sha + '.bin'
                if row['member'] != member:
                    raise PackageError('invalid member identity')
                raw = z.read(member)
                if len(raw) != row['size'] or digest(raw) != sha:
                    raise PackageError('payload identity mismatch')
                # Re-derive even when a sidecar has been removed from a valid NIF.
                if _json(_structure(raw)) != _json(row['structure']):
                    raise PackageError('structure differs from original')
                expected.add(member)
                original = None
                if edited:
                    _sha(row['original_sha256'])
                    original_member = 'originals/' + row['original_sha256'] + '.bin'
                    if row['original_member'] != original_member or type(row['original_size']) is not int:
                        raise PackageError('invalid original identity')
                    original = z.read(original_member)
                    if len(original) != row['original_size'] or digest(original) != row['original_sha256']:
                        raise PackageError('original source identity mismatch')
                    if _json(_structure(original)) != _json(row['original_structure']):
                        raise PackageError('original source structure mismatch')
                    from .editing import validate_native_edit
                    rules=validate_native_edit(original,raw)
                    if row.get('normalization',[])!=rules:
                        raise PackageError('normalization report differs from validated edits')
                    expected.add(original_member)
                if not edited and 'normalization' in row:
                    raise PackageError('normalization requires preserved original')
                originals.append(Source(path, row['archive_name'], row['archive_sha256'], raw,
                                        tuple(row['dependencies']),tuple(row['unresolved']),original))
            if logical_path(manifest['primary']).casefold() not in keys:
                raise PackageError('primary absent')
            for row in manifest['resources']:
                if any(logical_path(p).casefold() not in keys for p in row['dependencies']):
                    raise PackageError('missing dependency')
            status = 'unresolved' if any(r['unresolved'] for r in manifest['resources']) else 'declared_edges_present'
            if manifest['dependency_status'] != status:
                raise PackageError('incorrect dependency status')
            if set(names) != expected:
                raise PackageError('unexpected package members')
            assembly = manifest.get('assembly')
            if assembly is not None:
                from .replay import restore
                replayed = restore(originals, manifest['primary'], assembly['recipe'])
                if _json(replayed.assembly()) != _json(assembly):
                    raise PackageError('assembly differs from original resources/recipe')
            return manifest
    except (KeyError, TypeError, AttributeError, IndexError, ValueError, UnicodeError, zipfile.BadZipFile, RuntimeError) as exc:
        raise PackageError(f'invalid package: {exc}') from exc


def open_preview(payload):
    """Verify and reconstruct without reading the original game installation."""
    payload=bytes(payload)
    manifest = verify(payload)
    if manifest.get('assembly') is None:
        raise PackageError('package has no preview assembly')
    from .replay import restore
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        sources = [Source(r['logical_path'], r['archive_name'], r['archive_sha256'], z.read(r['member']),
                          tuple(r['dependencies']),tuple(r['unresolved']),
                          z.read(r['original_member']) if manifest['schema'] == EDIT_SCHEMA else None)
                   for r in manifest['resources']]
    return restore(sources, manifest['primary'], manifest['assembly']['recipe'])


def save_new(payload, destination):
    """Verify, fsync and atomically publish a NEW file; never overwrite."""
    verify(payload)
    destination = Path(destination).absolute()
    if destination.exists():
        raise PackageError('destination exists; choose a new filename')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.model-package-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        verify(temporary.read_bytes())
        # Hard-link creation is atomic and fails if a racing writer created the
        # destination. Unlike replace(), it cannot overwrite unrelated content.
        os.link(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination
