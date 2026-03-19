"""
scanner.py - BLE Device Scanner for Tuiss SmartView Blinds

Scans for nearby BLE devices and can filter by name.
"""

import asyncio
import logging
from typing import Optional

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

logger = logging.getLogger(__name__)


async def scan_devices(
    timeout: float = 10.0,
    name_filter: Optional[str] = None,
) -> list[BLEDevice]:
    """
    Scan for nearby BLE devices.

    Args:
        timeout: How long to scan for, in seconds.
        name_filter: Optional substring to filter device names (case-insensitive).

    Returns:
        List of discovered BLEDevice objects.
    """
    logger.info("Starting BLE scan (timeout=%.1fs)...", timeout)
    devices: dict[str, tuple[BLEDevice, AdvertisementData]] = {}

    def detection_callback(device: BLEDevice, advertisement_data: AdvertisementData) -> None:
        devices[device.address] = (device, advertisement_data)

    scanner = BleakScanner(detection_callback=detection_callback)
    await scanner.start()
    await asyncio.sleep(timeout)
    await scanner.stop()

    results: list[BLEDevice] = []
    for device, _adv in devices.values():
        if name_filter:
            name = device.name or ""
            if name_filter.lower() not in name.lower():
                continue
        results.append(device)

    return results


def print_devices(devices: list[BLEDevice]) -> None:
    """Print a formatted table of discovered BLE devices."""
    if not devices:
        print("No devices found.")
        return

    print(f"\n{'#':<4} {'Name':<30} {'Address':<20} {'RSSI'}")
    print("-" * 65)
    for idx, device in enumerate(devices, start=1):
        name = device.name or "(unknown)"
        rssi = getattr(device, "rssi", "N/A")
        print(f"{idx:<4} {name:<30} {device.address:<20} {rssi}")
    print()
