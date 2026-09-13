import struct
import unittest
from model_viewer.nif import parse,geometry,NifError
from model_viewer.item_editing import edit_item,validate_item
from model_viewer.editing import validate_native_edit
from model_viewer.animation_editing import append_blocks
from model_viewer.package import Source,build,verify
from test_model_viewer_replay import triangle


def item():
    old=parse(triangle()); shape=bytearray(old.body(0))
    struct.pack_into('<i',shape,len(shape)-17,3)
    tr=(0,0,0,1,0,0,0,1,0,0,0,1,1)
    node=struct.pack('<iIiiH13fIiII',-1,1,4,-1,0,*tr,0,-1,1,2)+struct.pack('<I',0)
    bodies=[struct.pack('<iBI',1,0,0),node,bytes(shape),old.body(1),struct.pack('<iI10f',0,10,0,0,0,1,0,0,0,1,1,0)]
    types=['CStreamableAssetData','NiNode','NiTriShape','NiTriShapeData','NiFloatsExtraData']
    out=b'Gamebryo File Format, Version 20.3.0.9\n'+struct.pack('<IBIIH',0x14030009,1,0x30000,5,5)
    for t in types:out+=struct.pack('<I',len(t))+t.encode()
    out+=struct.pack('<5H5I',*range(5),*map(len,bodies))+struct.pack('<III',1,8,8)+b'MaxBound'+struct.pack('<I',0)
    return out+b''.join(bodies)+struct.pack('<Ii',1,0)


class ItemEditingTests(unittest.TestCase):
    def test_package_and_protected_fields(self):
        raw=item();new=edit_item(raw,{2:dict(vertices=[(0,0,0),(2,0,0),(2,2,0),(0,2,0)],triangles=[(0,1,2),(0,2,3)],uv_sets=[])})
        self.assertTrue(validate_native_edit(raw,new))
        p=build([Source('house.item','test.dv2','0'*64,new,original_payload=raw)],'house.item')
        verify(p)
        doc=parse(new)
        bound=bytearray(doc.body(4));bound[-1]^=1
        with self.assertRaises(NifError):validate_item(raw,append_blocks(new,{4:bytes(bound)},[]))
        node=bytearray(doc.body(1));node[16]^=1
        with self.assertRaises(NifError):validate_item(raw,append_blocks(new,{1:bytes(node)},[]))
        with self.assertRaises(NifError):validate_item(raw,append_blocks(new,{4:parse(raw).body(4)},[]))


if __name__=='__main__':unittest.main()
