"""Named static ITEM parameters; typed storage, semantics intentionally raw."""
import math
import struct
from .nif import Reader,NifError
from . import scene
from .item_editing import layout

FLOATS={'FallOffPower','ObjectHDRScale','ObjectNormalScale','worldScale'}
FLAGS={'CanBeFogged','EnableBannerWave','EnableFallOff','UseColoring','UseEnvMapping'}


def parameters(payload):
    model,_,_,_=layout(payload);doc=model.document;result={}
    for shape in model.components:
        rows={}
        for index in model.nodes[shape]['extra']:
            if index<0:continue
            b=doc.blocks[index];r=Reader(doc.body(index));name=scene.name(r,doc)
            if name in FLOATS and b.type=='NiFloatExtraData':value=r.vectors(1,1)[0][0];kind='float'
            elif name in FLAGS and b.type=='NiBooleanExtraData':value=r.flag();kind='bool'
            elif name=='FallOffColor' and b.type=='NiColorExtraData':value=r.vectors(1,4)[0];kind='color'
            elif name=='AnisotropicMapIndex' and b.type=='NiIntegerExtraData':value=r.one('I');kind='readonly-index'
            else:continue
            r.finish()
            if name in rows:raise NifError('Ambiguous named ITEM parameter')
            rows[name]=dict(block=index,kind=kind,value=value)
        result[shape]=rows
    return result


def body(payload,shape,name,value):
    from .nif import parse
    row=parameters(payload).get(shape,{}).get(name)
    if row is None:raise NifError('Unknown ITEM parameter')
    kind=row['kind']
    if kind=='readonly-index':raise NifError('AnisotropicMapIndex remains read-only until index target is known')
    if kind=='bool':
        if type(value)!=bool:raise NifError('Boolean ITEM parameter required')
        encoded=struct.pack('<B',value)
    else:
        values=(value,) if kind=='float' else tuple(value)
        if len(values)!=(1 if kind=='float' else 4) or any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>1e6 for v in values):
            raise NifError('Finite bounded numeric ITEM parameter required')
        encoded=struct.pack('<'+str(len(values))+'f',*values)
    return row['block'],parse(payload).body(row['block'])[:4]+encoded


def edit(payload,changes):
    from .animation_editing import append_blocks
    replacements={}
    for shape,values in changes.items():
        for name,value in values.items():
            index,data=body(payload,shape,name,value)
            if index in replacements and replacements[index]!=data:raise NifError('Conflicting shared parameter values')
            replacements[index]=data
    return append_blocks(payload,replacements,[]) if replacements else payload


def validate_block(original,current,index):
    from .nif import parse
    old=parameters(original);new=parameters(current)
    owners=[(shape,name) for shape,rows in old.items() for name,row in rows.items() if row['block']==index]
    if not owners:raise NifError('Unowned or unsupported extra-data edit')
    for shape,name in owners:
        i,data=body(original,shape,name,new[shape][name]['value'])
        if i!=index or data!=parse(current).body(index):raise NifError('Protected ITEM parameter metadata changed')
