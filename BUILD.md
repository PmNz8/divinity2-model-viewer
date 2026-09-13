# Build Model Viewer 0.1.10

Windows, Python3.12.6 x64. Install requirements.txt into an isolated environment,
then run tools/build_model_viewer.py --output NEW_DIRECTORY from this checkout.
The source tree contains the curated tests, codecs, build script and full notices;
no sibling project or research checkout is needed. The script runs tests before
building. The resulting binary folder is portable; keep every runtime file.

The candidate is unsigned. WGL rendering was tested on Intel UHD730. Existing
optional FreeGLUT VC90/VC100 dependency warnings remain; cross-machine testing
of this final private preview is not certified. This is a private pre-release,
not completion of public-release qualification.
