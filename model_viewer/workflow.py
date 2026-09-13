"""Read-only association proposals and evidence-bounded assembly diagnostics."""
from collections import Counter
from copy import copy
import math
from . import scene,animation
from .assets import decode_image


def texture_proposals(preview):
    if not preview.model: raise ValueError('Open a model first')
    if not hasattr(preview.corpus,'texture_candidates'): raise ValueError('Open a Packed corpus to choose texture sources')
    return [dict(block=i,reference=ref['filename'],current=preview.texture_sources.get(i),
                 candidates=tuple(preview.corpus.texture_candidates(ref['filename'])) if ref['external'] else
                 (preview.corpus.select(preview.primary.logical_path,preview.primary.archive_name),))
            for i,ref in preview.model.texture_references.items()]


def apply_textures(preview,choices):
    """Validate/decode the complete confirmed batch before changing state."""
    staged=copy(preview)
    staged.texture_sources=dict(preview.texture_sources); staged.images=dict(preview.images)
    for block,occurrence in choices.items():
        if block not in preview.model.texture_references:
            raise ValueError('Invalid texture block')
        if preview.model.texture_references[block]['external']:
            source=preview.corpus.read(occurrence)
            staged.texture_sources[block]=source; staged.images[block]=decode_image(source.payload)
        else:
            staged.set_texture(block,occurrence)
    preview.corpus.check()
    preview.texture_sources=staged.texture_sources; preview.images=staged.images
    return len(choices)


def target_diagnostics(doc,nodes,roots=None):
    names=Counter(n['name'] for n in nodes.values()); required=set(); failures=[]
    for index in doc.roots if roots is None else roots:
        try: required.update(t['node_name'] for t in animation.sequence(doc,index)['controlled'])
        except ValueError as exc: failures.append(f'root #{index}: {exc}')
    return dict(missing=sorted(n for n in required if names[n]==0),
                ambiguous=sorted(n for n in required if names[n]>1),parse_errors=failures)


def assembly_diagnostics(preview):
    if not preview.model: return ['Open a model first.']
    lines=['Associations are explicit selections, not certified game dependencies.']
    container = preview.container or {}
    if container:
        lines.append('Embedded model edit target (whole native resource): '+preview.primary.logical_path)
        lines.append('External mesh labels are not automatic patch targets. Unedited container data is retained.')
    if container.get('animation_preview_error'):
        lines.append('Animation preview unavailable; native clips preserved unchanged: '+container['animation_preview_error'])
    if container.get('clips'):
        lines.append('ITEM embedded animation metadata: model '+container['model_reference']+
                     '; target '+container['target_name'])
        for row, block in zip(container['sequences'], container['clips']):
            lines.append(f"ITEM sequence {row['sequence_index']}: {row['reference']} -> embedded block #{block}")
        lines.append('Reference filenames are metadata, not instructions to load external files. Manager transitions are not simulated.')
        if container.get('animation_preview_error'):
            lines.append('ITEM animation preview unavailable: '+container['animation_preview_error'])
    for label,source in [('Model',preview.primary),('Skeleton',preview.skeleton_source),('Animation',preview.animation_source)]:
        lines.append(f'{label}: '+(source.logical_path+' ['+source.archive_name+']' if source else 'not selected'))
    if preview.skeleton:
        lines.append('Without KF: external skeleton reference pose, not necessarily mesh bind pose.')
        _,world=scene.hierarchy(preview.skeleton)
        residuals=[]
        for index,bindings in preview.bindings.items():
            geo=preview.model.components[index]['geometry']; vertices=geo['vertices']
            size=math.sqrt(sum((max(v[a] for v in vertices)-min(v[a] for v in vertices))**2 for a in range(3)))
            matrices=[scene.multiply(world[b['node']],b['inverse_bind']) for b in bindings]
            if not matrices: continue
            # Common transform cancels global offsets; disagreements flag a
            # reference/bind mismatch, NOT an automatically invalid skeleton.
            first=matrices[0]
            residual=max(max(abs(m[i][j]-first[i][j])/(size if j==3 and size else 1.) for i in range(3) for j in range(4)) for m in matrices)
            residuals.append(residual)
            lines.append(f'Component #{index}: reference/bind transform spread {residual:.5g} (translation normalized by mesh diagonal).')
        if residuals and max(residuals)>0.01:
            lines.append('WARNING: reference transforms differ from mesh binding; check proportions with the intended KF. This alone does not prove an invalid pair.')
    if preview.animation_source:
        from .nif import parse
        report=target_diagnostics(parse(preview.animation_source.payload),preview.skeleton,preview.animation_roots)
        lines+=['Missing targets: '+(', '.join(report['missing']) or 'none'),
                'Ambiguous targets: '+(', '.join(report['ambiguous']) or 'none')]+report['parse_errors']
        lines.append(f'{len(preview.clips)} decoded clips. Matching names do not prove compatible scale/proportions.')
    missing=[r['filename'] for i,r in preview.model.texture_references.items() if r['external'] and i not in preview.texture_sources]
    lines.append('Missing texture sources: '+(', '.join(missing) or 'none'))
    lines.append('Physics, manager transitions and complete game dependency graph are outside this report.')
    return lines
