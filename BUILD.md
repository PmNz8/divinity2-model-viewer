# Build Model Viewer 0.2.0

Windows, Python3.12.6 x64. Install requirements.txt into an isolated environment,
then run tools/build_model_viewer.py --output NEW_DIRECTORY from this checkout.
The source tree contains the curated tests, codecs, build script and full notices;
no sibling project or research checkout is needed. The script runs tests before
building. The resulting binary folder is portable; keep every runtime file.

The executable is unsigned. Rendering uses Tk/WGL, not GLUT. The local PyInstaller
hook excludes GLUT DLLs before dependency analysis and retains license notices.
The build rejects unexpected GLUT DLLs in the final distribution.

BUILD_INFO.json is generated for each build; it is not a checked-in snapshot of
an older release. Source commit, dependency versions and file hashes are recorded.
