#!/usr/bin/env bash
# Optional: turn the Pi into a Wi-Fi access point so phones can connect and open the web UI.
# WARNING: Enabling AP mode may disconnect your existing Wi-Fi client/SSH session.
# Prefer a wired Ethernet or console keyboard when trying this the first time.

set -euo pipefail

SSID="${1:-TonexPi}"
PASSWORD="${2:-tonex1234}"

if [[ ${#PASSWORD} -lt 8 ]]; then
  echo "Password must be at least 8 characters (WPA requirement)." >&2
  exit 1
fi

# Find a wireless interface (usually wlan0 on Raspberry Pi)
WLAN=""
if command -v iw &>/dev/null; then
  WLAN="$(iw dev 2>/dev/null | awk '/Interface/ {print $2; exit}')"
fi
if [[ -z "${WLAN}" ]]; then
  for cand in wlan0 wlp1s0; do
    if [[ -d "/sys/class/net/${cand}" ]]; then
      WLAN="${cand}"
      break
    fi
  done
fi
if [[ -z "${WLAN}" ]]; then
  echo "No wireless interface found. Is Wi-Fi enabled?" >&2
  exit 1
fi

if ! command -v nmcli &>/dev/null; then
  echo "nmcli (NetworkManager) not found." >&2
  echo "On Raspberry Pi OS Bookworm, enable NetworkManager:" >&2
  echo "  sudo raspi-config -> Advanced Options -> Network Config -> NetworkManager" >&2
  echo "Then reboot and run this script again." >&2
  echo "" >&2
  echo "Alternative: follow the official hostapd guide:" >&2
  echo "  https://www.raspberrypi.com/documentation/computers/configuration.html#host-access-point-setup" >&2
  exit 1
fi

if ! systemctl is-active --quiet NetworkManager 2>/dev/null; then
  echo "NetworkManager does not appear to be running." >&2
  echo "Start it with: sudo systemctl enable --now NetworkManager" >&2
  exit 1
fi

echo "Wireless interface: ${WLAN}"
echo "Creating hotspot SSID=${SSID} (WPA2-PSK)"
echo ""

# Remove stale hotspot with same connection name if present
nmcli -t -f NAME connection show 2>/dev/null | grep -qx 'tonex-hotspot' && \
  sudo nmcli connection delete tonex-hotspot 2>/dev/null || true

sudo nmcli device wifi hotspot ifname "${WLAN}" con-name tonex-hotspot ssid "${SSID}" password "${PASSWORD}"

echo ""
echo "Done. On your phone, join Wi-Fi:"
echo "  SSID:     ${SSID}"
echo "  Password: ${PASSWORD}"
echo ""
echo "Open the TONEX web UI (NetworkManager hotspot gateway is usually 10.42.0.1):"
echo "  http://10.42.0.1:8080"
echo ""
echo "To stop the hotspot later:"
echo "  sudo nmcli connection down tonex-hotspot"
echo "To start it again:"
echo "  sudo nmcli connection up tonex-hotspot"
