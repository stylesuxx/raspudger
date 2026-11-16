#!/usr/bin/env bash
# Provision a freshly flashed Raspberry Pi as a rig DUT bridge.
#
# Pi Imager already sets the login user and its SSH key, so this script owns the
# rest: free the PL011 UART from Bluetooth and the serial console so it drives
# the device under test, install ser2net to bridge that UART to TCP 5000, and
# give the rig user GPIO and serial access for pinctrl and the relay.
#
# The config.txt / cmdline.txt changes are firmware-level and take effect on the
# next boot, so they apply only on real hardware. Run as root on the Pi:
# `sudo ./provision.sh`. Re-running is safe.
set -euo pipefail

rig_user="${RIG_USER:-rig}"
uart_port="${RIG_UART_PORT:-5000}"
uart_device="${RIG_UART_DEVICE:-/dev/serial0}"
uart_baud="${RIG_UART_BAUD:-115200}"

if [ "$(id -u)" -ne 0 ]; then
  echo "provision.sh must run as root (use sudo)" >&2
  exit 1
fi

if [ -d /boot/firmware ]; then
  boot_dir=/boot/firmware
else
  boot_dir=/boot
fi
config_txt="$boot_dir/config.txt"
cmdline_txt="$boot_dir/cmdline.txt"

ensure_config_line() {
  local line="$1"
  if ! grep -qxF "$line" "$config_txt"; then
    printf '%s\n' "$line" >>"$config_txt"
  fi
}

echo "installing ser2net"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ser2net

echo "freeing the UART in $config_txt"
touch "$config_txt"
ensure_config_line "enable_uart=1"
ensure_config_line "dtoverlay=disable-bt"
systemctl disable --now hciuart.service 2>/dev/null || true

echo "disabling the serial login console"
if [ -f "$cmdline_txt" ]; then
  sed -i -E 's/console=(serial0|ttyAMA0|ttyS0),[0-9]+ ?//g' "$cmdline_txt"
fi
systemctl disable --now serial-getty@ttyAMA0.service 2>/dev/null || true
systemctl disable --now serial-getty@serial0.service 2>/dev/null || true

echo "writing /etc/ser2net.yaml"
cat >/etc/ser2net.yaml <<EOF
%YAML 1.1
---
connection: &dut
    accepter: tcp,$uart_port
    enable: on
    options:
      kickolduser: true
    connector: serialdev,$uart_device,${uart_baud}n81,local
EOF

echo "granting $rig_user gpio and serial access"
usermod -aG gpio,dialout "$rig_user"

# restart, not just start: the package may already be running with its default
# config, so the freshly written one loads only on a restart.
systemctl enable ser2net
systemctl restart ser2net

echo "provisioned. reboot to apply the UART firmware changes: sudo reboot"
