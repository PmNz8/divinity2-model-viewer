import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile
from dataclasses import replace
from model_viewer import normalization, package, editing
from model_viewer.controller import Preview
from model_viewer.replay import PackageCorpus, restore


class NormalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture=Path('D:/testblender/player_cat_aroot_rename/DKS_Patch.dv2')
        if not fixture.exists(): raise unittest.SkipTest('local pinned CAT fixture unavailable')
        from tools.dv2_archive.src.dv2lib import DV2Session
        raw=bytearray(DV2Session(fixture).read_entry_bytes('Win32/Characters/Templates/Player_DragonMale.cat'))
        struct.pack_into('<i',raw,31103,4); struct.pack_into('<i',raw,32173,7)
        cls.raw=bytes(raw)
        assert package.digest(cls.raw)==normalization.ORIGINAL

    def preview(self):
        source=package.Source('Win32/Characters/Templates/Player_DragonMale.cat','CharacterTemplates.dv2','a'*64,self.raw)
        preview=Preview(PackageCorpus([source])); preview.open_model(source)
        return preview

    def test_copy_original_report_animation_and_idempotence(self):
        preview=self.preview(); before=preview.package()
        new=normalization.normalized_preview(preview)
        self.assertEqual(preview.package(),before)
        self.assertEqual(len(new.clips),51)
        self.assertEqual(new.primary.original_payload,self.raw)
        self.assertEqual(normalization.normalize(new.primary.payload),(new.primary.payload,[]))
        result=new.package(); report=package.verify(result)
        self.assertEqual(len(report['resources'][0]['normalization']),2)
        self.assertEqual(package.open_preview(result).package(),result)

    def test_normalized_geometry_roundtrip(self):
        new=normalization.normalized_preview(self.preview())
        g=new.model.components[228]['geometry']; vertices=list(g['vertices'])
        vertices[0]=tuple(x+.25 for x in vertices[0])
        edited,_=editing.edit_geometry(new.primary.payload,{228:{'vertices':vertices}})
        source=replace(new.primary,payload=edited)
        rebuilt=restore([source],source.logical_path,new.assembly()['recipe'])
        output=rebuilt.package(); restored=package.open_preview(output)
        self.assertEqual(restored.primary.original_payload,self.raw)
        self.assertEqual(len(package.verify(output)['resources'][0]['normalization']),2)

    def test_report_tamper_rejected(self):
        raw=normalization.normalized_preview(self.preview()).package()
        with zipfile.ZipFile(io.BytesIO(raw)) as z: members={n:z.read(n) for n in z.namelist()}
        manifest=json.loads(members['manifest.json']); manifest['resources'][0]['normalization']=[]
        members['manifest.json']=json.dumps(manifest).encode(); stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:
            for k,v in members.items(): z.writestr(k,v)
        with self.assertRaises(package.PackageError): package.verify(stream.getvalue())

    def test_combined_clip_geometry_keeps_report(self):
        from model_viewer.animation_editing import edit_clips
        from model_viewer.animation import sequence
        new=normalization.normalized_preview(self.preview())
        vertices=[tuple(v*1.1 for v in p) for p in new.model.components[228]['geometry']['vertices']]
        geometry,_=editing.edit_geometry(new.primary.payload,{228:{'vertices':vertices}})
        root=new.animation_roots[0]; clip=sequence(new.model.document,root)
        name=clip['controlled'][0]['node_name']
        edited=edit_clips(geometry,{root:{name:[(clip['start'],(0.,0.,0.),(1.,0.,0.,0.),1.)]}})
        self.assertEqual(editing.validate_native_edit(self.raw,edited),['player-dragon-root-names/1','player-dragon-div2-removal/1'])

    def test_unknown_source_not_normalized(self):
        raw=bytearray(self.raw); raw[31103]^=1
        self.assertEqual(normalization.normalize(bytes(raw)),(bytes(raw),[]))

    def test_protected_edit_rejected_after_normalization(self):
        normalized,_=normalization.normalize(self.raw); bad=bytearray(normalized); bad[-1]^=1
        with self.assertRaises(ValueError): editing.validate_native_edit(self.raw,bytes(bad))


if __name__=='__main__': unittest.main()
