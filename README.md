# alexa-blinds-test

A Python BLE (Bluetooth Low Energy) tool for discovering and controlling
**Tuiss SmartView (Blinds2Go)** smart blinds locally from a PC — the first
step toward full Alexa integration.

---

## Requirements

- Python 3.10+
- A Bluetooth adapter (built-in or USB dongle)
- Windows, macOS, or Linux

### System dependencies for QR code features

The QR code reader (`qr-scan` command and GUI QR scanning) uses
[pyzbar](https://pypi.org/project/pyzbar/) which requires the **zbar**
shared library:

| OS | Install command |
|---|---|
| Ubuntu / Debian | `sudo apt install libzbar0` |
| Fedora | `sudo dnf install zbar` |
| macOS | `brew install zbar` |
| Windows | Included with the pyzbar wheel — no extra step needed |

> QR scanning is **optional**. The core BLE features (scan, connect,
> listen, send) only need `bleak` and work without zbar.

---

## Setup

Install all dependencies using the requirements file:

```bash
pip install -r requirements.txt
```

This installs:

| Package | Purpose |
|---|---|
| [bleak](https://pypi.org/project/bleak/) | Bluetooth Low Energy communication |
| [opencv-contrib-python-headless](https://pypi.org/project/opencv-contrib-python-headless/) | QR code decoding (includes WeChatQRCode) |
| [pyzbar](https://pypi.org/project/pyzbar/) | Additional QR code decoder |

If you only need the core BLE features (no QR scanning) you can install
just bleak:

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

1. **Identify your blind** — use one of these methods in the Scan tab:
   - 📷 Click the **camera button** to scan the QR code on the blind's
     battery compartment with your webcam, or
   - 📁 Click the **image file button** to load a photo of the QR code, or
   - ⌨️ Type the **hex pairing code** (e.g. `BFC83FE0`) from the QR
     sticker into the manual entry field and click **Apply**, or
   - Simply click **Scan** to discover all nearby BLE devices and pick
     yours from the list.
2. If you used a QR code or pairing code, the app automatically scans for
   nearby BLE devices and highlights matches in green.
3. Double-click a device (or select it and click **Select Device →**).
4. Click **Connect** in the top bar.
5. Switch to **Services** to explore the GATT profile.
6. Switch to **Listen**, click **Start Listening**, then use the Tuiss app
   to capture commands.
7. Switch to **Send**, pick a write characteristic, enter hex bytes, and
   click **Send**.

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
| `pair <code>` | Find a BLE device by its hex pairing code |
| `qr-scan` | Read the QR code on a blind (camera or image file) |

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

### Connecting with a pairing code

Each Tuiss SmartView blind has a small QR code sticker in the battery
compartment.  Scanning (or reading) this QR code gives you a **hex
pairing code** such as `BFC83FE0`.  The tool matches this code against
the names and addresses of nearby BLE devices to find your blind.

```bash
# Find the blind that matches pairing code BFC83FE0
python cli.py pair BFC83FE0

# Find the blind and immediately connect to it
python cli.py pair BFC83FE0 --connect

# Allow a longer BLE scan (default is 10 seconds)
python cli.py pair BFC83FE0 --timeout 20 --connect
```

If you have a photo of the QR code you can let the tool read it
automatically:

```bash
# Read the QR code from an image file
python cli.py qr-scan --image qr_photo.jpg

# Read the QR code and scan for matching BLE devices
python cli.py qr-scan --image qr_photo.jpg --scan

# Read the QR code, find the matching device, and connect
python cli.py qr-scan --image qr_photo.jpg --connect

# Use the webcam to scan the QR code (live camera view)
python cli.py qr-scan

# Camera scan with a custom timeout (default 30 seconds)
python cli.py qr-scan --timeout 15
```

---

## Project Structure

```
.
├── app.py              # Desktop GUI (tkinter) — launch with: python app.py
├── cli.py              # CLI entry point
├── scanner.py          # BLE scanner (scan & filter devices)
├── client.py           # BLE client (connect, services, notify, send)
├── qr_reader.py        # QR code reader & pairing-code parser
├── test_qr_reader.py   # Tests for the QR reader module
├── requirements.txt
└── README.md
```

---

## How It Works

### Step 1 — Discover your blinds

**Option A — Scan by name** (no pairing code needed):

```bash
python cli.py scan --filter blind
```

Note the **MAC address** shown for your Tuiss device.

**Option B — Use a known pairing code** (recommended):

Look at the QR code sticker in the battery compartment of your blind.
The code is typically 8 hex characters (e.g. `BFC83FE0`).

```bash
python cli.py pair BFC83FE0
```

The tool scans for nearby BLE devices and highlights any whose name or
MAC address contains the pairing code.

**Option C — Scan the QR code directly**:

```bash
python cli.py qr-scan --image qr_photo.jpg --scan
```

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

## Troubleshooting

| Problem | Solution |
|---|---|
| `ModuleNotFoundError: No module named 'bleak'` | Run `pip install -r requirements.txt` |
| `ImportError: Unable to find zbar shared library` | Install the zbar system library (see [Requirements](#system-dependencies-for-qr-code-features)) |
| No devices found during scan | Make sure the blind is powered on, in range, and not connected to another app |
| Pairing code doesn't match any device | Try a longer scan timeout (`--timeout 20`) or move closer to the blind |
| `Could not open camera` | Ensure a webcam is connected; try `--image` with a photo instead |

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
