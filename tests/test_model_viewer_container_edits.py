import struct
import unittest
from dataclasses import replace
from test_model_viewer_replay import triangle
from model_viewer.nif import parse, NifError
from model_viewer.assets import load_model
from model_viewer.package import Source, open_preview, verify
from model_viewer.controller import Preview
from model_viewer.replay import PackageCorpus
from model_viewer.editing import edit_geometry, validate_native_edit
from model_viewer.animation_editing import edit_clips, append_blocks


def fixture(missing=False, item=False):
    def p(fmt,*v): return struct.pack('<'+fmt,*v)
    def string(s):
        b=s.encode(); return p('I',len(b))+b
    t=(0,0,0,1,0,0,0,1,0,0,0,1,1)
    def node(children): return p('iIiH13fIiI',0,0,-1,0,*t,0,-1,len(children))+p(str(len(children))+'i',*children)+p('I',0)
    doc=parse(triangle())
    seq=p('iIiII',1,0,-1,1,1)+p('7i',9,-1,7 if missing else 0,-1,2,-1,-1)+p('fiI3fiiI',1,-1,0,1,0,1,-1,-1,0)
    rows=[('NiTriShape',doc.body(0)),('NiTriShapeData',doc.body(1)),('NiNode',node([0])),
          ('NiNode',node([])),('NiFloatsExtraData',p('iI',-1,0)),
          ('MdlMan::CSkeletonDataEntry',p('IBii',0,1,4,3)),
          ('MdlMan::CMeshDataEntry',p('IBiBi',1,1,5,0,2)),
          ('MdlMan::CAnimationDataEntry',p('IBiIi',2,1,6,1,8)),
          ('NiControllerSequence',seq),('NiTransformInterpolator',p('8fi',0,0,0,1,0,0,0,1,-1)),
          ('MdlMan::CModelTemplateDataEntry',p('IBiiI3i',3,1,3,4,3,5,6,7))]
    root=10
    if item:
        seq=bytearray(seq); struct.pack_into('<i',seq,20,4)
        manager=string('mesh.nif')+string('node')+p('IIffI',1,2,.1,.1,1)
        manager+=p('I',0)+string('anim.kf')+p('III',0,0,0)
        rows=rows[:3]+[('NiControllerSequence',bytes(seq)),rows[9],
              ('CStreamableAssetData',p('iBI',2,1,len(manager))+manager+p('Ii',1,3))]
        root=5
    types=list(dict.fromkeys(k for k,b in rows)); strings=['node','clip','NiTransformController','test.cat','skel.nif','mesh.nif','anim.kf','AROOT_MISSING']
    return (b'Gamebryo File Format, Version 20.3.0.9\n'+p('IBIIH',0x14030009,1,0x30000,len(rows),len(types))+
            b''.join(string(s) for s in types)+p(str(len(rows))+'H',*(types.index(k) for k,b in rows))+
            p(str(len(rows))+'I',*(len(b) for k,b in rows))+p('II',len(strings),max(map(len,strings)))+
            b''.join(string(s) for s in strings)+p('I',0)+b''.join(b for k,b in rows)+p('Ii',1,root))


class ContainerEditTests(unittest.TestCase):
    def preview(self,raw,original=None):
        s=Source('Win32/test.cat','test.dv2','0'*64,raw,original_payload=original)
        p=Preview(PackageCorpus([s])); p.open_model(s); return p

    def test_missing_target_static_roundtrip_preserves_clips(self):
        raw=fixture(True); p=self.preview(raw)
        self.assertEqual(p.clips,[]); self.assertTrue(p.skeleton)
        self.assertIn('AROOT_MISSING',p.container['animation_preview_error'])
        self.assertEqual(p.container['entries'][-1]['clips'],(8,))
        data=p.package(); q=open_preview(data)
        self.assertEqual(q.primary.payload,raw); self.assertEqual(q.package(),data)
        self.assertEqual(len(q.frame()[0]),1)

    def test_combined_geometry_animation_roundtrip(self):
        raw=fixture(); geo,_=edit_geometry(raw,{0:dict(vertices=((0,0,.25),(1,0,0),(0,1,0)))})
        edited=edit_clips(geo,{8:{'node':[(0.,(0.,0.,1.),(1.,0.,0.,0.),1.),(1.,(0.,0.,2.),(1.,0.,0.,0.),1.)]}})
        validate_native_edit(raw,edited)
        p=self.preview(edited,raw); q=open_preview(p.package())
        self.assertEqual(q.model.components[0]['geometry']['vertices'][0],(0.,0.,.25))
        self.assertEqual(q.primary.original_payload,raw); self.assertEqual(len(q.clips),1)
        self.assertEqual(verify(q.package())['primary'],'Win32/test.cat')
        a,b=parse(raw),parse(edited)
        self.assertTrue(all(a.body(i)==b.body(i) for i in (2,3,4,5,6,7,9,10)))

    def test_combined_edits_reject_non_target_changes(self):
        raw=fixture(); edited=edit_clips(raw,{8:{'node':[(0.,(0.,0.,1.),(1.,0.,0.,0.),1.)]}})
        doc=parse(edited)
        for index in (2,6,10):
            body=bytearray(doc.body(index)); body[0]^=1
            bad=append_blocks(edited,{index:bytes(body)},[])
            with self.assertRaises(NifError): validate_native_edit(raw,bad)
        with self.assertRaises(NifError): edit_clips(raw,{9:{'node':[]}})

    def test_static_geometry_edit_does_not_strip_unsupported_clips(self):
        raw=fixture(True); edited,_=edit_geometry(raw,{0:dict(vertices=((0,0,.25),(1,0,0),(0,1,0)))})
        q=open_preview(self.preview(edited,raw).package())
        self.assertEqual(parse(raw).body(8),q.model.document.body(8))
        self.assertIn('AROOT_MISSING',q.container['animation_preview_error'])

    def test_animated_item_combined_edit(self):
        raw=fixture(item=True)
        geo,_=edit_geometry(raw,{0:dict(vertices=((0,0,.25),(1,0,0),(0,1,0)))})
        edited=edit_clips(geo,{3:{'node':[(0.,(1.,2.,3.),(1.,0.,0.,0.),1.)]}})
        validate_native_edit(raw,edited)
        s=Source('Win32/test.item','test.dv2','0'*64,edited,original_payload=raw)
        p=Preview(PackageCorpus([s])); p.open_model(s)
        q=open_preview(p.package())
        self.assertEqual(q.model.components[0]['geometry']['vertices'][0],(0.,0.,.25))
        self.assertEqual(q.primary.original_payload,raw)
        self.assertEqual(len(q.clips),1)


if __name__=='__main__': unittest.main()
