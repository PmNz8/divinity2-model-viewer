"""Fixed-topology native edits. Exact fields only; opaque blocks stay untouched."""
import math
import struct
from .nif import parse, geometry, Reader, NifError
from . import scene


def flatten(rows):
    return [v for row in rows for v in row]


def vectors(values,count,width):
    if len(values) != count or any(len(row) != width for row in values):
        raise NifError('fixed topology/array shape required')
    if any(not math.isfinite(v) or abs(v)>1e12 for row in values for v in row):
        raise NifError('nonfinite/excessive edited value')
    return tuple(tuple(float(v) for v in row) for row in values)


def bounds(points):
    if not points:
        raise NifError('cannot bound empty point set')
    low=tuple(min(p[i] for p in points) for i in range(3))
    high=tuple(max(p[i] for p in points) for i in range(3))
    center=tuple((a+b)*.5 for a,b in zip(low,high))
    radius=max(math.sqrt(sum((v-c)**2 for v,c in zip(p,center))) for p in points)
    # Avoid rounding down a float32 culling sphere.
    return (*center,radius*(1+1e-6)+1e-5), (low,high)


def skin_partition(doc,index,vertex_count,bone_count):
    if doc.blocks[index].type != 'NiSkinPartition':
        raise NifError('unsupported partition type')
    r=Reader(doc.body(index)); parts=[]
    for _ in range(r.count(4096)):
        nv,nt,nb,ns,nw=r.unpack('5H')
        if not 0<nv<=vertex_count or not 0<nb<=bone_count or not 0<nw<=8 or ns:
            raise NifError('unsupported partition dimensions/strips')
        bones=r.unpack(f'{nb}H')
        if any(b>=bone_count for b in bones) or len(set(bones))!=nb:
            raise NifError('invalid partition bone palette')
        if not r.flag(): raise NifError('partition vertex map required')
        vertex_map=r.unpack(f'{nv}H')
        if any(v>=vertex_count for v in vertex_map) or len(set(vertex_map))!=nv:
            raise NifError('invalid partition vertex map')
        if not r.flag(): raise NifError('partition weights required')
        weight_offset=r.pos; weights=r.vectors(nv,nw)
        if any(w<0 or w>1 for row in weights for w in row): raise NifError('invalid partition weights')
        if not r.flag(): raise NifError('partition faces required')
        triangles=tuple(r.unpack('3H') for _ in range(nt))
        if any(v>=nv for t in triangles for v in t): raise NifError('partition face outside map')
        if not r.flag(): raise NifError('partition bone indices required')
        indices=tuple(r.unpack(f'{nw}B') for _ in range(nv))
        if any(v>=nb for row in indices for v in row): raise NifError('partition bone index outside palette')
        parts.append(dict(bones=bones,vertex_map=vertex_map,weights=weights,indices=indices,
                          weight_offset=doc.blocks[index].start+weight_offset,
                          triangles=tuple(tuple(vertex_map[v] for v in t) for t in triangles)))
    r.finish()
    return parts


def geometry_spans(doc,index):
    geo=geometry(doc,index); r=Reader(doc.body(index)); spans={}
    _,nv,_,_=r.unpack('iHBB')
    def field(name,count,width):
        start=r.pos; r.vectors(count,width); spans[name]=(doc.blocks[index].start+start,count,width)
    if r.flag(): field('vertices',nv,3)
    flags=r.one('H')
    if r.flag():
        field('normals',nv,3)
        if flags&4096:
            field('tangents',nv,3); field('bitangents',nv,3)
    if r.flag(): field('div2',nv,1)
    field('sphere',1,4); r.one('H'); field('aabb',2,3)
    if r.flag(): field('colors',nv,4)
    for i in range(flags&63): field('uv'+str(i),nv,2)
    return geo,spans


def normal_tangents(vertices,triangles,uv,*,normals=None,orthogonal_fallback=False):
    # Smooth within existing vertex identities, never weld/split topology.
    ns=[[0.,0.,0.] for _ in vertices]; ts=[[0.,0.,0.] for _ in vertices]; bs=[[0.,0.,0.] for _ in vertices]
    def sub(a,b): return tuple(x-y for x,y in zip(a,b))
    def cross(a,b): return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
    def unit(a):
        length=math.sqrt(sum(x*x for x in a))
        return tuple(x/length for x in a) if length>1e-15 else (0.,0.,1.)
    for a,b,c in triangles:
        e1,e2=sub(vertices[b],vertices[a]),sub(vertices[c],vertices[a]); n=cross(e1,e2)
        t,bt=(0.,0.,0.),(0.,0.,0.)
        if uv:
            u1,u2=sub(uv[b],uv[a]),sub(uv[c],uv[a]); det=u1[0]*u2[1]-u1[1]*u2[0]
            if abs(det)>1e-15:
                t=tuple((x*u2[1]-y*u1[1])/det for x,y in zip(e1,e2))
                bt=tuple((y*u1[0]-x*u2[0])/det for x,y in zip(e1,e2))
        for v in (a,b,c):
            for target,value in ((ns,n),(ts,t),(bs,bt)):
                for axis in range(3): target[v][axis]+=value[axis]
    normal=[unit(n) for n in ns] if normals is None else normals
    tangent=[]; bitangent=[]
    for n,t,b in zip(normal,ts,bs):
        dot=sum(x*y for x,y in zip(n,t))
        if orthogonal_fallback:
            nn=sum(x*x for x in n)
            projected=tuple(x-dot*y/nn for x,y in zip(t,n))
            if sum(x*x for x in projected)<=1e-30:
                axis=min(range(3),key=lambda k:abs(n[k]))
                projected=tuple(float(k==axis)-n[axis]*n[k]/nn for k in range(3))
            t=unit(projected)
        else:
            t=unit(tuple(x-dot*y for x,y in zip(t,n)))
        bt=cross(n,t); sign=-1 if sum(x*y for x,y in zip(bt,b))<0 else 1
        tangent.append(t); bitangent.append(tuple(sign*x for x in bt))
    return normal,tangent,bitangent


def edit_geometry(payload,changes):
    """Changes keyed by NiTriShape index; arrays retain exact sizes/identities."""
    doc=parse(payload); out=bytearray(payload); spans_written=[]
    def write(offset,rows,count,width):
        rows=vectors(rows,count,width); data=struct.pack('<'+str(count*width)+'f',*flatten(rows))
        if out[offset:offset+len(data)] != data:
            out[offset:offset+len(data)]=data; spans_written.append((offset,offset+len(data)))
    seen_data=set()
    for index,change in changes.items():
        node=scene.node(doc,index)
        if node['type']!='NiTriShape' or node['data'] in seen_data:
            raise NifError('geometry must have unambiguous shape ownership')
        seen_data.add(node['data']); geo,spans=geometry_spans(doc,node['data'])
        if (geo['additional_data']!=-1 or geo['div2_floats'] or geo['aabb_corners'] not in (0,2)
                or (geo['aabb_corners']==0 and any(v for row in geo['aabb'] for v in row))):
            raise NifError('unsupported derived geometry layout for editing')
        if set(change)-{'vertices','uv_sets','colors'}:
            raise NifError('unsupported geometry edit field')
        vertices=vectors(change.get('vertices',geo['vertices']),len(geo['vertices']),3)
        uv=change.get('uv_sets',geo['uv_sets'])
        if len(uv)!=len(geo['uv_sets']): raise NifError('UV layer count changed')
        uv=tuple(vectors(layer,len(vertices),2) for layer in uv)
        position_changed=vertices!=geo['vertices']; uv_changed=uv!=geo['uv_sets']
        changed_vertices={i for i,(a,b) in enumerate(zip(vertices,geo['vertices'])) if a!=b}
        changed_uv={i for new,old in zip(uv,geo['uv_sets']) for i,(a,b) in enumerate(zip(new,old)) if a!=b}
        write(spans['vertices'][0],vertices,len(vertices),3)
        for i,layer in enumerate(uv): write(spans['uv'+str(i)][0],layer,len(vertices),2)
        if 'colors' in change:
            if 'colors' not in spans: raise NifError('cannot add native color array')
            write(spans['colors'][0],change['colors'],len(vertices),4)
        if position_changed or uv_changed:
            normal,tangent,bitangent=normal_tangents(vertices,geo['triangles'],uv[0] if uv else None)
            for key,value in (('normals',normal),('tangents',tangent),('bitangents',bitangent)):
                if key in spans and (position_changed or key!='normals'):
                    targets=changed_vertices if key=='normals' else changed_vertices|changed_uv
                    affected={v for triangle in geo['triangles'] if targets.intersection(triangle) for v in triangle}
                    merged=[value[i] if i in affected else old for i,old in enumerate(geo[key])]
                    write(spans[key][0],merged,len(vertices),3)
        if position_changed:
            sphere,aabb=bounds(vertices); write(spans['sphere'][0],[sphere],1,4)
            if geo['aabb_corners']==2: write(spans['aabb'][0],aabb,2,3)
            if node['skin']!=-1:
                instance=scene.skin_instance(doc,node['skin']); data=scene.skin_data(doc,instance['data'])
                if instance['partition']!=-1:
                    skin_partition(doc,instance['partition'],len(vertices),len(instance['bones']))
                r=Reader(doc.body(instance['data'])); scene.transform(r); r.count(4096); has_weights=r.flag()
                if not has_weights: raise NifError('skin edit needs explicit weights')
                for bone in data['bones']:
                    scene.transform(r); offset=doc.blocks[instance['data']].start+r.pos
                    r.vectors(1,4); corners=r.one('H'); original_aabb=r.vectors(2,3)
                    if corners not in (0,2) or (corners==0 and any(v for row in original_aabb for v in row)):
                        raise NifError('unsupported bone bounds layout')
                    count=r.one('H'); r.read(count*6)
                    points=[scene.point(scene.matrix(bone['transform']),vertices[v]) for v,w in bone['weights'] if w>0]
                    if points and any(v in changed_vertices and w>0 for v,w in bone['weights']):
                        sphere,aabb=bounds(points); write(offset,[sphere],1,4)
                        if corners==2: write(offset+18,aabb,2,3)
                r.finish()
    result=bytes(out)
    # Independent structural reparse and byte-range guard.
    reparsed=parse(result)
    for index in changes: geometry(reparsed,scene.node(reparsed,index)['data'])
    position=0
    for start,end in sorted(spans_written):
        if payload[position:start]!=result[position:start]: raise NifError('non-target bytes changed')
        position=max(position,end)
    if payload[position:]!=result[position:]: raise NifError('non-target tail changed')
    return result,spans_written


def edit_materials(payload,changes):
    doc=parse(payload); out=bytearray(payload)
    for index,change in changes.items():
        source=scene.material(doc,index)
        if set(change)-{'ambient','diffuse','specular','emissive','glossiness','alpha'}:
            raise NifError('unsupported material field')
        r=Reader(doc.body(index)); scene.net(r,doc); offset=doc.blocks[index].start+r.pos
        values=[]
        for key in ('ambient','diffuse','specular','emissive'):
            row=vectors([change.get(key,source[key])],1,3)[0]
            if any(v<0 or v>1 for v in row): raise NifError('material color outside [0,1]')
            values.extend(row)
        gloss,alpha=change.get('glossiness',source['glossiness']),change.get('alpha',source['alpha'])
        if not math.isfinite(gloss) or not 0<=gloss<=1e6 or not math.isfinite(alpha) or not 0<=alpha<=1:
            raise NifError('invalid material gloss/alpha')
        out[offset:offset+56]=struct.pack('<14f',*values,gloss,alpha)
    checked=parse(bytes(out))
    for index in changes: scene.material(checked,index)
    return bytes(out)


def edit_weights(payload,changes):
    """Existing influence memberships only; mirror CPU/hardware weight arrays."""
    doc=parse(payload); out=bytearray(payload); written_data=set()
    for shape,new in changes.items():
        node=scene.node(doc,shape); instance=scene.skin_instance(doc,node['skin'])
        if instance['data'] in written_data: raise NifError('shared skin data edits unsupported')
        written_data.add(instance['data'])
        data=scene.skin_data(doc,instance['data']); geo=geometry(doc,node['data'])
        if not data['has_weights'] or set(new)!=set(range(len(data['bones']))):
            raise NifError('skin bone membership changed')
        old=[dict(bone['weights']) for bone in data['bones']]
        sums=[0.]*len(geo['vertices'])
        for i,bone in enumerate(old):
            if set(new[i])!=set(bone): raise NifError('adding/removing influence entries unsupported')
            for vertex,weight in new[i].items():
                if not math.isfinite(weight) or not 0<=weight<=1: raise NifError('invalid weight')
                sums[vertex]+=weight
        if any(abs(v-1)>1e-4 for v in sums): raise NifError('weights must sum to one per vertex')
        if instance['partition']!=-1:
            parts=skin_partition(doc,instance['partition'],len(sums),len(old))
            for part in parts:
                offset=part['weight_offset']; width=len(part['indices'][0]); values=[]
                for vertex,indices,weights in zip(part['vertex_map'],part['indices'],part['weights']):
                    bone_ids=[part['bones'][i] for i in indices]
                    represented={i:sum(w for b,w in zip(bone_ids,weights) if b==i) for i in bone_ids}
                    if any(abs(represented.get(i,0)-bone.get(vertex,0))>1e-4 for i,bone in enumerate(old)):
                        raise NifError('CPU/hardware skin weights disagree')
                    if any(bone.get(vertex,0)>0 and i not in represented for i,bone in new.items()):
                        raise NifError('new weight needs a different hardware palette')
                    used=set()
                    for i in bone_ids:
                        values.append(0. if i in used else new[i].get(vertex,0.)); used.add(i)
                out[offset:offset+len(values)*4]=struct.pack('<'+str(len(values))+'f',*values)
        r=Reader(doc.body(instance['data'])); scene.transform(r); r.count(4096); r.flag()
        for i,bone in enumerate(data['bones']):
            r.read(52); bounds_offset=doc.blocks[instance['data']].start+r.pos
            r.read(16); corners=r.one('H'); r.read(24); count=r.one('H')
            if {v for v,w in bone['weights'] if w>0}!={v for v,w in new[i].items() if w>0}:
                points=[scene.point(scene.matrix(bone['transform']),geo['vertices'][v]) for v,w in new[i].items() if w>0]
                if points:
                    sphere,aabb=bounds(points); struct.pack_into('<4f',out,bounds_offset,*sphere)
                    if corners==2: struct.pack_into('<6f',out,bounds_offset+18,*flatten(aabb))
                    elif corners!=0: raise NifError('unsupported edited bone bounds')
            for _ in range(count):
                vertex=r.one('H'); offset=doc.blocks[instance['data']].start+r.pos; r.one('f')
                struct.pack_into('<f',out,offset,new[i][vertex])
        r.finish()
    checked=parse(bytes(out))
    for shape in changes:
        instance=scene.skin_instance(checked,scene.node(checked,shape)['skin']); scene.skin_data(checked,instance['data'])
    return bytes(out)


def validate_native_edit(original,current):
    from .normalization import normalize
    baseline,rules=normalize(original)
    if rules:
        try:
            _validate_native_edit(baseline,current)
            return rules
        except NifError:
            pass
    try:
        _validate_native_edit(original,current)
    except NifError as fixed_error:
        from .item_editing import validate_item
        try: return validate_item(original,current)
        except (NifError,ValueError,KeyError,IndexError,struct.error): raise fixed_error
    return []


def _validate_native_edit(original,current):
    """Independently enforce v2 lineage boundaries, not just current-file hashes."""
    if original==current: return
    old,new=parse(original),parse(current)
    if (len(old.roots)==1 and old.blocks[old.roots[0]].type in
            ('MdlMan::CModelTemplateDataEntry','CStreamableAssetData') and
            (len(old.blocks)!=len(new.blocks) or any(
                b.type=='NiControllerSequence' and old.body(b.index)!=new.body(b.index)
                for b in old.blocks))):
        # Validate combined container edits as two independently bounded edits:
        # fixed-layout geometry/material/skin, then owned animation appends.
        from .animation_editing import append_blocks, validate_clip_edit
        if len(new.blocks)<len(old.blocks) or any(new.blocks[b.index].type!=b.type for b in old.blocks):
            raise NifError('original container blocks removed/retyped')
        sequences={b.index:new.body(b.index) for b in old.blocks if b.type=='NiControllerSequence'}
        other={b.index:new.body(b.index) for b in old.blocks if b.type!='NiControllerSequence'}
        additions=[(b.type,new.body(b.index)) for b in new.blocks[len(old.blocks):]]
        geometry_only=append_blocks(original,other,[])
        validate_native_edit(original,geometry_only)
        animation_only=append_blocks(original,sequences,additions)
        validate_clip_edit(original,animation_only)
        if append_blocks(geometry_only,sequences,additions)!=current:
            raise NifError('combined container changed protected envelope')
        return
    if old.roots and all(old.blocks[i].type=='NiControllerSequence' for i in old.roots):
        from .animation_editing import validate_clip_edit
        validate_clip_edit(original,current); return
    if len(old.blocks)==1 and old.blocks[0].type=='NiPersistentSrcTextureRendererData':
        from tools.texture_codec.nif_texture import parse_texture_resource,serialize_texture_resource
        texture=parse_texture_resource(original)
        result=serialize_texture_resource(texture,{m.index:current[m.absolute_offset:m.end_offset] for m in texture.mips})
        if result!=current: raise NifError('edited texture changed bytes outside existing mip spans')
        return
    if len(original)!=len(current) or old.blocks!=new.blocks or old.roots!=new.roots:
        raise NifError('fixed-topology resource envelope/block layout changed')
    shapes={b.index:scene.node(old,b.index) for b in old.blocks if b.type=='NiTriShape'}
    spans=[]
    def add(offset,size): spans.append((offset,offset+size))
    for block in old.blocks:
        if old.body(block.index)==new.body(block.index): continue
        if block.type in ('NiFloatExtraData','NiBooleanExtraData','NiColorExtraData'):
            from .item_parameters import validate_block
            validate_block(original,current,block.index)
            add(block.start+4,block.end-block.start-4)
        elif block.type=='NiPersistentSrcTextureRendererData':
            from .embedded_texture import resource,validate_body
            owners=[b.index for b in old.blocks if b.type=='NiSourceTexture'
                    and scene.source_texture(old,b.index)['pixel_data']==block.index]
            if not owners: raise NifError('Unowned embedded texture edit')
            for owner in owners: resource(original,owner)
            validate_body(old.body(block.index),new.body(block.index))
            add(block.start,block.end-block.start)
        elif block.type=='NiTriShapeData':
            geo,fields=geometry_spans(old,block.index)
            if geo['additional_data']!=-1 or geo['div2_floats'] or geo['aabb_corners'] not in (0,2):
                raise NifError('unsupported edited geometry layout')
            for name,(offset,count,width) in fields.items():
                if name=='div2' or (name=='aabb' and geo['aabb_corners']==0): continue
                add(offset,count*width*4)
            geometry(new,block.index)
        elif block.type=='NiMaterialProperty':
            scene.material(new,block.index); r=Reader(old.body(block.index)); scene.net(r,old); add(block.start+r.pos,56)
        elif block.type=='NiSkinData':
            data=scene.skin_data(old,block.index); scene.skin_data(new,block.index)
            r=Reader(old.body(block.index)); r.read(52); r.count(4096); has_weights=r.flag()
            if not has_weights: raise NifError('edited skin has no explicit weights')
            for bone in data['bones']:
                r.read(52); add(block.start+r.pos,16); r.read(16); corners=r.one('H')
                if corners==2: add(block.start+r.pos,24)
                elif corners!=0: raise NifError('unsupported skin bounds')
                r.read(24); count=r.one('H')
                for _ in range(count): r.read(2); add(block.start+r.pos,4); r.read(4)
            r.finish()
        elif block.type=='NiSkinPartition':
            owners=[]
            for shape in shapes.values():
                if shape['skin']!=-1:
                    instance=scene.skin_instance(old,shape['skin'])
                    if instance['partition']==block.index: owners.append((shape,instance))
            if len(owners)!=1: raise NifError('ambiguous partition ownership')
            shape,instance=owners[0]; count=len(geometry(old,shape['data'])['vertices'])
            parts=skin_partition(old,block.index,count,len(instance['bones']))
            skin_partition(new,block.index,count,len(instance['bones']))
            for part in parts: add(part['weight_offset'],len(part['weights'])*len(part['weights'][0])*4)
        else:
            raise NifError('unsupported edited native block: '+block.type)
    position=0
    for start,end in sorted(spans):
        if original[position:start]!=current[position:start]: raise NifError('edited resource changed protected bytes')
        position=max(position,end)
    if original[position:]!=current[position:]: raise NifError('edited resource changed protected tail')
