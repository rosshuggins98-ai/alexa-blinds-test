"""
qr_reader.py - QR Code Reader for Tuiss SmartView Blinds Pairing

Reads QR codes from camera or image files and extracts the BLE MAC
address used to identify the correct blind during pairing.
"""

import logging
import re
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Regex pattern for BLE MAC addresses (e.g. AA:BB:CC:DD:EE:FF)
_MAC_RE = re.compile(r"(?:[0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}")


def parse_mac_address(qr_data: Optional[str]) -> Optional[str]:
    """
    Extract a BLE MAC address from raw QR code data.

    Handles several common formats:
        - Plain MAC: ``AA:BB:CC:DD:EE:FF``
        - Hyphenated: ``AA-BB-CC-DD-EE-FF``
        - With prefix: ``BLE:AA:BB:CC:DD:EE:FF``
        - Embedded in URL: ``https://...?mac=AA:BB:CC:DD:EE:FF``
        - Surrounded by other text

    Returns:
        Upper-cased, colon-separated MAC address, or ``None``.
    """
    if not qr_data:
        return None
    match = _MAC_RE.search(qr_data)
    if match:
        mac = match.group(0).upper().replace("-", ":")
        return mac
    return None


def read_qr_from_image(image_path: str) -> Optional[str]:
    """
    Decode a QR code from an image file.

    Args:
        image_path: Path to the image file (PNG, JPEG, etc.).

    Returns:
        Decoded QR string, or ``None`` if no QR code was found.
    """
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"Image file not found: {image_path}")

    img = cv2.imread(str(path))
    if img is None:
        raise ValueError(f"Could not read image: {image_path}")

    detector = cv2.QRCodeDetector()
    data, points, _ = detector.detectAndDecode(img)

    if data:
        logger.info("QR code decoded from file: %s", data)
        return data

    logger.warning("No QR code found in %s", image_path)
    return None


def read_qr_from_camera(
    timeout_seconds: float = 30.0,
    camera_index: int = 0,
) -> Optional[str]:
    """
    Open the camera and scan for a QR code until one is found or the
    timeout is reached.

    A window titled *Scan QR Code* is displayed so the user can aim the
    camera.  Press ``q`` to cancel early.

    Args:
        timeout_seconds: Maximum time to keep scanning.
        camera_index: Index of the camera device (default ``0``).

    Returns:
        Decoded QR string, or ``None`` if cancelled / timed out.
    """
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise RuntimeError(
            f"Could not open camera (index {camera_index}). "
            "Make sure a camera is connected."
        )

    detector = cv2.QRCodeDetector()
    result: Optional[str] = None
    start = cv2.getTickCount()
    freq = cv2.getTickFrequency()

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            data, points, _ = detector.detectAndDecode(frame)
            if data:
                result = data
                logger.info("QR code decoded from camera: %s", data)
                break

            # Draw helper overlay
            h, w = frame.shape[:2]
            box_size = min(h, w) // 2
            x1 = (w - box_size) // 2
            y1 = (h - box_size) // 2
            cv2.rectangle(
                frame, (x1, y1), (x1 + box_size, y1 + box_size),
                (0, 255, 0), 2,
            )
            cv2.putText(
                frame,
                "Point camera at the QR code on your blind",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2,
            )

            elapsed = (cv2.getTickCount() - start) / freq
            remaining = max(0, timeout_seconds - elapsed)
            cv2.putText(
                frame,
                f"Time remaining: {remaining:.0f}s  (press 'q' to cancel)",
                (10, h - 15),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (200, 200, 200),
                1,
            )

            cv2.imshow("Scan QR Code", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

            if elapsed >= timeout_seconds:
                logger.warning("QR camera scan timed out after %.0fs", timeout_seconds)
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()

    return result
