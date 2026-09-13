"""Guarded same-target, same-duration KF motion baking; old block IDs retained."""
import math
import struct
from .nif import Reader,parse,NifError
from . import scene,animation


def pack(fmt,*values): return struct.pack('<'+fmt,*values)


def editable_roots(doc):
    """Explicit sequence ownership; never infer roots from block order."""
    from . import containers
    kind=doc.blocks[doc.roots[0]].type if len(doc.roots)==1 else ''
    if kind=='MdlMan::CModelTemplateDataEntry':
        wrapper=containers.cat(doc)
        return tuple(i for e in wrapper['entries'] if e['kind']=='CAnimationDataEntry' for i in e['clips'])
    if kind=='CStreamableAssetData':
        return tuple(containers.item(doc).get('clips',()))
    allowed={'NiControllerSequence','NiTransformInterpolator','NiTransformData',
             'NiBSplineCompTransformInterpolator','NiBSplineTransformInterpolator',
             'NiBSplineData','NiBSplineBasisData','NiTextKeyExtraData'}
    if not doc.roots or any(doc.blocks[i].type!='NiControllerSequence' for i in doc.roots) or any(b.type not in allowed for b in doc.blocks):
        raise NifError('animation editing requires recognized KF or owned CAT/ITEM sequences')
    return doc.roots


def append_blocks(payload,replacements,additions):
    doc=parse(payload)
    if doc.groups:
        raise NifError('appending blocks with nonempty group table is unsupported')
    if len(doc.blocks)+len(additions)>16384:
        raise NifError('edited block count exceeds reader limit')
    r=Reader(payload); r.read(len(b'Gamebryo File Format, Version 20.3.0.9\n')); r.read(9)
    prefix=payload[:r.pos]; old_count=r.count(16384)
    types=[r.string() for _ in range(r.one('H'))]
    indices=list(r.unpack(f'{old_count}H')); r.read(old_count*4)
    metadata=payload[r.pos:doc.blocks[0].start]
    bodies=[replacements.get(i,doc.body(i)) for i in range(old_count)]
    for kind,body in additions:
        if kind not in types: types.append(kind)
        indices.append(types.index(kind)); bodies.append(body)
    out=bytearray(prefix+pack('IH',len(bodies),len(types)))
    for kind in types:
        encoded=kind.encode(); out+=pack('I',len(encoded))+encoded
    out+=pack(str(len(indices))+'H',*indices)+pack(str(len(bodies))+'I',*(len(b) for b in bodies))
    out+=metadata+b''.join(bodies)+payload[doc.footer_start:]
    result=bytes(out); checked=parse(result)
    for i in range(old_count):
        if i not in replacements and checked.body(i)!=doc.body(i):
            raise NifError('opaque/original block changed')
    return result


def sampled_transform_data(samples):
    if not samples or len(samples)>100000:
        raise NifError('invalid sample count')
    previous=-math.inf
    for time,translation,quaternion,scale in samples:
        if not all(math.isfinite(v) for v in (time,*translation,*quaternion,scale)) or scale<=0:
            raise NifError('invalid native animation sample')
        if time<=previous: raise NifError('animation sample times must increase')
        previous=time
        if len(translation)!=3 or len(quaternion)!=4 or abs(sum(q*q for q in quaternion)-1)>1e-4:
            raise NifError('invalid animation transform dimensions/quaternion')
    out=bytearray()
    for channel,width in ((2,4),(1,3),(3,1)):
        values=[(time,(sample[channel],) if channel==3 else sample[channel]) for sample in samples for time in [sample[0]]]
        if all(value==values[0][1] for _,value in values): values=values[:1]
        out+=pack('II',len(values),1)
        for time,value in values: out+=pack('f'+str(width)+'f',time,*value)
    return bytes(out)


def edit_clips(payload,changes):
    """changes[root][original_node_name] -> ordered native local TRS samples."""
    if not changes: return payload
    doc=parse(payload)
    roots=editable_roots(doc)
    replacements={}; additions=[]
    for root,targets in changes.items():
        if root not in roots: raise NifError('animation sequence must be an explicitly owned root')
        sequence=animation.sequence(doc,root)
        r=Reader(doc.body(root)); scene.name(r,doc); r.read(r.count(65536)*4); scene.ref(r,doc)
        count=r.count(16384); r.one('I'); offsets={}
        for _ in range(count):
            offset=r.pos; interpolator=scene.ref(r,doc); controller=scene.ref(r,doc)
            names=[scene.name(r,doc) for _ in range(5)]
            if names[0] in offsets or controller!=-1:
                raise NifError('shared/controller-bound native target needs separate support')
            offsets[names[0]]=offset
        if set(targets)-set(offsets): raise NifError('adding animation targets is unsupported')
        body=bytearray(doc.body(root))
        for name,samples in targets.items():
            if not samples or abs(samples[0][0]-sequence['start'])>1e-5 or (len(samples)>1 and abs(samples[-1][0]-sequence['stop'])>1e-5):
                raise NifError('clip duration must remain unchanged')
            data=sampled_transform_data(samples)
            data_id=len(doc.blocks)+len(additions); additions.append(('NiTransformData',data))
            _,translation,quat,scale=samples[0]
            interp=pack('8fi',*translation,*quat,scale,data_id)
            interp_id=len(doc.blocks)+len(additions); additions.append(('NiTransformInterpolator',interp))
            struct.pack_into('<i',body,offsets[name],interp_id)
        replacements[root]=bytes(body)
    result=append_blocks(payload,replacements,additions)
    checked=parse(result)
    for root in changes:
        for target in animation.sequence(checked,root)['controlled']:
            animation.compile_interpolator(checked,target['interpolator'])
    return result


def validate_clip_edit(original,current):
    old,new=parse(original),parse(current)
    roots=editable_roots(old)
    if roots!=editable_roots(new) or old.roots!=new.roots or old.strings!=new.strings or old.groups!=new.groups:
        raise NifError('edited KF changed its original identity/layout')
    if len(new.blocks)<len(old.blocks): raise NifError('original animation blocks removed')
    for block in old.blocks:
        if new.blocks[block.index].type!=block.type: raise NifError('original animation block type changed')
        before,after=old.body(block.index),new.body(block.index)
        if before==after: continue
        if block.index not in roots or block.type!='NiControllerSequence' or len(before)!=len(after):
            raise NifError('original animation data may only be retained, not overwritten')
        r=Reader(before); scene.name(r,old); r.read(r.count(65536)*4); scene.ref(r,old)
        count=r.count(16384); r.one('I'); masked=bytearray(after)
        for _ in range(count):
            offset=r.pos; old_ref=scene.ref(r,old); controller=scene.ref(r,old)
            for _ in range(5): scene.name(r,old)
            ref=struct.unpack_from('<i',after,offset)[0]
            if ref!=old_ref:
                if controller!=-1 or not len(old.blocks)<=ref<len(new.blocks) or new.blocks[ref].type!='NiTransformInterpolator':
                    raise NifError('changed animation target does not use a new supported interpolator')
                animation.compile_interpolator(new,ref)
                masked[offset:offset+4]=before[offset:offset+4]
        if bytes(masked)!=before: raise NifError('sequence metadata/targets/duration changed')
    for block in new.blocks[len(old.blocks):]:
        if block.type=='NiTransformData': animation.transform_data(new,block.index)
        elif block.type=='NiTransformInterpolator': animation.compile_interpolator(new,block.index)
        else: raise NifError('unsupported appended animation block')
