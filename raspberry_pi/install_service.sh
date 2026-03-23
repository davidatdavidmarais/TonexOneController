#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="tonex-foot-controller.service"
SERVICE_SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_SOURCE_FILE="${SERVICE_SOURCE_DIR}/${SERVICE_NAME}"
SERVICE_TARGET_FILE="/etc/systemd/system/${SERVICE_NAME}"

if [[ ! -f "${SERVICE_SOURCE_FILE}" ]]; then
  echo "Service file not found: ${SERVICE_SOURCE_FILE}" >&2
  exit 1
fi

echo "Installing ${SERVICE_NAME} to ${SERVICE_TARGET_FILE}"
sudo cp "${SERVICE_SOURCE_FILE}" "${SERVICE_TARGET_FILE}"

echo "Reloading systemd daemon"
sudo systemctl daemon-reload

echo "Enabling ${SERVICE_NAME}"
sudo systemctl enable "${SERVICE_NAME}"

echo "Starting ${SERVICE_NAME}"
sudo systemctl restart "${SERVICE_NAME}"

echo "Service status:"
sudo systemctl --no-pager status "${SERVICE_NAME}" || true

echo
echo "Done. Useful commands:"
echo "  sudo systemctl restart ${SERVICE_NAME}"
echo "  sudo systemctl stop ${SERVICE_NAME}"
echo "  sudo journalctl -u ${SERVICE_NAME} -f"
