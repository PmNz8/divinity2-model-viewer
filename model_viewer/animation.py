"""Bounded DIV2 animation decoding; source bytes remain authoritative."""
import bisect
import math
from .nif import Reader, NifError
from .scene import ref, name


def _reader(doc, index, kind):
    if doc.blocks[index].type != kind:
        raise NifError('unsupported animation class: ' + doc.blocks[index].type)
    return Reader(doc.body(index))


def _floats(r, n):
    return r.vectors(1, n)[0]


def _pose(r):
    return dict(translation=_floats(r, 3), quaternion=_floats(r, 4), scale=_floats(r, 1)[0])


def sequence(doc, index):
    r = _reader(doc, index, 'NiControllerSequence')
    out = dict(name=name(r, doc))
    out['div2_ints'] = r.unpack(f'{r.count(65536)}i')
    out['div2_ref'] = ref(r, doc)
    count, out['grow_by'] = r.count(16384), r.one('I')
    controlled = []
    for _ in range(count):
        target = dict(interpolator=ref(r, doc), controller=ref(r, doc))
        for key in ('node_name', 'property_type', 'controller_type', 'controller_id', 'interpolator_id'):
            target[key] = name(r, doc)
        controlled.append(target)
    out.update(controlled=tuple(controlled), weight=_floats(r, 1)[0],
               text_keys=ref(r, doc), cycle=r.one('I'))
    out['frequency'], out['start'], out['stop'] = _floats(r, 3)
    out.update(manager=ref(r, doc), accum_root=name(r, doc), accum_flags=r.one('I'))
    r.finish()
    if out['stop'] < out['start'] or out['cycle'] not in (0, 1, 2):
        raise NifError('invalid sequence time/cycle')
    return out


def spline_data(doc, index):
    r = _reader(doc, index, 'NiBSplineData')
    floats = r.vectors(r.count(16_000_000), 1)
    compact = r.unpack(f'{r.count(16_000_000)}h')
    r.finish()
    return dict(floats=tuple(v[0] for v in floats), compact=compact)


def spline_basis(doc, index):
    r = _reader(doc, index, 'NiBSplineBasisData')
    count = r.count(1_000_000)
    r.finish()
    if count < 4:
        raise NifError('cubic spline needs at least four control points')
    return count


def interpolator(doc, index):
    kind = doc.blocks[index].type
    if kind not in ('NiTransformInterpolator', 'NiBSplineCompTransformInterpolator',
                    'NiBSplineTransformInterpolator'):
        raise NifError('unsupported transform interpolator: ' + kind)
    r = Reader(doc.body(index))
    out = dict(type=kind)
    if kind == 'NiTransformInterpolator':
        out.update(pose=_pose(r), data=ref(r, doc))
    else:
        out['start'], out['stop'] = _floats(r, 2)
        out.update(data=ref(r, doc), basis=ref(r, doc), pose=_pose(r), handles=r.unpack('3I'))
        if kind == 'NiBSplineCompTransformInterpolator':
            out['compression'] = r.vectors(3, 2)
        if out['stop'] < out['start']:
            raise NifError('invalid spline time range')
    r.finish()
    return out


def _keys(r, width, quaternion=False, count=None, kind=None):
    if count is None:
        count = r.count(1_000_000)
    if not count:
        return dict(kind=0, keys=())
    if kind is None:
        kind = r.one('I')
    if kind not in (1, 2, 3, 5):
        raise NifError('unsupported key interpolation')
    keys = []
    for _ in range(count):
        key = dict(time=_floats(r, 1)[0], value=_floats(r, width))
        if kind == 2 and not quaternion:
            key.update(forward=_floats(r, width), backward=_floats(r, width))
        if kind == 3:
            key['tbc'] = _floats(r, 3)
        if keys and key['time'] <= keys[-1]['time']:
            raise NifError('non-increasing key times')
        keys.append(key)
    return dict(kind=kind, keys=tuple(keys))


def transform_data(doc, index):
    r = _reader(doc, index, 'NiTransformData')
    count = r.count(1_000_000)
    kind = r.one('I') if count else 0
    if kind == 4:
        if count != 1:
            raise NifError('invalid XYZ rotation key count')
        rotation = dict(kind=4, axes=tuple(_keys(r, 1) for _ in range(3)))
    else:
        rotation = _keys(r, 4, quaternion=True, count=count, kind=kind)
    out = dict(rotation=rotation, translation=_keys(r, 3), scale=_keys(r, 1))
    r.finish()
    return out


def normalize_quaternion(q):
    length = math.sqrt(sum(v*v for v in q))
    if not math.isfinite(length) or length < 1e-12:
        raise NifError('invalid quaternion')
    return tuple(v / length for v in q)


def rotation_matrix(q):
    w, x, y, z = normalize_quaternion(q)
    return ((1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)),
            (2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)),
            (2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)))


def euler_xyz_quaternion(angles):
    """Column-vector Rz * Ry * Rx, radians; NIF XYZ rotation keys."""
    x,y,z=(v*.5 for v in angles)
    cx,cy,cz=math.cos(x),math.cos(y),math.cos(z)
    sx,sy,sz=math.sin(x),math.sin(y),math.sin(z)
    return (cx*cy*cz+sx*sy*sz, sx*cy*cz-cx*sy*sz,
            cx*sy*cz+sx*cy*sz, cx*cy*sz-sx*sy*cz)


def slerp(a, b, t):
    a, b = normalize_quaternion(a), normalize_quaternion(b)
    dot = sum(x*y for x, y in zip(a, b))
    if dot < 0:
        b, dot = tuple(-v for v in b), -dot
    if dot > .9995:
        return normalize_quaternion(tuple(x+(y-x)*t for x, y in zip(a, b)))
    angle = math.acos(max(-1., min(1., dot)))
    return tuple((x*math.sin((1-t)*angle)+y*math.sin(t*angle))/math.sin(angle)
                 for x, y in zip(a, b))


def cubic_spline(points, time):
    """Open uniform cubic spline, normalized time; de Boor evaluation."""
    n = len(points)
    if n < 4 or not math.isfinite(time):
        raise NifError('invalid spline input')
    if time <= 0:
        return points[0]
    if time >= 1:
        return points[-1]
    # Uniform internal knots; four repeated endpoint knots.
    knots = (0.,)*4 + tuple(i/(n-3) for i in range(1, n-3)) + (1.,)*4
    span = min(n-1, bisect.bisect_right(knots, time)-1)
    values = [list(points[span-3+j]) for j in range(4)]
    for level in range(1, 4):
        for j in range(3, level-1, -1):
            left, right = knots[span-3+j], knots[span+1+j-level]
            alpha = (time-left)/(right-left)
            values[j] = [(1-alpha)*a+alpha*b for a, b in zip(values[j-1], values[j])]
    return tuple(values[3])


def sample_keys(group, time, quaternion=False):
    keys = group['keys']
    if not keys:
        return None
    if group['kind'] not in (1, 2, 5) or (quaternion and group['kind']==2):
        raise NifError('decoded key type is not supported for playback')
    if time <= keys[0]['time']:
        return keys[0]['value']
    if time >= keys[-1]['time']:
        return keys[-1]['value']
    i = bisect.bisect_right([k['time'] for k in keys], time)-1
    a, b = keys[i:i+2]
    if group['kind'] == 5:
        return a['value']
    t = (time-a['time'])/(b['time']-a['time'])
    if group['kind']==2:
        # NIF quadratic scalar/vector keys store normalized Hermite tangents:
        # outgoing Backward at a, incoming Forward at b (not seconds-scaled).
        h00=1-3*t*t+2*t*t*t; h01=1-h00
        h10=t*(1-t)*(1-t); h11=t*t*(t-1)
        return tuple(h00*x+h01*y+h10*outgoing+h11*incoming
                     for x,y,outgoing,incoming in zip(a['value'],b['value'],a['backward'],b['forward']))
    if quaternion:
        return slerp(a['value'], b['value'], t)
    return tuple(x+(y-x)*t for x, y in zip(a['value'], b['value']))


def compile_interpolator(doc, index):
    """Validate referenced curves once, before playback begins."""
    out = interpolator(doc, index)
    if out['type'] == 'NiTransformInterpolator':
        out['keys'] = transform_data(doc, out['data']) if out['data'] != -1 else None
        if out['keys']:
            rotation=out['keys']['rotation']
            groups=[out['keys']['translation'],out['keys']['scale']]
            if rotation['kind']==4:
                if len(rotation['axes'])!=3: raise NifError('XYZ rotation requires three axes')
                groups.extend(rotation['axes'])
            elif rotation['kind'] not in (0,1,5):
                raise NifError('unsupported quaternion key interpolation')
            if any(g['kind'] not in (0,1,2,5) for g in groups):
                raise NifError('unsupported playback key interpolation')
    else:
        channels = []
        active = any(h != 65535 for h in out['handles'])
        data = spline_data(doc, out['data']) if active else None
        count = spline_basis(doc, out['basis']) if active else 0
        for axis, (handle, width) in enumerate(zip(out['handles'], (3, 4, 1))):
            if handle == 65535:
                channels.append(None)
                continue
            compressed = 'compression' in out
            values = data['compact' if compressed else 'floats']
            if handle+count*width > len(values):
                raise NifError('spline handle range outside control data')
            values = values[handle:handle+count*width]
            if compressed:
                offset, half = out['compression'][axis]
                if half < 0 or max(abs(offset), abs(half)) >= 3e38:
                    raise NifError('invalid active compression range')
                values = tuple(offset+x*half/32767. for x in values)
            channels.append(tuple(tuple(values[j:j+width]) for j in range(0, len(values), width)))
        out['channels'] = tuple(channels)
    return out


def sample_interpolator(curve, time, base):
    """Absent channels keep the supplied skeleton local transform."""
    if not math.isfinite(time):
        raise NifError('nonfinite animation time')
    pose = dict(curve['pose'])
    if curve['type'] == 'NiTransformInterpolator':
        if curve['keys']:
            for channel, key in (('translation', 'translation'), ('quaternion', 'rotation'), ('scale', 'scale')):
                group=curve['keys'][key]
                if channel=='quaternion' and group['kind']==4:
                    angles=[sample_keys(axis,time) for axis in group['axes']]
                    value=euler_xyz_quaternion([v[0] if v is not None else 0. for v in angles])
                else:
                    value = sample_keys(group, time, quaternion=channel == 'quaternion')
                if value is not None:
                    pose[channel] = value[0] if channel == 'scale' else value
    else:
        duration = curve['stop']-curve['start']
        t = (time-curve['start'])/duration if duration else 0.
        for channel, points in zip(('translation', 'quaternion', 'scale'), curve['channels']):
            if points is not None:
                value = cubic_spline(points, t)
                pose[channel] = value[0] if channel == 'scale' else value
    out = dict(base)
    for channel in ('translation', 'quaternion', 'scale'):
        value = pose[channel]
        values = (value,) if channel == 'scale' else value
        # NiQuatTransform invalid-channel sentinel is -FLT_MAX.
        if all(v <= -3e38 for v in values):
            continue
        if any(not math.isfinite(v) or abs(v) >= 3e38 for v in values):
            raise NifError('invalid mixed transform sentinel')
        out['rotation' if channel == 'quaternion' else channel] = rotation_matrix(value) if channel == 'quaternion' else value
    return out


def compile_clip(doc, index, nodes):
    out = sequence(doc, index)
    by_name = {}
    for node_id, obj in nodes.items():
        by_name.setdefault(obj['name'], []).append(node_id)
    bindings, used = [], set()
    for target in out['controlled']:
        if (target['property_type'] or target['controller_type'] != 'NiTransformController'
                or target['controller_id'] or target['interpolator_id']):
            raise NifError('unsupported controlled property/type')
        matches = by_name.get(target['node_name'], [])
        if len(matches) != 1 or matches[0] in used:
            raise NifError('missing/ambiguous animation target: ' + target['node_name'])
        used.add(matches[0])
        bindings.append((matches[0], compile_interpolator(doc, target['interpolator'])))
    out['bindings'] = tuple(bindings)
    return out


def posed_nodes(clip, nodes, time):
    """Explicit clip-local seconds; no blending or root-motion extraction."""
    out = dict(nodes)
    for index, curve in clip['bindings']:
        out[index] = dict(nodes[index], transform=sample_interpolator(curve, time, nodes[index]['transform']))
    return out
