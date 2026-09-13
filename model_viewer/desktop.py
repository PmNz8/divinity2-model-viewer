"""Native read-only source browser and explicit NIF preview workflow."""
from pathlib import Path
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .sources import Corpus
from .controller import Preview
from .viewport import Viewport
from .filtering import path_filter


class App(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.pack(fill='both', expand=True)
        self.preview = None
        self.rows = []
        self.playing = False
        self.last_tick = time.perf_counter()
        self.clock_value = 0.
        self.frame_count = 0
        self.updating = False
        self.callback = None
        self.filter_callback = None
        self.status = tk.StringVar(value='Open a Packed corpus. Source archives are read-only; export creates a new file.')
        toolbar = ttk.Frame(self); toolbar.pack(fill='x', padx=6, pady=6)
        ttk.Button(toolbar, text='Open Packed folder', command=lambda:self.guard(self.choose_corpus)).pack(side='left')
        ttk.Button(toolbar, text='Open package', command=lambda:self.guard(self.choose_package)).pack(side='left')
        ttk.Button(toolbar, text='Export source package', command=lambda:self.guard(self.export_dialog)).pack(side='left', padx=6)
        ttk.Button(toolbar, text='Diagnostyka modelu', command=lambda:self.guard(self.normalization_dialog)).pack(side='left')
        self.normalize_export=tk.BooleanVar(value=True)
        ttk.Checkbutton(toolbar,text='Normalizuj do edycji',variable=self.normalize_export).pack(side='left')
        self.source_label = ttk.Label(toolbar, text='No source selected'); self.source_label.pack(side='left')
        panes = ttk.Panedwindow(self, orient='horizontal'); panes.pack(fill='both', expand=True)
        browser = ttk.Frame(panes, width=330); panes.add(browser, weight=1)
        self.search = tk.StringVar()
        ttk.Label(browser, text='Live filter: text or * / ? pattern (first 500)').pack(anchor='w')
        entry = ttk.Entry(browser, textvariable=self.search); entry.pack(fill='x')
        entry.bind('<Return>', lambda e:self.refresh_browser())
        ttk.Button(browser, text='Search', command=self.refresh_browser).pack(fill='x')
        self.search_trace = self.search.trace_add('write', self.schedule_filter)
        browser_list = ttk.Frame(browser); browser_list.pack(fill='both', expand=True)
        self.browser = ttk.Treeview(browser_list, columns=('archive',), show='tree headings', selectmode='browse')
        self.browser.heading('#0', text='Resource'); self.browser.heading('archive', text='Physical archive')
        self.browser.column('#0', width=245); self.browser.column('archive', width=130)
        self.browser.grid(row=0,column=0,sticky='nsew')
        browser_list.rowconfigure(0,weight=1); browser_list.columnconfigure(0,weight=1)
        for orient, command, option, row, column, sticky in [('vertical',self.browser.yview,'yscrollcommand',0,1,'ns'),('horizontal',self.browser.xview,'xscrollcommand',1,0,'ew')]:
            bar = ttk.Scrollbar(browser_list,orient=orient,command=command)
            bar.grid(row=row,column=column,sticky=sticky); self.browser.configure(**{option:bar.set})
        buttons = ttk.Frame(browser); buttons.pack(fill='x')
        for label, role in [('Model','model'), ('Skeleton','skeleton'), ('Animation','animation')]:
            ttk.Button(buttons,text='Use as '+label,command=lambda r=role:self.guard(lambda:self.use_selected(r))).pack(fill='x')
        center = ttk.Frame(panes); panes.add(center, weight=4)
        self.viewport = Viewport(center); self.viewport.pack(fill='both', expand=True)
        controls = ttk.Frame(center); controls.pack(fill='x')
        self.clip = ttk.Combobox(controls, state='readonly', width=24)
        self.clip.pack(side='left'); self.clip.bind('<<ComboboxSelected>>',lambda e:self.guard(self.select_clip))
        self.play_button = ttk.Button(controls,text='Play',command=self.toggle_play); self.play_button.pack(side='left')
        self.show_skeleton = tk.BooleanVar(value=False)
        ttk.Checkbutton(controls,text='Skeleton overlay',variable=self.show_skeleton,
                        command=lambda:self.guard(lambda:self.draw(False))).pack(side='left')
        self.slider = ttk.Scale(center,from_=0,to=1,command=self.seek); self.slider.pack(fill='x')
        self.time_label = ttk.Label(center,text='Clip-local seconds; preview loop at 1x (no root-motion extraction)')
        self.time_label.pack(anchor='w')
        side = ttk.Frame(panes,width=280); panes.add(side,weight=1)
        ttk.Label(side,text='Components: select explicitly; no automatic LOD').pack(anchor='w')
        self.components = tk.Listbox(side,selectmode='extended',exportselection=False,height=7)
        self.components.pack(fill='x')
        ttk.Button(side,text='Show selected components',command=lambda:self.guard(self.select_components)).pack(fill='x')
        ttk.Label(side,text='Texture references (all slots)').pack(anchor='w',pady=(10,0))
        self.textures = tk.Listbox(side,exportselection=False,height=6); self.textures.pack(fill='x')
        ttk.Button(side,text='Choose texture source…',command=lambda:self.guard(self.texture_dialog)).pack(fill='x')
        ttk.Button(side,text='Match textures in batch…',command=lambda:self.guard(self.texture_batch_dialog)).pack(fill='x')
        ttk.Button(side,text='Diagnose assembly…',command=lambda:self.guard(self.diagnose)).pack(fill='x')
        self.normal_enabled=tk.BooleanVar(value=True); self.normal_y=tk.BooleanVar(value=False)
        self.normal_mode=tk.StringVar(value='AUTO')
        ttk.Checkbutton(side,text='Normal-map preview',variable=self.normal_enabled,command=lambda:self.guard(lambda:self.draw(False))).pack(anchor='w')
        normal_modes=ttk.Combobox(side,textvariable=self.normal_mode,values=('AUTO','RGB','AGB','AG'),state='readonly')
        normal_modes.pack(fill='x'); normal_modes.bind('<<ComboboxSelected>>',lambda e:self.guard(lambda:self.draw(False)))
        ttk.Checkbutton(side,text='Invert normal Y (preview only)',variable=self.normal_y,command=lambda:self.guard(lambda:self.draw(False))).pack(anchor='w')
        self.details = tk.Text(side,width=35,height=16,wrap='word',state='disabled'); self.details.pack(fill='both',expand=True)
        ttk.Label(self,textvariable=self.status,wraplength=1300).pack(fill='x',padx=6,pady=6)
        self.callback = self.after(16,self.tick)

    def guard(self, action):
        try:
            return action()
        except Exception as exc:
            self.playing = False
            self.play_button.configure(text='Play')
            self.status.set(str(exc))
            messagebox.showerror('Operation rejected',str(exc),parent=self)

    def choose_corpus(self):
        path = filedialog.askdirectory(title='Select Packed corpus',parent=self)
        if path:
            self.open_corpus(path)

    def choose_package(self):
        path = filedialog.askopenfilename(title='Open verified source package', parent=self,
                                          filetypes=[('D2 model package','*.d2model')])
        if path:
            self.open_package(path)

    def open_package(self, path):
        from .package import open_preview, MAX_PACKAGE
        path = Path(path)
        if path.stat().st_size > MAX_PACKAGE + 16*1024*1024:
            raise ValueError('package too large')
        preview = open_preview(path.read_bytes())
        self.preview = preview
        self.playing = False; self.play_button.configure(text='Play')
        self.browser.delete(*self.browser.get_children()); self.rows = []
        self.populate_model()
        self.source_label.configure(text=str(path)+' — offline package')
        self.draw(True)
        self.status.set('Verified originals and assembly. Offline preview; archive hashes are recorded provenance.')

    def populate_model(self):
        self.components.delete(0,'end')
        for row,(i,c) in enumerate(self.preview.model.components.items()):
            self.components.insert('end',f'#{i} {c["name"]} ({len(c["geometry"]["vertices"])} vertices)')
            if i in self.preview.selected:
                self.components.selection_set(row)
        self.textures.delete(0,'end')
        for i,r in self.preview.model.texture_references.items():
            self.textures.insert('end',f'#{i} {r["filename"]}')
        self.clip.configure(values=[c['name'] for c in self.preview.clips]); self.clip.set('')
        if self.preview.clips:
            self.clip.current(0); self.select_clip()

    def open_corpus(self,path):
        self.status.set('Indexing complete archive corpus…'); self.update_idletasks()
        corpus = Corpus(path)
        self.preview = Preview(corpus)
        self.playing = False
        self.play_button.configure(text='Play')
        self.clock_value = 0.
        self.details.configure(state='normal'); self.details.delete('1.0','end'); self.details.configure(state='disabled')
        self.time_label.configure(text='Select a model; drag to orbit, mouse wheel to zoom.')
        self.viewport.set_meshes([])
        self.viewport.set_skeleton({}, {})
        self.components.delete(0,'end'); self.textures.delete(0,'end')
        self.clip.configure(values=()); self.clip.set('')
        self.source_label.configure(text=str(path))
        self.status.set(f'{len(corpus.archives)} archives / {len(corpus.entries)} logical paths. Duplicate sources require explicit selection.')
        self.refresh_browser()

    def schedule_filter(self, *_):
        if self.filter_callback is not None:
            self.after_cancel(self.filter_callback)
        self.filter_callback = self.after(150, self.refresh_browser)

    def refresh_browser(self):
        if self.filter_callback is not None:
            self.after_cancel(self.filter_callback)
            self.filter_callback = None
        self.browser.delete(*self.browser.get_children())
        self.rows = []
        if not self.preview or not hasattr(self.preview.corpus, 'entries'):
            return
        matches = path_filter(self.search.get())
        for key in sorted(self.preview.corpus.entries):
            if not matches(key) or not key.endswith(('.nif','.kf','.cat','.item')):
                continue
            for row in self.preview.corpus.entries[key]:
                i = len(self.rows); self.rows.append(row)
                self.browser.insert('', 'end', iid=str(i), text=row.path, values=(row.archive,))
                if len(self.rows) >= 500:
                    return

    def use_selected(self, role):
        rows = self.browser.selection()
        if not rows:
            raise ValueError('Select one physical resource row first')
        self.load_occurrence(self.rows[int(rows[0])],role)

    def load_occurrence(self,row,role):
        self.playing = False; self.play_button.configure(text='Play')
        if role == 'model':
            self.preview.open_model(row)
            self.populate_model()
            self.source_label.configure(text=row.path+' — '+row.archive)
        elif role == 'skeleton':
            self.preview.set_skeleton(row)
            self.clip.configure(values=()); self.clip.set('')
        elif role == 'animation':
            self.preview.set_animation(row)
            self.clip.configure(values=[c['name'] for c in self.preview.clips]); self.clip.current(0)
            self.select_clip()
        else:
            raise ValueError('unknown source role')
        self.draw(True)
        self.status.set('Loaded '+role+': '+row.path+' from '+row.archive)

    def select_components(self):
        if not self.preview or not self.preview.model:
            return
        keys = list(self.preview.model.components)
        self.preview.set_components([keys[i] for i in self.components.curselection()])
        self.draw(True)

    def texture_dialog(self):
        if not self.preview or not hasattr(self.preview.corpus, 'texture_candidates'):
            raise ValueError('Open a Packed corpus to change source associations')
        selected = self.textures.curselection()
        if not selected:
            raise ValueError('Select a texture reference first')
        block = list(self.preview.model.texture_references)[selected[0]]
        ref = self.preview.model.texture_references[block]
        if not ref['external']:
            source=self.preview.primary
            self.preview.set_texture(block,self.preview.corpus.select(source.logical_path,source.archive_name))
            self.draw(False)
            self.status.set('Loaded embedded texture from owning model, block '+str(ref['pixel_data']))
            return
        rows = self.preview.corpus.texture_candidates(ref['filename'])
        if not rows:
            raise ValueError('No same-stem NIF candidates; automatic mapping is unavailable')
        window = tk.Toplevel(self); window.title('Choose physical texture source'); window.geometry('850x300')
        ttk.Label(window,text='Filename matches are suggestions, not proof of game lookup. Choose explicitly.').pack(fill='x')
        listing = tk.Listbox(window,exportselection=False); listing.pack(fill='both',expand=True)
        for row in rows:
            listing.insert('end',row.path+' — '+row.archive)
        def accept():
            if not listing.curselection():
                raise ValueError('Select one candidate')
            self.preview.set_texture(block,rows[listing.curselection()[0]])
            self.draw(False); window.destroy()
        ttk.Button(window,text='Use selected source',command=lambda:self.guard(accept)).pack()

    def select_clip(self):
        i = self.clip.current()
        if i < 0:
            return
        clip = self.preview.clips[i]
        self.clock_value = clip['start']
        self.slider.configure(from_=clip['start'],to=clip['stop'])
        self.draw(False)

    def texture_batch_dialog(self):
        from .workflow import texture_proposals,apply_textures
        proposals=texture_proposals(self.preview) if self.preview else []
        if not proposals: raise ValueError('No texture references to match')
        preview=self.preview
        window=tk.Toplevel(self); window.title('Review texture associations'); window.geometry('1000x560')
        ttk.Label(window,text='Suggestions only. Confirm physical sources; ambiguous rows are never auto-selected.',wraplength=960).pack(fill='x')
        canvas=tk.Canvas(window); bar=ttk.Scrollbar(window,orient='vertical',command=canvas.yview)
        bar.pack(side='right',fill='y'); canvas.pack(fill='both',expand=True); canvas.configure(yscrollcommand=bar.set)
        body=ttk.Frame(canvas); canvas.create_window((0,0),window=body,anchor='nw')
        body.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        fields=[]
        for row in proposals:
            current=row['current']; candidates=row['candidates']
            status='current: '+current.archive_name if current else ('missing' if not candidates else ('ambiguous' if len(candidates)>1 else 'one suggestion'))
            ttk.Label(body,text=f"#{row['block']} {row['reference']} — {status}").pack(anchor='w',pady=(7,0))
            choices=['Keep current / leave unresolved']+[r.path+' — '+r.archive for r in candidates]
            box=ttk.Combobox(body,values=choices,width=125,state='readonly'); box.pack(fill='x')
            box.current(1 if not current and len(candidates)==1 else 0); fields.append((row,box))
        def accept():
            if self.preview is not preview: raise ValueError('Model changed; reopen matching dialog')
            chosen={row['block']:row['candidates'][box.current()-1] for row,box in fields if box.current()>0}
            count=apply_textures(preview,chosen)
            self.draw(False); self.status.set(f'Attached {count} explicitly confirmed texture sources.'); window.destroy()
        ttk.Button(window,text='Confirm selected associations',command=lambda:self.guard(accept)).pack(fill='x')
        return window,fields,accept

    def diagnose(self):
        from .workflow import assembly_diagnostics
        if not self.preview: raise ValueError('Open a model first')
        window=tk.Toplevel(self); window.title('Assembly diagnostics'); window.geometry('900x650')
        text=tk.Text(window,wrap='word'); text.pack(fill='both',expand=True)
        text.insert('1.0','\n\n'.join(assembly_diagnostics(self.preview))); text.configure(state='disabled')
        return window

    def toggle_play(self):
        if not self.preview or self.clip.current() < 0:
            self.status.set('Choose a skeleton and animation clip first.'); return
        self.playing = not self.playing
        self.last_tick = time.perf_counter()
        self.play_button.configure(text='Pause' if self.playing else 'Play')

    def seek(self,value):
        if not self.updating and self.preview and self.clip.current() >= 0:
            self.clock_value = float(value)
            self.guard(lambda:self.draw(False))

    def draw(self,fit=False,positions_only=False):
        if not self.preview or not self.preview.model:
            return
        i = self.clip.current()
        meshes,parents,world = self.preview.frame(i if i >= 0 else None,self.clock_value)
        if positions_only:
            self.viewport.update_vertices([m['vertices'] for m in meshes])
        else:
            self.viewport.normal_enabled=self.normal_enabled.get()
            self.viewport.normal_mode=self.normal_mode.get(); self.viewport.normal_flip_y=self.normal_y.get()
            self.viewport.set_meshes(meshes,fit=fit)
        self.viewport.set_skeleton(parents,world,self.show_skeleton.get())
        self.updating = True
        try:
            self.slider.set(self.clock_value)
        finally:
            self.updating = False
        self.time_label.configure(text=f'{self.clock_value:.3f} s — preview loop at 1x; no root-motion extraction')
        if not positions_only:
            warnings = sorted({v for m in meshes for v in m['warnings']})
            if self.preview.container:
                warnings.insert(0,'Embedded mesh edit target: whole '+self.preview.primary.logical_path)
                error=self.preview.container.get('animation_preview_error')
                if error: warnings.insert(0,'Animation preview unavailable (native clips preserved): '+error)
            self.details.configure(state='normal'); self.details.delete('1.0','end')
            self.details.insert('end','Preview scope:\n'+('\n'.join(warnings) or 'Base-color geometry preview.')+
                                '\n\nOriginal bytes and unimplemented data remain preserved. Viewer is read-only; no game installation.')
            self.details.configure(state='disabled')
        self.frame_count += 1

    def tick(self):
        now = time.perf_counter(); delta = now-self.last_tick; self.last_tick = now
        if self.playing and self.preview and self.clip.current() >= 0:
            clip = self.preview.clips[self.clip.current()]
            duration = clip['stop']-clip['start']
            self.clock_value = clip['start']+(self.clock_value-clip['start']+delta)%duration if duration > 0 else clip['start']
            self.guard(lambda:self.draw(False,positions_only=True))
        self.callback = self.after(16,self.tick)

    def normalization_dialog(self):
        from .normalization import diagnostics
        window=tk.Toplevel(self); window.title('Diagnostyka modelu')
        table=ttk.Treeview(window,columns=('found','action'),show='headings',height=5)
        table.heading('found',text='Wykryto'); table.heading('action',text='Przy eksporcie')
        table.column('found',width=255); table.column('action',width=300)
        for row in diagnostics(self.preview): table.insert('','end',values=row)
        table.pack(fill='both',expand=True,padx=10,pady=10)
        ttk.Label(window,text='Normalizacja dotyczy eksportowanej kopii. Oryginał pozostaje bez zmian.').pack(padx=10,pady=6)
        ttk.Checkbutton(window,text='Normalizuj do edycji',variable=self.normalize_export).pack(pady=6)
        return window

    def export_dialog(self):
        if not self.preview or not self.preview.model:
            raise ValueError('Open a model first')
        path = filedialog.asksaveasfilename(parent=self,title='Export new source package',
                                          defaultextension='.d2model',filetypes=[('Model source package','*.d2model')])
        if path:
            result = self.preview.export(path,normalize=self.normalize_export.get())
            coverage = self.preview.assembly()['dependency_status']
            self.status.set('Verified visual package: '+str(result)+' — '+coverage)

    def destroy(self):
        self.search.trace_remove('write', self.search_trace)
        if self.filter_callback is not None:
            self.after_cancel(self.filter_callback); self.filter_callback = None
        if self.callback:
            self.after_cancel(self.callback); self.callback = None
        super().destroy()


def main():
    from . import __version__
    root = tk.Tk(); root.title(f'Divinity II Model Viewer {__version__} — visual-only'); root.geometry('1450x900')
    root.minsize(1050,650)
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
