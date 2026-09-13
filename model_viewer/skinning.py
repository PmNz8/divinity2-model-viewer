"""Explicit external-skeleton binding and world-space linear blend skinning.

No auto-selected skeleton, LOD or inferred bone alias. Coordinates follow
world(bone) * stored bone-to-skin inverse bind * source vertex.
"""
from .nif import NifError
from .scene import matrix, multiply, point


def bind(instance, data, mesh_nodes, skeleton_nodes, vertex_count):
    if not data['has_weights'] or len(instance['bones']) != len(data['bones']):
        raise NifError('unsupported skin weight association')
    names = {}
    for index, obj in skeleton_nodes.items():
        names.setdefault(obj['name'], []).append(index)
    bindings, sums = [], [0.] * vertex_count
    for original, bone in zip(instance['bones'], data['bones']):
        if original not in mesh_nodes:
            raise NifError('missing mesh bone node')
        name = mesh_nodes[original]['name']
        matches = names.get(name, [])
        if not name or len(matches) != 1:
            raise NifError('missing/ambiguous external skin bone: ' + name)
        for vertex, weight in bone['weights']:
            if not 0 <= vertex < vertex_count:
                raise NifError('skin vertex outside owner geometry')
            sums[vertex] += weight
        bindings.append(dict(node=matches[0], name=name, inverse_bind=matrix(bone['transform']),
                             weights=bone['weights']))
    if any(abs(total-1.) > 1e-4 for total in sums):
        raise NifError('unsupported non-unit skin weight sum')
    return tuple(bindings)


def deform(bindings, world, vertices):
    out = [[0., 0., 0.] for _ in vertices]
    for bone in bindings:
        if bone['node'] not in world:
            raise NifError('posed skeleton missing bound bone')
        transform = multiply(world[bone['node']], bone['inverse_bind'])
        for index, weight in bone['weights']:
            p = point(transform, vertices[index])
            for axis in range(3):
                out[index][axis] += weight*p[axis]
    return tuple(tuple(p) for p in out)
