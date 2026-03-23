#!/usr/bin/env python3
"""Simple web controller for TONEX One on Raspberry Pi.

Exposes a tiny web UI with Previous / Next preset controls.
"""

from __future__ import annotations

import argparse
import html
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import ThreadingMixIn

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
    <div class="preset">Preset: <span id="preset">{preset}</span></div>
    <div class="row">
      <button class="prev" id="prevBtn">Previous</button>
      <button class="next" id="nextBtn">Next</button>
    </div>
    <div class="status" id="status">{status}</div>
  </div>
  <script>
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
        self._controller = TonexOneUsb(port=port)
        self._connected = False
        self._last_error = ""

    def _connect_locked(self) -> None:
        if self._connected:
            return
        self._controller.open()
        self._controller.sync()
        self._connected = True
        self._last_error = ""

    def _with_reconnect(self, op):
        try:
            return op()
        except Exception as first_err:
            self._last_error = str(first_err)
            try:
                self._controller.close()
            except Exception:
                pass
            self._connected = False
            self._connect_locked()
            return op()

    def get_status(self) -> tuple[int | None, str]:
        with self._lock:
            try:
                self._connect_locked()
                state = self._with_reconnect(self._controller.request_state)
                return state.active_preset(), "Connected"
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

    def _html(self, status: int, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        active, status = self.controller_state.get_status()
        preset_text = "?" if active is None else str(active)
        page = HTML_PAGE.format(preset=html.escape(preset_text), status=html.escape(status))
        self._html(HTTPStatus.OK, page)

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in ("/api/prev", "/api/next"):
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        try:
            if self.path.endswith("/prev"):
                active, message = self.controller_state.prev()
            else:
                active, message = self.controller_state.next()

            self._json(
                HTTPStatus.OK,
                '{{"ok":true,"active_preset":%d,"message":"%s"}}'
                % (active, message.replace('"', "'")),
            )
        except Exception as err:
            self._json(
                HTTPStatus.BAD_GATEWAY,
                '{{"ok":false,"error":"%s"}}' % str(err).replace('"', "'"),
            )

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        # Keep service logs clean unless needed.
        return


class ThreadingServer(ThreadingMixIn, ThreadingHTTPServer):
    daemon_threads = True


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Web controller for TONEX One")
    parser.add_argument("--host", default="0.0.0.0", help="Listen address")
    parser.add_argument("--port", type=int, default=8080, help="Listen port")
    parser.add_argument("--tonex-port", default="/dev/ttyACM0", help="TONEX CDC serial device path")
    return parser


def main() -> int:
    args = _build_parser().parse_args()

    Handler.controller_state = TonexControllerState(port=args.tonex_port)
    server = ThreadingServer((args.host, args.port), Handler)
    print(f"TONEX web controller listening on http://{args.host}:{args.port} (TONEX {args.tonex_port})")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
