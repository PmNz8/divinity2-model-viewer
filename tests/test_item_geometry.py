import unittest
from model_viewer.item_geometry import replace_geometry,position_matches
from model_viewer.nif import parse,geometry,NifError
from test_model_viewer_replay import triangle


class ItemGeometryTests(unittest.TestCase):
    def test_degenerate_uv_basis_is_orthogonal_in_static_writer_mode(self):
        from model_viewer.editing import normal_tangents
        vertices=((0,0,0),(1,0,0),(0,1,0));triangles=((0,1,2),)
        for normal in ((0,0,1),(.6,0,.8)):
            ns,ts,bs=normal_tangents(vertices,triangles,((0,0),)*3,
                normals=(normal,)*3,orthogonal_fallback=True)
            for n,t,b in zip(ns,ts,bs):
                self.assertAlmostEqual(sum(x*y for x,y in zip(n,t)),0)
                self.assertAlmostEqual(sum(x*y for x,y in zip(n,b)),0)
                self.assertAlmostEqual(sum(x*x for x in t),1)
                self.assertAlmostEqual(sum(x*x for x in b),1)

    def test_variable_arrays_and_opaque_preservation(self):
        raw=triangle()
        new=replace_geometry(raw,1,[(0,0,0),(1,0,0),(1,1,0),(0,1,0)],[(0,1,2),(0,2,3)],[])
        old,doc=parse(raw),parse(new)
        self.assertEqual(old.body(0),doc.body(0))
        self.assertEqual(old.strings,doc.strings)
        self.assertEqual(old.roots,doc.roots)
        self.assertEqual(len(geometry(doc,1)['vertices']),4)
        self.assertEqual(len(geometry(doc,1)['triangles']),2)

    def test_match_rule_and_invalid_indices(self):
        self.assertEqual(position_matches([(0,0,0),(1,0,0),(0,0,0)]),((2,),(),(0,)))
        for faces in [[(0,0,1)],[(0,1,3)],[(0,1,True)]]:
            with self.assertRaises(NifError):
                replace_geometry(triangle(),1,[(0,0,0),(1,0,0),(0,1,0)],faces,[])


if __name__=='__main__': unittest.main()
