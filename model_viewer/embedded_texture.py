"""Embedded renderer blocks via the unchanged strict standalone texture codec.

The temporary one-block envelope is an in-memory codec adapter, never a new
external resource or an inference from a texture filename.
"""
import struct
from tools.texture_codec.nif_texture import parse_texture_resource, serialize_texture_resource
from .nif import parse, NifError
from . import scene


def wrapper(body):
    kind=b'NiPersistentSrcTextureRendererData'
    return (b'Gamebryo File Format, Version 20.3.0.9\n'
            +struct.pack('<IBIIHI',0x14030009,1,0x30000,1,1,len(kind))+kind
            +struct.pack('<H4I',0,len(body),0,0,0)+body+struct.pack('<Ii',1,0))


def resource(payload, source_block):
    doc=parse(payload)
    if not 0<=source_block<len(doc.blocks) or doc.blocks[source_block].type!='NiSourceTexture':
        raise NifError('Expected embedded NiSourceTexture owner')
    ref=scene.source_texture(doc,source_block)
    target=ref['pixel_data']
    if ref['external'] or target<0 or doc.blocks[target].type!='NiPersistentSrcTextureRendererData':
        raise NifError('Source does not own a supported embedded renderer block')
    return target,parse_texture_resource(wrapper(doc.body(target)))


def validate_body(original,current):
    old=parse_texture_resource(wrapper(original))
    new=parse_texture_resource(wrapper(current))
    rebuilt=serialize_texture_resource(old,{m.index:new.mip_bytes(m.index) for m in new.mips})
    if rebuilt!=wrapper(current):
        raise NifError('Embedded texture changed protected layout/descriptor')


def edit(payload,source_block,rgba,size,*,profile):
    from .texture_editing import edit_texture
    from .animation_editing import append_blocks
    target,_=resource(payload,source_block)
    raw=wrapper(parse(payload).body(target))
    changed=edit_texture(raw,rgba,size,profile=profile)
    if changed==raw:
        return payload
    new=parse(changed).body(0)
    validate_body(parse(raw).body(0),new)
    return append_blocks(payload,{target:new},[])
