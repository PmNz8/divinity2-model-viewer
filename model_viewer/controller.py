"""UI-independent preview state. Source choices are explicit and scoped."""
from dataclasses import replace
from .assets import load_model, render_component, decode_image
from . import scene, animation, skinning, containers
from .nif import parse, NifError
from .package import build, save_new


class Preview:
    def __init__(self, corpus):
        self.corpus = corpus
        self.model = None
        self.primary = None
        self.skeleton_source = None
        self.animation_source = None
        self.skeleton = {}
        self.clips = []
        self.texture_sources = {}
        self.images = {}
        self.selected = ()
        self.bindings = {}
        self.container = None
        self.skeleton_root = None
        self.animation_roots = ()

    def open_model(self, occurrence):
        source = self.corpus.read(occurrence)
        model = load_model(source.payload)
        if not model.components:
            raise NifError('source contains no supported displayable components')
        kind = model.document.blocks[model.document.roots[0]].type if model.document.roots else ''
        container, skeleton, roots, skeleton_root = None, {}, (), None
        if kind == 'MdlMan::CModelTemplateDataEntry':
            container = containers.cat(model.document)
            sk = [e for e in container['entries'] if e['kind'] == 'CSkeletonDataEntry']
            if len(sk) != 1:
                raise NifError('CAT preview requires one embedded skeleton')
            skeleton_root = sk[0]['root']
            skeleton = containers.subtree(model.nodes, skeleton_root)
            owned = set(skeleton)
            for entry in container['entries']:
                if entry['kind'] == 'CMeshDataEntry':
                    subtree = containers.subtree(model.nodes, entry['root'])
                    if owned.intersection(subtree):
                        raise NifError('overlapping CAT scene ownership')
                    owned.update(subtree)
            if owned != set(model.nodes):
                raise NifError('unowned CAT scene nodes')
            roots = tuple(i for e in container['entries'] if e['kind'] == 'CAnimationDataEntry' for i in e['clips'])
            if len(set(roots)) != len(roots):
                raise NifError('duplicate CAT clip ownership')
        elif kind == 'CStreamableAssetData':
            container = containers.item(model.document)
            if set(containers.subtree(model.nodes, container['root'])) != set(model.nodes):
                raise NifError('unowned ITEM scene nodes')
            if container.get('clips'):
                skeleton_root = container['root']
                skeleton = containers.subtree(model.nodes, skeleton_root)
                # Retain all metadata if a clip uses unsupported property channels.
                # Never silently play a partially decoded sequence.
                try:
                    for index in container['clips']:
                        animation.compile_clip(model.document, index, skeleton)
                except NifError as exc:
                    container['animation_preview_error'] = str(exc)
                    skeleton, skeleton_root = {}, None
                else:
                    roots = container['clips']
        try:
            clips = [animation.compile_clip(model.document, i, skeleton) for i in roots]
        except NifError as exc:
            if kind != 'MdlMan::CModelTemplateDataEntry':
                raise
            # Preserve every native clip and its ownership, but never play a
            # partially bound sequence or invent a runtime-only root node.
            container['animation_preview_error'] = str(exc)
            clips, roots = [], ()
        selected = (next(iter(model.components)),)
        bindings = self._bind(skeleton, selected, model) if skeleton else {}
        # All validation above occurs before replacing the current selection.
        self.__init__(self.corpus)
        self.primary, self.model = source, model
        # An explicit UI default, not an inferred LOD relation.
        self.selected = selected
        self.container, self.skeleton, self.skeleton_root = container, skeleton, skeleton_root
        self.clips, self.animation_roots = clips, roots
        if skeleton:
            self.skeleton_source = source
            self.bindings = bindings
        if roots:
            self.animation_source = source

    def set_components(self, indices):
        indices = tuple(indices)
        if not indices or len(set(indices)) != len(indices) or any(i not in self.model.components for i in indices):
            raise NifError('invalid component selection')
        bindings = self._bind(self.skeleton, indices) if self.skeleton else {}
        self.selected, self.bindings = indices, bindings

    def _bind(self, nodes, indices, model=None):
        model = model or self.model
        bindings = {}
        for index in indices:
            component = model.components[index]
            if component['skin'] != -1:
                inst = scene.skin_instance(model.document, component['skin'])
                data = scene.skin_data(model.document, inst['data'])
                bindings[index] = skinning.bind(inst, data, model.nodes, nodes,
                                                len(component['geometry']['vertices']))
        return bindings

    def set_skeleton(self, occurrence):
        if self.model is None:
            raise NifError('open a model first')
        source = self.corpus.read(occurrence)
        model = load_model(source.payload)
        nodes = model.nodes
        if not nodes or model.components:
            raise NifError('select a skeleton-only NiNode resource')
        bindings = self._bind(nodes, self.selected)
        self.skeleton_source, self.skeleton, self.bindings = source, nodes, bindings
        self.skeleton_root = None
        self.animation_source, self.clips = None, []
        self.animation_roots = ()

    def set_animation(self, occurrence):
        if not self.skeleton:
            raise NifError('select an external skeleton first')
        source = self.corpus.read(occurrence)
        doc = parse(source.payload)
        from .workflow import target_diagnostics
        check=target_diagnostics(doc,self.skeleton)
        if check['missing'] or check['ambiguous']:
            raise NifError('Animation target mismatch. Missing: '+(', '.join(check['missing']) or 'none')+
                           '; ambiguous: '+(', '.join(check['ambiguous']) or 'none'))
        clips = [animation.compile_clip(doc, i, self.skeleton) for i in doc.roots]
        if not clips:
            raise NifError('no supported animation clips')
        self.animation_source, self.clips = source, clips
        self.animation_roots = doc.roots

    def set_texture(self, block, occurrence):
        if block not in self.model.texture_references:
            raise NifError('texture reference absent')
        reference = self.model.texture_references[block]
        source = self.corpus.read(occurrence)
        if not reference['external']:
            if source != self.primary:
                raise NifError('Embedded texture must use its owning model resource')
            from .embedded_texture import resource
            from .assets import RGBAImage
            _, texture = resource(source.payload,block)
            mip=texture.mips[0]
            image=RGBAImage((mip.width,mip.height),texture.decode_mip())
        else:
            image = decode_image(source.payload)
        self.texture_sources[block], self.images[block] = source, image

    def texture_key(self, block):
        ref=self.model.texture_references[block]
        return (self.texture_sources[block].logical_path.casefold(),
                None if ref['external'] else ref['pixel_data'])

    def frame(self, clip_index=None, time=0.):
        if self.model is None:
            return [], {}, {}
        nodes = self.skeleton
        if clip_index is not None:
            nodes = animation.posed_nodes(self.clips[clip_index], nodes, time)
        parents, world = scene.hierarchy(nodes) if nodes else ({}, {})
        meshes = []
        for index in self.selected:
            mesh = render_component(self.model, index, self.images)
            if index in self.bindings:
                mesh['vertices'] = skinning.deform(self.bindings[index], world,
                                                  self.model.components[index]['geometry']['vertices'])
            elif (clip_index is not None and index in world and
                  self.skeleton_source == self.primary and self.model.components[index]['skin'] == -1):
                mesh['vertices'] = tuple(scene.point(world[index], v)
                                         for v in self.model.components[index]['geometry']['vertices'])
            elif self.model.components[index]['skin'] != -1:
                mesh['warnings'].append('unposed source geometry; external skeleton not selected')
            meshes.append(mesh)
        return meshes, parents, world

    def package(self):
        if self.primary is None:
            raise NifError('open a model first')
        self.corpus.check()
        originals = [self.primary, *self.texture_sources.values()]
        if self.skeleton_source:
            originals.append(self.skeleton_source)
        if self.animation_source:
            originals.append(self.animation_source)
        # Rehash each used archive once, and reread every payload before export.
        checked, sources = set(), {}
        for old in originals:
            selected = self.corpus.select(old.logical_path, old.archive_name)
            fresh = self.corpus.read(selected, fresh_hash=old.archive_name not in checked)
            checked.add(old.archive_name)
            if fresh.payload != old.payload or fresh.archive_sha256 != old.archive_sha256:
                raise NifError('preview source identity changed before export')
            key = fresh.logical_path.casefold()
            if key in sources and sources[key] != fresh:
                raise NifError('conflicting sources selected for one logical path')
            sources[key] = fresh
        missing = [f'texture block {block}: {ref["filename"]}' for block, ref in self.model.texture_references.items()
                   if block not in self.texture_sources]
        if any(self.model.components[i]['skin'] != -1 for i in self.selected) and not self.skeleton:
            missing.append('external skeleton not selected')
        primary = sources[self.primary.logical_path.casefold()]
        sources[primary.logical_path.casefold()] = replace(primary,
            dependencies=tuple(s.logical_path for s in sources.values() if s.logical_path != primary.logical_path),
            unresolved=tuple(missing))
        self.corpus.check()
        result=build(sources.values(), self.primary.logical_path, assembly=self.assembly())
        return result

    def assembly(self):
        """Replayable preview recipe plus metadata derived from original blocks."""
        if self.primary is None:
            raise NifError('open a model first')
        components = []
        for index, c in self.model.components.items():
            node = self.model.nodes[index]
            geometry = c['geometry']
            components.append(dict(block=index, name=c['name'], data_block=node['data'],
                                   skin_block=c['skin'], selected=index in self.selected,
                                   parent=self.model.parents.get(index), world=self.model.world[index],
                                   vertices=len(geometry['vertices']), triangles=len(geometry['triangles']),
                                   uv_sets=len(geometry['uv_sets']), colors=bool(geometry['colors']),
                                   material=c['material'], texturing=c['texturing'], warnings=c['warnings']))
        recipe = dict(components=list(self.selected),
                      skeleton=dict(resource=self.skeleton_source.logical_path, root=self.skeleton_root) if self.skeleton_source else None,
                      animation=dict(resource=self.animation_source.logical_path, roots=self.animation_roots) if self.animation_source else None,
                      textures=[dict(block=b, resource=s.logical_path) for b,s in sorted(self.texture_sources.items())])
        unresolved = [f'texture block {b}: {r["filename"]}' for b,r in self.model.texture_references.items() if b not in self.texture_sources]
        if any(self.model.components[i]['skin'] != -1 for i in self.selected) and not self.skeleton:
            unresolved.append('external skeleton not selected')
        return dict(schema='divinity2.preview-assembly/1', recipe=recipe, components=components,
                    container=self.container, texture_references={str(k): v for k, v in self.model.texture_references.items()},
                    skeleton_nodes=[dict(block=i, name=n['name'], children=n['children'], transform=n['transform'])
                                    for i,n in sorted(self.skeleton.items())],
                    clips=[dict(root=i, name=c['name'], start=c['start'], stop=c['stop'])
                           for i,c in zip(self.animation_roots,self.clips)],
                    dependency_scope='primary_texture_references_and_selected_preview_roles',
                    dependency_status='unresolved' if unresolved else 'complete_for_declared_preview_scope',
                    unresolved=unresolved,
                    exclusions=['native edit/rebuild', 'engine shader equivalence', 'automatic LOD selection',
                                'manager transitions/events/root motion', 'complete game-runtime dependency graph'])

    def export(self, destination, *, normalize=False):
        from pathlib import Path
        if hasattr(self.corpus, 'root') and Path(destination).resolve().is_relative_to(self.corpus.root):
            raise NifError('export inside source corpus is forbidden')
        if normalize:
            from .normalization import normalized_preview
            return save_new(normalized_preview(self).package(), destination)
        return save_new(self.package(), destination)
