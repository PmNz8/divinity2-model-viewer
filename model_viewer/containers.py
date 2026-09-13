"""Bounded CAT/ITEM wrappers. No shifted indices or string-table scanning.

CAT external paths label baked entries; they do not prove that an external
file is identical to the embedded copy. Preview uses the embedded graph.
Unknown manager bytes are retained and never used to infer playback rules.
"""
from .nif import Reader, NifError
from . import scene

PREFIX = 'MdlMan::'
KINDS = ('CSkeletonDataEntry', 'CAMDataEntry', 'CMeshDataEntry', 'CAnimationDataEntry')


def typed_ref(r, doc, kinds):
    index = scene.ref(r, doc)
    if index == -1 or doc.blocks[index].type not in kinds:
        raise NifError('unexpected container reference type')
    return index


def header(r, doc):
    ordinal = r.one('I')
    if not r.flag():
        raise NifError('unsupported non-embedded CAT entry')
    path = scene.name(r, doc)
    if not path:
        raise NifError('empty CAT entry path')
    return dict(ordinal=ordinal, reference=path)


def cat(doc):
    if len(doc.roots) != 1 or doc.blocks[doc.roots[0]].type != PREFIX + 'CModelTemplateDataEntry':
        raise NifError('unsupported CAT root')
    root = doc.roots[0]
    r = Reader(doc.body(root))
    result = header(r, doc)
    result['extra'] = typed_ref(r, doc, ('NiFloatsExtraData',))
    entries = tuple(typed_ref(r, doc, tuple(PREFIX+k for k in KINDS))
                    for _ in range(r.count(4096)))
    r.finish()
    if len(set(entries)) != len(entries):
        raise NifError('duplicate CAT entry')
    actual = {b.index for b in doc.blocks if b.type.startswith(PREFIX) and b.index != root}
    if actual != set(entries):
        raise NifError('unowned CAT entry')
    result.update(root=root, entries=[])
    for index in entries:
        kind = doc.blocks[index].type[len(PREFIX):]
        r = Reader(doc.body(index))
        entry = header(r, doc)
        entry.update(block=index, kind=kind)
        if kind == 'CSkeletonDataEntry':
            entry['root'] = typed_ref(r, doc, ('NiNode',))
        elif kind == 'CMeshDataEntry':
            entry['unknown_byte'] = r.one('B')
            if entry['unknown_byte'] != 0:
                raise NifError('unsupported CAT mesh entry flag')
            entry['root'] = typed_ref(r, doc, ('NiNode',))
        elif kind == 'CAnimationDataEntry':
            entry['clips'] = tuple(typed_ref(r, doc, ('NiControllerSequence',))
                                   for _ in range(r.count(4096)))
        elif kind == 'CAMDataEntry':
            # Length-prefixed manager payload, not a guessed path scan.
            size = r.count(1 << 20)
            entry['manager_offset'] = r.pos
            entry['manager_size'] = size
            r.read(size)
        r.finish()
        result['entries'].append(entry)
    return result


def item(doc):
    if len(doc.roots) != 1 or doc.blocks[doc.roots[0]].type != 'CStreamableAssetData':
        raise NifError('unsupported ITEM root')
    r = Reader(doc.body(doc.roots[0]))
    root = typed_ref(r, doc, ('NiNode', 'NiLODNode'))
    animated = r.flag()
    if not animated:
        if r.count(4096) != 0:
            raise NifError('unsupported static ITEM references')
        r.finish()
        return dict(root=root, opaque_tail_hex=bytes(5).hex())
    size = r.count(1 << 20)
    manager = Reader(r.read(size))
    model_reference, target_name = manager.string(), manager.string()
    if not model_reference or not target_name or manager.unpack('II') != (1, 2):
        raise NifError('unsupported ITEM manager header')
    parameters = manager.vectors(1, 2)[0]
    records = []
    for ordinal in range(manager.count(4096)):
        identifier, reference = manager.one('I'), manager.string()
        sequence_index = manager.one('I')
        pairs = tuple(manager.unpack('II') for _ in range(manager.count(4096)))
        if identifier != ordinal or sequence_index != ordinal or not reference:
            raise NifError('unsupported ITEM sequence mapping')
        records.append(dict(identifier=identifier, reference=reference,
                            sequence_index=sequence_index, raw_pairs=pairs))
    if manager.one('I') != 0:
        raise NifError('unsupported ITEM manager suffix')
    manager.finish()
    clips = tuple(typed_ref(r, doc, ('NiControllerSequence',)) for _ in range(r.count(4096)))
    r.finish()
    if not clips or len(clips) != len(records) or len(set(clips)) != len(clips):
        raise NifError('invalid ITEM embedded sequence table')
    for record in records:
        if any(target >= len(records) or value != 5 for target, value in record['raw_pairs']):
            raise NifError('unsupported ITEM manager pair')
    return dict(root=root, manager_size=size, model_reference=model_reference,
                target_name=target_name, raw_parameters=parameters,
                sequences=records, clips=clips,
                interpretation='embedded clip references; manager transition semantics not implemented')


def subtree(nodes, root):
    result, pending = {}, [root]
    while pending:
        index = pending.pop()
        if index in result:
            raise NifError('repeated container scene node')
        if index not in nodes:
            raise NifError('missing container scene node')
        result[index] = nodes[index]
        pending.extend(c for c in nodes[index]['children'] if c != -1)
    return result
