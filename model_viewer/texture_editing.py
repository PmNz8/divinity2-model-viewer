"""Reuse fixed-layout BC writer and existing explicit MIP0 area filtering."""
from tools.texture_codec.nif_texture import parse_texture_resource,decode_texture_mip,serialize_texture_resource
from tools.texture_codec.bc import encode_mip,FORMAT_BC1,FORMAT_BC3
from tools.texture_codec.mip_generation import downsample
from .nif import NifError


def edit_texture(payload,rgba,size,*,profile):
    if profile not in ('raw','srgb'): raise NifError('Choose raw or srgb mip generation explicitly')
    resource=parse_texture_resource(payload)
    base=resource.mips[0]
    if tuple(size)!=(base.width,base.height) or len(rgba)!=base.width*base.height*4:
        raise NifError('texture dimensions/channel count changed')
    original_rgba=decode_texture_mip(resource)
    if rgba==original_rgba: return payload
    if resource.pixel_format not in (FORMAT_BC1,FORMAT_BC3):
        raise NifError('edited texture requires BC1 or BC3; BC2 remains unchanged-only')
    if resource.pixel_format==FORMAT_BC1 and all(a==255 for a in original_rgba[3::4]) and any(a!=255 for a in rgba[3::4]):
        raise NifError('Cannot introduce alpha into an originally opaque BC1 texture')
    replacements={}; width,height=size
    for index,mip in enumerate(resource.mips):
        if index:
            if (mip.width,mip.height)!=(max(1,width//2),max(1,height//2)):
                raise NifError('nonstandard mip chain cannot be regenerated')
            rgba=downsample(rgba,width,height,mip.width,mip.height,profile=profile)
            width,height=mip.width,mip.height
        replacements[index]=encode_mip(rgba,width,height,resource.pixel_format,
                                       bc1_binary_alpha=resource.pixel_format==FORMAT_BC1)
    return serialize_texture_resource(resource,replacements,expected_source_sha256=resource.payload_sha256)
