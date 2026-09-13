"""Explicit scene/skin readers for the supported DIV2 NIF envelope.

Schema anchor: niftools/nifxml 292bb940, checked against bounded original
fixtures. No heuristic offsets, implicit LOD selection or native writer.
Matrices are row-major with column-vector multiplication.
"""
import math
from .nif import Reader, NifError


def ref(r, doc):
    value = r.one('i')
    if value != -1 and not 0 <= value < len(doc.blocks):
        raise NifError('invalid block reference')
    return value


def refs(r, doc):
    return tuple(ref(r, doc) for _ in range(r.count(len(doc.blocks))))


def name(r, doc):
    value = r.one('i')
    if value == -1:
        return ''
    if not 0 <= value < len(doc.strings):
        raise NifError('invalid string reference')
    return doc.strings[value]


def net(r, doc):
    return dict(name=name(r, doc), extra=refs(r, doc), controller=ref(r, doc))


def transform(r, av=False):
    if av:
        translation, rotation = r.vectors(1, 3)[0], r.vectors(3, 3)
    else:
        rotation, translation = r.vectors(3, 3), r.vectors(1, 3)[0]
    # Treat the serialized triples as rows for our column-vector transform.
    # Despite nifxml's column-major member description, transposing here
    # contradicts Deer KF quaternion rotations and breaks the skinned preview.
    # See the animation/GPU evidence; do not infer math from field names alone.
    scale = r.vectors(1, 1)[0][0]
    return dict(rotation=rotation, translation=translation, scale=scale)


def matrix(t):
    return tuple(tuple(t['rotation'][i][j] * t['scale'] for j in range(3))
                 + (t['translation'][i],) for i in range(3)) + ((0., 0., 0., 1.),)


IDENTITY = ((1., 0., 0., 0.), (0., 1., 0., 0.), (0., 0., 1., 0.), (0., 0., 0., 1.))


def multiply(a, b):
    result = tuple(tuple(sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)) for i in range(4))
    if not all(math.isfinite(v) for row in result for v in row):
        raise NifError('nonfinite composed transform')
    return result


def point(m, p):
    return tuple(sum(m[i][j] * p[j] for j in range(3)) + m[i][3] for i in range(3))


def node(doc, index):
    kind = doc.blocks[index].type
    if kind not in ('NiNode', 'NiTriShape', 'NiLODNode'):
        raise NifError('unsupported scene node class: ' + kind)
    r = Reader(doc.body(index))
    out = net(r, doc)
    out.update(block=index, type=kind, flags=r.one('H'), transform=transform(r, av=True),
               properties=refs(r, doc), collision=ref(r, doc))
    if kind in ('NiNode', 'NiLODNode'):
        out.update(children=refs(r, doc), effects=refs(r, doc))
        if kind == 'NiLODNode':
            out.update(switch_flags=r.one('H'), active_child=r.one('I'), lod_data=ref(r, doc))
            if out['lod_data'] == -1 or doc.blocks[out['lod_data']].type != 'NiRangeLODData':
                raise NifError('unsupported LOD data class')
    else:
        out.update(data=ref(r, doc), skin=ref(r, doc))
        count = r.count(4096)
        out['materials'] = tuple(name(r, doc) for _ in range(count))
        out['material_extra'] = r.unpack(f'{count}i')
        out['active_material'] = r.one('i')
        out['material_needs_update'] = r.flag()
        out['children'] = ()
    r.finish()
    return out


def hierarchy(nodes):
    """Reject ambiguous parents/cycles, including disconnected cycles."""
    parents = {}
    for index, obj in nodes.items():
        for child in obj['children']:
            if child == -1:
                continue
            if child not in nodes:
                raise NifError('unsupported/missing child scene class')
            if child in parents:
                raise NifError('multiple parent or repeated child')
            parents[child] = index
    world = {}
    for index in nodes:
        chain, seen, current = [], set(), index
        while current not in world:
            if current in seen:
                raise NifError('cyclic scene hierarchy')
            seen.add(current)
            chain.append(current)
            if current not in parents:
                break
            current = parents[current]
        for current in reversed(chain):
            parent = world[parents[current]] if current in parents else IDENTITY
            world[current] = multiply(parent, matrix(nodes[current]['transform']))
    return parents, world


def skin_instance(doc, index):
    if doc.blocks[index].type != 'NiSkinInstance':
        raise NifError('unsupported skin instance')
    r = Reader(doc.body(index))
    out = dict(data=ref(r, doc), partition=ref(r, doc), root=ref(r, doc), bones=refs(r, doc))
    r.finish()
    for key, kind in (('data', 'NiSkinData'), ('partition', 'NiSkinPartition'), ('root', 'NiNode')):
        target = out[key]
        if target == -1 and key == 'partition':
            continue
        if target == -1 or doc.blocks[target].type != kind:
            raise NifError('wrong skin reference type: ' + key)
    if any(b == -1 or doc.blocks[b].type != 'NiNode' for b in out['bones']):
        raise NifError('wrong bone reference type')
    if len(set(out['bones'])) != len(out['bones']):
        raise NifError('duplicate skin bone')
    return out


def skin_data(doc, index):
    if doc.blocks[index].type != 'NiSkinData':
        raise NifError('unsupported skin data')
    r = Reader(doc.body(index))
    out = dict(transform=transform(r))
    count, has_weights = r.count(4096), r.flag()
    bones = []
    for _ in range(count):
        bone = dict(transform=transform(r), sphere=r.vectors(1, 4)[0],
                    aabb_corners=r.one('H'), aabb=r.vectors(2, 3))
        n = r.one('H')
        weights = tuple(r.unpack('Hf') for _ in range(n)) if has_weights else ()
        if any(not math.isfinite(w) or not 0 <= w <= 1 for _, w in weights):
            raise NifError('invalid skin weight')
        if len({i for i, _ in weights}) != len(weights):
            raise NifError('duplicate vertex in bone weights')
        bone.update(declared_vertices=n, weights=weights)
        bones.append(bone)
    r.finish()
    out.update(has_weights=has_weights, bones=tuple(bones))
    return out


def material(doc, index):
    if doc.blocks[index].type != 'NiMaterialProperty':
        raise NifError('unsupported material class')
    r = Reader(doc.body(index))
    out = net(r, doc)
    for key in ('ambient', 'diffuse', 'specular', 'emissive'):
        out[key] = r.vectors(1, 3)[0]
    out['glossiness'], out['alpha'] = r.vectors(1, 2)[0]
    r.finish()
    return out


def source_texture(doc, index):
    if doc.blocks[index].type != 'NiSourceTexture':
        raise NifError('unsupported texture source class')
    r = Reader(doc.body(index))
    out = net(r, doc)
    out.update(external=r.flag(), filename=name(r, doc), pixel_data=ref(r, doc),
               format_preferences=r.unpack('3I'), is_static=r.flag(),
               direct_render=r.flag(), persist_render_data=r.flag())
    r.finish()
    return out


def texturing(doc, index):
    if doc.blocks[index].type != 'NiTexturingProperty':
        raise NifError('unsupported texturing class')
    r = Reader(doc.body(index))
    out = net(r, doc)
    out['flags'] = r.one('H')
    count = r.count(12)
    if count < 5:
        raise NifError('unsupported texture slot count')

    def descriptor():
        d = dict(source=ref(r, doc), flags=r.one('H'))
        if d['source'] != -1 and doc.blocks[d['source']].type != 'NiSourceTexture':
            raise NifError('wrong texture source reference')
        if r.flag():
            d.update(translation=r.vectors(1, 2)[0], scale=r.vectors(1, 2)[0],
                     rotation=r.vectors(1, 1)[0][0], method=r.one('I'), center=r.vectors(1, 2)[0])
        return d

    slots = {}
    for slot in ('base', 'dark', 'detail', 'gloss', 'glow', 'bump', 'normal', 'parallax',
                 'decal0', 'decal1', 'decal2', 'decal3')[:count]:
        if r.flag():
            d = descriptor()
            if slot == 'bump':
                d['luma_and_matrix'] = r.vectors(1, 6)[0]
            elif slot == 'parallax':
                d['offset'] = r.vectors(1, 1)[0][0]
            slots[slot] = d
    shaders = []
    for _ in range(r.count(4096)):
        d = descriptor() if r.flag() else None
        if d is not None:
            d['map_id'] = r.one('I')
        shaders.append(d)
    out.update(slots=slots, shader_textures=tuple(shaders))
    r.finish()
    return out
