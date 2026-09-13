"""Offline preview reconstruction solely from validated package originals."""
from .nif import NifError


class PackageCorpus:
    """Read-only source adapter; physical archive hashes are provenance only."""
    def __init__(self, sources):
        self.sources = {s.logical_path.casefold(): s for s in sources}

    def select(self, path, archive=None):
        source = self.sources.get(path.casefold())
        if source is None or (archive is not None and source.archive_name != archive):
            raise NifError('assembly resource absent')
        return source

    def read(self, source, **kwargs):
        if self.sources.get(source.logical_path.casefold()) != source:
            raise NifError('unknown package source')
        return source

    def check(self):
        pass


def restore(sources, primary, recipe):
    from .controller import Preview
    corpus = PackageCorpus(sources)
    preview = Preview(corpus)
    preview.open_model(corpus.select(primary))
    if not isinstance(recipe, dict) or set(recipe) != {'components','skeleton','animation','textures'}:
        raise NifError('invalid assembly recipe')
    indices = recipe['components']
    if not isinstance(indices, list) or any(type(i) is not int for i in indices):
        raise NifError('invalid component recipe')
    preview.set_components(indices)
    skeleton = recipe['skeleton']
    if skeleton is not None:
        if set(skeleton) != {'resource','root'}:
            raise NifError('invalid skeleton recipe')
        source = corpus.select(skeleton['resource'])
        if source.logical_path.casefold() != primary.casefold():
            preview.set_skeleton(source)
        if preview.skeleton_root != skeleton['root'] or not preview.skeleton:
            raise NifError('invalid skeleton root')
    elif preview.skeleton:
        raise NifError('missing embedded skeleton recipe')
    anim = recipe['animation']
    if anim is not None:
        if set(anim) != {'resource','roots'}:
            raise NifError('invalid animation recipe')
        source = corpus.select(anim['resource'])
        if source.logical_path.casefold() != primary.casefold():
            preview.set_animation(source)
        if list(preview.animation_roots) != list(anim['roots']) or not preview.clips:
            raise NifError('invalid animation roots')
    elif preview.clips:
        raise NifError('missing embedded animation recipe')
    if not isinstance(recipe['textures'], list):
        raise NifError('invalid texture recipe')
    seen = set()
    for row in recipe['textures']:
        if not isinstance(row, dict) or set(row) != {'block','resource'} or type(row['block']) is not int or row['block'] in seen:
            raise NifError('invalid/duplicate texture mapping')
        seen.add(row['block'])
        preview.set_texture(row['block'], corpus.select(row['resource']))
    return preview
