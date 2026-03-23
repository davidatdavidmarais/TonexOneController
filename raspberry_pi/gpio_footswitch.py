#!/usr/bin/env python3
"""GPIO footswitch driver for TONEX One on Raspberry Pi.

Default behavior:
- GPIO17: preset down
- GPIO27: preset up
"""

from __future__ import annotations

import argparse
import signal
import sys
import time

from gpiozero import Button

from tonex_one_usb import TonexOneUsb


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TONEX One GPIO footswitch controller")
    parser.add_argument("--port", default="/dev/ttyACM0", help="TONEX One CDC device path")
    parser.add_argument("--pin-up", type=int, default=27, help="BCM GPIO for preset up")
    parser.add_argument("--pin-down", type=int, default=17, help="BCM GPIO for preset down")
    parser.add_argument("--pull-up", action="store_true", help="Use pull-up wiring (active low)")
    parser.add_argument("--debounce-ms", type=float, default=30.0, help="Button debounce time in ms")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    stop = False

    def _handle_signal(signum, frame):
        del signum, frame
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    print(
        f"Connecting TONEX One on {args.port}. "
        f"GPIO up={args.pin_up}, down={args.pin_down}, pull_up={args.pull_up}"
    )

    with TonexOneUsb(port=args.port) as controller:
        state = controller.sync()
        print(f"Connected. Active preset: {state.active_preset()}")

        debounce_seconds = max(args.debounce_ms, 0.0) / 1000.0
        btn_up = Button(args.pin_up, pull_up=args.pull_up, bounce_time=debounce_seconds)
        btn_down = Button(args.pin_down, pull_up=args.pull_up, bounce_time=debounce_seconds)

        def on_up():
            next_state = controller.preset_up()
            print(f"Preset up -> {next_state.active_preset()}")

        def on_down():
            next_state = controller.preset_down()
            print(f"Preset down -> {next_state.active_preset()}")

        btn_up.when_pressed = on_up
        btn_down.when_pressed = on_down

        while not stop:
            time.sleep(0.1)

    print("Stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
