"""Visual branch boundaries: no optional native attachment decoding."""
import ast
import io
import json
from pathlib import Path
import unittest
import zipfile
from model_viewer import package

class VisualOnlyTests(unittest.TestCase):
    def test_attachment_contracts_rejected_before_member_access(self):
        for version in (3,4):
            stream=io.BytesIO()
            with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_STORED) as z:
                z.writestr('manifest.json',json.dumps({'schema':f'divinity2.model-source-package/{version}'}))
            with self.subTest(version=version),self.assertRaisesRegex(package.PackageError,'Visual-only'):
                package.open_preview(stream.getvalue())

    def test_viewer_native_modules_absent(self):
        root=Path(package.__file__).parent
        self.assertFalse(list(root.glob('physics*.py')))
        self.assertFalse(hasattr(__import__('model_viewer.controller',fromlist=['Preview']).Preview,'physics_attachment'))

    def test_no_native_imports_in_viewer(self):
        root=Path(package.__file__).parent
        for p in root.glob('*.py'):
            for node in ast.walk(ast.parse(p.read_text(encoding='utf8'))):
                if isinstance(node,ast.ImportFrom):
                    names=[node.module or '']+[n.name for n in node.names]
                elif isinstance(node,ast.Import):names=[n.name for n in node.names]
                else:continue
                self.assertFalse(any('physx' in n.lower() or 'physics' in n.lower() for n in names),p.name)
