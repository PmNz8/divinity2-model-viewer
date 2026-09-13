import math
import struct
import unittest
from model_viewer import animation as a
from model_viewer.nif import NifError, Reader


BASE = dict(translation=(1., 2., 3.), rotation=((1., 0., 0.), (0., 1., 0.), (0., 0., 1.)), scale=2.)


class AnimationTests(unittest.TestCase):
    def test_quadratic_tangent_direction_and_normalized_time(self):
        group=dict(kind=2,keys=(dict(time=2.,value=(0.,),forward=(99.,),backward=(2.,)),
                                dict(time=6.,value=(1.,),forward=(-1.,),backward=(99.,))))
        self.assertEqual(a.sample_keys(group,1.),(0.,))
        self.assertEqual(a.sample_keys(group,7.),(1.,))
        self.assertAlmostEqual(a.sample_keys(group,3.)[0],.484375)
        self.assertAlmostEqual(a.sample_keys(group,4.)[0],.875)
        vector=dict(kind=2,keys=(dict(time=2.,value=(0.,2.),forward=(99.,99.),backward=(2.,4.)),
                                 dict(time=6.,value=(1.,4.),forward=(-1.,-2.),backward=(99.,99.))))
        self.assertEqual(a.sample_keys(vector,4.),(.875,3.75))
        with self.assertRaises(NifError): a.sample_keys(group,3.,quaternion=True)

    def test_xyz_rotation_order_noncommuting(self):
        # X90 then Z90: x -> y, y -> z, z -> x.
        matrix=a.rotation_matrix(a.euler_xyz_quaternion((math.pi/2,0.,math.pi/2)))
        expected=((0.,0.,1.),(1.,0.,0.),(0.,1.,0.))
        for row,want in zip(matrix,expected):
            for value,target in zip(row,want): self.assertAlmostEqual(value,target)

    def test_xyz_interpolator_and_quadratic_scale(self):
        constant=lambda value:dict(kind=2,keys=(dict(time=0.,value=(value,),forward=(0.,),backward=(0.,)),))
        curve=dict(type='NiTransformInterpolator',pose=dict(translation=BASE['translation'],quaternion=(1.,0.,0.,0.),scale=1.),
                   keys=dict(rotation=dict(kind=4,axes=(constant(0.),constant(0.),constant(math.pi/2))),
                             translation=dict(kind=0,keys=()),scale=constant(3.)))
        pose=a.sample_interpolator(curve,.5,BASE)
        self.assertEqual(pose['scale'],3.)
        self.assertEqual(pose['translation'],BASE['translation'])
        self.assertAlmostEqual(pose['rotation'][1][0],1.)

    def test_cubic_bezier_and_endpoint_clamp(self):
        points = ((0.,), (0.,), (1.,), (1.,))
        for t in (0., .1, .5, .9, 1.):
            self.assertAlmostEqual(a.cubic_spline(points, t)[0], 3*t*t-2*t*t*t)
        self.assertEqual(a.cubic_spline(points, -1), points[0])
        self.assertEqual(a.cubic_spline(points, 2), points[-1])

    def test_uniform_multispan_constant_and_symmetry(self):
        for n in (4, 5, 10):
            for t in (.01, .2, .5, .7, .99):
                self.assertAlmostEqual(a.cubic_spline(((7.,),)*n, t)[0], 7.)
                points = tuple((float(i),) for i in range(n))
                self.assertAlmostEqual(a.cubic_spline(points, t)[0]+a.cubic_spline(points, 1-t)[0], n-1.)

    def test_quaternion_shortest_path_and_rotation(self):
        q = a.slerp((1., 0., 0., 0.), (0., 0., 0., 1.), .5)
        r = a.rotation_matrix(q)
        self.assertAlmostEqual(r[0][0], 0.)
        self.assertAlmostEqual(r[1][0], 1.)
        self.assertEqual(a.slerp((1., 0., 0., 0.), (-1., 0., 0., 0.), .5), (1., 0., 0., 0.))
        with self.assertRaises(NifError):
            a.normalize_quaternion((0.,)*4)

    def test_absent_channels_retain_base(self):
        invalid = -3.4028234663852886e38
        curve = dict(type='NiTransformInterpolator', keys=None,
                     pose=dict(translation=(invalid,)*3, quaternion=(invalid,)*4, scale=invalid))
        self.assertEqual(a.sample_interpolator(curve, 0., BASE), BASE)
        curve['pose']['translation'] = (invalid, 0., 0.)
        with self.assertRaises(NifError):
            a.sample_interpolator(curve, 0., BASE)

    def test_key_types_and_order_fail_closed(self):
        raw = struct.pack('<II4f', 2, 1, 1., 2., 0., 3.)
        with self.assertRaises(NifError):
            a._keys(Reader(raw), 1)
        with self.assertRaises(NifError):
            a.sample_keys(dict(kind=3, keys=({'time':0., 'value':(0.,)},)), 0.)
        with self.assertRaises(NifError):
            a.cubic_spline(((0.,),)*4, math.nan)


if __name__ == '__main__':
    unittest.main()
