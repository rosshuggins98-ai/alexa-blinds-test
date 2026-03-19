"""
app.py - Desktop GUI for Tuiss SmartView Blinds BLE Control

Launch with:
    python app.py

Requires Python 3.10+ and the bleak library:
    pip install -r requirements.txt

tkinter is included with Python on Windows and macOS.
On Ubuntu/Debian Linux: sudo apt install python3-tk
"""

import asyncio
import logging
import threading
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import filedialog, messagebox, scrolledtext
from typing import Optional

from bleak.backends.device import BLEDevice

from client import BlindsClient
from qr_reader import parse_mac_address, parse_pairing_code, read_qr_from_camera, read_qr_from_image
from scanner import scan_devices

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Background asyncio loop (shared by all BLE operations)
# ---------------------------------------------------------------------------
_loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()


def _start_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


_loop_thread = threading.Thread(target=_start_loop, args=(_loop,), daemon=True)
_loop_thread.start()


def _run_async(coro):
    """Submit a coroutine to the background event loop and return a Future."""
    return asyncio.run_coroutine_threadsafe(coro, _loop)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

class BlindsApp(tk.Tk):
    """Main application window."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Tuiss SmartView Blinds — BLE Control")
        self.resizable(True, True)
        self.minsize(720, 520)

        # Shared state
        self._client: Optional[BlindsClient] = None
        self._selected_device: Optional[BLEDevice] = None
        self._scanned_devices: list[BLEDevice] = []
        # (service_uuid, char_uuid, properties) tuples
        self._characteristics: list[tuple[str, str, str]] = []

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # ── Status bar ────────────────────────────────────────────────
        status_frame = ttk.Frame(self, relief=tk.SUNKEN)
        status_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self._status_var = tk.StringVar(value="Ready.")
        ttk.Label(status_frame, textvariable=self._status_var, anchor=tk.W,
                  padding=(6, 2)).pack(fill=tk.X)

        # ── Connection bar ────────────────────────────────────────────
        conn_frame = ttk.LabelFrame(self, text="Connected Device", padding=6)
        conn_frame.pack(fill=tk.X, padx=8, pady=(8, 0))

        self._conn_label_var = tk.StringVar(value="No device selected.")
        ttk.Label(conn_frame, textvariable=self._conn_label_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True)

        self._btn_disconnect = ttk.Button(
            conn_frame, text="Disconnect", command=self._disconnect,
            state=tk.DISABLED)
        self._btn_disconnect.pack(side=tk.RIGHT, padx=(4, 0))

        self._btn_connect = ttk.Button(
            conn_frame, text="Connect", command=self._connect,
            state=tk.DISABLED)
        self._btn_connect.pack(side=tk.RIGHT, padx=(4, 0))

        # ── Notebook ──────────────────────────────────────────────────
        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        self._tab_scan = ScanTab(nb, self)
        self._tab_services = ServicesTab(nb, self)
        self._tab_listen = ListenTab(nb, self)
        self._tab_send = SendTab(nb, self)

        nb.add(self._tab_scan, text="  Scan  ")
        nb.add(self._tab_services, text="  Services  ")
        nb.add(self._tab_listen, text="  Listen  ")
        nb.add(self._tab_send, text="  Send  ")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def set_status(self, msg: str) -> None:
        """Update the bottom status bar (thread-safe)."""
        self.after(0, lambda: self._status_var.set(msg))

    def _select_device(self, device: BLEDevice) -> None:
        """Called by ScanTab when the user picks a device."""
        self._selected_device = device
        name = device.name or "(unknown)"
        self._conn_label_var.set(f"{name}  [{device.address}]  — not connected")
        self._btn_connect.config(state=tk.NORMAL)
        self._btn_disconnect.config(state=tk.DISABLED)
        self.set_status(f"Device selected: {name} ({device.address})")

    def _connect(self) -> None:
        if self._selected_device is None:
            messagebox.showwarning("No device", "Please scan and select a device first.")
            return
        if self._client and self._client.is_connected():
            messagebox.showinfo("Already connected", "Already connected to a device.")
            return

        address = self._selected_device.address
        self._client = BlindsClient(address)
        self._btn_connect.config(state=tk.DISABLED)
        self.set_status(f"Connecting to {address}…")

        def _done(fut):
            try:
                fut.result()
                name = (self._selected_device.name or "(unknown)"
                        if self._selected_device else address)
                self.after(0, self._on_connected, name, address)
            except Exception as exc:  # noqa: BLE001
                self.after(0, self._on_connect_error, exc)

        _run_async(self._client.connect()).add_done_callback(_done)

    def _on_connected(self, name: str, address: str) -> None:
        self._conn_label_var.set(f"{name}  [{address}]  ✓ connected")
        self._btn_disconnect.config(state=tk.NORMAL)
        self._btn_connect.config(state=tk.DISABLED)
        self.set_status(f"Connected to {name} ({address})")
        # Populate Services tab
        self._tab_services.refresh()
        # Populate Send tab characteristic list
        self._tab_send.refresh()

    def _on_connect_error(self, exc: Exception) -> None:
        self._btn_connect.config(state=tk.NORMAL)
        self._conn_label_var.set("Connection failed.")
        self.set_status(f"Connection error: {exc}")
        messagebox.showerror("Connection Error", str(exc))

    def _disconnect(self) -> None:
        if self._client is None or not self._client.is_connected():
            return
        self._btn_disconnect.config(state=tk.DISABLED)
        self.set_status("Disconnecting…")

        # Stop any active listener first
        self._tab_listen.stop_listening()

        def _done(fut):
            self.after(0, self._on_disconnected)

        _run_async(self._client.disconnect()).add_done_callback(_done)

    def _on_disconnected(self) -> None:
        name = ""
        if self._selected_device:
            name = self._selected_device.name or self._selected_device.address
        self._conn_label_var.set(
            f"{name}  [{self._selected_device.address if self._selected_device else ''}]"
            "  — disconnected")
        self._btn_connect.config(state=tk.NORMAL)
        self._btn_disconnect.config(state=tk.DISABLED)
        self.set_status("Disconnected.")
        self._tab_services.clear()
        self._tab_send.clear()
        self._tab_listen.on_disconnected()

    def _on_close(self) -> None:
        """Gracefully stop background tasks and close the window."""
        if self._client and self._client.is_connected():
            _run_async(self._client.disconnect())
        _loop.call_soon_threadsafe(_loop.stop)
        self.destroy()


# ---------------------------------------------------------------------------
# Tab: Scan
# ---------------------------------------------------------------------------

class ScanTab(ttk.Frame):
    def __init__(self, parent: ttk.Notebook, app: BlindsApp) -> None:
        super().__init__(parent, padding=8)
        self._app = app
        self._qr_mac: Optional[str] = None
        self._qr_pairing_code: Optional[str] = None
        self._build()

    def _build(self) -> None:
        # ── QR Code / Pairing Code ────────────────────────────────────
        qr_frame = ttk.LabelFrame(self, text="Step 1 — Identify Your Blind", padding=6)
        qr_frame.pack(fill=tk.X, pady=(0, 8))

        # Row 1: QR scanning
        qr_row = ttk.Frame(qr_frame)
        qr_row.pack(fill=tk.X)

        ttk.Label(
            qr_row,
            text="Scan QR code:",
        ).pack(side=tk.LEFT)

        self._btn_qr_camera = ttk.Button(
            qr_row, text="📷  Camera", command=self._qr_scan_camera)
        self._btn_qr_camera.pack(side=tk.LEFT, padx=(8, 0))

        self._btn_qr_file = ttk.Button(
            qr_row, text="📁  Image File", command=self._qr_scan_file)
        self._btn_qr_file.pack(side=tk.LEFT, padx=(4, 0))

        self._qr_status_var = tk.StringVar(value="")
        ttk.Label(qr_row, textvariable=self._qr_status_var,
                  foreground="grey").pack(side=tk.LEFT, padx=(12, 0))

        # Row 2: Manual pairing code entry
        code_row = ttk.Frame(qr_frame)
        code_row.pack(fill=tk.X, pady=(4, 0))

        ttk.Label(code_row, text="Or enter code:").pack(side=tk.LEFT)
        self._code_var = tk.StringVar()
        self._code_entry = ttk.Entry(code_row, textvariable=self._code_var, width=20)
        self._code_entry.pack(side=tk.LEFT, padx=(8, 0))

        self._btn_code_apply = ttk.Button(
            code_row, text="Apply", command=self._apply_manual_code)
        self._btn_code_apply.pack(side=tk.LEFT, padx=(4, 0))

        ttk.Label(
            code_row,
            text="(hex code printed on the blind's QR sticker, e.g. BFC83FE0)",
            foreground="grey",
        ).pack(side=tk.LEFT, padx=(8, 0))

        # ── BLE scan controls ────────────────────────────────────────
        scan_frame = ttk.LabelFrame(self, text="Step 2 — Scan for BLE Devices", padding=6)
        scan_frame.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(scan_frame, text="Filter:").pack(side=tk.LEFT)
        self._filter_var = tk.StringVar()
        ttk.Entry(scan_frame, textvariable=self._filter_var, width=16).pack(
            side=tk.LEFT, padx=(4, 12))

        ttk.Label(scan_frame, text="Timeout (s):").pack(side=tk.LEFT)
        self._timeout_var = tk.DoubleVar(value=10.0)
        ttk.Spinbox(scan_frame, from_=3, to=60, increment=1,
                    textvariable=self._timeout_var, width=6).pack(
            side=tk.LEFT, padx=(4, 12))

        self._btn_scan = ttk.Button(scan_frame, text="▶  Scan", command=self._start_scan)
        self._btn_scan.pack(side=tk.LEFT)

        # Results table
        cols = ("name", "address", "rssi")
        self._tree = ttk.Treeview(self, columns=cols, show="headings",
                                   selectmode="browse")
        self._tree.heading("name",    text="Device Name")
        self._tree.heading("address", text="MAC Address")
        self._tree.heading("rssi",    text="RSSI")
        self._tree.column("name",    width=240, anchor=tk.W)
        self._tree.column("address", width=160, anchor=tk.W)
        self._tree.column("rssi",    width=70,  anchor=tk.CENTER)

        vsb = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.LEFT, fill=tk.Y)

        # Select button
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, pady=(6, 0))
        self._btn_select = ttk.Button(
            btn_frame, text="Select Device →", command=self._select_device,
            state=tk.DISABLED)
        self._btn_select.pack(side=tk.RIGHT)

        self._tree.bind("<<TreeviewSelect>>",
                        lambda _e: self._btn_select.config(state=tk.NORMAL))
        self._tree.bind("<Double-1>", lambda _e: self._select_device())

    # -- QR scanning -------------------------------------------------

    def _qr_scan_camera(self) -> None:
        """Open the camera to scan a QR code."""
        self._app.set_status("Opening camera to scan QR code…")
        self._btn_qr_camera.config(state=tk.DISABLED)

        def _scan():
            try:
                data = read_qr_from_camera(timeout_seconds=30)
                self._app.after(0, self._on_qr_result, data)
            except Exception as exc:  # noqa: BLE001
                self._app.after(0, self._on_qr_error, exc)

        threading.Thread(target=_scan, daemon=True).start()

    def _qr_scan_file(self) -> None:
        """Let the user choose an image file containing a QR code."""
        path = filedialog.askopenfilename(
            title="Select QR Code Image",
            filetypes=[
                ("Image Files", "*.png *.jpg *.jpeg *.bmp *.tiff *.webp"),
                ("All Files", "*.*"),
            ],
        )
        if not path:
            return
        try:
            data = read_qr_from_image(path)
            self._on_qr_result(data)
        except Exception as exc:  # noqa: BLE001
            self._on_qr_error(exc)

    def _on_qr_result(self, data: Optional[str]) -> None:
        self._btn_qr_camera.config(state=tk.NORMAL)
        if data is None:
            self._qr_status_var.set(
                "No QR code detected — enter the code manually below.")
            self._app.set_status(
                "QR scan: no code detected.  "
                "Tip: enter the pairing code printed on the QR sticker manually.")
            return

        mac = parse_mac_address(data)
        if mac:
            self._qr_mac = mac
            self._qr_pairing_code = None
            self._qr_status_var.set(f"✓ Device MAC: {mac}")
            self._app.set_status(f"QR scan successful — device MAC: {mac}")
            self._auto_select_qr_device()
            return

        code = parse_pairing_code(data)
        if code:
            self._qr_mac = None
            self._qr_pairing_code = code
            self._qr_status_var.set(
                f"✓ Pairing code: {code}  — scan BLE devices to find your blind")
            self._app.set_status(f"QR scan successful — pairing code: {code}")
            self._auto_select_by_pairing_code()
            return

        # Fallback — show whatever we got
        self._qr_mac = None
        self._qr_pairing_code = None
        self._qr_status_var.set(f"QR data: {data}  (no MAC or pairing code found)")
        self._app.set_status(f"QR code read but no MAC or pairing code found: {data}")

    def _on_qr_error(self, exc: Exception) -> None:
        self._btn_qr_camera.config(state=tk.NORMAL)
        self._qr_status_var.set("QR scan failed.")
        self._app.set_status(f"QR scan error: {exc}")
        messagebox.showerror("QR Scan Error", str(exc))

    def _apply_manual_code(self) -> None:
        """Apply a manually-entered pairing code or MAC address."""
        raw = self._code_var.get().strip()
        if not raw:
            return

        mac = parse_mac_address(raw)
        if mac:
            self._qr_mac = mac
            self._qr_pairing_code = None
            self._qr_status_var.set(f"✓ Device MAC: {mac}")
            self._app.set_status(f"Manual entry — device MAC: {mac}")
            self._auto_select_qr_device()
            return

        code = parse_pairing_code(raw)
        if code:
            self._qr_mac = None
            self._qr_pairing_code = code
            self._qr_status_var.set(
                f"✓ Pairing code: {code}  — scan BLE devices to find your blind")
            self._app.set_status(f"Manual entry — pairing code: {code}")
            self._auto_select_by_pairing_code()
            return

        # Accept any even-length hex string the user types
        cleaned = raw.upper().replace(" ", "").replace(":", "").replace("-", "")
        import re
        if re.fullmatch(r"[0-9A-F]{4,16}", cleaned) and len(cleaned) % 2 == 0:
            self._qr_mac = None
            self._qr_pairing_code = cleaned
            self._qr_status_var.set(
                f"✓ Pairing code: {cleaned}  — scan BLE devices to find your blind")
            self._app.set_status(f"Manual entry — pairing code: {cleaned}")
            self._auto_select_by_pairing_code()
            return

        messagebox.showwarning(
            "Invalid Code",
            "Enter a hex pairing code (e.g. BFC83FE0) or "
            "a MAC address (e.g. AA:BB:CC:DD:EE:FF)."
        )

    def _auto_select_qr_device(self) -> None:
        """If a QR MAC was scanned, try to select the matching device."""
        if not self._qr_mac:
            return
        mac_upper = self._qr_mac.upper()
        for device in self._app._scanned_devices:
            if device.address.upper() == mac_upper:
                # Highlight in treeview and auto-select
                self._tree.selection_set(device.address)
                self._tree.see(device.address)
                self._app._select_device(device)
                self._app.set_status(
                    f"Auto-selected device matching QR code: {device.name or device.address}")
                return

    def _auto_select_by_pairing_code(self) -> None:
        """If a QR pairing code was scanned, try to find a matching device.

        Checks both device names and MAC addresses for the pairing code
        substring (case-insensitive).  Tags matching rows in the tree.
        """
        if not self._qr_pairing_code:
            return
        code_upper = self._qr_pairing_code.upper()
        matches: list[BLEDevice] = []
        for device in self._app._scanned_devices:
            name = (device.name or "").upper()
            addr = device.address.upper().replace(":", "").replace("-", "")
            if code_upper in name or code_upper in addr:
                matches.append(device)
                # Highlight the matching row with a tag
                try:
                    self._tree.item(device.address, tags=("qr_match",))
                except tk.TclError:
                    pass

        if matches:
            self._tree.tag_configure("qr_match", background="#d4edda")
            first = matches[0]
            self._tree.selection_set(first.address)
            self._tree.see(first.address)
            self._app._select_device(first)
            self._app.set_status(
                f"Found {len(matches)} device(s) matching pairing code "
                f"{self._qr_pairing_code}: {first.name or first.address}")
        else:
            if self._app._scanned_devices:
                self._app.set_status(
                    f"No device found matching pairing code "
                    f"{self._qr_pairing_code} — try scanning again")

    # -- BLE scanning ------------------------------------------------

    def _start_scan(self) -> None:
        self._btn_scan.config(state=tk.DISABLED, text="Scanning…")
        self._btn_select.config(state=tk.DISABLED)
        # Clear old results
        for item in self._tree.get_children():
            self._tree.delete(item)
        self._app._scanned_devices.clear()

        name_filter = self._filter_var.get().strip() or None
        timeout = self._timeout_var.get()
        self._app.set_status(f"Scanning for {timeout:.0f}s…")

        def _done(fut):
            try:
                devices: list[BLEDevice] = fut.result()
                self._app.after(0, self._populate, devices)
            except Exception as exc:  # noqa: BLE001
                self._app.after(0, self._scan_error, exc)

        _run_async(scan_devices(timeout=timeout, name_filter=name_filter)).add_done_callback(
            _done)

    def _populate(self, devices: list[BLEDevice]) -> None:
        self._app._scanned_devices = devices
        for device in devices:
            rssi = getattr(device, "rssi", "N/A")
            self._tree.insert(
                "", tk.END,
                iid=device.address,
                values=(device.name or "(unknown)", device.address, rssi),
            )
        self._btn_scan.config(state=tk.NORMAL, text="▶  Scan")
        count = len(devices)
        self._app.set_status(f"Scan complete — {count} device(s) found.")
        # If a QR code was previously scanned, auto-select the matching device
        self._auto_select_qr_device()
        self._auto_select_by_pairing_code()

    def _scan_error(self, exc: Exception) -> None:
        self._btn_scan.config(state=tk.NORMAL, text="▶  Scan")
        self._app.set_status(f"Scan error: {exc}")
        messagebox.showerror("Scan Error", str(exc))

    def _select_device(self) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        address = sel[0]  # iid is the address
        device = next(
            (d for d in self._app._scanned_devices if d.address == address), None)
        if device:
            self._app._select_device(device)


# ---------------------------------------------------------------------------
# Tab: Services
# ---------------------------------------------------------------------------

class ServicesTab(ttk.Frame):
    def __init__(self, parent: ttk.Notebook, app: BlindsApp) -> None:
        super().__init__(parent, padding=8)
        self._app = app
        self._build()

    def _build(self) -> None:
        self._tree = ttk.Treeview(self, show="tree headings")
        self._tree.heading("#0", text="Service / Characteristic")
        self._tree["columns"] = ("handle", "properties", "description")
        self._tree.heading("handle",      text="Handle")
        self._tree.heading("properties",  text="Properties")
        self._tree.heading("description", text="Description")
        self._tree.column("#0",           width=300, anchor=tk.W)
        self._tree.column("handle",       width=70,  anchor=tk.CENTER)
        self._tree.column("properties",   width=200, anchor=tk.W)
        self._tree.column("description",  width=180, anchor=tk.W)

        vsb = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self._tree.yview)
        hsb = ttk.Scrollbar(self, orient=tk.HORIZONTAL, command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self._placeholder = ttk.Label(
            self, text="Connect to a device to view its GATT services.",
            foreground="grey")
        self._placeholder.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

    def refresh(self) -> None:
        """Populate the tree from the connected client."""
        self._placeholder.place_forget()
        self.clear()
        client = self._app._client
        if client is None or not client.is_connected():
            return

        assert client._client is not None
        self._app._characteristics.clear()

        for service in client._client.services:
            svc_node = self._tree.insert(
                "", tk.END,
                text=f"Service: {service.uuid}",
                values=("", "", service.description),
                open=True,
                tags=("service",),
            )
            for char in service.characteristics:
                props = ", ".join(char.properties)
                self._tree.insert(
                    svc_node, tk.END,
                    text=char.uuid,
                    values=(f"0x{char.handle:04x}", props, char.description),
                    tags=("characteristic",),
                )
                self._app._characteristics.append(
                    (service.uuid, char.uuid, props))

        self._tree.tag_configure("service", background="#eef2ff")

    def clear(self) -> None:
        for item in self._tree.get_children():
            self._tree.delete(item)


# ---------------------------------------------------------------------------
# Tab: Listen
# ---------------------------------------------------------------------------

class ListenTab(ttk.Frame):
    def __init__(self, parent: ttk.Notebook, app: BlindsApp) -> None:
        super().__init__(parent, padding=8)
        self._app = app
        self._listening = False
        self._build()

    def _build(self) -> None:
        ctrl = ttk.Frame(self)
        ctrl.pack(fill=tk.X, pady=(0, 6))

        self._btn_listen = ttk.Button(
            ctrl, text="▶  Start Listening", command=self._toggle_listen)
        self._btn_listen.pack(side=tk.LEFT)

        self._btn_clear = ttk.Button(
            ctrl, text="Clear Log", command=self._clear_log)
        self._btn_clear.pack(side=tk.LEFT, padx=(8, 0))

        self._log = scrolledtext.ScrolledText(
            self, state=tk.DISABLED, wrap=tk.NONE,
            font=("Courier New", 10))
        self._log.pack(fill=tk.BOTH, expand=True)

    def _toggle_listen(self) -> None:
        if self._listening:
            self.stop_listening()
        else:
            self._start_listening()

    def _start_listening(self) -> None:
        client = self._app._client
        if client is None or not client.is_connected():
            messagebox.showwarning(
                "Not Connected", "Please connect to a device first.")
            return

        self._listening = True
        self._btn_listen.config(text="■  Stop Listening")
        self._app.set_status("Listening for BLE notifications…")

        def _notify_callback(char, data: bytearray) -> None:
            line = f"[{char.uuid}]  {data.hex()}\n"
            self._app.after(0, self._append_log, line)

        def _done(fut):
            try:
                fut.result()
            except Exception as exc:  # noqa: BLE001
                self._app.after(0, self._listen_error, exc)

        _run_async(client.start_notify(callback=_notify_callback)).add_done_callback(
            _done)

    def stop_listening(self) -> None:
        if not self._listening:
            return
        self._listening = False
        self._btn_listen.config(text="▶  Start Listening")
        client = self._app._client
        if client and client.is_connected():
            _run_async(client.stop_notify())
        self._app.set_status("Stopped listening.")

    def on_disconnected(self) -> None:
        self._listening = False
        self._btn_listen.config(text="▶  Start Listening")

    def _append_log(self, text: str) -> None:
        self._log.config(state=tk.NORMAL)
        self._log.insert(tk.END, text)
        self._log.see(tk.END)
        self._log.config(state=tk.DISABLED)

    def _clear_log(self) -> None:
        self._log.config(state=tk.NORMAL)
        self._log.delete("1.0", tk.END)
        self._log.config(state=tk.DISABLED)

    def _listen_error(self, exc: Exception) -> None:
        self._listening = False
        self._btn_listen.config(text="▶  Start Listening")
        messagebox.showerror("Listen Error", str(exc))


# ---------------------------------------------------------------------------
# Tab: Send
# ---------------------------------------------------------------------------

class SendTab(ttk.Frame):
    def __init__(self, parent: ttk.Notebook, app: BlindsApp) -> None:
        super().__init__(parent, padding=8)
        self._app = app
        self._build()

    def _build(self) -> None:
        # Characteristic selector
        row = ttk.Frame(self)
        row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row, text="Characteristic UUID:", width=22, anchor=tk.W).pack(
            side=tk.LEFT)
        self._char_var = tk.StringVar()
        self._char_combo = ttk.Combobox(
            row, textvariable=self._char_var, width=44)
        self._char_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Hex data input
        row2 = ttk.Frame(self)
        row2.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row2, text="Hex data:", width=22, anchor=tk.W).pack(
            side=tk.LEFT)
        self._hex_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self._hex_var, width=30,
                  font=("Courier New", 11)).pack(side=tk.LEFT)
        ttk.Label(row2, text="  e.g. 01ff0a", foreground="grey").pack(
            side=tk.LEFT)

        # Send button + response log
        btn_row = ttk.Frame(self)
        btn_row.pack(fill=tk.X, pady=(0, 8))
        self._btn_send = ttk.Button(
            btn_row, text="Send ▶", command=self._send)
        self._btn_send.pack(side=tk.LEFT)

        ttk.Label(self, text="Response / Log:", anchor=tk.W).pack(
            fill=tk.X, pady=(4, 0))
        self._log = scrolledtext.ScrolledText(
            self, height=12, state=tk.DISABLED, wrap=tk.NONE,
            font=("Courier New", 10))
        self._log.pack(fill=tk.BOTH, expand=True)

    def refresh(self) -> None:
        """Populate the characteristic combobox after connecting."""
        writable = [
            uuid
            for _svc, uuid, props in self._app._characteristics
            if "write" in props or "write-without-response" in props
        ]
        if not writable:
            # Fall back to all characteristics
            writable = [uuid for _svc, uuid, _props in self._app._characteristics]
        self._char_combo["values"] = writable
        if writable:
            self._char_var.set(writable[0])

    def clear(self) -> None:
        self._char_combo["values"] = []
        self._char_var.set("")

    def _send(self) -> None:
        char_uuid = self._char_var.get().strip()
        hex_data = self._hex_var.get().strip()

        if not char_uuid:
            messagebox.showwarning("Missing UUID", "Please enter or select a characteristic UUID.")
            return
        if not hex_data:
            messagebox.showwarning("Missing Data", "Please enter hex data to send.")
            return
        try:
            data = bytes.fromhex(hex_data)
        except ValueError:
            messagebox.showerror("Invalid Hex", f"'{hex_data}' is not valid hex.")
            return

        client = self._app._client
        if client is None or not client.is_connected():
            messagebox.showwarning("Not Connected",
                                   "Please connect to a device first.")
            return

        self._btn_send.config(state=tk.DISABLED)
        self._app.set_status(f"Sending {hex_data} to {char_uuid}…")

        def _done(fut):
            try:
                fut.result()
                self._app.after(0, self._log_line,
                                f"[OK]  → {char_uuid}  data={hex_data}\n")
                self._app.after(0, self._app.set_status, "Send successful.")
            except Exception as exc:  # noqa: BLE001
                self._app.after(0, self._log_line,
                                f"[ERROR]  {exc}\n")
                self._app.after(0, self._app.set_status, f"Send error: {exc}")
            self._app.after(0, lambda: self._btn_send.config(state=tk.NORMAL))

        _run_async(client.send_command(char_uuid, data)).add_done_callback(_done)

    def _log_line(self, text: str) -> None:
        self._log.config(state=tk.NORMAL)
        self._log.insert(tk.END, text)
        self._log.see(tk.END)
        self._log.config(state=tk.DISABLED)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=logging.INFO,
    )
    app = BlindsApp()
    app.mainloop()


if __name__ == "__main__":
    main()
