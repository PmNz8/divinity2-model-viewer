"""Package PyOpenGL for the viewer's WGL/Tk viewport, without GLUT binaries."""
from pathlib import PurePosixPath

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = ['OpenGL.platform.win32'] + collect_submodules('OpenGL.arrays')
excludedimports = ['OpenGL.GLUT']


def include_data(source):
    # Keep licenses and all unrelated PyOpenGL assets. Exclude before dependency
    # analysis, so unused FreeGLUT VC9/VC10 DLLs cannot introduce CRT warnings.
    name = PurePosixPath(str(source).replace('\\', '/')).name.casefold()
    return not (name.endswith('.dll') and 'glut' in name)


datas = [(source, target) for source, target in collect_data_files('OpenGL')
         if include_data(source)]
