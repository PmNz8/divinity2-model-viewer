"""Recognized static ITEM topology edits; conservative bounds working policy.

No new block identities, materials or hierarchy. Preserve all unedited data.
MaxBound sphere interpretation and position matches are provisional, explicit
authoring rules, not certified runtime semantics.
"""
import struct
from . import scene,containers
from .nif import parse,Reader,NifError,geometry
from .assets import load_model
from .editing import bounds
from .item_geometry import geometry_body
from .animation_editing import append_blocks

RULE='static-item-topology-position-matches-conservative-bounds/1'


def layout(payload):
    model=load_model(payload); doc=model.document
    container=containers.item(doc)
    if container.get('clips') or not model.components or any(c['skin']!=-1 for c in model.components.values()):
        raise NifError('Static unskinned ITEM required')
    if set(containers.subtree(model.nodes,container['root']))!=set(model.nodes):
        raise NifError('Unowned ITEM scene nodes')
    if any(n['controller']!=-1 for n in model.nodes.values()):
        raise NifError('Controlled scene nodes unsupported for static topology')
    owners={}
    for i,n in model.nodes.items():
        if n['type']=='NiTriShape': owners.setdefault(n['data'],[]).append(i)
    if any(len(v)!=1 for v in owners.values()): raise NifError('Shared geometry requires explicit ownership handling')
    maxbounds=[]
    for b in doc.blocks:
        if b.type=='NiFloatsExtraData':
            r=Reader(doc.body(b.index)); name=scene.name(r,doc)
            if name=='MaxBound':
                if b.index not in model.nodes[container['root']]['extra'] or r.count()!=10:
                    raise NifError('Unsupported MaxBound owner/layout')
                r.vectors(10,1); r.finish(); maxbounds.append(b.index)
    if len(maxbounds)!=1: raise NifError('One recognized root MaxBound required')
    return model,container,owners,maxbounds[0]


def maxbound_body(payload):
    model,container,_,index=layout(payload)
    # All LOD branches, in root-local coordinates. Conservatively includes every
    # manually edited variant instead of leaving another LOD outside bounds.
    nodes={i:dict(n) for i,n in model.nodes.items()}
    nodes[container['root']]['transform']=dict(translation=(0,0,0),rotation=((1,0,0),(0,1,0),(0,0,1)),scale=1)
    _,world=scene.hierarchy(nodes)
    points=[scene.point(world[i],v) for i,c in model.components.items() for v in c['geometry']['vertices']]
    sphere,aabb=bounds(points)
    values=(*sphere,*aabb[0],*aabb[1])
    return index,model.document.body(index)[:8]+struct.pack('<10f',*values)


def edit_item(payload,changes):
    model,_,owners,_=layout(payload); replacements={}
    if not changes:return payload
    for shape,change in changes.items():
        if shape not in model.components: raise NifError('Unknown ITEM component')
        allowed={'vertices','triangles','uv_sets','colors','normals'}
        if set(change)-allowed: raise NifError('Unsupported topology edit field')
        data=model.nodes[shape]['data']; g=model.components[shape]['geometry']
        replacements[data]=geometry_body(g,change['vertices'],change['triangles'],change['uv_sets'],
                                         colors=change.get('colors'),normals=change.get('normals'))
    changed=append_blocks(payload,replacements,[])
    index,body=maxbound_body(changed)
    return append_blocks(changed,{index:body},[])


def validate_item(original,current):
    old_model,_,owners,bound=layout(original); old=old_model.document; new=parse(current)
    if len(old.blocks)!=len(new.blocks) or any(a.type!=b.type for a,b in zip(old.blocks,new.blocks)):
        raise NifError('ITEM blocks removed/added/retyped')
    # Envelope reconstructed from original must be exact, including string,
    # footer, group and type tables (offsets/sizes may change).
    if append_blocks(original,{b.index:new.body(b.index) for b in new.blocks},[])!=current:
        raise NifError('ITEM protected envelope changed')
    changed=[i for i in owners if old.body(i)!=new.body(i)]
    if not changed: raise NifError('No geometry change for topology policy')
    for i in changed:
        g=geometry(old,i); actual=geometry(new,i)
        expected=geometry_body(g,actual['vertices'],actual['triangles'],actual['uv_sets'],
                               colors=actual['colors'] if g['colors'] else None,
                               normals=actual['normals'] if g['normals'] else None)
        if expected!=new.body(i): raise NifError('Topology derived fields or protected flags differ')
    index,body=maxbound_body(current)
    if index!=bound or new.body(bound)!=body: raise NifError('ITEM MaxBound does not match current geometry')
    # Other permitted edits use existing fixed-layout validator after restoring
    # only the independently validated geometry and derived bound blocks.
    rest=append_blocks(current,{i:old.body(i) for i in (*changed,bound)},[])
    from .editing import _validate_native_edit
    _validate_native_edit(original,rest)
    return [RULE]
