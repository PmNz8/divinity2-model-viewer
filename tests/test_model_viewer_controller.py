from pathlib import Path
from types import SimpleNamespace
import unittest
from model_viewer.controller import Preview
from model_viewer.nif import NifError
from model_viewer.package import Source


class ControllerTests(unittest.TestCase):
    def preview(self):
        source = Source('bad.nif','A.dv2','a'*64,b'unsupported payload')
        # Real Corpus stores a resolved root (also when cwd is a junction).
        corpus = SimpleNamespace(root=Path.cwd().resolve(), read=lambda row:source)
        return Preview(corpus)

    def test_failed_open_preserves_existing_state(self):
        p = self.preview()
        marker = object()
        p.primary = p.model = marker
        with self.assertRaises(NifError):
            p.open_model(None)
        self.assertIs(p.primary,marker)
        self.assertIs(p.model,marker)

    def test_missing_roles_and_invalid_selection(self):
        p = self.preview()
        with self.assertRaises(NifError):
            p.set_skeleton(None)
        with self.assertRaises(NifError):
            p.set_animation(None)
        p.model = SimpleNamespace(components={1:{}}, texture_references={})
        p.selected = (1,)
        for selection in [(),(1,1),(2,)]:
            with self.assertRaises(NifError):
                p.set_components(selection)
            self.assertEqual(p.selected,(1,))
        with self.assertRaises(NifError):
            p.set_texture(9,None)

    def test_source_tree_export_forbidden(self):
        p = self.preview()
        with self.assertRaisesRegex(NifError,'source corpus'):
            p.export(Path.cwd()/'never-created.d2model')


if __name__ == '__main__':
    unittest.main()
