#!/usr/bin/env python3
"""Simple web controller for TONEX One on Raspberry Pi.

Exposes a tiny web UI with Previous / Next preset controls.
"""

from __future__ import annotations

import argparse
import glob
import html
import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tonex_one_usb import TonexOneUsb


HTML_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>TONEX One Controller</title>
  <style>
    body {{
      font-family: Arial, sans-serif;
      margin: 0;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #0f1115;
      color: #fff;
    }}
    .card {{
      width: min(92vw, 420px);
      background: #1a1f29;
      border-radius: 12px;
      padding: 24px;
      box-sizing: border-box;
      box-shadow: 0 12px 30px rgba(0, 0, 0, 0.35);
      text-align: center;
    }}
    h1 {{ margin-top: 0; font-size: 1.3rem; }}
    .preset {{ font-size: 2.2rem; margin: 12px 0 20px; }}
    select {{
      width: 100%;
      margin-bottom: 10px;
      padding: 12px;
      border-radius: 8px;
      border: 1px solid #4c566a;
      background: #12161e;
      color: #fff;
      font-size: 1rem;
    }}
    .row {{ display: flex; gap: 10px; }}
    button {{
      flex: 1;
      border: none;
      border-radius: 10px;
      color: #fff;
      padding: 16px;
      font-size: 1.1rem;
      cursor: pointer;
    }}
    .prev {{ background: #34495e; }}
    .next {{ background: #16a085; }}
    .status {{ margin-top: 14px; font-size: 0.95rem; color: #c9d0dd; min-height: 1.2em; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>TONEX One</h1>
    <select id="portSelect">{port_options}</select>
    <div class="row" style="margin-bottom: 12px;">
      <button class="prev" id="refreshPortsBtn">Refresh Ports</button>
      <button class="next" id="connectBtn">Connect</button>
    </div>
    <div class="preset">Preset: <span id="preset">{preset}</span></div>
    <div class="row">
      <button class="prev" id="prevBtn">Previous</button>
      <button class="next" id="nextBtn">Next</button>
    </div>
    <div class="status" id="status">{status}</div>
  </div>
  <script>
    async function refreshPorts() {{
      const select = document.getElementById("portSelect");
      const status = document.getElementById("status");
      try {{
        const response = await fetch("/api/ports");
        const data = await response.json();
        if (!response.ok) {{
          throw new Error(data.error || "Failed to list ports");
        }}
        const currentValue = select.value;
        select.innerHTML = "";
        if (data.ports.length === 0) {{
          const option = document.createElement("option");
          option.value = "";
          option.textContent = "No serial ports found";
          select.appendChild(option);
        }} else {{
          for (const port of data.ports) {{
            const option = document.createElement("option");
            option.value = port;
            option.textContent = port;
            select.appendChild(option);
          }}
        }}

        const selected = data.selected_port || currentValue;
        if (selected) {{
          select.value = selected;
        }}
        status.textContent = data.message || "Ports refreshed";
      }} catch (err) {{
        status.textContent = "Error: " + err.message;
      }}
    }}

    async function connectPort() {{
      const status = document.getElementById("status");
      const select = document.getElementById("portSelect");
      const selectedPort = select.value || "";
      status.textContent = "Connecting...";
      try {{
        const response = await fetch("/api/connect", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ port: selectedPort }})
        }});
        const data = await response.json();
        if (!response.ok) {{
          throw new Error(data.error || "Connect failed");
        }}
        document.getElementById("preset").textContent = data.active_preset;
        status.textContent = data.message || "Connected";
      }} catch (err) {{
        status.textContent = "Error: " + err.message;
      }}
    }}

    async function callAction(action) {{
      const status = document.getElementById("status");
      status.textContent = "Sending...";
      try {{
        const response = await fetch("/api/" + action, {{ method: "POST" }});
        const data = await response.json();
        if (!response.ok) {{
          throw new Error(data.error || "Request failed");
        }}
        document.getElementById("preset").textContent = data.active_preset;
        status.textContent = data.message || "OK";
      }} catch (err) {{
        status.textContent = "Error: " + err.message;
      }}
    }}
    document.getElementById("refreshPortsBtn").addEventListener("click", refreshPorts);
    document.getElementById("connectBtn").addEventListener("click", connectPort);
    document.getElementById("prevBtn").addEventListener("click", () => callAction("prev"));
    document.getElementById("nextBtn").addEventListener("click", () => callAction("next"));
  </script>
</body>
</html>
"""


class TonexControllerState:
    def __init__(self, port: str):
        self._lock = threading.Lock()
        self._port = port
        self._controller = TonexOneUsb(port=port) if port else None
        self._connected = False
        self._last_error = ""

    @staticmethod
    def list_ports() -> list[str]:
        ports = sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
        return ports

    def selected_port(self) -> str:
        return self._port

    def set_port(self, port: str) -> None:
        if not port:
            raise ValueError("Please select a serial port")

        if port == self._port and self._controller is not None:
            return

        if self._controller is not None:
            try:
                self._controller.close()
            except Exception:
                pass

        self._port = port
        self._controller = TonexOneUsb(port=port)
        self._connected = False
        self._last_error = ""

    def _connect_locked(self) -> None:
        if self._connected:
            return
        if self._controller is None:
            raise RuntimeError("No serial port selected")
        self._controller.open()
        self._controller.sync()
        self._connected = True
        self._last_error = ""

    def _with_reconnect(self, op):
        try:
            return op()
        except Exception as first_err:
            self._last_error = str(first_err)
            if self._controller is not None:
                try:
                    self._controller.close()
                except Exception:
                    pass
            self._connected = False
            self._connect_locked()
            return op()

    def connect(self, port: str | None = None) -> tuple[int, str]:
        with self._lock:
            if port is not None and port != "":
                self.set_port(port)
            elif not self._port:
                ports = self.list_ports()
                if not ports:
                    raise RuntimeError("No serial devices found (/dev/ttyACM* or /dev/ttyUSB*)")
                self.set_port(ports[0])

            self._connect_locked()
            state = self._with_reconnect(self._controller.request_state)
            return state.active_preset(), f"Connected to {self._port}"

    def get_status(self) -> tuple[int | None, str]:
        with self._lock:
            if not self._port:
                return None, "Select a serial port and press Connect"
            try:
                if not self._connected:
                    return None, f"Selected port: {self._port} (not connected)"
                state = self._with_reconnect(self._controller.request_state)
                return state.active_preset(), f"Connected: {self._port}"
            except Exception as err:
                self._last_error = str(err)
                return None, f"Not connected: {self._last_error}"

    def prev(self) -> tuple[int, str]:
        with self._lock:
            self._connect_locked()
            state = self._with_reconnect(self._controller.preset_down)
            return state.active_preset(), "Moved to previous preset"

    def next(self) -> tuple[int, str]:
        with self._lock:
            self._connect_locked()
            state = self._with_reconnect(self._controller.preset_up)
            return state.active_preset(), "Moved to next preset"


class Handler(BaseHTTPRequestHandler):
    controller_state: TonexControllerState

    def _json(self, status: int, payload: str) -> None:
        body = payload.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            return {}
        body = self.rfile.read(content_length)
        if not body:
            return {}
        return json.loads(body.decode("utf-8"))

    def _html(self, status: int, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/ports":
            ports = self.controller_state.list_ports()
            payload = {
                "ok": True,
                "ports": ports,
                "selected_port": self.controller_state.selected_port(),
                "message": "Ports listed",
            }
            self._json(HTTPStatus.OK, json.dumps(payload))
            return

        if self.path != "/":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        active, status = self.controller_state.get_status()
        ports = self.controller_state.list_ports()
        selected_port = self.controller_state.selected_port()
        options = []
        if not ports:
            options.append('<option value="">No serial ports found</option>')
        else:
            for port in ports:
                selected = " selected" if port == selected_port else ""
                options.append(f'<option value="{html.escape(port)}"{selected}>{html.escape(port)}</option>')

        preset_text = "?" if active is None else str(active)
        page = HTML_PAGE.format(
            preset=html.escape(preset_text),
            status=html.escape(status),
            port_options="\n".join(options),
        )
        self._html(HTTPStatus.OK, page)

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/connect":
            try:
                data = self._read_json()
                requested_port = str(data.get("port", "")).strip()
                active, message = self.controller_state.connect(requested_port or None)
                self._json(
                    HTTPStatus.OK,
                    json.dumps(
                        {
                            "ok": True,
                            "active_preset": active,
                            "message": message,
                            "selected_port": self.controller_state.selected_port(),
                        }
                    ),
                )
            except Exception as err:
                self._json(HTTPStatus.BAD_GATEWAY, json.dumps({"ok": False, "error": str(err)}))
            return

        if self.path not in ("/api/prev", "/api/next"):
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        try:
            if self.path.endswith("/prev"):
                active, message = self.controller_state.prev()
            else:
                active, message = self.controller_state.next()

            self._json(HTTPStatus.OK, json.dumps({"ok": True, "active_preset": active, "message": message}))
        except Exception as err:
            self._json(HTTPStatus.BAD_GATEWAY, json.dumps({"ok": False, "error": str(err)}))

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        # Keep service logs clean unless needed.
        return


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Web controller for TONEX One")
    parser.add_argument("--host", default="0.0.0.0", help="Listen address")
    parser.add_argument("--port", type=int, default=8080, help="Listen port")
    parser.add_argument("--tonex-port", default="/dev/ttyACM0", help="TONEX CDC serial device path")
    return parser


def main() -> int:
    args = _build_parser().parse_args()

    Handler.controller_state = TonexControllerState(port=args.tonex_port)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    print(f"TONEX web controller listening on http://{args.host}:{args.port} (TONEX {args.tonex_port})")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
