"""Versioned source-bound normalization. Unknown layouts never gain write support."""
from dataclasses import replace
import hashlib
import struct
from .nif import parse, Reader, NifError

ORIGINAL='4dac08134c9ccb62223e799a68ec4f21a688acac92c96ca82ec087d68c77d492'
RENAMED='4b89ebbf39663ad7c947493a5d6cc906266956277493321658b2628a22bf79db'
NORMALIZED='c81176c66022f1052c98da1cd1aa0eb02282bfdddea6b6153c023a57eb7093a9'


def normalize(raw):
    sha=hashlib.sha256(raw).hexdigest()
    if sha not in (ORIGINAL,RENAMED): return raw, []
    from .editing import geometry_spans
    doc=parse(raw); out=bytearray(raw); rules=[]
    if sha==ORIGINAL:
        for index,name in ((4,'AROOT_HERO_DRAGON'),(9,'AROOT_HERO_DRAGON NonAccum')):
            struct.pack_into('<i',out,doc.blocks[index].start,doc.strings.index(name))
        rules.append('player-dragon-root-names/1')
    _,spans=geometry_spans(doc,245); start,count,width=spans['div2']
    if (count,width)!=(6053,1) or out[start-1]!=1: raise NifError('normalization layout mismatch')
    r=Reader(raw); r.read(len(b'Gamebryo File Format, Version 20.3.0.9\n')); r.read(9)
    blocks=r.count(16384)
    for _ in range(r.one('H')): r.string()
    r.read(blocks*2); size_offset=r.pos+245*4
    struct.pack_into('<I',out,size_offset,len(doc.body(245))-count*4)
    out[start-1]=0; del out[start:start+count*4]
    current=bytes(out)
    if hashlib.sha256(current).hexdigest()!=NORMALIZED: raise NifError('normalization result mismatch')
    rules.append('player-dragon-div2-removal/1')
    return current,rules


def diagnostics(preview):
    if not preview or not preview.model: return [('No model loaded','Open a model')]
    _,rules=normalize(preview.primary.payload)
    rows=[]
    if 'player-dragon-root-names/1' in rules:
        rows.append(('Animation target name mismatch','Align node names with animation targets'))
    has_div2=any(c['geometry']['div2_floats'] for c in preview.model.components.values())
    if has_div2:
        rows.append(('DIV2 table','Remove table' if rules else 'No supported normalization rule'))
    if preview.container and preview.container.get('animation_preview_error') and not rules:
        rows.append(('Animation mismatch','No supported normalization rule'))
    return rows or [('No normalization required','No changes')]


def normalized_preview(preview):
    # Reopen a freshly verified snapshot to preserve all explicit associations
    # and the untouched physical-source provenance without mutating the viewer.
    from .package import open_preview
    from .controller import Preview
    from .replay import PackageCorpus
    copied=open_preview(preview.package())
    raw=copied.primary.payload; current,rules=normalize(raw)
    if not rules: return copied
    sources=dict(copied.corpus.sources); key=copied.primary.logical_path.casefold()
    old=sources[key]
    sources[key]=replace(old,payload=current,original_payload=old.original_payload if old.original_payload is not None else raw)
    result=Preview(PackageCorpus(sources.values())); result.open_model(sources[key])
    result.set_components(list(copied.selected))
    for source,method in ((copied.skeleton_source,result.set_skeleton),(copied.animation_source,result.set_animation)):
        if source and source.logical_path.casefold()!=key: method(sources[source.logical_path.casefold()])
    for block,source in copied.texture_sources.items(): result.set_texture(block,sources[source.logical_path.casefold()])
    return result
