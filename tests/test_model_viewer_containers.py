import struct
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from model_viewer.nif import Document, Block, NifError
from model_viewer.containers import cat, item


def document(rows):
    payload, blocks = b'', []
    for kind, body in rows:
        blocks.append(Block(len(blocks), kind, len(payload), len(payload)+len(body)))
        payload += body
    return Document(payload, 0x30000, ('Templates/test.cat', 'test/Skeleton.nif'), (), tuple(blocks), (0,), len(payload))


class ContainerTests(unittest.TestCase):
    def rows(self):
        return [('MdlMan::CModelTemplateDataEntry', struct.pack('<IBiiii', 1, 1, 0, 1, 1, 2)),
                ('NiFloatsExtraData', b''),
                ('MdlMan::CSkeletonDataEntry', struct.pack('<IBii', 0, 1, 1, 3)),
                ('NiNode', b'')]

    def test_unaligned_normal_indices(self):
        result = cat(document(self.rows()))
        self.assertEqual(result['entries'][0]['root'], 3)
        self.assertEqual(result['entries'][0]['reference'], 'test/Skeleton.nif')

    def test_truncation_trailing_and_wrong_target(self):
        for index in (0, 2):
            rows = self.rows()
            kind, body = rows[index]
            for bad in [body[:i] for i in range(len(body))] + [body+b'\0']:
                rows[index] = kind, bad
                with self.assertRaises(NifError):
                    cat(document(rows))
        rows = self.rows()
        rows[3] = 'NiTriShape', b''
        with self.assertRaises(NifError):
            cat(document(rows))

    def test_item_tail_fail_closed(self):
        rows = [('CStreamableAssetData', struct.pack('<i', 1)+bytes(5)), ('NiNode', b'')]
        self.assertEqual(item(document(rows))['root'], 1)
        for tail in (bytes(4), bytes(6), bytes(4)+b'\1'):
            rows[0] = 'CStreamableAssetData', struct.pack('<i', 1)+tail
            with self.assertRaises(NifError):
                item(document(rows))

    def animated_rows(self):
        def string(value):
            data = value.encode()
            return struct.pack('<I', len(data))+data
        manager = string('test.nif')+string('AROOT')+struct.pack('<IIffI', 1, 2, .1, .1, 2)
        for i in range(2):
            manager += struct.pack('<I', i)+string('test.kf')+struct.pack('<IIII', i, 1, 1-i, 5)
        manager += bytes(4)
        body = struct.pack('<iBI', 1, 1, len(manager))+manager+struct.pack('<Iii', 2, 2, 3)
        return [('CStreamableAssetData', body), ('NiNode', b''),
                ('NiControllerSequence', b''), ('NiControllerSequence', b'')]

    def test_animated_item_metadata(self):
        result = item(document(self.animated_rows()))
        self.assertEqual(result['clips'], (2, 3))
        self.assertEqual(result['sequences'][1]['reference'], 'test.kf')
        self.assertEqual(result['sequences'][0]['raw_pairs'], ((1, 5),))

    def test_animated_item_truncation_and_wrong_refs(self):
        rows = self.animated_rows()
        body = rows[0][1]
        for bad in [body[:i] for i in range(len(body))]+[body+b'\0', body[:-4]+struct.pack('<i', 1), body[:-4]+struct.pack('<i', 2)]:
            with self.assertRaises(NifError):
                item(document([(rows[0][0], bad)]+rows[1:]))

    def test_assembly_texture_keys_are_json_stable(self):
        import json
        from model_viewer.controller import Preview
        from model_viewer.package import _json
        preview = Preview(None)
        preview.primary = SimpleNamespace(logical_path='test.item')
        preview.model = SimpleNamespace(components={}, texture_references={36: {'filename':'a'}, 124: {'filename':'b'}})
        assembly = preview.assembly()
        self.assertEqual(_json(assembly), _json(json.loads(_json(assembly))))

    def test_rigid_embedded_animation_uses_posed_world(self):
        from model_viewer.controller import Preview
        from model_viewer import scene
        preview = Preview(None)
        preview.primary = preview.skeleton_source = object()
        preview.selected = (1,)
        preview.model = SimpleNamespace(components={1: {'skin':-1, 'geometry':{'vertices':((1.,2.,3.),)}}})
        preview.clips = [object()]
        world = {1: ((1,0,0,10),(0,1,0,20),(0,0,1,30),(0,0,0,1))}
        with patch('model_viewer.controller.render_component', return_value={'vertices':((0,0,0),)}), \
             patch('model_viewer.controller.animation.posed_nodes', return_value={1:{}}), \
             patch('model_viewer.controller.scene.hierarchy', return_value=({}, world)):
            meshes, _, _ = preview.frame(0, .5)
        self.assertEqual(meshes[0]['vertices'], ((11.,22.,33.),))


if __name__ == '__main__':
    unittest.main()
