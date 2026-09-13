"""Synthetic guards; no redistribution of game data."""
import struct
import unittest
from model_viewer.nif import parse, NifError


def envelope(body=b'abcd'):
    def string(s):
        return struct.pack('<I', len(s)) + s
    return (b'Gamebryo File Format, Version 20.3.0.9\n'
            + struct.pack('<IBIIH', 0x14030009, 1, 0x30000, 1, 1)
            + string(b'UnknownBlock') + struct.pack('<HI', 0, len(body))
            + struct.pack('<III', 0, 0, 0) + body + struct.pack('<Ii', 1, 0))


class EnvelopeTests(unittest.TestCase):
    def test_unknown_block_retained(self):
        payload = envelope()
        doc = parse(payload)
        self.assertEqual(doc.body(0), b'abcd')
        self.assertEqual(doc.payload, payload)
        self.assertEqual(doc.roots, (0,))
        self.assertEqual(doc.footer_start, len(payload) - 8)
        self.assertEqual(doc.sidecar()['blocks'][0]['type'], 'UnknownBlock')

    def test_every_truncation_rejected(self):
        p = envelope()
        for end in range(len(p)):
            with self.subTest(end=end), self.assertRaises(NifError):
                parse(p[:end])

    def test_trailing_and_invalid_root_rejected(self):
        with self.assertRaises(NifError):
            parse(envelope() + b'x')
        with self.assertRaises(NifError):
            parse(envelope()[:-4] + struct.pack('<i', 1))


if __name__ == '__main__':
    unittest.main()
