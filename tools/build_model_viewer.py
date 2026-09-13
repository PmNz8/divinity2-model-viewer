"""Curated local build. No installation, publication or game asset collection."""
import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

MODULES = ('__init__ __main__ animation animation_editing assets containers controller desktop '
           'diagnostics editing item_geometry item_editing item_parameters embedded_texture filtering nif package replay scene skinning sources texture_editing viewport normal_maps normalization workflow').split()
CODEC = '__init__ bc nif_texture png roundtrip mip_generation'.split()
DOCS = ['README.md','LIMITATIONS.md']
REQUIRED = {'numpy':'2.2.6','pillow':'11.3.0','PyOpenGL':'3.1.10','pyopengltk':'0.0.4',
            'pyinstaller':'6.22.2','altgraph':'0.17.5','packaging':'26.3',
            'pefile':'2024.8.26','pyinstaller-hooks-contrib':'2026.7',
            'pywin32-ctypes':'0.2.3','setuptools':'84.0.0'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(output):
    root = Path(__file__).resolve().parents[1]
    output = output.absolute()
    if output.exists() or output.is_symlink() or any(p.name.casefold() == 'packed' for p in (output,*output.parents)):
        raise ValueError('output must be new and outside Packed')
    if any(p.exists() and (p.is_symlink() or p.is_junction()) for p in output.parents):
        raise ValueError('linked output parent rejected')
    if sys.platform != 'win32' or sys.version_info[:2] != (3,12):
        raise ValueError('Windows Python 3.12 required')
    for name, version in REQUIRED.items():
        if metadata.version(name) != version:
            raise ValueError('unexpected dependency version: '+name)
    files = [f'model_viewer/{m}.py' for m in MODULES]
    files += [f'tools/texture_codec/{m}.py' for m in CODEC]
    files += ['tools/dv2_archive/src/dv2lib.py','tools/dv2_archive/tests/synth_builder.py']
    files += [p.relative_to(root).as_posix() for p in sorted((root/'tests').glob('test_model_viewer*.py')) if 'physics' not in p.name]
    files += ['tests/'+name for name in ('test_item_editing.py','test_item_geometry.py','test_item_parameters.py','test_embedded_texture.py','test_texture_roundtrip.py')]
    files += ['model_viewer/docs/'+name for name in DOCS]
    files += ['tools/build_model_viewer.py','tools/pyinstaller_hooks/hook-OpenGL.py',
              'tools/windows_version.txt','model_viewer/LICENSE']
    files += [p.relative_to(root).as_posix() for p in (root/'model_viewer/LICENSES').rglob('*') if p.is_file()]
    identities = {name:digest(root/name) for name in files}
    output.mkdir(parents=True)
    source = output/'source'; source.mkdir()
    for name in files:
        destination = source/name; destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(root/name,destination)
    (source/'launcher.py').write_text('from model_viewer.__main__ import main\nmain()\n',encoding='utf-8')
    (source/'requirements.txt').write_text(''.join(f'{k}=={v}\n' for k,v in REQUIRED.items()),encoding='utf-8')
    shutil.copy2(root/'model_viewer/docs/README.md',source/'README.md')
    notices = ['# Third-party dependencies\n',
               'Own code: AGPL-3.0-only. Local candidate, not a public release.\n',
               'The reused texture-codec mip generation module is AGPL-3.0-only (PmNz8); see LICENSES/codec-AGPL-3.0.txt.\n',
               'Original dependency license files accompany this record under LICENSES.\n']
    shutil.copytree(root/'model_viewer/LICENSES',source/'LICENSES')
    shutil.copy2(root/'model_viewer/LICENSE',source/'LICENSE')
    shutil.copy2(root/'model_viewer/LICENSE',source/'LICENSES/codec-AGPL-3.0.txt')
    for name,version in REQUIRED.items():
        dist = metadata.distribution(name)
        notices.append(f'\n## {name} {version}\nLicense metadata: {dist.metadata.get("License-Expression") or dist.metadata.get("License") or "see dependency license files"}\n')
        for item in dist.files or []:
            if any(word in item.name.casefold() for word in ('license','copying','copyright')):
                src = Path(dist.locate_file(item))
                if src.is_file():
                    dst = source/'LICENSES'/name/Path(*item.parts)
                    if '..' in item.parts or item.is_absolute():
                        raise ValueError('unsafe dependency license path')
                    dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
    (source/'THIRD_PARTY_NOTICES.md').write_text('\n'.join(notices),encoding='utf-8')
    subprocess.run([sys.executable,'-B','-m','unittest','discover','-s','tests'],cwd=source,check=True)
    command = [sys.executable,'-m','PyInstaller','--onedir','--windowed','--noupx','--name','Divinity2ModelViewer',
               '--distpath',str(output/'binary'),'--workpath',str(output/'build'),
               '--specpath',str(output),'--collect-submodules','OpenGL.platform',
               '--hidden-import','OpenGL.arrays.numpymodule',
               '--additional-hooks-dir',str(source/'tools/pyinstaller_hooks'),
               '--version-file',str(source/'tools/windows_version.txt'),str(source/'launcher.py')]
    environment = os.environ.copy()
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    for key in ('PYTHONPATH','PYTHONHOME','TCL_LIBRARY','TK_LIBRARY','TCLLIBPATH'):
        environment.pop(key,None)
    environment['PATH']=os.pathsep.join(map(str,(Path(sys.prefix)/'Scripts',Path(sys.base_prefix),Path(sys.base_prefix)/'DLLs',Path(os.environ['SystemRoot'])/'System32',Path(os.environ['SystemRoot']))))
    for name in ('tests','test','unittest','doctest','pytest','numpy.testing','numpy._core.tests','OpenGL.GLUT'):
        command[command.index(str(source/'launcher.py')):command.index(str(source/'launcher.py'))]=['--exclude-module',name]
    subprocess.run(command,cwd=source,env=environment,check=True)
    binary = output/'binary/Divinity2ModelViewer'
    if any('glut' in p.name.casefold() for p in binary.rglob('*.dll')):
        raise RuntimeError('Unused GLUT DLL leaked into the distribution')
    for name in ('README.md','THIRD_PARTY_NOTICES.md','LICENSE'):
        shutil.copy2(source/name,binary/name)
    shutil.copytree(source/'LICENSES',binary/'LICENSES')
    for name in DOCS:
        shutil.copy2(root/'model_viewer/docs'/name,binary/name)
    if identities != {name:digest(root/name) for name in files}:
        raise RuntimeError('source changed during build')
    version = subprocess.check_output([sys.executable,'-c','from model_viewer import __version__; print(__version__)'],cwd=source,text=True).strip()
    manifest = dict(version=version,experimental=True,published=False,dependencies=REQUIRED,
                    repository_revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
                    source_hashes=identities,
                    source_files={p.relative_to(source).as_posix():digest(p) for p in sorted(source.rglob('*')) if p.is_file() and '__pycache__' not in p.parts},
                    binary_files={p.relative_to(binary).as_posix():digest(p) for p in sorted(binary.rglob('*')) if p.is_file()})
    for folder in (source,binary):
        (folder/'BUILD_INFO.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps(dict(source=str(source),binary=str(binary))))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args().output)
