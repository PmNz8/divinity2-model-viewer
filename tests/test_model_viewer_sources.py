import tempfile
import unittest
from pathlib import Path
from model_viewer.sources import Corpus, SourceError
from tools.dv2_archive.tests.synth_builder import build_synthetic


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def archive(self, name, entries):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(build_synthetic([(p.replace('/', '\\'), b, 'raw') for p, b in entries], 1))
        return path

    def test_recursive_duplicates_require_explicit_selection(self):
        self.archive('Patch.dv2', [('Win32/mesh.nif', b'patch')])
        self.archive('Map/Map.dv2', [('win32/mesh.NIF', b'map')])
        c = Corpus(self.root)
        self.assertEqual(len(c.occurrences('WIN32\\MESH.nif')), 2)
        with self.assertRaises(SourceError):
            c.select('win32/mesh.nif')
        selected = c.select('win32/mesh.nif', 'Map/Map.dv2')
        self.assertEqual(c.read(selected).payload, b'map')
        self.assertEqual(len(c.candidates('C:\\authoring\\mesh.nif')), 2)

    def test_drift_and_inventory_fail(self):
        path = self.archive('A.dv2', [('a.nif', b'a')])
        c = Corpus(self.root)
        selected = c.select('a.nif')
        c.read(selected)
        path.write_bytes(path.read_bytes() + b'changed')
        with self.assertRaises(SourceError):
            c.read(selected)
        c = Corpus(self.root)
        self.archive('B.dv2', [('b.nif', b'b')])
        with self.assertRaises(SourceError):
            c.check()

    def test_stable_identity_and_missing(self):
        self.archive('A.dv2', [('a.nif', b'original')])
        c = Corpus(self.root)
        a = c.read(c.select('a.nif'))
        b = c.read(c.select('a.nif'), fresh_hash=True)
        self.assertEqual(a, b)
        with self.assertRaises(SourceError):
            c.select('missing.nif')


if __name__ == '__main__':
    unittest.main()
