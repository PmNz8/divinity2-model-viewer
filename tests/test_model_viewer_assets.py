import unittest
from types import SimpleNamespace
from model_viewer.assets import render_component
from model_viewer.nif import NifError
from model_viewer.scene import IDENTITY


class AssetTests(unittest.TestCase):
    def model(self, flags=0, **base):
        component = dict(skin=-1, material=None, warnings=[],
                         geometry=dict(vertices=((0,0,0),(1,0,0),(0,1,0)), triangles=((0,1,2),),
                                       uv_sets=(((0,0),(1,0),(0,1)),)),
                         texturing=dict(slots=dict(base=dict(source=4, flags=flags, **base))))
        return SimpleNamespace(components={1:component}, world={1:IDENTITY})

    def test_explicit_texture_and_uv_selection(self):
        image = object()
        rendered = render_component(self.model(0x3200), 1, {4:image})
        self.assertIs(rendered['image'], image)
        self.assertEqual(rendered['clamp'], 3)
        self.assertEqual(rendered['uv'][1], (1,0))
        self.assertTrue(rendered['warnings'])
        with self.assertRaises(NifError):
            render_component(self.model(1), 1, {4:image})

    def test_missing_and_unimplemented_transform_not_silent(self):
        self.assertNotIn('image', render_component(self.model(), 1))
        self.assertTrue(render_component(self.model(), 1)['warnings'])
        rendered = render_component(self.model(translation=(1,2)), 1, {4:object()})
        self.assertNotIn('image', rendered)
        self.assertIn('UV transform', rendered['warnings'][0])
