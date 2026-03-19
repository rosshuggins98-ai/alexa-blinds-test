"""
client.py - BLE Client for Tuiss SmartView Blinds

Handles connecting to a BLE device, enumerating services/characteristics,
subscribing to notifications, and sending raw byte commands.
"""

import asyncio
import logging
from typing import Callable, Optional

from bleak import BleakClient, BleakError
from bleak.backends.characteristic import BleakGATTCharacteristic

logger = logging.getLogger(__name__)


class BlindsClient:
    """Async BLE client wrapper for interacting with a smart blinds device."""

    def __init__(self, address: str) -> None:
        self.address = address
        self._client: Optional[BleakClient] = None

    async def connect(self) -> None:
        """Connect to the BLE device at the stored address."""
        logger.info("Connecting to %s ...", self.address)
        self._client = BleakClient(self.address)
        await self._client.connect()
        if self._client.is_connected:
            logger.info("Connected to %s", self.address)
        else:
            raise ConnectionError(f"Failed to connect to {self.address}")

    async def disconnect(self) -> None:
        """Disconnect from the BLE device."""
        if self._client and self._client.is_connected:
            await self._client.disconnect()
            logger.info("Disconnected from %s", self.address)

    def is_connected(self) -> bool:
        """Return True if currently connected."""
        return self._client is not None and self._client.is_connected

    def _require_connected(self) -> None:
        if not self.is_connected():
            raise ConnectionError("Not connected to any device. Run 'connect' first.")

    async def list_services(self) -> None:
        """Print all GATT services and their characteristics."""
        self._require_connected()
        assert self._client is not None

        print("\n=== GATT Services ===")
        for service in self._client.services:
            print(f"\nService: {service.uuid}  ({service.description})")
            for char in service.characteristics:
                props = ", ".join(char.properties)
                print(f"  Characteristic: {char.uuid}")
                print(f"    Handle : 0x{char.handle:04x}")
                print(f"    Props  : {props}")
                print(f"    Desc   : {char.description}")
                for descriptor in char.descriptors:
                    print(f"      Descriptor: {descriptor.uuid}  handle=0x{descriptor.handle:04x}")
        print()

    async def start_notify(
        self,
        callback: Optional[Callable[[BleakGATTCharacteristic, bytearray], None]] = None,
    ) -> None:
        """
        Subscribe to notifications on all notify/indicate characteristics.

        Args:
            callback: Optional custom callback. Defaults to logging hex data.
        """
        self._require_connected()
        assert self._client is not None

        def default_callback(characteristic: BleakGATTCharacteristic, data: bytearray) -> None:
            logger.info(
                "[NOTIFY] uuid=%s  data=%s",
                characteristic.uuid,
                data.hex(),
            )
            print(f"[NOTIFY] {characteristic.uuid}: {data.hex()}")

        handler = callback or default_callback
        subscribed: list[str] = []

        for service in self._client.services:
            for char in service.characteristics:
                if "notify" in char.properties or "indicate" in char.properties:
                    try:
                        await self._client.start_notify(char.uuid, handler)
                        subscribed.append(char.uuid)
                        logger.info("Subscribed to notifications on %s", char.uuid)
                    except BleakError as exc:
                        logger.warning("Could not subscribe to %s: %s", char.uuid, exc)

        if subscribed:
            print(f"Listening on {len(subscribed)} characteristic(s). Press Ctrl+C to stop.\n")
        else:
            print("No notify/indicate characteristics found on this device.")

    async def stop_notify(self) -> None:
        """Unsubscribe from all active notifications."""
        if not self.is_connected():
            return
        assert self._client is not None
        for service in self._client.services:
            for char in service.characteristics:
                if "notify" in char.properties or "indicate" in char.properties:
                    try:
                        await self._client.stop_notify(char.uuid)
                    except BleakError as exc:
                        logger.warning("Could not unsubscribe from %s: %s", char.uuid, exc)

    async def send_command(self, char_uuid: str, data: bytes) -> None:
        """
        Write raw bytes to a specific characteristic.

        Args:
            char_uuid: UUID of the target characteristic.
            data: Raw bytes to send.
        """
        self._require_connected()
        assert self._client is not None

        # Determine whether to use write-with-response or write-without-response
        char = self._client.services.get_characteristic(char_uuid)
        if char is None:
            raise ValueError(f"Characteristic {char_uuid} not found on this device.")

        response = "write" in char.properties
        await self._client.write_gatt_char(char_uuid, data, response=response)
        logger.info(
            "Sent to %s: %s (response=%s)",
            char_uuid,
            data.hex(),
            response,
        )
        print(f"[SEND] {char_uuid}: {data.hex()}  (response={response})")
