# Working on Raspudger

Guidance for an agent changing this repository. (This is distinct from
`priming/AGENTS.md`, which is injected into the containerized agent that drives a
DUT; this file is for development of the codebase itself.)

## Architecture: deep modules behind clean seams

The rig is built as a few deep modules, each with a small interface and a lot of
behaviour behind it. Keep it that way; the friction this project has hit came
from letting behaviour leak into the thin layers.

- `rig_mcp/transport.py` is the seam to the Pi: a small `Transport` protocol with
  two adapters, `SshTransport` (real) and `FakeTransport` (tests). Everything that
  touches the Pi goes through it, and every test fakes at it. Tests never need the
  network, a device, or a live service.
- `rig_mcp/tools.py` (`RigTools`) holds the transport-side behaviour (exec, UART
  send/expect/exchange/capture, line config, handoff, power). Timing is injected
  (`sleep`/`clock`) so tests never wait.
- `rig_mcp/state.py` holds `StateStore` (device-as-argument, pure file I/O) and
  `DeviceState`, the view bound to the one device of a session. `DeviceState`
  owns the "no device bound" guard and the `StateError` -> error-payload
  translation in one place each; do not re-implement either in a tool.
- `rig_mcp/config.py` (`RigConfig.from_env`) is pure over a mapping.
- `raspudger/monitor.py` is the read-only serial monitor: ser2net traces both
  directions of the line to one file in wire order, and the monitor tails it over
  SSH, so it observes the session without owning the line and never contends with
  the agent. Target resolution and save-path selection are pure functions tested
  directly; the SSH subprocess and terminal writes live in `cli`.

The pattern throughout is pure-core + thin-shell: parsing and logic are pure and
unit-tested; I/O is isolated at a seam. `main.py` / `build_live_tools` is the one
composition root that touches the real environment and network.

## Pi-side serial console workarounds

The interactive console (`rasp monitor --interactive`) runs picocom on the raw
line through `rig-serial-lease`, and two flags there are load-bearing for
non-obvious platform reasons:

- `rig-serial-lease` runs the leased command under `timeout --foreground`. GNU
  `timeout` otherwise puts the command in a background process group, which
  cannot read the controlling terminal: an interactive console gets no keystrokes
  and no terminal signals, and on an SSH disconnect the command misses SIGHUP,
  orphans, and keeps the serial device open so ser2net cannot reclaim the line.
  `--foreground` keeps it in the terminal's foreground group and fixes both.
- `rig-serial-console` runs picocom with `--omap crcrlf`, so Enter sends CR+LF.
  A bare CR (picocom's default) is ignored by DUT consoles that terminate a
  command line on LF, so without it typed commands never execute. picocom also
  runs with `-c` (local echo) because a DUT that does not echo its input leaves
  an otherwise silent console. minicom cannot send CR+LF on Enter at all, which
  is why the console uses picocom.

## MCP tools are registered from their implementation, not restated

`rig_mcp/server.py` is a thin registration layer. A tool that is a pure
pass-through to a method on `RigTools` or `DeviceState` is registered **by
reference** (see the `passthrough` table): the MCP name, description, and
parameter schema come from the method's name, docstring, and signature, so they
cannot drift from the code the agent actually runs.

- Add a tool by adding the method (with its type hints and an agent-facing
  docstring) and one line in the `passthrough` table. Do not hand-write a
  `@app.tool()` body that restates the method's parameters or docstring; that is
  the duplication this layout exists to prevent.
- Only a tool with genuine server-local logic (a capability report, the network
  credentials, a capture that spans the transport and the device workspace) is
  written out as an `@app.tool()` function.
- The method's docstring is the single source of the agent-facing description.
  Write it there, once.

## Don't duplicate code or invariants

One rule, one home. A validation or invariant that appears in two places will
drift; factor it to a single function the call sites share (for example, the
"name cannot escape the workspace" check). Before copying a guard, an error
message, or a contract into a second place, make the first place reusable
instead.

## Conventions

- No `git commit` and no `git add`: staging and committing are the user's.
- No em dashes, no emojis.
- Full descriptive names; boolean helpers prefixed `is_`/`has_`; type hints on
  signatures.
- Comments and docstrings state the status quo (positive facts), not history,
  dates, or what the code does not do.

## Before reporting work done

Run the project gate with the venv binaries (the shell PATH has wrong versions):

```
make check    # ruff check + mypy raspudger rig_mcp rig_proxy + pytest + ruff format --check
```

Report failures with their output rather than describing them.
