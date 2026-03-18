# alexa-blinds-test

A Python BLE (Bluetooth Low Energy) tool for discovering and controlling
**Tuiss SmartView (Blinds2Go)** smart blinds locally from a PC — the first
step toward full Alexa integration.

---

## Requirements

- Python 3.10+
- A Bluetooth adapter (built-in or USB dongle)
- Windows, macOS, or Linux

---

## Setup

Install the single dependency using the requirements file (recommended):

```bash
pip install -r requirements.txt
```

Or install directly:

```bash
pip install bleak
```

---

## Desktop GUI App (recommended)

The easiest way to use the tool is the graphical desktop app:

```bash
python app.py
```

> **Requires tkinter** — bundled with Python on Windows and macOS.
> On Ubuntu/Debian Linux: `sudo apt install python3-tk`

The app has four tabs:

| Tab | What it does |
|---|---|
| **Scan** | Discover nearby BLE devices (filter by name, set timeout) |
| **Services** | View all GATT services and characteristics after connecting |
| **Listen** | Subscribe to BLE notifications and log incoming data in hex |
| **Send** | Write raw hex bytes to any characteristic |

### Quick start

1. Click **Scan** — devices appear in the list.
2. Double-click a device (or select it and click **Select Device →**).
3. Click **Connect** in the top bar.
4. Switch to **Services** to explore the GATT profile.
5. Switch to **Listen**, click **Start Listening**, then use the Tuiss app to capture commands.
6. Switch to **Send**, pick a write characteristic, enter hex bytes, and click **Send**.

---

## Command-Line Interface

```
python cli.py [-v] <command> [options]
```

### Commands

| Command | Description |
|---|---|
| `scan` | Scan for nearby BLE devices |
| `connect <address>` | Test-connect to a device |
| `list-services <address>` | Enumerate GATT services and characteristics |
| `listen <address>` | Sniff/log all BLE notifications |
| `send <address> <char-uuid> <hex>` | Send raw bytes to a characteristic |

### Examples

```bash
# Scan for all nearby BLE devices (10-second scan)
python cli.py scan

# Scan and filter by name (e.g. "blind", "tuiss", "smart")
python cli.py scan --filter blind

# Extend scan time to 20 seconds
python cli.py scan --timeout 20

# Connect to a device to verify it is reachable
python cli.py connect AA:BB:CC:DD:EE:FF

# List all GATT services and characteristics
python cli.py list-services AA:BB:CC:DD:EE:FF

# Listen for BLE notifications (sniffing mode, Ctrl+C to stop)
python cli.py listen AA:BB:CC:DD:EE:FF

# Send raw bytes to a characteristic
python cli.py send AA:BB:CC:DD:EE:FF 0000fff1-0000-1000-8000-00805f9b34fb 01ff0a

# Enable verbose/debug logging for any command
python cli.py -v scan
```

---

## Project Structure

```
.
├── app.py          # Desktop GUI (tkinter) — launch with: python app.py
├── cli.py          # CLI entry point
├── scanner.py      # BLE scanner (scan & filter devices)
├── client.py       # BLE client (connect, services, notify, send)
├── requirements.txt
└── README.md
```

---

## How It Works

### Step 1 — Discover your blinds

```bash
python cli.py scan --filter blind
```

Note the **MAC address** shown for your Tuiss device.

### Step 2 — Explore its GATT profile

```bash
python cli.py list-services AA:BB:CC:DD:EE:FF
```

This lists every service and characteristic UUID, along with their
properties (`read`, `write`, `notify`, etc.).

### Step 3 — Sniff traffic while using the Tuiss app

```bash
python cli.py listen AA:BB:CC:DD:EE:FF
```

With this running, open the official Tuiss SmartView app and press the
open/close buttons.  Incoming notification data will be logged in hex,
helping you reverse-engineer the command format.

### Step 4 — Replay commands

Once you have identified a likely write characteristic and command bytes:

```bash
python cli.py send AA:BB:CC:DD:EE:FF <char-uuid> <hex-command>
```

---

## Next Steps Toward Alexa Integration

1. **Identify commands** — Use the `listen` + Tuiss app method above to
   capture the exact byte sequences for open, close, and position.
2. **Build a local HTTPS server** — Wrap the `BlindsClient` in a small
   Flask/FastAPI server exposing `/open`, `/close`, `/position` endpoints.
3. **Create an Alexa Smart Home Skill** — Use the
   [Alexa Smart Home Skill API](https://developer.amazon.com/en-US/docs/alexa/smarthome/understand-the-smart-home-skill-api.html)
   with an AWS Lambda function that calls your local server (via
   port-forwarding or a tunnel such as ngrok).
4. **Alternatively use Matter/Thread** — If the blinds ever gain Matter
   support, native Alexa integration becomes trivial.
