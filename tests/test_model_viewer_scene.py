import struct
import unittest
from model_viewer.nif import Block, Document, NifError, Reader
from model_viewer.scene import hierarchy, point, node, material, skin_data, matrix, transform as read_transform


def fixture(kind, data):
    return Document(data, 0x30000, ('test',), (), (Block(0, kind, 0, len(data)),), (0,), len(data))


def transform(translation=(0, 0, 0), scale=1, rotation=((1, 0, 0), (0, 1, 0), (0, 0, 1))):
    return dict(translation=translation, rotation=rotation, scale=scale)


class SceneTests(unittest.TestCase):
    def test_disk_triples_follow_validated_math_convention(self):
        raw = struct.pack('<13f', 0, 1, 0, -1, 0, 0, 0, 0, 1, 5, 0, 0, 2)
        self.assertEqual(point(matrix(read_transform(Reader(raw))), (1, 0, 0)), (5, -2, 0))

    def test_full_parent_composition(self):
        nodes = {
            0: dict(children=(1,), transform=transform((5, 0, 0), 2, ((0, -1, 0), (1, 0, 0), (0, 0, 1)))),
            1: dict(children=(2,), transform=transform((1, 0, 0))),
            2: dict(children=(), transform=transform((1, 0, 0))),
        }
        parents, world = hierarchy(nodes)
        self.assertEqual(parents, {1: 0, 2: 1})
        self.assertEqual(point(world[2], (1, 0, 0)), (5, 6, 0))

    def test_invalid_hierarchies(self):
        for edges in ({0: (1,), 1: (0,)}, {0: (2,), 1: (2,), 2: ()}, {0: (1,)}, {0: (1, 1), 1: ()}):
            with self.subTest(edges=edges), self.assertRaises(NifError):
                hierarchy({k: dict(children=v, transform=transform()) for k, v in edges.items()})

    def test_node_exact_end_and_refs(self):
        raw = struct.pack('<iIiH13fIiII', 0, 0, -1, 14,
                          1, 2, 3, 1, 0, 0, 0, 1, 0, 0, 0, 1, 1, 0, -1, 0, 0)
        obj = node(fixture('NiNode', raw), 0)
        self.assertEqual(obj['transform']['translation'], (1, 2, 3))
        for end in range(len(raw)):
            with self.assertRaises(NifError):
                node(fixture('NiNode', raw[:end]), 0)
        with self.assertRaises(NifError):
            node(fixture('NiNode', raw + b'\0'), 0)

    def test_material_nonfinite_rejected(self):
        raw = struct.pack('<iIi14f', 0, 0, -1, *([1.] * 14))
        self.assertEqual(material(fixture('NiMaterialProperty', raw), 0)['alpha'], 1.)
        with self.assertRaises(NifError):
            material(fixture('NiMaterialProperty', raw[:-4] + struct.pack('<f', float('nan'))), 0)

    def test_skin_weight_bounds(self):
        t = struct.pack('<13f', 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1)
        prefix = t + struct.pack('<IB', 1, 1) + t + struct.pack('<4fH6fH', *([0.] * 4), 2, *([0.] * 6), 1)
        for weight in (-.1, 1.1, float('inf')):
            with self.assertRaises(NifError):
                skin_data(fixture('NiSkinData', prefix + struct.pack('<Hf', 0, weight)), 0)
        result = skin_data(fixture('NiSkinData', prefix + struct.pack('<Hf', 0, .5)), 0)
        self.assertEqual(result['bones'][0]['weights'], ((0, .5),))


if __name__ == '__main__':
    unittest.main()
