# Raspudger

An AI agent that probes embedded devices to find vulnerabilities over a hardware
interface. A Raspberry Pi acts as the physical bridge to a device under test
(DUT); an agent on a separate host drives the Pi to interrogate the device,
looking for previously unknown vulnerabilities.

> Status: early development. The host wrapper, the rig MCP server, the SSH/UART
> transport, provisioning, and a container sim all work end to end, and the spine
> runs on a real Raspberry Pi 3 driving the ESP32-C3 test DUT over UART.

## What it is

A reproducible bench for authorized security testing of embedded hardware. Attach
a DUT to the Pi over UART, point the
agent at the Pi, and give it an objective such as "find vulnerabilities in this
device." The agent interacts with the device, captures evidence, and analyzes it
on the host.

Design principles:

- Agent-agnostic. The agent is a vendor CLI (Claude Code is the reference target)
  in a container. Swapping agents is an adapter plus config, because the rig
  exposes its tools through a standard MCP interface.
- The Pi is a disposable sensor. It owns physical I/O and holds no durable state;
  heavy analysis and findings live on the host. A Pi can be wiped and re-flashed
  without losing anything.
- Credentials are scoped and contained. The agent uses your Claude subscription
  login in the gitignored agent home; the Pi SSH key is mounted in and used only
  by the rig MCP server.
- The agent has a general shell on the Pi plus guarded tools for dangerous or
  structured actions.

## How it works

```
DUT ── UART/power ── Raspberry Pi ──SSH + TCP── Host (Docker)
       (3.3V)        disposable                 agent container
                     sensor                     ├─ agent CLI {Claude | ...}
                                                 └─ rig-mcp-server (holds Pi key)
```

The agent runs in a container. Inside it, `rig-mcp-server` is the MCP server that
reaches the Pi: SSH for `exec` and GPIO (`pinctrl`), a TCP socket to ser2net for
the UART. The `rasp` wrapper assembles the container, mounts the Pi key,
registers the server, and starts an interactive or unattended (`--task`) session.
Findings land in the project folder, keyed per device.

The hardware tools: `pi_exec`, `uart_send`, `uart_expect`, `uart_exchange`,
`dut_power`, `dut_power_cycle`, `state_get`, `state_record_finding`.

## Design

### Three layers, the Pi stays dumb

The rig is three layers: the DUT, the "disposable" Pi, and the clean host.

The Pi owns physical I/O (the UART and the power relay) and runs only `sshd`,
ser2net, and provisioning scripts, holding no durable state. All heavy lifting
(firmware extraction, analysis, per-device state) is host-side.

Keeping the Pi dumb is what makes it replaceable: wipe and re-flash it without
losing anything. The trust boundary around it is covered in Security model below.

This is also what makes it relatively agnostic to which Pi you are using. Pi
Zero 2W for example is enough if you just want serial access to the DUT. Go with
a Pi 3 instead if you want to be able to easily plug in additional hardware like
JTAG, SPI or even an Android Phone or better WiFi.

### Tool surface: guarded core plus open shell

The agent has a general execution channel (`pi_exec`) and composes what it
needs, so no action is ever blocked. A small set of typed, guarded tools covers
the few actions that are dangerous or benefit from structure. Raw shell is the
floor and is always available.

An action earns a typed tool when any of these holds:

- it is physical or irreversible (power, reset, reflash)
- it needs an interlock the agent could get wrong (the power-cycle UART tristate)
- it must be atomic and distinctly logged for the audit trail
- it is run often enough that reliability beats flexibility
- a structured return materially helps the agent reason (a UART read as matched
  prompt, bytes, and timeout flag rather than scraped terminal text)

Everything else stays raw shell. The guarded tools do not run on the Pi; they run
host-side in the rig MCP server, which holds the Pi SSH key and executes over the
segmented network.

> The agent calls the tools and never holds the key or reaches the Pi directly.

### The power-cycle interlock

Power-cycling the DUT is a sequence with a safety interlock, which is why it is a
guarded tool rather than a raw GPIO toggle. `dut_power_cycle` runs it so the agent
cannot skip a step and chase a half-booted DUT:

1. tristate the UART TX so the Pi does not back-power the DUT through its I/O
   protection diodes
2. cut power
3. wait the configured off interval
4. restore power
5. re-open the UART

The same back-power interlock applies whenever DUT power is cut.

### Agent-agnostic front-ends on one tool substrate

The container runs the agent's own CLI as a full session, not a custom loop. A
per-agent adapter knows how to launch that CLI and register the rig MCP server
with it, so swapping the adapter changes the brain and nothing else.

Two front-end kinds sit on the same MCP tool substrate: an agent CLI, bringing
its own tool loop, permissions, and resumable sessions, or a thin
provider-neutral API loop for a model whose CLI cannot mount MCP.

The rig integration is written once, against MCP.

Supported agents:

* Claude

### Control-channel protection

The agent has a sudo shell on the Pi and could sever its own control link (on a
Zero 2 W the control channel is the onboard WiFi). A priming rule covers every
board: do not touch the interface the SSH control connection arrives on
(derivable from `SSH_CONNECTION` / `ip route get`), its managing service, `sshd`,
or firewall rules, and stop and ask if a task seems to need it. The rule is
advisory, so manual repower is the backstop until automated recovery exists.

### UART electrical limits

The core interface is the Pi's built-in UART on GPIO14 (TX) / GPIO15 (RX), 3.3 V
logic. It has no galvanic isolation: the DUT wires straight into the Pi's SoC
pins, which is acceptable for known-good DUTs. For unknown or possibly hostile
devices, a digital UART isolator (ADuM-based) protects the host behind the
disposable Pi. One hardware UART means one DUT at a time.

### Network topology

A DUT often exposes several interfaces at once, and the rig drives them together.
A router, for example, is wired to the bench over UART while also serving a web
interface on its network. The channels work hand in hand: pull a credential or an
exploit over UART, then exercise it against the DUT's web interface over the
network, or confirm over UART what a network request did. The segmented test
network is an additional channel alongside the wired ones, not a separate kind of
DUT.

To give the rig that network channel, a dedicated test router is the isolated
backbone, off the main LAN. The Pi sits on the router's LAN over ethernet, and the
host reaches it through a WAN-to-Pi port-forward of SSH (22) and ser2net (5000).
The DUT joins the router's WiFi, or wires into its LAN, so the Pi and the DUT
share one subnet: the Pi reaches the DUT's network services, while the host still
reaches only the Pi through the forward. Everything stays off the main LAN, which
is the isolation the security model wants.

The rig must stay single-homed on the test network. A second link, for example
the Pi still joined to the main WiFi, breaks the forward through asymmetric
routing: the router translates an inbound connection to the Pi, but the Pi, with
a direct route to the main LAN over its other interface, answers the client there
instead of back through the router, so the handshake never completes while
same-subnet access keeps working and masks the fault. Leave the Pi's only default
route via the test router.

The test network is configured in `rig.env` with `RIG_DUT_NET_SSID` and
`RIG_DUT_NET_PSK` (optionally `RIG_DUT_NET_SUBNET` and `RIG_DUT_NET_IFACE`). The
agent reads them from the `dut_network_info` tool to onboard a DUT, which then
lands on the Pi's subnet; the onboarding step itself is DUT-specific. The PSK is a
low-value credential for a disposable test network. The host container cannot
reach the DUT subnet, so network scans run on the Pi (`nmap` installed over SSH),
with analysis kept host-side, and a tunnel through the Pi reaches a DUT web
interface.

Router setup for the network shape: run the test router in router/NAT mode with
its WAN on the main network and the Pi on its LAN side, not bridged as a plain
access point (bridging puts the DUT on the main LAN and loses the isolation).
Port-forward WAN to the Pi's LAN IP for SSH (22) and ser2net (5000), and give the
Pi a DHCP reservation so the forward target does not drift. `RIG_PI_HOST` is then
the router's WAN IP, or the Pi's LAN IP when the host is behind the same router.

### Scope of the core

The core is UART plus a power relay. Planned but outside the core: SPI flash tap,
JTAG/SWD, logic analyzer, boot-strap pins, current sense, WiFi testing, and
multiple DUTs at once.

## Prerequisites

On the host:

- Docker with the Compose plugin (the agent and the sim run in containers).
- Python 3.11 or newer (the wrapper is a small Python program).
- git and bash; Linux or macOS.
- A Claude subscription for the browser login, or an API key (see
  Authentication). Signing in needs a browser on some machine, not the host.

## Shopping list

For the sim (Target A) you need none of this; it runs in containers. The hardware
below is for a real rig (Target B).

The rig:

- A 40-pin arm64 Raspberry Pi: Pi 3, 4, 5, or Zero 2 W. A Pi 3 or newer is the
  tested target.
- A microSD card (8 GB or more) and a power supply for that Pi model.
- A relay or load switch to cut and restore DUT power from a GPIO. An
  opto-isolated relay module that triggers from 3.3 V logic works; the default
  `RIG_POWER_ACTIVE_HIGH=false` suits an active-low module. For a low-voltage DC
  DUT, a high-side MOSFET load switch is faster and quieter than a mechanical
  relay.
- Female-to-female jumper wires for the UART lines (TX, RX, GND) and the relay
  trigger.
- A bidirectional logic level shifter only if the DUT's UART is 5 V. The Pi's
  GPIO is 3.3 V and not 5 V tolerant. The ESP32 test DUT below is 3.3 V and needs
  none.

Network isolation:

- A cheap unmanaged switch or a spare router to keep the Pi and DUT off your main
  LAN, plus an Ethernet cable. The Pi's WiFi also works for the control channel.

The test DUT (optional, see Test DUT below):

- An ESP32-C3 board (Waveshare ESP32-C3-Zero or similar) and a USB-C cable.
- One male-to-male jumper for the pin loopback self-test, plus three
  female-to-female jumpers to the Pi.

## Quickstart

### Shared setup (sim or hardware)

1. Build the agent image:
   ```
   make build-image
   ```
2. Authenticate the agent once (browser login, persisted in `data/agent-home/`):
   ```
   ./rasp --agent claude --login
   ```

Then bring up the rig and write its `rig.env`. That is the only part that differs
between the sim and real hardware; pick one of the two below, then run the
session.

### Target A: simulated rig (no hardware)

`pi-sim/` is a systemd container that stands in for the Pi.

1. Build and start the sim (generates its dedicated SSH key on first run):
   ```
   ./pi-sim/up.sh -d
   ```
2. Write `rig.env` (`cp rig.env.example rig.env`, then set these):
   ```
   RIG_PI_HOST=pi-sim
   RIG_PI_USER=rig
   RIG_PI_SSH_KEY=data/pi-sim/id_ed25519
   RIG_PI_SSH_PORT=22
   RIG_UART_PORT=5000
   RIG_PIN_POWER=17
   RIG_PIN_UART_TX=14
   RIG_POWER_ACTIVE_HIGH=false
   ```

Optional direct checks: `ssh -p 2222 -i data/pi-sim/id_ed25519 rig@localhost`, and
`printf 'id\n' | nc -q1 localhost 5000` (the fake DUT replies `pi-sim-dut v0.1`).

### Target B: real Raspberry Pi

Needs a 40-pin arm64 Pi (Zero 2 W, 3, 4, or 5), the power relay and wiring, and a
segmented network that isolates the Pi next to the untrusted DUT.

1. Generate a dedicated SSH key for the Pi. No passphrase, because the rig MCP
   server connects non-interactively (`BatchMode=yes`, no ssh-agent in the
   container):
   ```
   mkdir -p data/pi
   ssh-keygen -t ed25519 -f data/pi/id_ed25519 -N '' -C rig@raspudger-001
   ```
2. Flash Raspberry Pi OS Lite (arm64) with Raspberry Pi Imager and apply its OS
   customization: hostname `raspudger-001`, username `rig` (matches
   `RIG_PI_USER`), and SSH enabled with `data/pi/id_ed25519.pub` as an authorized
   key.
3. Wire the DUT: UART TX/RX/GND to the Pi UART pins (GPIO14/GPIO15/GND), and the
   relay coil to the power pin (default BCM 17) with the DUT power on the relay's
   NO/COM.
4. Boot the Pi on the segmented network, then provision it:
   ```
   scp pi/provision.sh rig@raspudger-001.local:/tmp/
   ssh rig@raspudger-001.local 'sudo /tmp/provision.sh && sudo reboot'
   ```
   This frees the PL011 UART from Bluetooth, disables the serial login console,
   installs ser2net on `/dev/serial0`, and grants the `rig` user GPIO and serial
   access. The reboot applies the firmware UART change.
5. Write `rig.env`:
   ```
   RIG_PI_HOST=raspudger-001.local
   RIG_PI_USER=rig
   RIG_PI_SSH_KEY=data/pi/id_ed25519
   RIG_PI_SSH_PORT=22
   RIG_PI_KNOWN_HOSTS=data/pi-known_hosts
   RIG_UART_PORT=5000
   RIG_PIN_POWER=17
   RIG_PIN_UART_TX=14
   RIG_POWER_ACTIVE_HIGH=false
   ```
   The Pi's host key changes on every reflash; delete the `RIG_PI_KNOWN_HOSTS`
   file to re-trust a reflashed Pi, and the operator's own `~/.ssh/known_hosts` is
   never touched. If `.local` does not resolve from inside the agent container,
   set `RIG_PI_HOST` to the Pi's IP or override it per run with `--rig-host`.

### Run the session

```
./rasp --agent claude --rig-config rig.env \
  --task "use the rig tools to enumerate the DUT over UART"
```

For the sim, add `--network raspudger_default` so the container reaches `pi-sim`
(stop it afterward with `docker compose down`). Omit `--task` for an interactive
session. Pin numbers are BCM; set `RIG_POWER_ACTIVE_HIGH=false` for an active-low
opto-isolated relay, `true` otherwise.

The agent runs its tools without per-call approval prompts by default
(`--permission-mode bypassPermissions`): the container is the sandbox boundary,
so the prompts add friction without adding protection. Pass
`--permission-mode default` to approve tools interactively instead.

## Test DUT (ESP32-C3)

`test-dut/` is a deliberately vulnerable UART target for exercising the rig
against known hardware. It is a PlatformIO firmware for an ESP32-C3 (Waveshare
ESP32-C3-Zero) that presents a small command shell over UART with five planted
weaknesses, so the agent has a real device to enumerate and a reproducible
scorecard.

Build and flash with the PlatformIO extension in VS Code: open `test-dut/`, then
Build and Upload. The firmware talks to the Pi on `Serial1` and keeps the USB
serial as a local telemetry console.

Wiring to the Pi (3.3V, no level shifter):

```
Pi TXD GPIO14  ->  ESP32-C3 GPIO4 (RX)
Pi RXD GPIO15  ->  ESP32-C3 GPIO5 (TX)
Pi GND         ->  ESP32-C3 GND
```

Pin self-test: jumper GPIO5 to GPIO4 and reset, or type `selftest` in the USB
monitor. A `PASS` confirms TX and RX are on the configured pins. The shell is
suspended while the jumper is in place, so the loopback does not feed itself.

USB telemetry console (115200 baud): a heartbeat with auth state and a running
`pwned` tally, each command the agent sends mirrored as `[rx]`, and a
`[PWNED n/5]` line the first time each planted weakness is tripped. The agent
never sees this console; it only has the UART.

The five planted weaknesses, with the full answer key in `test-dut/src/main.cpp`:
weak documented credentials, a backdoor password, a hidden undocumented command,
an unauthenticated config leak, and an arbitrary memory read.

## Rig settings (`rig.env`)

`rasp` reads these from `--rig-config` (default `rig.env`, gitignored) and
`--rig-host`, mounts the key into the container, and registers `rig-mcp-server`
with the agent via `--strict-mcp-config --mcp-config` (no approval prompt). With
no `rig.env` and no `--rig-host`, no rig is wired.

- `RIG_PI_HOST`, `RIG_PI_USER`, `RIG_PI_SSH_KEY`, `RIG_PI_SSH_PORT`: how to reach
  the Pi over SSH. The key path is on the host and is mounted in.
- `RIG_PI_KNOWN_HOSTS`: a dedicated known_hosts for the disposable Pi.
- `RIG_UART_HOST` (defaults to `RIG_PI_HOST`), `RIG_UART_PORT`: the ser2net bridge
  to the DUT serial line.
- `RIG_PIN_POWER`, `RIG_PIN_UART_TX`, `RIG_POWER_ACTIVE_HIGH`: the GPIO pin map and
  relay polarity.

`.mcp.json.example` documents the server entry for registering it by hand outside
`rasp`.

## Authentication

The default is the browser login, which uses your existing Claude subscription
(not a pay-per-token API key). `./rasp --agent claude --login` starts the
container interactively; copy the login URL (press `c`), sign in on any machine,
and paste the code back. Credentials persist in `data/agent-home/claude`
(gitignored), so later runs reuse the login.

For headless use with no browser, put one credential in a dotenv file passed with
`--config` (default `config.env`, gitignored; see `config.env.example`):

- `CLAUDE_CODE_OAUTH_TOKEN`: a one-year token from `claude setup-token` (uses the
  subscription).
- `ANTHROPIC_API_KEY`: an API key from the Anthropic Console, billed per token.
  Setting it overrides the subscription.

### Model proxy for the API-key path

When the credential is an `ANTHROPIC_API_KEY`, `rasp` runs a `rig-model-proxy`
sidecar that holds the key and forwards to the Anthropic API, and points the
agent's `ANTHROPIC_BASE_URL` at it. The real key never enters the DUT-facing
container: the agent authenticates to the proxy with a random per-session token
(`ANTHROPIC_AUTH_TOKEN`), and the proxy checks that token, strips it, and injects
the real key before forwarding. The token is generated per run and held only in
the two containers' environments, so another container that can reach the proxy
port but cannot read the agent's environment is rejected. The agent also runs
with `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` so every request stays on the
proxy path. The sidecar and its network are created at session start and removed
at the end. All of this is automatic; `config.env` holds only the real key.

- `--no-model-proxy` injects the key straight into the agent instead (the older
  behavior). The subscription and browser-login paths are unaffected either way,
  since the CLI needs those in process and they cannot be proxied out.
- `--model-proxy-max-requests N` caps how many model requests the proxy forwards
  in a session.

The proxy runs from the agent image, so rebuild it (`make build-image`) after
updating before using this path.

## Security model

- The agent runs in a container that bounds a prompt injection from untrusted DUT
  output to what the container can reach: the mounted project folder, the Pi SSH
  key, and the subscription login. The container is the trust boundary; tightening
  its egress and break-out surface, and snapshotting project state for rollback,
  are tracked as follow-up work.
- The subscription login lives in the gitignored agent home mounted into the
  container; if leaked it allows subscription use as you until revoked, not
  account takeover or API billing.
- An `ANTHROPIC_API_KEY` is held in the model proxy sidecar, not the agent. The
  agent reaches the model through the proxy with a per-session token, so a prompt
  injection cannot read the paid key out of the agent container; it can still
  spend through the proxy, bounded by `--model-proxy-max-requests` (see Model
  proxy above; `--no-model-proxy` opts out).
- The Pi SSH key is mounted into the container for the rig MCP server. It is
  presented with `IdentitiesOnly` and verified against a dedicated known_hosts, so
  it never touches the operator's `~/.ssh`. The Pi is disposable and segmented, so
  the key is low value by construction.
- The Pi must sit on a segmented network isolated from the host network.
  Everything the Pi and DUT return is treated as untrusted data; analysis happens
  on the clean host.

### Operator responsibilities

The project does not configure your network or hosts. You provide, and are
responsible for: the segmented network that isolates the Pi, the secrets passed to
the wrapper, the physical wiring to the DUT, and authorization to test the target.
The security properties above assume these are in place.

## Skills, plugins, and settings

Each agent has a persisted home at `data/agent-home/<agent>` (mounted as its
config directory) holding its login, `settings.json`, skills, slash commands,
subagents, and plugins. It survives across runs. All user-managed runtime state
lives under `data/` (agent homes and project findings), gitignored and managed by
each user. Override locations with `--data-dir`, `--agent-home`, or
`--project-folder`.

## Scope

Intended for authorized security testing: your own devices, engagements you are
contracted for, and research on hardware you are permitted to analyze.

## Contributiong
Contribution is very welcome, feel free to open PRs.
