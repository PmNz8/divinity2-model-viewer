import unittest
from model_viewer import skinning, scene
from model_viewer.nif import NifError


def transform(x):
    return dict(rotation=((1.,0.,0.), (0.,1.,0.), (0.,0.,1.)), translation=(x,0.,0.), scale=1.)


class SkinTests(unittest.TestCase):
    def test_bind_inverse_and_posed_delta(self):
        instance = dict(bones=(7,))
        data = dict(has_weights=True, bones=(dict(transform=transform(-10.), weights=((0,1.),)),))
        bindings = skinning.bind(instance, data, {7:dict(name='bone')}, {2:dict(name='bone')}, 1)
        self.assertEqual(skinning.deform(bindings, {2:scene.matrix(transform(10.))}, ((3.,0.,0.),)), ((3.,0.,0.),))
        self.assertEqual(skinning.deform(bindings, {2:scene.matrix(transform(15.))}, ((3.,0.,0.),)), ((8.,0.,0.),))

    def test_ambiguous_missing_and_nonunit_rejected(self):
        instance = dict(bones=(7,))
        data = dict(has_weights=True, bones=(dict(transform=transform(0.), weights=((0,1.),)),))
        for nodes in ({}, {2:dict(name='bone'), 3:dict(name='bone')}):
            with self.assertRaises(NifError):
                skinning.bind(instance, data, {7:dict(name='bone')}, nodes, 1)
        data['bones'][0]['weights'] = ((0,.2),)
        with self.assertRaises(NifError):
            skinning.bind(instance, data, {7:dict(name='bone')}, {2:dict(name='bone')}, 1)
