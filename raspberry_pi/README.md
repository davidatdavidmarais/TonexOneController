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

## Wi-Fi access point (hotspot) for phone-only use

The web controller already listens on all interfaces (`0.0.0.0`). You can make the Pi broadcast its own Wi-Fi network so a phone joins it and opens the page without your home router.

**Warning:** Turning the Pi into an access point can drop your existing Wi-Fi client connection (and SSH over Wi-Fi). Use Ethernet, a monitor/keyboard, or try this when you can recover access if something goes wrong.

### Easiest path: NetworkManager hotspot (Raspberry Pi OS Bookworm)

1. Ensure NetworkManager is active (not “legacy” dhcpcd-only networking). If needed: `sudo raspi-config` → Advanced Options → Network Config → **NetworkManager**, then reboot.

2. Run the helper script (optional custom SSID and password, min 8 chars for WPA):

```bash
cd raspberry_pi
chmod +x setup_wifi_ap.sh
./setup_wifi_ap.sh
# or: ./setup_wifi_ap.sh MyTonexPi mysecret12
```

3. On your phone, join that Wi-Fi, then open:

```text
http://10.42.0.1:8080
```

(NetworkManager’s hotspot gateway is usually `10.42.0.1`. If that fails, check the Pi with `ip -4 addr show` while the hotspot is up.)

### Stop / start the hotspot

```bash
sudo nmcli connection down tonex-hotspot
sudo nmcli connection up tonex-hotspot
```

### Alternative: hostapd (advanced)

If you do not use NetworkManager, use the Raspberry Pi documentation for a full access-point setup (static IP, DHCP, routing): [Set up a routed wireless access point](https://www.raspberrypi.com/documentation/computers/configuration.html#host-access-point-setup). After that, use the Pi’s AP IP address with port `8080` (often `192.168.4.1` in those guides).

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

This service now runs the web controller (`web_controller.py`) and exposes a small web page with **Previous** and **Next** buttons.

Before installing, edit the service file to match your user, repo path, and USB device:

- `User=...`
- `WorkingDirectory=...`
- `ExecStart=...`

Then install and enable:

```bash
cd raspberry_pi
./install_service.sh
```

Open from your phone/laptop browser:

```text
http://<your-raspberry-pi-ip>:8080
```

Find your Pi IP with:

```bash
hostname -I
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
