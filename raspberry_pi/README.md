# Raspberry Pi support for TONEX One USB control

This folder adds a Raspberry Pi implementation for controlling the TONEX One over USB,
using the same low-level protocol/framing as the ESP32 firmware.

## What this gives you

- Direct USB control from a Raspberry Pi to TONEX One (`/dev/ttyACM*`)
- Preset operations from command line:
  - read status
  - preset up/down
  - set a specific preset index (0-19)
- Optional GPIO footswitch bridge for simple hardware buttons

## Hardware needed

- Raspberry Pi (any recent model with USB host)
- IK Multimedia TONEX One connected by USB
- Optional footswitch buttons to GPIO pins and GND

## Setup

```bash
cd raspberry_pi
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

If your user cannot access serial ports, add it to the dialout group and relog:

```bash
sudo usermod -aG dialout $USER
```

## CLI usage

Run these from the `raspberry_pi` directory.

```bash
python tonex_one_usb.py --port /dev/ttyACM0 sync
python tonex_one_usb.py --port /dev/ttyACM0 status
python tonex_one_usb.py --port /dev/ttyACM0 preset-up
python tonex_one_usb.py --port /dev/ttyACM0 preset-down
python tonex_one_usb.py --port /dev/ttyACM0 set-preset 5
python tonex_one_usb.py --port /dev/ttyACM0 set-preset 12 --slot 0
```

Slot mapping: `0=A`, `1=B`, `2=C`.

## GPIO footswitch usage

Default BCM pins:

- `GPIO27`: preset up
- `GPIO17`: preset down

Run:

```bash
python gpio_footswitch.py --port /dev/ttyACM0
```

If your switch wiring uses pull-up logic:

```bash
python gpio_footswitch.py --port /dev/ttyACM0 --pull-up
```

Use Ctrl+C to stop.

## Run on boot with systemd

Files included:

- `tonex-foot-controller.service`
- `install_service.sh`

Before installing, edit the service file to match your user, repo path, and USB device:

- `User=...`
- `WorkingDirectory=...`
- `ExecStart=...`

Then install and enable:

```bash
cd raspberry_pi
./install_service.sh
```

Useful commands:

```bash
sudo systemctl restart tonex-foot-controller.service
sudo systemctl stop tonex-foot-controller.service
sudo systemctl status tonex-foot-controller.service
sudo journalctl -u tonex-foot-controller.service -f
```

## Notes

- Preset indexes use TONEX internal zero-based values (`0..19`).
- The script forces direct monitoring on when sending state updates, matching firmware behavior.
- If your device path is not `/dev/ttyACM0`, check with `ls /dev/ttyACM*`.
