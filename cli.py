"""
cli.py - Command-Line Interface for Tuiss SmartView Blinds BLE Control

Usage:
    python cli.py scan [--filter <name>] [--timeout <seconds>]
    python cli.py connect <address>
    python cli.py list-services <address>
    python cli.py listen <address>
    python cli.py send <address> <char-uuid> <hex-data>

Examples:
    python cli.py scan
    python cli.py scan --filter blind
    python cli.py connect AA:BB:CC:DD:EE:FF
    python cli.py list-services AA:BB:CC:DD:EE:FF
    python cli.py listen AA:BB:CC:DD:EE:FF
    python cli.py send AA:BB:CC:DD:EE:FF 0000fff1-0000-1000-8000-00805f9b34fb 01ff0a
"""

import argparse
import asyncio
import logging
import sys

from client import BlindsClient
from scanner import print_devices, scan_devices


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=level,
    )


# ---------------------------------------------------------------------------
# Sub-command handlers
# ---------------------------------------------------------------------------


async def cmd_scan(args: argparse.Namespace) -> None:
    """Scan for nearby BLE devices."""
    devices = await scan_devices(
        timeout=args.timeout,
        name_filter=args.filter,
    )
    print_devices(devices)


async def cmd_connect(args: argparse.Namespace) -> None:
    """Connect to a device and confirm the connection, then disconnect."""
    client = BlindsClient(args.address)
    try:
        await client.connect()
        print(f"Successfully connected to {args.address}.")
    except Exception as exc:
        print(f"[ERROR] Could not connect: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        await client.disconnect()


async def cmd_list_services(args: argparse.Namespace) -> None:
    """Connect to a device and list all GATT services and characteristics."""
    client = BlindsClient(args.address)
    try:
        await client.connect()
        await client.list_services()
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        await client.disconnect()


async def cmd_listen(args: argparse.Namespace) -> None:
    """Connect to a device and listen for BLE notifications (sniffing mode)."""
    client = BlindsClient(args.address)
    try:
        await client.connect()
        await client.start_notify()
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping listener...")
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        await client.stop_notify()
        await client.disconnect()


async def cmd_send(args: argparse.Namespace) -> None:
    """Connect to a device and send raw bytes to a characteristic."""
    try:
        data = bytes.fromhex(args.hex_data)
    except ValueError:
        print(f"[ERROR] Invalid hex string: '{args.hex_data}'", file=sys.stderr)
        sys.exit(1)

    client = BlindsClient(args.address)
    try:
        await client.connect()
        await client.send_command(args.char_uuid, data)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        await client.disconnect()


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="BLE control tool for Tuiss SmartView blinds.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose/debug logging.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # scan
    p_scan = subparsers.add_parser("scan", help="Scan for nearby BLE devices.")
    p_scan.add_argument(
        "--filter",
        metavar="NAME",
        default=None,
        help="Filter results by device name substring (case-insensitive).",
    )
    p_scan.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        metavar="SECONDS",
        help="Scan duration in seconds (default: 10).",
    )

    # connect
    p_connect = subparsers.add_parser(
        "connect",
        help="Connect to a device and verify the connection.",
    )
    p_connect.add_argument("address", help="Device MAC address (e.g. AA:BB:CC:DD:EE:FF).")

    # list-services
    p_ls = subparsers.add_parser(
        "list-services",
        help="List all GATT services and characteristics of a device.",
    )
    p_ls.add_argument("address", help="Device MAC address.")

    # listen
    p_listen = subparsers.add_parser(
        "listen",
        help="Subscribe to all notifications from a device (sniffing mode).",
    )
    p_listen.add_argument("address", help="Device MAC address.")

    # send
    p_send = subparsers.add_parser(
        "send",
        help="Send raw bytes to a specific characteristic.",
    )
    p_send.add_argument("address", help="Device MAC address.")
    p_send.add_argument("char_uuid", metavar="char-uuid", help="Target characteristic UUID.")
    p_send.add_argument(
        "hex_data",
        metavar="hex-data",
        help="Hex-encoded bytes to send (e.g. 01ff0a).",
    )

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    _setup_logging(verbose=args.verbose)

    handlers = {
        "scan": cmd_scan,
        "connect": cmd_connect,
        "list-services": cmd_list_services,
        "listen": cmd_listen,
        "send": cmd_send,
    }

    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    asyncio.run(handler(args))


if __name__ == "__main__":
    main()
