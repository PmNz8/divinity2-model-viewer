"""Scene assembly for explicit component selection and dependency inspection."""
from dataclasses import dataclass
from . import scene
from .nif import parse, geometry, NifError


@dataclass
class Model:
    document: object
    nodes: dict
    parents: dict
    world: dict
    components: dict
    texture_references: dict


def load_model(payload):
    doc = parse(payload)
    nodes = {b.index: scene.node(doc, b.index) for b in doc.blocks if b.type in ('NiNode', 'NiTriShape', 'NiLODNode')}
    parents, world = scene.hierarchy(nodes)
    textures = {b.index: scene.source_texture(doc, b.index) for b in doc.blocks if b.type == 'NiSourceTexture'}
    components = {}
    for index, node in nodes.items():
        if node['type'] != 'NiTriShape':
            continue
        if node['data'] == -1:
            raise NifError('shape has no geometry')
        geo = geometry(doc, node['data'])
        if not geo['vertices'] or not geo['triangles']:
            raise NifError('shape has no displayable geometry')
        chain, current = [], index
        while True:
            chain.append(current)
            if current not in parents:
                break
            current = parents[current]
        properties = {}
        for ancestor in reversed(chain):
            local = set()
            for prop in nodes[ancestor]['properties']:
                if prop == -1:
                    continue
                kind = doc.blocks[prop].type
                if kind in local:
                    raise NifError('ambiguous duplicate property class')
                local.add(kind)
                properties[kind] = prop
        material = scene.material(doc, properties['NiMaterialProperty']) if 'NiMaterialProperty' in properties else None
        texturing = scene.texturing(doc, properties['NiTexturingProperty']) if 'NiTexturingProperty' in properties else None
        warnings = list(geo['warnings'])
        warnings += ['preview does not implement property: ' + p for p in properties
                     if p not in ('NiMaterialProperty', 'NiTexturingProperty')]
        if geo['colors']:
            warnings.append('vertex colors preserved; preview currently uses material/base texture only')
        if texturing and any(k != 'base' for k in texturing['slots']):
            warnings.append('non-base texture slots preserved, not shaded')
        components[index] = dict(block=index, name=node['name'], geometry=geo, material=material,
                                 texturing=texturing, skin=node['skin'], warnings=warnings)
    return Model(doc, nodes, parents, world, components, textures)


def render_component(model, index, images=None):
    """One explicit component; no claim that block order identifies an LOD."""
    c = model.components[index]
    geo = c['geometry']
    vertices = geo['vertices']
    if c['skin'] == -1:
        vertices = tuple(scene.point(model.world[index], v) for v in vertices)
    material = c['material']
    out = dict(vertices=vertices, triangles=geo['triangles'], color=(1., 1., 1., 1.), warnings=list(c['warnings']))
    out['warnings']=[w.replace('non-base texture slots preserved, not shaded',
                     'Base and supported normal slots can be previewed; other texture roles remain unshaded') for w in out['warnings']]
    if material:
        out['color'] = (*material['diffuse'], material['alpha'])
    texturing = c['texturing']
    base = texturing['slots'].get('base') if texturing else None
    if base:
        flags = base['flags']
        uv_index, filtering, clamp = flags & 255, (flags >> 8) & 15, (flags >> 12) & 3
        if uv_index >= len(geo['uv_sets']):
            raise NifError('base texture references absent UV set')
        if 'translation' in base:
            out['warnings'].append('UV transform preserved but unsupported for textured preview')
        elif images and base['source'] in images:
            out.update(image=images[base['source']], uv=geo['uv_sets'][uv_index], clamp=clamp)
            if filtering not in (0, 1):
                out['warnings'].append('preview uses bilinear base level; native filter/mips preserved')
            out['filter'] = 'nearest' if filtering == 0 else 'linear'
        else:
            out['warnings'].append('base texture unresolved: select a source explicitly')
    normal=texturing['slots'].get('normal') if texturing else None
    if normal:
        uv_index=normal['flags']&255
        if uv_index>=len(geo['uv_sets']): raise NifError('normal map references absent UV set')
        if 'translation' in normal:
            out['warnings'].append('Normal-map UV transform unsupported; normal preview disabled')
        elif images and normal['source'] in images:
            out.update(normal_image=images[normal['source']],normal_uv=geo['uv_sets'][uv_index],
                       normal_clamp=(normal['flags']>>12)&3,normal_filter='nearest' if (normal['flags']>>8)&15==0 else 'linear')
            out['warnings'].append('Normal preview: AUTO channel selection is heuristic; Y convention is user-selectable, not game-certified')
    return out


@dataclass(frozen=True)
class RGBAImage:
    size: tuple[int, int]
    pixels: bytes

    def tobytes(self):
        return self.pixels


def decode_image(payload):
    from tools.texture_codec.nif_texture import parse_texture_resource, decode_texture_mip
    resource = parse_texture_resource(payload)
    mip = resource.mips[0]
    return RGBAImage((mip.width, mip.height), decode_texture_mip(resource))
