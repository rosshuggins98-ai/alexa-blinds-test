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

# WeChatQRCode is available in opencv-contrib but not in plain opencv.
_HAS_WECHAT_QR = hasattr(cv2, "wechat_qrcode")

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

def _add_quiet_zone(img: np.ndarray, pad: int = 40) -> np.ndarray:
    """Add a white border around the image to ensure a QR quiet zone."""
    value = 255 if len(img.shape) == 2 else (255, 255, 255)
    return cv2.copyMakeBorder(
        img, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=value,
    )


def _preprocessing_variants(
    img: np.ndarray,
    *,
    quick: bool = False,
) -> list[tuple[str, np.ndarray]]:
    """
    Return a list of ``(name, image)`` tuples created by applying
    different preprocessing strategies to *img*.  The first entry is
    always the original image so the fast-path (clean QR) costs almost
    nothing.

    When *quick* is ``True`` a smaller set of strategies is used, which
    is better suited for per-frame camera scanning where latency matters.
    """
    variants: list[tuple[str, np.ndarray]] = [("original", img)]

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
    variants.append(("grayscale", gray))

    if quick:
        # Lightweight set for live camera frames
        thresh = cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            51, 10,
        )
        variants.append(("adaptive_b51_c10", thresh))
        variants.append(("adaptive_b51_c10_pad", _add_quiet_zone(thresh)))
        return variants

    # ------------------------------------------------------------------
    # Full set for static images (e.g. photos loaded from file).
    # ------------------------------------------------------------------

    # Padded original / grayscale (fixes missing quiet zone)
    variants.append(("original_pad", _add_quiet_zone(img)))
    variants.append(("grayscale_pad", _add_quiet_zone(gray)))

    # Downscaled variants — large phone photos (3000×4000) can confuse
    # decoders; resizing to a moderate resolution often helps.
    h, w = gray.shape[:2]
    for target in (800, 1200):
        if max(h, w) > target * 1.5:
            scale = target / max(h, w)
            small = cv2.resize(gray, None, fx=scale, fy=scale,
                               interpolation=cv2.INTER_AREA)
            variants.append((f"downscale_{target}", small))
            variants.append((f"downscale_{target}_pad",
                             _add_quiet_zone(small)))

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
            variants.append((f"adaptive_b{block_size}_c{c_val}_pad",
                             _add_quiet_zone(thresh)))

    # CLAHE contrast enhancement
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    variants.append(("clahe", enhanced))
    variants.append(("clahe_pad", _add_quiet_zone(enhanced)))

    # Otsu binarisation
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(("otsu", otsu))
    variants.append(("otsu_pad", _add_quiet_zone(otsu)))

    # Sharpening
    kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
    sharpened = cv2.filter2D(gray, -1, kernel)
    variants.append(("sharpen", sharpened))
    variants.append(("sharpen_pad", _add_quiet_zone(sharpened)))

    # --- Additional strategies for severely degraded real-world photos ---

    # Denoising (non-local means) — much better than simple blur
    denoised = cv2.fastNlMeansDenoising(gray, h=12)
    variants.append(("denoise", denoised))
    variants.append(("denoise_pad", _add_quiet_zone(denoised)))
    for block_size in (31, 51, 101):
        dt = cv2.adaptiveThreshold(
            denoised, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            block_size, 10,
        )
        variants.append((f"denoise_adaptive_b{block_size}", dt))
        variants.append((f"denoise_adaptive_b{block_size}_pad",
                         _add_quiet_zone(dt)))

    # Bilateral filter — edge-preserving smoothing
    bilateral = cv2.bilateralFilter(gray, 11, 75, 75)
    for block_size in (31, 51, 101):
        bt = cv2.adaptiveThreshold(
            bilateral, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            block_size, 10,
        )
        variants.append((f"bilateral_adaptive_b{block_size}_pad",
                         _add_quiet_zone(bt)))

    # Morphological cleanup — close small gaps then remove speckles
    morph_kernel = np.ones((3, 3), np.uint8)
    for block_size in (31, 51, 101):
        thresh = cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            block_size, 10,
        )
        cleaned = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, morph_kernel)
        cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, morph_kernel)
        variants.append((f"morph_b{block_size}_pad", _add_quiet_zone(cleaned)))

    # Gamma correction — recovers detail in shadowed areas
    for gamma in (0.5, 0.7, 1.5):
        table = np.array([
            np.clip(((i / 255.0) ** gamma) * 255, 0, 255)
            for i in range(256)
        ], dtype=np.uint8)
        corrected = cv2.LUT(gray, table)
        variants.append((f"gamma_{gamma}", corrected))
        variants.append((f"gamma_{gamma}_pad", _add_quiet_zone(corrected)))

    # Upscaled variants — helps when QR modules are very small / blurry
    scale = 2
    up = cv2.resize(gray, None, fx=scale, fy=scale,
                    interpolation=cv2.INTER_CUBIC)
    variants.append(("upscale_2x", up))
    variants.append(("upscale_2x_pad", _add_quiet_zone(up)))
    for block_size in (51, 101):
        ut = cv2.adaptiveThreshold(
            up, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            block_size, 10,
        )
        variants.append((f"upscale_adaptive_b{block_size}_pad",
                         _add_quiet_zone(ut)))

    # Combined: CLAHE → adaptive threshold → padding
    for block_size in (51, 101):
        ct = cv2.adaptiveThreshold(
            enhanced, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            block_size, 10,
        )
        variants.append((f"clahe_adaptive_b{block_size}_pad",
                         _add_quiet_zone(ct)))

    # Combined: denoise → CLAHE → adaptive threshold → padding
    dn_enhanced = clahe.apply(denoised)
    for block_size in (51, 101):
        dct = cv2.adaptiveThreshold(
            dn_enhanced, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            block_size, 10,
        )
        variants.append((f"denoise_clahe_adaptive_b{block_size}_pad",
                         _add_quiet_zone(dct)))

    return variants


def _try_decode(img: np.ndarray) -> Optional[str]:
    """
    Attempt to decode a QR code from *img* using WeChatQRCode, pyzbar,
    and the basic OpenCV detector (in order of robustness).
    Returns the decoded string or ``None``.
    """
    # --- WeChatQRCode (most robust for real-world images) ---
    if _HAS_WECHAT_QR:
        try:
            if len(img.shape) == 2:
                detect_img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            else:
                detect_img = img
            wechat = cv2.wechat_qrcode.WeChatQRCode()
            results, _ = wechat.detectAndDecode(detect_img)
            if results and results[0]:
                return results[0]
        except Exception:  # noqa: BLE001
            pass

    # --- pyzbar ---
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


def decode_qr(img: np.ndarray, *, quick: bool = False) -> Optional[str]:
    """
    Decode a QR code from an OpenCV image array, trying multiple
    preprocessing strategies until one succeeds.

    Args:
        img: BGR or grayscale image (NumPy array).
        quick: When ``True`` use a lightweight set of preprocessing
            strategies suitable for live camera frames.

    Returns:
        Decoded QR string, or ``None`` if no QR code was found.
    """
    for name, variant in _preprocessing_variants(img, quick=quick):
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

            data = decode_qr(frame, quick=True)
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
