"""
test_qr_reader.py - Tests for QR code reading and MAC address extraction.
"""

import os
import tempfile
from unittest.mock import patch

import numpy as np
import pytest

from qr_reader import decode_qr, parse_mac_address, read_qr_from_image


# ---------------------------------------------------------------------------
# parse_mac_address
# ---------------------------------------------------------------------------

class TestParseMacAddress:
    """Test MAC address extraction from QR code data."""

    def test_plain_mac_colon_separated(self):
        assert parse_mac_address("AA:BB:CC:DD:EE:FF") == "AA:BB:CC:DD:EE:FF"

    def test_plain_mac_hyphen_separated(self):
        assert parse_mac_address("AA-BB-CC-DD-EE-FF") == "AA:BB:CC:DD:EE:FF"

    def test_lowercase_mac(self):
        assert parse_mac_address("aa:bb:cc:dd:ee:ff") == "AA:BB:CC:DD:EE:FF"

    def test_mixed_case_mac(self):
        assert parse_mac_address("aA:Bb:cC:dD:eE:fF") == "AA:BB:CC:DD:EE:FF"

    def test_mac_with_prefix(self):
        assert parse_mac_address("BLE:AA:BB:CC:DD:EE:FF") == "AA:BB:CC:DD:EE:FF"

    def test_mac_in_url(self):
        result = parse_mac_address(
            "https://example.com/pair?mac=11:22:33:44:55:66&model=blind"
        )
        assert result == "11:22:33:44:55:66".upper()

    def test_mac_embedded_in_text(self):
        assert parse_mac_address(
            "Device BF:12:34:AB:CD:EF blinds"
        ) == "BF:12:34:AB:CD:EF"

    def test_no_mac_returns_none(self):
        assert parse_mac_address("hello world") is None

    def test_empty_string_returns_none(self):
        assert parse_mac_address("") is None

    def test_none_returns_none(self):
        # Ensure graceful handling even if somehow None gets through
        assert parse_mac_address(None) is None

    def test_partial_mac_not_matched(self):
        # Only 5 octets – not a valid MAC
        assert parse_mac_address("AA:BB:CC:DD:EE") is None

    def test_first_mac_is_returned(self):
        """When multiple MACs appear, the first should be returned."""
        data = "primary=11:22:33:44:55:66 backup=AA:BB:CC:DD:EE:FF"
        assert parse_mac_address(data) == "11:22:33:44:55:66".upper()


# ---------------------------------------------------------------------------
# read_qr_from_image
# ---------------------------------------------------------------------------

class TestReadQrFromImage:
    """Test QR code reading from image files."""

    def test_file_not_found_raises(self):
        with pytest.raises(FileNotFoundError):
            read_qr_from_image("/nonexistent/path/to/image.png")

    def test_unreadable_image_raises(self, tmp_path):
        bad_file = tmp_path / "bad.png"
        bad_file.write_text("not an image")
        with pytest.raises(ValueError, match="Could not read image"):
            read_qr_from_image(str(bad_file))

    def test_image_without_qr_returns_none(self, tmp_path):
        """A blank image should return None."""
        import cv2

        blank = np.zeros((200, 200, 3), dtype=np.uint8)
        img_path = str(tmp_path / "blank.png")
        cv2.imwrite(img_path, blank)
        assert read_qr_from_image(img_path) is None

    def test_image_with_qr_returns_data(self, tmp_path):
        """Generate a QR code image and verify it can be read back."""
        import cv2

        # Generate a QR code using OpenCV's QRCodeEncoder
        mac = "AA:BB:CC:DD:EE:FF"
        encoder = cv2.QRCodeEncoder.create()
        qr_img = encoder.encode(mac)

        # Make the image large enough for reliable detection
        qr_img = cv2.resize(qr_img, (400, 400), interpolation=cv2.INTER_NEAREST)

        img_path = str(tmp_path / "qr_test.png")
        cv2.imwrite(img_path, qr_img)

        result = read_qr_from_image(img_path)
        assert result == mac


# ---------------------------------------------------------------------------
# decode_qr — robust detection with preprocessing
# ---------------------------------------------------------------------------

class TestDecodeQr:
    """Test the multi-strategy QR decoder against degraded images."""

    @staticmethod
    def _make_qr(text: str = "AA:BB:CC:DD:EE:FF", size: int = 100) -> np.ndarray:
        """Helper: generate a clean QR code as a grayscale image."""
        import cv2

        encoder = cv2.QRCodeEncoder.create()
        qr = encoder.encode(text)
        return cv2.resize(qr, (size, size), interpolation=cv2.INTER_NEAREST)

    def test_clean_image(self):
        """A clean QR should be decoded on the fast path."""
        import cv2

        qr = self._make_qr()
        img = cv2.cvtColor(qr, cv2.COLOR_GRAY2BGR)
        assert decode_qr(img) == "AA:BB:CC:DD:EE:FF"

    def test_low_contrast(self):
        """A washed-out, low-contrast image should still be decoded."""
        import cv2

        qr = self._make_qr()
        canvas = np.full((400, 400, 3), 190, dtype=np.uint8)
        qr_c = cv2.cvtColor(qr, cv2.COLOR_GRAY2BGR)
        canvas[50:150, 200:300] = qr_c
        low_contrast = cv2.convertScaleAbs(canvas, alpha=0.35, beta=100)
        assert decode_qr(low_contrast) == "AA:BB:CC:DD:EE:FF"

    def test_noisy_image(self):
        """A noisy image should still be decoded via preprocessing."""
        import cv2

        qr = self._make_qr(size=200)
        canvas = np.full((500, 500, 3), 200, dtype=np.uint8)
        qr_c = cv2.cvtColor(qr, cv2.COLOR_GRAY2BGR)
        canvas[50:250, 200:400] = qr_c
        noise = np.random.normal(0, 25, canvas.shape).astype(np.int16)
        noisy = np.clip(canvas.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        assert decode_qr(noisy) == "AA:BB:CC:DD:EE:FF"

    def test_combined_degradation(self):
        """Blur + low contrast + noise + JPEG — simulating a real phone photo."""
        import cv2

        qr = self._make_qr(size=150)
        canvas = np.full((600, 400, 3), 190, dtype=np.uint8)
        qr_c = cv2.cvtColor(qr, cv2.COLOR_GRAY2BGR)
        canvas[50:200, 150:300] = qr_c

        blurred = cv2.GaussianBlur(canvas, (5, 5), 1.5)
        low_c = cv2.convertScaleAbs(blurred, alpha=0.4, beta=90)
        noise = np.random.normal(0, 12, low_c.shape).astype(np.int16)
        degraded = np.clip(low_c.astype(np.int16) + noise, 0, 255).astype(np.uint8)

        assert decode_qr(degraded) == "AA:BB:CC:DD:EE:FF"

    def test_defocus_blur_with_shadow(self):
        """Defocus blur + uneven shadow + tight quiet zone — real camera photo."""
        import cv2

        np.random.seed(42)
        qr = self._make_qr(size=350)
        canvas = np.full((366, 366, 3), 200, dtype=np.uint8)
        qr_c = cv2.cvtColor(qr, cv2.COLOR_GRAY2BGR)
        canvas[8:358, 8:358] = qr_c

        # Disc-shaped defocus blur (realistic camera out-of-focus)
        k = 25
        kern = np.zeros((k, k), dtype=np.float32)
        cv2.circle(kern, (k // 2, k // 2), k // 2, 1, -1)
        kern /= kern.sum()
        blurred = cv2.filter2D(canvas, -1, kern)

        # Uneven lighting
        rows, cols = blurred.shape[:2]
        for y in range(rows):
            for x in range(cols):
                factor = 1.3 - 0.6 * (x / cols) - 0.15 * (1 - y / rows)
                blurred[y, x] = np.clip(
                    blurred[y, x].astype(np.float32) * factor, 0, 255,
                ).astype(np.uint8)

        noise = np.random.normal(0, 8, blurred.shape).astype(np.int16)
        noisy = np.clip(blurred.astype(np.int16) + noise, 0, 255).astype(np.uint8)

        assert decode_qr(noisy) == "AA:BB:CC:DD:EE:FF"

    def test_blank_image_returns_none(self):
        """A completely blank image should return None."""
        blank = np.zeros((200, 200, 3), dtype=np.uint8)
        assert decode_qr(blank) is None
