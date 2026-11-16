# pi-sim

A development stand-in for the rig's Raspberry Pi, so the `SshTransport`, the
provisioning, and the live MCP server can be built without hardware.

It is a **systemd container** (Debian, the base of Raspberry Pi OS) that boots
like the real OS, runs `pi/provision.sh` to set itself up, and serves SSH plus a
ser2net UART bridge. The rig reaches it exactly as it would a real Pi: SSH for
`exec` and GPIO (`pinctrl`), and a ser2net TCP port for UART. The code under test
(the rig MCP server) runs on the host, so the container only has to be a faithful
SSH + ser2net + serial target, which it is in seconds.

Running `provision.sh` inside the container makes it the single source of truth
for how the Pi is set up, sim and hardware alike. The container passes
`RIG_UART_DEVICE=/run/dut-serial` so the ser2net connector points at the fake-DUT
pty instead of `/dev/serial0`; everything else in the script runs unchanged.

## What works vs not

- `exec` over real SSH: yes.
- UART over ser2net TCP: yes, on `tcp localhost:5000`. ser2net bridges the port
  to a serial line; `fake-dut.py` stands in for the device, owning a pty and
  publishing its slave at `/run/dut-serial`. It answers a small command set
  (`id`, `help`, `ping`) so `uart_send` / `uart_expect` run end to end.
- GPIO: stubbed. A container has no `/dev/gpiomem`, so `pinctrl` is a stub that
  logs each op to `/var/log/pinctrl.log`; the rig's power/tristate calls are
  observable but move no real pins.
- Firmware UART steps (`config.txt`, `cmdline.txt`): `provision.sh` runs them but
  they no-op here (no `/boot/firmware`); they take effect on real hardware only.

## Run

Needs Docker with the Compose plugin. From the repo root:

```
./pi-sim/up.sh -d          # build and start detached (foreground without -d)
ssh -p 2222 -i data/pi-sim/id_ed25519 rig@localhost
printf 'id\n' | nc -q1 localhost 5000   # poke the fake DUT over the UART bridge
docker compose down        # stop and remove
```

`up.sh` generates the dedicated SSH key under `data/pi-sim/` on first run and
injects its public half into the image. The container is privileged (systemd as
PID 1); that applies to this dev sim only, never the agent container.

The service is `pi-sim` in the repo's `compose.yaml`, on the default compose
network, so the agent container reaches it by the name `pi-sim` while the host
sees the published ports 2222 and 5000.
