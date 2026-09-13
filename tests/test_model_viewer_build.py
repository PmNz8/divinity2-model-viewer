"""Distribution guards; no game data or GUI required."""
from pathlib import Path
import runpy
import unittest


class BuildTests(unittest.TestCase):
    def test_opengl_hook(self):
        root = Path(__file__).resolve().parents[1]
        hook = runpy.run_path(str(root/'tools/pyinstaller_hooks/hook-OpenGL.py'))
        include = hook['include_data']
        for name in ('freeglut64.vc9.dll', 'FREEGLUT32.VC10.DLL', 'glut32.dll'):
            self.assertFalse(include('C:/example/'+name))
        for name in ('freeglut_COPYING.txt', 'gle64.vc14.dll', 'other.dll'):
            self.assertTrue(include('C:/example/'+name))
        self.assertIn('OpenGL.platform.win32', hook['hiddenimports'])
        self.assertIn('OpenGL.GLUT', hook['excludedimports'])
        self.assertTrue(all(include(source) for source, _ in hook['datas']))

    def test_versions_agree(self):
        from model_viewer import __version__
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(__version__, '0.2.1')
        for name in ('model_viewer/docs/README.md', 'tools/windows_version.txt'):
            self.assertIn(__version__, (root/name).read_text(encoding='utf8'))
