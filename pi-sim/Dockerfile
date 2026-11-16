# A development stand-in for the rig's Raspberry Pi: a systemd container that
# boots like the real OS, runs pi/provision.sh to set itself up, and serves SSH
# plus a ser2net UART bridge to a fake-DUT console. The code under test (the rig
# MCP server) runs on the host and reaches this exactly as it would a real Pi.
#
# GPIO is stubbed (no gpiomem in a container) and the firmware UART steps in
# provision.sh no-op here (no /boot/firmware); both are validated on hardware.
FROM debian:13-slim

ARG RIG_PUBKEY
RUN test -n "$RIG_PUBKEY" || { echo "RIG_PUBKEY build arg is required; run pi-sim/up.sh" >&2; exit 1; }

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      systemd systemd-sysv dbus \
      openssh-server sudo \
      ser2net python3 \
      iproute2 procps ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# A rig user with passwordless sudo and the dev-sim SSH key, matching how Pi
# Imager prepares the real Pi before provisioning. The gpio group exists on
# Raspberry Pi OS; create it here so provision.sh's group add succeeds.
RUN useradd --create-home --shell /bin/bash rig \
 && install -d -m 0700 -o rig -g rig /home/rig/.ssh \
 && printf '%s\n' "$RIG_PUBKEY" > /home/rig/.ssh/authorized_keys \
 && chmod 0600 /home/rig/.ssh/authorized_keys \
 && chown rig:rig /home/rig/.ssh/authorized_keys \
 && printf 'rig ALL=(ALL) NOPASSWD:ALL\n' > /etc/sudoers.d/rig \
 && chmod 0440 /etc/sudoers.d/rig \
 && ssh-keygen -A \
 && groupadd -f gpio

COPY pi-sim/pinctrl /usr/local/bin/pinctrl
COPY pi-sim/fake-dut.py /usr/local/bin/fake-dut.py
COPY pi-sim/wait-for-dut-serial.sh /usr/local/bin/wait-for-dut-serial
COPY pi/provision.sh /opt/rig/provision.sh
COPY pi-sim/fake-dut.service /etc/systemd/system/fake-dut.service
COPY pi-sim/rig-provision.service /etc/systemd/system/rig-provision.service
COPY pi-sim/ser2net-wait-dut.conf /etc/systemd/system/ser2net.service.d/wait-dut.conf
RUN chmod 0755 /usr/local/bin/pinctrl /usr/local/bin/fake-dut.py \
      /usr/local/bin/wait-for-dut-serial /opt/rig/provision.sh \
 && : >/var/log/pinctrl.log && chmod 0666 /var/log/pinctrl.log \
 && systemctl enable ssh fake-dut.service rig-provision.service \
 && systemctl mask getty@tty1.service console-getty.service \
      systemd-networkd-wait-online.service systemd-modules-load.service

EXPOSE 22 5000
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
