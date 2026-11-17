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
here="$(cd "$(dirname "$0")" && pwd)"

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

echo "installing ser2net, picocom, and locales"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
# picocom is the terminal for the interactive serial console (rasp monitor
# --interactive). locales-all so a locale an SSH client forwards (LC_*/LANG)
# always resolves, instead of the "invalid locale" warning and degraded UTF-8.
apt-get install -y -qq ser2net picocom locales-all

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

echo "granting $rig_user passwordless sudo"
# The agent drives the Pi as $rig_user over SSH and needs full control: install
# packages, manage services, open raw devices, lease the serial line. Pi Imager
# gives the first user sudo; this makes it passwordless so the agent never stalls
# on a prompt.
printf '%s ALL=(ALL) NOPASSWD:ALL\n' "$rig_user" >/etc/sudoers.d/"$rig_user"
chmod 0440 /etc/sudoers.d/"$rig_user"

echo "installing serial helpers"
install -m 0755 "$here/rig-serial-config" "$here/rig-serial-lease" \
  "$here/rig-serial-monitor" "$here/rig-serial-trim" "$here/rig-serial-console" \
  /usr/local/bin/
install -m 0644 "$here/systemd/rig-serial-trim.service" "$here/systemd/rig-serial-trim.timer" \
  /etc/systemd/system/
install -d -m 0755 /var/log/rig
cat >/etc/rig-serial.env <<EOF
RIG_UART_DEVICE=$uart_device
RIG_UART_PORT=$uart_port
RIG_UART_BAUD=$uart_baud
RIG_UART_TRACE=/var/log/rig/uart.log
RIG_UART_TRACE_MAX_BYTES=2097152
EOF

# The trace files are a rolling buffer on the Pi; the durable transcript is saved
# host-side by the monitor. This timer trims the buffer so it stays small.
echo "enabling the UART trace trim timer"
systemctl enable rig-serial-trim.timer

echo "granting $rig_user gpio and serial access"
usermod -aG gpio,dialout "$rig_user"

# rig-serial-config writes /etc/ser2net.yaml from the line settings and restarts
# the bridge; enable it so it also comes up on boot.
echo "writing /etc/ser2net.yaml and starting ser2net"
systemctl enable ser2net
rig-serial-config "${uart_baud}n81"

echo "provisioned. reboot to apply the UART firmware changes: sudo reboot"
