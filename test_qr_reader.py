"""
test_qr_reader.py - Tests for QR code reading and MAC address extraction.
"""

import os
import tempfile
from unittest.mock import patch

import numpy as np
import pytest

from qr_reader import parse_mac_address, read_qr_from_image


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
