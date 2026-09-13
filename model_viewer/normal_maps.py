"""Explicit preview-only normal decoding. Original texture bytes stay intact."""
import math

MODES=('AUTO','RGB','AGB','AG')

def suggest_mode(rgba):
    # A heuristic, never proof of an engine shader's swizzle or Y convention.
    pixels=len(rgba)//4; step=max(1,pixels//4096)
    samples=[rgba[i*4:i*4+4] for i in range(0,pixels,step)]
    return 'AGB' if samples and all(p[0]<4 for p in samples) and any(32<p[3]<224 for p in samples) else 'RGB'

def decode_normal(r,g,b,a,mode='RGB',flip_y=False):
    if mode not in MODES[1:]: raise ValueError('Explicit normal mode required')
    x=2*(r if mode=='RGB' else a)-1; y=(2*g-1)*(-1 if flip_y else 1)
    z=math.sqrt(max(0.,1-x*x-y*y)) if mode=='AG' else 2*b-1
    length=math.sqrt(x*x+y*y+z*z)
    return (x/length,y/length,z/length) if length>1e-10 else (0.,0.,1.)

def preview_rgba(rgba,mode='AUTO',flip_y=False):
    if mode not in MODES: raise ValueError('Unsupported normal interpretation')
    if mode=='AUTO': mode=suggest_mode(rgba)
    out=bytearray(len(rgba))
    for i in range(0,len(rgba),4):
        xyz=decode_normal(*(v/255 for v in rgba[i:i+4]),mode,flip_y)
        out[i:i+4]=bytes((*[max(0,min(255,round((v*.5+.5)*255))) for v in xyz],255))
    return bytes(out)
