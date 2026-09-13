"""Bounded owned-GUI audit used to verify the frozen distribution as well."""
import json
from pathlib import Path
import tkinter as tk
from .desktop import App


def run(package, output):
    output = Path(output)
    if output.exists():
        raise ValueError('diagnostic output must be new')
    root = tk.Tk(); root.geometry('1450x900')
    errors = []
    root.report_callback_exception = lambda kind, value, tb: errors.append(str(value))
    app = App(root)
    try:
        root.update()
        app.open_package(package); root.update()
        before = app.frame_count
        if app.preview.clips:
            app.play_button.invoke()
        root.after(1200, root.quit); root.mainloop()
        if app.playing:
            app.play_button.invoke()
        if app.preview.clips and app.frame_count - before < 2:
            raise RuntimeError('play button did not advance animation')
        if errors:
            raise RuntimeError(str(errors))
        exported=output.with_suffix('.d2model')
        expected=app.preview.package()
        app.preview.export(exported,normalize=False)
        if exported.read_bytes()!=expected:
            raise RuntimeError('Visual export differs from source-preserving package')
        from .package import open_preview
        if open_preview(exported.read_bytes()).package()!=expected:
            raise RuntimeError('Visual export did not roundtrip exactly')
        result = dict(package=str(Path(package).resolve()),
                      components=len(app.preview.model.components), clips=len(app.preview.clips),
                      frames=app.frame_count-before, context=app.viewport.context_info,
                      dependency_status=app.preview.assembly()['dependency_status'],
                      callback_errors=errors,visual_export_roundtrip=True)
    finally:
        root.destroy()
    result['viewport_disposed'] = app.viewport.disposed
    with output.open('x',encoding='utf-8') as stream:
        json.dump(result,stream,indent=2); stream.write('\n')
