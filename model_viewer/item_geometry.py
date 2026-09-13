"""Bounded variable-topology geometry writer for recognized static ITEM edits.

Position-match rebuilding is an explicit provisional rule, not a claim about
all engine uses of match groups. Ownership/lineage guards live in item_editing.
"""
from collections import defaultdict
import struct
from .nif import geometry,parse,NifError
from .editing import vectors,bounds,normal_tangents
from .animation_editing import append_blocks


def position_matches(vertices):
    buckets=defaultdict(list)
    for i,v in enumerate(vertices): buckets[tuple(v)].append(i)
    if sum(len(b)*(len(b)-1) for b in buckets.values())>2_000_000:
        raise NifError('Position-match table exceeds bounded budget')
    return tuple(tuple(j for j in buckets[tuple(v)] if i!=j) for i,v in enumerate(vertices))


def geometry_body(template,vertices,triangles,uv_sets,*,normals=None,colors=None):
    """Retain known layout settings; rebuild arrays, bounds and match indices."""
    g=template
    if g['additional_data']!=-1 or g['div2_floats'] or g['aabb_corners'] not in (0,2):
        raise NifError('Unsupported variable-topology geometry layout')
    if not 3<=len(vertices)<=65535 or not 1<=len(triangles)<=65535:
        raise NifError('Geometry exceeds native uint16 vertex/triangle limits')
    vertices=vectors(vertices,len(vertices),3)
    vertices=tuple(struct.unpack('<3f',struct.pack('<3f',*v)) for v in vertices)
    triangles=tuple(tuple(t) for t in triangles)
    if any(len(t)!=3 or len(set(t))!=3 or any(type(i)!=int or not 0<=i<len(vertices) for i in t) for t in triangles):
        raise NifError('Invalid triangle indices')
    if len(uv_sets)!=len(g['uv_sets']): raise NifError('Retain template UV layer count')
    uv=tuple(vectors(layer,len(vertices),2) for layer in uv_sets)
    uv=tuple(tuple(struct.unpack('<2f',struct.pack('<2f',*v)) for v in layer) for layer in uv)
    ns=vectors(normals,len(vertices),3) if normals is not None else normal_tangents(vertices,triangles,uv[0] if uv else ())[0]
    ns=tuple(struct.unpack('<3f',struct.pack('<3f',*v)) for v in ns)
    if any(abs(sum(x*x for x in v)-1)>1e-4 for v in ns): raise NifError('Unit normals required')
    computed,tangents,bitangents=normal_tangents(vertices,triangles,uv[0] if uv else (),normals=ns,orthogonal_fallback=True)
    ns=computed
    if bool(g['colors'])!=(colors is not None): raise NifError('Retain template color layout')
    cs=vectors(colors,len(vertices),4) if colors is not None else ()
    sphere,aabb=bounds(vertices)
    if g['aabb_corners']==0:
        if any(v for row in g['aabb'] for v in row): raise NifError('Unsupported inactive AABB data')
        aabb=g['aabb']
    matches=position_matches(vertices) if g['match_groups'] else ()
    out=bytearray()
    def pack(fmt,*v): out.extend(struct.pack('<'+fmt,*v))
    def rows(values):
        flat=[x for row in values for x in row]
        pack(str(len(flat))+'f',*flat)
    pack('iHBB',g['group_id'],len(vertices),g['keep_flags'],g['compress_flags'])
    pack('B',1); rows(vertices); pack('HB',g['flags'],bool(g['normals']))
    if g['normals']:
        rows(ns)
        if g['tangents']: rows(tangents); rows(bitangents)
    pack('B',0); rows([sphere]); pack('H',g['aabb_corners']); rows(aabb)
    pack('B',bool(cs))
    if cs: rows(cs)
    for layer in uv: rows(layer)
    pack('HiHIB',g['consistency'],-1,len(triangles),len(triangles)*3,1)
    for t in triangles: pack('3H',*t)
    pack('H',len(matches))
    for row in matches: pack('H',len(row)); pack(str(len(row))+'H',*row)
    return bytes(out)


def replace_geometry(payload,data_block,vertices,triangles,uv_sets,**kwargs):
    doc=parse(payload); g=geometry(doc,data_block)
    body=geometry_body(g,vertices,triangles,uv_sets,**kwargs)
    result=append_blocks(payload,{data_block:body},[])
    check=geometry(parse(result),data_block)
    if len(check['vertices'])!=len(vertices) or check['triangles']!=tuple(map(tuple,triangles)):
        raise NifError('Geometry rewrite readback differs')
    return result
