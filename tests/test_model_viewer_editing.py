from dataclasses import replace
import io
import json
import struct
import unittest
import zipfile
from test_model_viewer_replay import triangle
from model_viewer.editing import edit_geometry
from model_viewer.nif import parse,geometry,NifError
from model_viewer.package import Source,build,verify,open_preview,PackageError,EDIT_SCHEMA
from model_viewer.controller import Preview
from model_viewer.replay import PackageCorpus


class EditingTests(unittest.TestCase):
    def test_v2_rejects_protected_topology_change(self):
        original=triangle(); changed=bytearray(original)
        geo=geometry(parse(original),1)
        struct.pack_into('<3H',changed,geo['uv_start']+13,0,2,1)
        source=Source('model.nif','test.dv2','0'*64,bytes(changed),original_payload=original)
        with self.assertRaises(PackageError): build([source],'model.nif')

    def test_fixed_geometry_and_noop(self):
        raw=triangle()
        self.assertEqual(edit_geometry(raw,{0:{}}),(raw,[]))
        result,ranges=edit_geometry(raw,{0:dict(vertices=[(0,0,.25),(1,0,0),(0,1,0)])})
        self.assertEqual(len(result),len(raw)); self.assertTrue(ranges)
        self.assertEqual(geometry(parse(result),1)['vertices'][0],(0,0,.25))
        for bad in ([(0,0,0)],[(float('nan'),0,0),(1,0,0),(0,1,0)]):
            with self.assertRaises(NifError): edit_geometry(raw,{0:dict(vertices=bad)})

    def test_edited_provenance_replay(self):
        original=triangle(); changed,_=edit_geometry(original,{0:dict(vertices=[(0,0,.25),(1,0,0),(0,1,0)])})
        source=Source('model.nif','test.dv2','0'*64,changed,original_payload=original)
        preview=Preview(PackageCorpus([source])); preview.open_model(source)
        payload=preview.package(); manifest=verify(payload)
        self.assertEqual(manifest['schema'],EDIT_SCHEMA)
        restored=open_preview(payload)
        self.assertEqual(restored.primary.original_payload,original)
        self.assertEqual(restored.primary.payload,changed)
        self.assertEqual(restored.package(),payload)
        z=zipfile.ZipFile(io.BytesIO(payload)); files={n:z.read(n) for n in z.namelist()}
        files[manifest['resources'][0]['original_member']]=b'corrupt'
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as bad:
            for n,b in files.items(): bad.writestr(n,b)
        with self.assertRaises(PackageError): verify(out.getvalue())
