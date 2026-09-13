import unittest
import struct
from model_viewer.item_parameters import parameters,edit
from model_viewer.editing import validate_native_edit
from model_viewer.animation_editing import append_blocks
from model_viewer.nif import parse,NifError
from test_item_editing import item


class ParameterTests(unittest.TestCase):
    def fixture(self):
        # The synthetic fixture's sole string is renamed, MaxBound remains
        # root-owned by adding a separate string in the existing envelope.
        raw=item();doc=parse(raw)
        name=b'CanBeFogged'
        # Locate known fixture global-string metadata structurally.
        from model_viewer.nif import Reader
        r=Reader(raw);r.read(len(b'Gamebryo File Format, Version 20.3.0.9\n')+9);count=r.one('I')
        for _ in range(r.one('H')):r.string()
        r.read(count*6);start=r.pos
        r.one('I');r.one('I');r.string();stop=r.pos
        raw=raw[:start]+struct.pack('<II',2,len(name))+struct.pack('<I',8)+b'MaxBound'+struct.pack('<I',len(name))+name+raw[stop:]
        doc=parse(raw);shape=doc.body(2)
        shape=shape[:4]+struct.pack('<Ii',1,5)+shape[8:]
        return append_blocks(raw,{2:shape},[('NiBooleanExtraData',struct.pack('<iB',1,1))])

    def test_typed_flag(self):
        raw=self.fixture();self.assertTrue(parameters(raw)[2]['CanBeFogged']['value'])
        new=edit(raw,{2:{'CanBeFogged':False}});validate_native_edit(raw,new)
        self.assertFalse(parameters(new)[2]['CanBeFogged']['value'])
        with self.assertRaises(NifError):edit(raw,{2:{'CanBeFogged':2}})
        with self.assertRaises(NifError):edit(raw,{2:{'unknown':False}})


if __name__=='__main__':unittest.main()
