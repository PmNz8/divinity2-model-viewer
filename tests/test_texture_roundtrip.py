from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

from tools.texture_codec import bc
from tools.texture_codec.nif_texture import EXPECTED_NIF_HEADER_LINE, EXPECTED_NIF_VERSION, TEXTURE_BLOCK_TYPE, parse_texture_resource
from tools.texture_codec.roundtrip import (
    MAX_SIDECAR_BYTES,
    SIDECAR_NAME,
    ChannelStatistics,
    TextureRoundTripError,
    build_export_set,
    decode_mip_views,
    export_texture_set,
    import_export_set,
    import_texture_set,
)
from tools.texture_codec.png import encode_png_gray, encode_png_rgb


def _pack_string(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack("<I", len(raw)) + raw


def _make_texture_payload(
    *,
    pixel_format: int,
    dimensions: tuple[tuple[int, int], ...],
    data: bytes,
    user_version: int = 0x00030000,
) -> bytes:
    sizes = tuple(bc.mip_size(width, height, pixel_format) for width, height in dimensions)
    if len(data) != sum(sizes):
        raise AssertionError("synthetic texture data has the wrong size")
    offsets: list[int] = []
    cursor = 0
    for size in sizes:
        offsets.append(cursor)
        cursor += size

    body = bytearray()
    body += struct.pack("<I", pixel_format)
    body += b"D" * 59
    body += bytes((len(dimensions),))
    body += b"\x00" * 7
    for (width, height), offset in zip(dimensions, offsets, strict=True):
        body += struct.pack("<III", width, height, offset)
    body += struct.pack("<4I", cursor, cursor, 1, 3)
    body += data

    output = bytearray(EXPECTED_NIF_HEADER_LINE.encode("ascii") + b"\n")
    output += struct.pack("<IBIIH", EXPECTED_NIF_VERSION, 1, user_version, 1, 1)
    output += _pack_string(TEXTURE_BLOCK_TYPE)
    output += struct.pack("<H", 0)
    output += struct.pack("<I", len(body))
    output += struct.pack("<II", 1, 7)
    output += _pack_string("texture")
    output += struct.pack("<I", 2)
    output += struct.pack("<II", 2, 7)
    output += body
    output += struct.pack("<Ii", 1, 0)
    return bytes(output)


def _bc1_block(color0: int, color1: int, indices: int = 0) -> bytes:
    return struct.pack("<HHI", color0, color1, indices)


def _bc2_block(alpha: bytes, color0: int = 0xF800, color1: int = 0x07E0) -> bytes:
    if len(alpha) != 8:
        raise AssertionError("BC2 alpha block must be 8 bytes")
    return alpha + _bc1_block(color0, color1)


def _bc3_block(
    alpha0: int = 255,
    alpha1: int = 0,
    alpha_indices: int = 0,
    color0: int = 0xF800,
    color1: int = 0x07E0,
    color_indices: int = 0,
) -> bytes:
    return (
        bytes((alpha0, alpha1))
        + alpha_indices.to_bytes(6, "little")
        + _bc1_block(color0, color1, color_indices)
    )


def _resource(
    pixel_format: int,
    data: bytes,
    dimensions: tuple[tuple[int, int], ...] = ((4, 4),),
    user_version: int = 0x00030000,
):
    payload = _make_texture_payload(
        pixel_format=pixel_format,
        dimensions=dimensions,
        data=data,
        user_version=user_version,
    )
    return parse_texture_resource(payload, "roundtrip-fixture")


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode(
        "utf-8"
    )


class TextureRoundTripViewsTests(unittest.TestCase):
    def test_views_are_tightly_packed_and_statistics_are_per_rgba_channel(self) -> None:
        indices = sum(index << (2 * pixel) for pixel, index in enumerate([0, 1, 2, 3] * 4))
        resource = _resource(bc.FORMAT_BC1, _bc1_block(0xF800, 0x07E0, indices))
        views = decode_mip_views(resource)
        self.assertEqual(views.index, 0)
        self.assertEqual((views.width, views.height), (4, 4))
        self.assertEqual(len(views.rgba), 64)
        self.assertEqual(len(views.rgb), 48)
        self.assertEqual(len(views.alpha), 16)
        self.assertEqual(views.rgb, b"".join(views.rgba[offset : offset + 3] for offset in range(0, 64, 4)))
        self.assertEqual(views.alpha, views.rgba[3::4])
        self.assertEqual(views.alpha_mode, "bc1_opaque")
        self.assertFalse(views.alpha_required)
        self.assertEqual(len(views.statistics), 4)
        self.assertTrue(all(isinstance(item, ChannelStatistics) for item in views.statistics))
        self.assertEqual(views.statistics[0].sample_count, 16)
        self.assertEqual(views.statistics[0].minimum, 0)
        self.assertEqual(views.statistics[0].maximum, 255)
        self.assertEqual(views.statistics[3].minimum, 255)
        self.assertEqual(views.statistics[3].maximum, 255)

    def test_bc1_ignores_transparent_padding_texels(self) -> None:
        # The only in-bounds texel of block 1 is local index 0.  Index 3 is
        # present only in padded local positions 1..3 and must not request an
        # alpha export.
        padding_indices = 0 | (3 << 2) | (3 << 4) | (3 << 6)
        resource = _resource(
            bc.FORMAT_BC1,
            _bc1_block(0xF800, 0x07E0) + _bc1_block(0x0000, 0xFFFF, padding_indices),
            dimensions=((5, 1),),
        )
        views = decode_mip_views(resource)
        self.assertFalse(views.alpha_required)
        self.assertEqual(views.alpha_mode, "bc1_opaque")
        self.assertEqual(set(views.alpha), {255})

        in_bounds_indices = 3 | (3 << 2) | (3 << 4) | (3 << 6)
        resource = _resource(
            bc.FORMAT_BC1,
            _bc1_block(0xF800, 0x07E0) + _bc1_block(0x0000, 0xFFFF, in_bounds_indices),
            dimensions=((5, 1),),
        )
        views = decode_mip_views(resource)
        self.assertTrue(views.alpha_required)
        self.assertEqual(views.alpha_mode, "bc1_binary")
        self.assertIn("mip-00.alpha.png", build_export_set(resource))

    def test_bc2_and_bc3_always_export_alpha(self) -> None:
        bc2 = _resource(bc.FORMAT_BC2, _bc2_block(bytes(range(8))))
        bc2_views = decode_mip_views(bc2)
        self.assertTrue(bc2_views.alpha_required)
        self.assertEqual(bc2_views.alpha_mode, "bc2_explicit")
        self.assertIn("mip-00.alpha.png", build_export_set(bc2))

        bc3 = _resource(bc.FORMAT_BC3, _bc3_block(alpha_indices=0x249249249249))
        bc3_views = decode_mip_views(bc3)
        self.assertTrue(bc3_views.alpha_required)
        self.assertEqual(bc3_views.alpha_mode, "bc3_interpolated")
        self.assertIn("mip-00.alpha.png", build_export_set(bc3))


class TextureRoundTripExportImportTests(unittest.TestCase):
    def test_export_is_deterministic_and_sidecar_is_canonical(self) -> None:
        resource = _resource(bc.FORMAT_BC1, _bc1_block(0xF800, 0x07E0))
        first = build_export_set(resource)
        second = build_export_set(resource)
        self.assertEqual(first, second)
        sidecar = first[SIDECAR_NAME]
        self.assertTrue(sidecar.endswith(b"\n"))
        self.assertEqual(sidecar, _canonical_json(json.loads(sidecar.decode("utf-8"))))
        self.assertEqual(
            json.loads(sidecar.decode("utf-8"))["source"]["payload_sha256"],
            hashlib.sha256(resource._payload).hexdigest(),
        )

    def test_noop_import_is_byte_perfect_for_all_formats_and_user_versions(self) -> None:
        fixtures = (
            (bc.FORMAT_BC1, _bc1_block(0xF800, 0x07E0)),
            (bc.FORMAT_BC2, _bc2_block(bytes((0x10, 0x32, 0x54, 0x76, 0x98, 0xBA, 0xDC, 0xFE)))),
            (bc.FORMAT_BC3, _bc3_block(alpha_indices=0x123456789ABC)),
        )
        for user_version in (0x00000000, 0x00030000):
            for pixel_format, data in fixtures:
                with self.subTest(user_version=user_version, pixel_format=pixel_format):
                    resource = _resource(pixel_format, data, user_version=user_version)
                    self.assertEqual(import_export_set(resource, build_export_set(resource)), resource._payload)

    def test_one_mip_bc1_edit_changes_only_that_compressed_range(self) -> None:
        data = _bc1_block(0xF800, 0x07E0) * 3
        resource = _resource(bc.FORMAT_BC1, data, dimensions=((8, 4), (4, 2)))
        files = build_export_set(resource)
        image = decode_mip_views(resource, 1)
        edited_rgb = bytearray(image.rgb)
        edited_rgb[:] = bytes((0, 0, 255)) * (image.width * image.height)
        files["mip-01.rgb.png"] = encode_png_rgb(image.width, image.height, edited_rgb)
        output = import_export_set(resource, files)
        mip = resource.mips[1]
        self.assertNotEqual(output[mip.absolute_offset : mip.end_offset], resource.mip_bytes(1))
        self.assertEqual(output[: mip.absolute_offset], resource._payload[: mip.absolute_offset])
        self.assertEqual(output[mip.end_offset :], resource._payload[mip.end_offset :])
        self.assertEqual(
            parse_texture_resource(output).mip_bytes(0), resource.mip_bytes(0)
        )

    def test_one_mip_bc3_edit_preserves_other_mips(self) -> None:
        data = _bc3_block() * 2 + _bc3_block(alpha_indices=0x123456789ABC)
        resource = _resource(bc.FORMAT_BC3, data, dimensions=((8, 4), (4, 2)))
        files = build_export_set(resource)
        image = decode_mip_views(resource, 1)
        edited_rgb = bytearray(image.rgb)
        edited_alpha = bytearray(image.alpha)
        edited_rgb[0:3] = bytes((0, 255, 0))
        edited_alpha[0] = 19
        files["mip-01.rgb.png"] = encode_png_rgb(image.width, image.height, edited_rgb)
        files["mip-01.alpha.png"] = encode_png_gray(image.width, image.height, edited_alpha)
        output = import_export_set(resource, files)
        mip = resource.mips[1]
        self.assertNotEqual(output[mip.absolute_offset : mip.end_offset], resource.mip_bytes(1))
        self.assertEqual(output[: mip.absolute_offset], resource._payload[: mip.absolute_offset])
        self.assertEqual(output[mip.end_offset :], resource._payload[mip.end_offset :])

    def test_bc2_edit_is_explicitly_rejected(self) -> None:
        resource = _resource(bc.FORMAT_BC2, _bc2_block(bytes(range(8))))
        files = build_export_set(resource)
        image = decode_mip_views(resource)
        rgb = bytearray(image.rgb)
        rgb[0] ^= 0xFF
        files["mip-00.rgb.png"] = encode_png_rgb(image.width, image.height, rgb)
        with self.assertRaisesRegex(TextureRoundTripError, "BC2 edits are unsupported"):
            import_export_set(resource, files)

    def test_wrong_png_type_or_dimensions_is_rejected(self) -> None:
        resource = _resource(bc.FORMAT_BC1, _bc1_block(0xF800, 0x07E0))
        files = build_export_set(resource)
        views = decode_mip_views(resource)
        files["mip-00.rgb.png"] = encode_png_gray(views.width, views.height, views.alpha)
        with self.assertRaises(TextureRoundTripError):
            import_export_set(resource, files)
        files = build_export_set(resource)
        files["mip-00.rgb.png"] = encode_png_rgb(1, 1, bytes((1, 2, 3)))
        with self.assertRaises(TextureRoundTripError):
            import_export_set(resource, files)


class TextureRoundTripStrictInputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.resource = _resource(bc.FORMAT_BC1, _bc1_block(0xF800, 0x07E0))
        self.files = build_export_set(self.resource)

    def assert_invalid(self, files: object) -> None:
        with self.assertRaises(TextureRoundTripError):
            import_export_set(self.resource, files)  # type: ignore[arg-type]

    def test_exact_file_set_and_basename_and_contiguous_value_guards(self) -> None:
        files = dict(self.files)
        del files["mip-00.rgb.png"]
        self.assert_invalid(files)
        files = dict(self.files)
        files["extra.bin"] = b"x"
        self.assert_invalid(files)
        files = dict(self.files)
        files["nested/file.bin"] = b"x"
        self.assert_invalid(files)
        files = dict(self.files)
        files["."] = b"x"
        self.assert_invalid(files)
        files = dict(self.files)
        files["mip-00.rgb.png"] = memoryview(files["mip-00.rgb.png"])[::2]
        self.assert_invalid(files)
        self.assert_invalid("not a mapping")

    def test_sidecar_rejects_malformed_duplicate_nonfinite_oversized_and_type_aliases(self) -> None:
        files = dict(self.files)
        files[SIDECAR_NAME] = b'{"schema": 1, "schema": 2}'
        self.assert_invalid(files)
        files = dict(self.files)
        files[SIDECAR_NAME] = b'{"value": NaN}'
        self.assert_invalid(files)
        files = dict(self.files)
        files[SIDECAR_NAME] = b" " * (MAX_SIDECAR_BYTES + 1)
        self.assert_invalid(files)

        for replacement in (True, 1.0):
            with self.subTest(replacement=replacement):
                files = dict(self.files)
                document = json.loads(files[SIDECAR_NAME].decode("utf-8"))
                document["source"]["payload_size"] = replacement
                files[SIDECAR_NAME] = _canonical_json(document)
                self.assert_invalid(files)

    def test_sidecar_mutation_of_each_identity_or_policy_field_is_rejected(self) -> None:
        paths = (
            ("source", "payload_sha256", "0" * 64),
            ("source", "payload_size", 1),
            ("source", "user_version", 0),
            ("source", "pixel_format", bc.FORMAT_BC3),
            ("source", "pixel_format_name", "BC3"),
            ("source", "mip_count", 2),
            ("policy", "semantic_kind", "normal_map"),
        )
        for section, key, value in paths:
            with self.subTest(section=section, key=key):
                files = dict(self.files)
                document = json.loads(files[SIDECAR_NAME].decode("utf-8"))
                document[section][key] = value
                files[SIDECAR_NAME] = _canonical_json(document)
                self.assert_invalid(files)
        files = dict(self.files)
        document = json.loads(files[SIDECAR_NAME].decode("utf-8"))
        document["schema"] = "other"
        files[SIDECAR_NAME] = _canonical_json(document)
        self.assert_invalid(files)
        files = dict(self.files)
        document = json.loads(files[SIDECAR_NAME].decode("utf-8"))
        document["mips"][0]["relative_offset"] = 1
        document["mips"][0]["compressed_sha256"] = "0" * 64
        document["mips"][0]["alpha_required"] = True
        document["mips"][0]["rgb_file"] = "other.png"
        files[SIDECAR_NAME] = _canonical_json(document)
        self.assert_invalid(files)

    def test_same_layout_different_source_is_rejected_and_source_is_unchanged(self) -> None:
        before = bytes(self.resource._payload)
        other_payload = bytearray(before)
        other_payload[self.resource.mips[0].absolute_offset] ^= 0x01
        other = parse_texture_resource(bytes(other_payload), "other-source")
        with self.assertRaises(TextureRoundTripError):
            import_export_set(other, self.files)
        self.assertEqual(self.resource._payload, before)
        self.assertEqual(import_export_set(self.resource, self.files), before)


class TextureRoundTripFilesystemTests(unittest.TestCase):
    def test_filesystem_sidecar_uses_the_stricter_size_limit(self) -> None:
        resource = _resource(bc.FORMAT_BC1, _bc1_block(0xF800, 0x07E0))
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            export_texture_set(resource, source)
            (source / SIDECAR_NAME).write_bytes(b" " * (MAX_SIDECAR_BYTES + 1))
            with self.assertRaisesRegex(TextureRoundTripError, "size limit"):
                import_texture_set(resource, source)

    def test_export_is_atomic_refuses_overwrite_and_cleans_failed_staging(self) -> None:
        resource = _resource(bc.FORMAT_BC1, _bc1_block(0xF800, 0x07E0))
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            destination = parent / "export"
            result = export_texture_set(resource, destination)
            self.assertEqual(result, destination)
            self.assertTrue((destination / SIDECAR_NAME).is_file())
            self.assertEqual(import_texture_set(resource, destination), resource._payload)
            with self.assertRaises(TextureRoundTripError):
                export_texture_set(resource, destination)

            failed = parent / "failed"
            with mock.patch("tools.texture_codec.roundtrip.os.replace", side_effect=OSError("boom")):
                with self.assertRaises(TextureRoundTripError):
                    export_texture_set(resource, failed)
            self.assertFalse(failed.exists())
            self.assertEqual(list(parent.glob(f".{failed.name}.*")), [])

    def test_import_rejects_nested_and_symlink_entries(self) -> None:
        resource = _resource(bc.FORMAT_BC1, _bc1_block(0xF800, 0x07E0))
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            source = parent / "source"
            export_texture_set(resource, source)
            nested = source / "nested"
            nested.mkdir()
            with self.assertRaises(TextureRoundTripError):
                import_texture_set(resource, source)
            nested.rmdir()

            symlink = source / "link"
            try:
                symlink.symlink_to(source / SIDECAR_NAME)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"symlink creation unavailable: {error}")
            with self.assertRaises(TextureRoundTripError):
                import_texture_set(resource, source)

            linked_directory = parent / "linked-directory"
            try:
                linked_directory.symlink_to(source, target_is_directory=True)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"directory symlink creation unavailable: {error}")
            with self.assertRaises(TextureRoundTripError):
                import_texture_set(resource, linked_directory)


if __name__ == "__main__":
    unittest.main()
