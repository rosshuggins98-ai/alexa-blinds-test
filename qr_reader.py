"""
qr_reader.py - QR Code Reader for Tuiss SmartView Blinds Pairing

Reads QR codes from camera or image files and extracts the BLE MAC
address used to identify the correct blind during pairing.

Uses multiple image-preprocessing strategies (adaptive thresholding,
contrast enhancement, sharpening, etc.) combined with both OpenCV and
pyzbar decoders so that real-world photos — taken at an angle, with
uneven lighting, or through a phone camera — are decoded reliably.
"""

import logging
import re
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from pyzbar.pyzbar import decode as pyzbar_decode

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


# ---------------------------------------------------------------------------
# Image preprocessing strategies
# ---------------------------------------------------------------------------

def _preprocessing_variants(img: np.ndarray) -> list[tuple[str, np.ndarray]]:
    """
    Return a list of ``(name, image)`` tuples created by applying
    different preprocessing strategies to *img*.  The first entry is
    always the original image so the fast-path (clean QR) costs almost
    nothing.
    """
    variants: list[tuple[str, np.ndarray]] = [("original", img)]

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
    variants.append(("grayscale", gray))

    # Adaptive thresholding with various block sizes — the most
    # effective strategy for real-world photos with uneven lighting.
    for block_size in (31, 51, 101):
        for c_val in (5, 10, 15):
            thresh = cv2.adaptiveThreshold(
                gray, 255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                block_size, c_val,
            )
            variants.append((f"adaptive_b{block_size}_c{c_val}", thresh))

    # CLAHE contrast enhancement
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    variants.append(("clahe", enhanced))

    # Otsu binarisation
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(("otsu", otsu))

    # Sharpening
    kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
    sharpened = cv2.filter2D(gray, -1, kernel)
    variants.append(("sharpen", sharpened))

    return variants


def _try_decode(img: np.ndarray) -> Optional[str]:
    """
    Attempt to decode a QR code from *img* using both the OpenCV
    detector and pyzbar.  Returns the decoded string or ``None``.
    """
    # --- pyzbar (generally more robust for real-world images) ---
    try:
        results = pyzbar_decode(img)
        if results:
            data = results[0].data.decode("utf-8", errors="replace")
            if data:
                return data
    except Exception:  # noqa: BLE001
        pass

    # --- OpenCV QRCodeDetector ---
    try:
        if len(img.shape) == 2:
            detect_img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        else:
            detect_img = img
        detector = cv2.QRCodeDetector()
        data, _, _ = detector.detectAndDecode(detect_img)
        if data:
            return data
    except Exception:  # noqa: BLE001
        pass

    return None


def decode_qr(img: np.ndarray) -> Optional[str]:
    """
    Decode a QR code from an OpenCV image array, trying multiple
    preprocessing strategies until one succeeds.

    Args:
        img: BGR or grayscale image (NumPy array).

    Returns:
        Decoded QR string, or ``None`` if no QR code was found.
    """
    for name, variant in _preprocessing_variants(img):
        data = _try_decode(variant)
        if data:
            logger.info("QR decoded via '%s' strategy: %s", name, data)
            return data
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def read_qr_from_image(image_path: str) -> Optional[str]:
    """
    Decode a QR code from an image file.

    Uses multiple preprocessing strategies and decoders so that
    real-world photos (angled, blurry, uneven lighting) are handled
    reliably.

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

    data = decode_qr(img)
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

    result: Optional[str] = None
    start = cv2.getTickCount()
    freq = cv2.getTickFrequency()

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            data = decode_qr(frame)
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
