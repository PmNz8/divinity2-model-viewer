import struct
import unittest
from model_viewer import embedded_texture as embedded
from model_viewer.nif import parse,NifError
from model_viewer.animation_editing import append_blocks
from model_viewer.editing import edit_geometry,validate_native_edit
from test_model_viewer_replay import triangle
from test_texture_roundtrip import _make_texture_payload,_bc1_block


def fixture():
    tex=_make_texture_payload(pixel_format=4,dimensions=((4,4),),data=_bc1_block(0xf800,0x07e0))
    body=parse(tex).body(0)
    source=struct.pack('<iIiBi i3I3B',-1,0,-1,0,-1,2,6,1,3,1,0,0)
    return append_blocks(triangle(),{},[('NiPersistentSrcTextureRendererData',body),('NiSourceTexture',source)])


class EmbeddedTests(unittest.TestCase):
    def test_preview_package_owner_roundtrip(self):
        from model_viewer.package import Source,open_preview,verify
        from model_viewer.replay import PackageCorpus
        from model_viewer.controller import Preview
        raw=fixture(); source=Source('model.item','test.dv2','0'*64,raw)
        p=Preview(PackageCorpus([source])); p.open_model(source)
        p.set_texture(3,source)
        self.assertEqual(p.texture_key(3),('model.item',2))
        data=p.package(); manifest=verify(data)
        self.assertEqual(len(manifest['resources']),1)
        restored=open_preview(data)
        self.assertEqual(restored.images[3],p.images[3])
        self.assertEqual(restored.package(),data)
        external=Source('external.nif','test.dv2','0'*64,embedded.wrapper(parse(raw).body(2)))
        p.corpus=PackageCorpus([source,external])
        with self.assertRaises(NifError): p.set_texture(3,external)

    def test_noop_and_combined_edit(self):
        raw=fixture(); target,tex=embedded.resource(raw,3)
        self.assertEqual(target,2)
        self.assertEqual(embedded.edit(raw,3,tex.decode_mip(),(4,4),profile='raw'),raw)
        changed=embedded.edit(raw,3,bytes((0,0,255,255))*16,(4,4),profile='raw')
        changed,_=edit_geometry(changed,{0:dict(vertices=[(0,0,.2),(1,0,0),(0,1,0)])})
        validate_native_edit(raw,changed)
        self.assertEqual(parse(raw).body(3),parse(changed).body(3))

    def test_protected_descriptor_and_owner(self):
        raw=fixture(); doc=parse(raw)
        bad=bytearray(doc.body(2)); bad[4]^=1
        with self.assertRaises(ValueError):
            validate_native_edit(raw,append_blocks(raw,{2:bytes(bad)},[]))
        with self.assertRaises(NifError): embedded.resource(raw,0)
        bad=bytearray(doc.body(3)); bad[12]=1
        with self.assertRaises(ValueError):
            embedded.resource(append_blocks(raw,{3:bytes(bad)},[]),3)


if __name__=='__main__': unittest.main()
