import io
import json
import unittest
import zipfile
import tempfile
from pathlib import Path
from model_viewer.package import Source, build, verify, save_new, PackageError


class PackageTests(unittest.TestCase):
    def test_atomic_new_file_no_overwrite(self):
        s = self.source()
        payload = build([s], s.logical_path)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'asset.d2model'
            save_new(payload, target)
            self.assertEqual(target.read_bytes(), payload)
            with self.assertRaises(PackageError):
                save_new(payload, target)
            self.assertEqual(list(Path(directory).iterdir()), [target])

    def rewrite(self, package, edit):
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(package)) as original, zipfile.ZipFile(output, 'w') as changed:
            for name in original.namelist():
                raw = original.read(name)
                if name == 'manifest.json':
                    doc = json.loads(raw)
                    edit(doc)
                    raw = json.dumps(doc).encode()
                changed.writestr(name, raw)
        return output.getvalue()

    def test_malformed_manifest_records(self):
        source = self.source()
        package = build([source], source.logical_path)
        for key, value in [('archive_sha256', '../x'), ('sha256', None), ('size', True),
                           ('dependencies', 'abc'), ('unresolved', [None]), ('archive_name', '')]:
            with self.subTest(key=key):
                altered = self.rewrite(package, lambda d: d['resources'][0].__setitem__(key, value))
                with self.assertRaises(PackageError):
                    verify(altered)
        altered = self.rewrite(package, lambda d: d.__setitem__('resources', [None]))
        with self.assertRaises(PackageError):
            verify(altered)

    def source(self, **changes):
        values = dict(logical_path='Win32/test.cat', archive_name='Example.dv2',
                      archive_sha256='a' * 64, payload=b'opaque-original',
                      unresolved=('CAT component interpretation pending',))
        values.update(changes)
        return Source(**values)

    def test_deterministic_original_preservation(self):
        source = self.source()
        package = build([source], source.logical_path)
        self.assertEqual(package, build([source], source.logical_path))
        manifest = verify(package)
        self.assertEqual(manifest['dependency_status'], 'unresolved')
        with zipfile.ZipFile(io.BytesIO(package)) as z:
            self.assertEqual(z.read(manifest['resources'][0]['member']), source.payload)

    def test_ambiguous_and_missing_dependencies(self):
        s = self.source()
        with self.assertRaises(PackageError):
            build([s, s], s.logical_path)
        with self.assertRaises(PackageError):
            build([self.source(dependencies=('Win32/missing.nif',))], s.logical_path)
        with self.assertRaises(PackageError):
            build([self.source(logical_path='../unsafe')], '../unsafe')

    def test_tampering_rejected(self):
        s = self.source()
        package = build([s], s.logical_path)
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(package)) as original, zipfile.ZipFile(output, 'w') as edited:
            for name in original.namelist():
                raw = original.read(name)
                if name == 'manifest.json':
                    doc = json.loads(raw)
                    doc['dependency_status'] = 'complete'
                    raw = json.dumps(doc).encode()
                edited.writestr(name, raw)
        with self.assertRaises(PackageError):
            verify(output.getvalue())


if __name__ == '__main__':
    unittest.main()
