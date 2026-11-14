"""Unit checks for the parent-side payload validators."""

from __future__ import annotations

import struct
import unittest

import validate

from .fixtures import make_png, make_wav


class PngTests(unittest.TestCase):
    def test_png_accepts_contract_limits(self):
        accepted, detail = validate.check_png(make_png(1080, 1920))
        self.assertTrue(accepted, detail)

    def test_png_rejects_signature_only(self):
        accepted, detail = validate.check_png(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
        self.assertFalse(accepted)
        self.assertIn("IHDR", detail)

    def test_png_rejects_side_over_cap(self):
        accepted, detail = validate.check_png(make_png(1921, 4))
        self.assertFalse(accepted)
        self.assertIn("side cap", detail)

    def test_png_rejects_missing_iend(self):
        data = make_png()
        accepted, detail = validate.check_png(data[:-12])
        self.assertFalse(accepted, detail)


class WavTests(unittest.TestCase):
    def test_wav_accepts_pcm_mono_16bit(self):
        accepted, detail = validate.check_wav(make_wav(1))
        self.assertTrue(accepted, detail)

    def test_wav_rejects_wrong_container(self):
        body = b"WAVX" + b"\x00" * 32
        accepted, detail = validate.check_wav(b"RIFF" + struct.pack("<I", len(body) + 4) + body)
        self.assertFalse(accepted)
        self.assertIn("WAVE", detail)

    def test_wav_rejects_overlong_duration(self):
        accepted, detail = validate.check_wav(make_wav(16.5))
        self.assertFalse(accepted)
        self.assertIn("over", detail)

    def test_wav_rejects_unknown_chunk(self):
        data = make_wav(1)
        body = b"junk" + struct.pack("<I", 0)
        extra = data[:4] + struct.pack("<I", len(data) + len(body) - 8) + data[8:] + body
        accepted, detail = validate.check_wav(extra)
        self.assertFalse(accepted)
        self.assertIn("chunk", detail)


if __name__ == "__main__":
    unittest.main()
