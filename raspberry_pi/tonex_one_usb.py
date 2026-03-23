#!/usr/bin/env python3
"""Raspberry Pi TONEX One USB controller.

This module talks directly to the TONEX One CDC endpoint (ToneX Control VCOM)
using the same framing and message style used in the ESP32 firmware.
"""

from __future__ import annotations

import argparse
import struct
import sys
import time
from dataclasses import dataclass
from typing import Optional

import serial


HELLO_REQUEST = bytes(
    [0xB9, 0x03, 0x00, 0x82, 0x04, 0x00, 0x80, 0x0B, 0x01, 0xB9, 0x02, 0x02, 0x0B]
)
STATE_REQUEST = bytes(
    [0xB9, 0x03, 0x00, 0x82, 0x06, 0x00, 0x80, 0x0B, 0x03, 0xB9, 0x02, 0x81, 0x06, 0x03, 0x0B]
)

SET_STATE_HEADER = bytes([0xB9, 0x03, 0x81, 0x06, 0x03, 0x82])

TONEX_STATE_OFFSET_START_STOMP_MODE = 19
TONEX_STATE_OFFSET_END_BYPASS_MODE = 12
TONEX_STATE_OFFSET_END_CURRENT_SLOT = 11
TONEX_STATE_OFFSET_END_SLOT_C_PRESET = 14
TONEX_STATE_OFFSET_END_SLOT_B_PRESET = 16
TONEX_STATE_OFFSET_END_SLOT_A_PRESET = 18


class TonexProtocolError(RuntimeError):
    """Raised for malformed TONEX frames/messages."""


@dataclass
class TonexState:
    state_data: bytes
    slot_a_preset: int
    slot_b_preset: int
    slot_c_preset: int
    current_slot: int

    def active_preset(self) -> int:
        if self.current_slot == 0:
            return self.slot_a_preset
        if self.current_slot == 1:
            return self.slot_b_preset
        return self.slot_c_preset


def calculate_crc(data: bytes) -> int:
    """CRC-16/X25 to match firmware implementation."""
    crc = 0xFFFF
    for value in data:
        crc ^= value
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0x8408
            else:
                crc >>= 1
    return (~crc) & 0xFFFF


def add_framing(payload: bytes) -> bytes:
    out = bytearray()
    out.append(0x7E)
    for b in payload:
        if b in (0x7E, 0x7D):
            out.append(0x7D)
            out.append(b ^ 0x20)
        else:
            out.append(b)

    crc = calculate_crc(payload)
    for b in (crc & 0xFF, (crc >> 8) & 0xFF):
        if b in (0x7E, 0x7D):
            out.append(0x7D)
            out.append(b ^ 0x20)
        else:
            out.append(b)

    out.append(0x7E)
    return bytes(out)


def remove_framing(frame: bytes) -> bytes:
    if len(frame) < 4 or frame[0] != 0x7E or frame[-1] != 0x7E:
        raise TonexProtocolError("Invalid frame markers")

    out = bytearray()
    i = 1
    while i < len(frame) - 1:
        value = frame[i]
        if value == 0x7D:
            if i + 1 >= len(frame) - 1:
                raise TonexProtocolError("Invalid escaped sequence")
            out.append(frame[i + 1] ^ 0x20)
            i += 2
            continue
        if value == 0x7E:
            break
        out.append(value)
        i += 1

    if len(out) < 2:
        raise TonexProtocolError("Frame too short")

    received_crc = (out[-1] << 8) | out[-2]
    payload = bytes(out[:-2])
    if calculate_crc(payload) != received_crc:
        raise TonexProtocolError("CRC mismatch")
    return payload


def parse_value(message: bytes, index: int) -> tuple[int, int]:
    if message[index] in (0x81, 0x82):
        value = (message[index + 2] << 8) | message[index + 1]
        return value, index + 3
    if message[index] == 0x80:
        return message[index + 1], index + 2
    return message[index], index + 1


def parse_message_type(payload: bytes) -> tuple[int, int, int]:
    if len(payload) < 5 or payload[0] != 0xB9 or payload[1] != 0x03:
        raise TonexProtocolError("Invalid TONEX payload header")

    index = 2
    msg_type, index = parse_value(payload, index)
    size, index = parse_value(payload, index)
    _unknown, index = parse_value(payload, index)
    if len(payload) - index != size:
        raise TonexProtocolError("Invalid TONEX payload length")
    return msg_type, index, size


def parse_state_from_payload(payload: bytes) -> TonexState:
    msg_type, index, _size = parse_message_type(payload)
    if msg_type != 0x0306:
        raise TonexProtocolError(f"Expected state update (0x0306), got 0x{msg_type:04X}")

    state_data = bytearray(payload[index:])
    if len(state_data) < max(
        TONEX_STATE_OFFSET_END_SLOT_A_PRESET,
        TONEX_STATE_OFFSET_END_SLOT_B_PRESET,
        TONEX_STATE_OFFSET_END_SLOT_C_PRESET,
        TONEX_STATE_OFFSET_END_CURRENT_SLOT,
    ):
        raise TonexProtocolError("State data too short")

    slot_a = state_data[-TONEX_STATE_OFFSET_END_SLOT_A_PRESET]
    slot_b = state_data[-TONEX_STATE_OFFSET_END_SLOT_B_PRESET]
    slot_c = state_data[-TONEX_STATE_OFFSET_END_SLOT_C_PRESET]
    current_slot = state_data[-TONEX_STATE_OFFSET_END_CURRENT_SLOT]
    return TonexState(bytes(state_data), slot_a, slot_b, slot_c, current_slot)


class TonexOneUsb:
    def __init__(self, port: str, timeout: float = 0.2, settle_delay_s: float = 0.25):
        self.port = port
        self.timeout = timeout
        self.settle_delay_s = settle_delay_s
        self._ser: Optional[serial.Serial] = None
        self._latest_state: Optional[TonexState] = None

    def open(self) -> None:
        self._ser = serial.Serial(
            self.port,
            baudrate=115200,
            timeout=self.timeout,
            write_timeout=self.timeout,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
        )
        time.sleep(self.settle_delay_s)

    def close(self) -> None:
        if self._ser and self._ser.is_open:
            self._ser.close()
        self._ser = None

    def __enter__(self) -> "TonexOneUsb":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _write_payload(self, payload: bytes) -> None:
        if not self._ser:
            raise RuntimeError("Device not open")
        frame = add_framing(payload)
        self._ser.write(frame)
        self._ser.flush()

    def _read_frame(self, timeout_s: float = 2.0) -> bytes:
        if not self._ser:
            raise RuntimeError("Device not open")

        deadline = time.monotonic() + timeout_s
        frame = bytearray()
        in_frame = False

        while time.monotonic() < deadline:
            chunk = self._ser.read(256)
            if not chunk:
                continue

            for value in chunk:
                if not in_frame:
                    if value == 0x7E:
                        frame = bytearray([0x7E])
                        in_frame = True
                    continue

                frame.append(value)
                if value == 0x7E and len(frame) > 1:
                    return bytes(frame)

        raise TimeoutError("Timed out waiting for TONEX response")

    def sync(self) -> TonexState:
        self._write_payload(HELLO_REQUEST)

        # Wait until we see HELLO (type 0x0002), then request state.
        hello_deadline = time.monotonic() + 3.0
        while time.monotonic() < hello_deadline:
            payload = remove_framing(self._read_frame(timeout_s=0.8))
            msg_type, _, _ = parse_message_type(payload)
            if msg_type == 0x0002:
                break
        else:
            raise TimeoutError("Did not receive TONEX hello response")

        return self.request_state()

    def request_state(self) -> TonexState:
        self._write_payload(STATE_REQUEST)

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            payload = remove_framing(self._read_frame(timeout_s=0.8))
            msg_type, _, _ = parse_message_type(payload)
            if msg_type == 0x0306:
                state = parse_state_from_payload(payload)
                self._latest_state = state
                return state
        raise TimeoutError("Did not receive TONEX state response")

    def set_preset(self, preset: int, slot: Optional[int] = None, toggle_bypass: bool = False) -> TonexState:
        if preset < 0 or preset > 19:
            raise ValueError("Preset must be in range 0..19")

        state = self._latest_state or self.request_state()
        state_data = bytearray(state.state_data)

        if slot is None:
            slot = state.current_slot
        if slot not in (0, 1, 2):
            raise ValueError("Slot must be 0 (A), 1 (B), or 2 (C)")

        # A/B mode for slot A/B, Stomp mode for slot C.
        state_data[TONEX_STATE_OFFSET_START_STOMP_MODE] = 1 if slot == 2 else 0

        # Ensure direct monitoring remains enabled.
        state_data[-7] = 1

        if toggle_bypass and slot == state.current_slot and preset == state.active_preset():
            state_data[-TONEX_STATE_OFFSET_END_BYPASS_MODE] = 0 if state_data[-TONEX_STATE_OFFSET_END_BYPASS_MODE] else 1
        else:
            state_data[-TONEX_STATE_OFFSET_END_BYPASS_MODE] = 0

        if slot == 0:
            state_data[-TONEX_STATE_OFFSET_END_SLOT_A_PRESET] = preset
        elif slot == 1:
            state_data[-TONEX_STATE_OFFSET_END_SLOT_B_PRESET] = preset
        else:
            state_data[-TONEX_STATE_OFFSET_END_SLOT_C_PRESET] = preset

        # Select the slot as active.
        state_data[-TONEX_STATE_OFFSET_END_CURRENT_SLOT] = slot

        payload = bytearray(SET_STATE_HEADER)
        payload.extend(struct.pack("<H", len(state_data)))
        payload.extend([0x80, 0x0B, 0x03])
        payload.extend(state_data)
        self._write_payload(bytes(payload))

        # Refresh local copy.
        return self.request_state()

    def preset_up(self) -> TonexState:
        state = self._latest_state or self.request_state()
        return self.set_preset((state.active_preset() + 1) % 20)

    def preset_down(self) -> TonexState:
        state = self._latest_state or self.request_state()
        return self.set_preset((state.active_preset() - 1) % 20)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TONEX One USB control for Raspberry Pi")
    parser.add_argument("--port", default="/dev/ttyACM0", help="TONEX One CDC device path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("sync", help="Perform hello + state sync")
    subparsers.add_parser("status", help="Read current state")
    subparsers.add_parser("preset-up", help="Increment active preset")
    subparsers.add_parser("preset-down", help="Decrement active preset")

    set_parser = subparsers.add_parser("set-preset", help="Set preset (0-19)")
    set_parser.add_argument("preset", type=int)
    set_parser.add_argument("--slot", type=int, choices=[0, 1, 2], help="Target slot: 0=A 1=B 2=C")
    set_parser.add_argument("--toggle-bypass", action="store_true", help="Toggle bypass if same preset is selected")
    return parser


def _print_state(state: TonexState) -> None:
    slot_name = {0: "A", 1: "B", 2: "C"}.get(state.current_slot, "?")
    print(
        f"Current slot: {slot_name} ({state.current_slot}) | "
        f"Preset A:{state.slot_a_preset} B:{state.slot_b_preset} C:{state.slot_c_preset} | "
        f"Active:{state.active_preset()}"
    )


def main() -> int:
    args = _build_parser().parse_args()

    try:
        with TonexOneUsb(port=args.port) as controller:
            if args.command == "sync":
                state = controller.sync()
            elif args.command == "status":
                state = controller.request_state()
            elif args.command == "preset-up":
                state = controller.preset_up()
            elif args.command == "preset-down":
                state = controller.preset_down()
            else:
                state = controller.set_preset(
                    preset=args.preset,
                    slot=args.slot,
                    toggle_bypass=args.toggle_bypass,
                )

            _print_state(state)
            return 0
    except (serial.SerialException, TimeoutError, TonexProtocolError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
