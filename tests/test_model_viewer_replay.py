import io
import json
import struct
import unittest
import zipfile
from model_viewer.package import Source, verify, open_preview, PackageError
from model_viewer.controller import Preview
from model_viewer.replay import PackageCorpus


def triangle():
    def pack(fmt, *v):
        return struct.pack('<'+fmt, *v)
    def string(s):
        return pack('I', len(s))+s
    transform = (0,0,0,1,0,0,0,1,0,0,0,1,1)
    shape = pack('iIiH13fIi', -1,0,-1,0,*transform,0,-1)+pack('iiIiB',1,-1,0,-1,0)
    geo = (pack('iHBBB9fHBB',0,3,0,0,1,0,0,0,1,0,0,0,1,0,0,0,0)
           + pack('4fH6fB',0,0,0,1,2,0,0,0,1,1,0,0)
           + pack('HiHIB3HH',0,-1,1,3,1,0,1,2,0))
    return (b'Gamebryo File Format, Version 20.3.0.9\n'
            + pack('IBIIH',0x14030009,1,0x30000,2,2)
            + string(b'NiTriShape')+string(b'NiTriShapeData')
            + pack('2H2I3I',0,1,len(shape),len(geo),0,0,0)+shape+geo+pack('Ii',1,0))


class ReplayTests(unittest.TestCase):
    def package(self):
        source = Source('Win32/triangle.nif','Synthetic.dv2','a'*64,triangle())
        p = Preview(PackageCorpus([source])); p.open_model(source)
        return p.package()

    def alter(self, payload, edit):
        out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(payload)) as z, zipfile.ZipFile(out,'w') as w:
            for name in z.namelist():
                data = z.read(name)
                if name == 'manifest.json':
                    manifest = json.loads(data); edit(manifest['assembly'])
                    data = json.dumps(manifest).encode()
                w.writestr(name,data)
        return out.getvalue()

    def test_offline_replay_and_determinism(self):
        payload = self.package()
        self.assertEqual(payload,self.package())
        p = open_preview(payload)
        self.assertEqual(p.frame()[0][0]['triangles'],((0,1,2),))
        self.assertEqual(verify(payload)['assembly']['dependency_status'],'complete_for_declared_preview_scope')

    def test_metadata_tampering(self):
        payload = self.package()
        for edit in [lambda a:a['components'][0].__setitem__('vertices',99),
                     lambda a:a['recipe'].__setitem__('components',[1]),
                     lambda a:a['recipe'].__setitem__('components',[False]),
                     lambda a:a['recipe'].__setitem__('textures',[{'block':0,'resource':'absent'}]),
                     lambda a:a.__setitem__('dependency_status','universal_complete'),
                     lambda a:a['recipe'].__setitem__('skeleton',{'resource':'absent','root':0})]:
            with self.assertRaises(PackageError):
                verify(self.alter(payload,edit))


if __name__ == '__main__':
    unittest.main()
