"""Rig tools: the logic the MCP server exposes, over a Transport.

The power-cycle interlock lives here (host-side), not in a Pi-side script, so it
is unit-testable: tristate UART TX, cut power, wait, restore power, un-tristate.
Timing uses an injected ``sleep``/``clock`` so tests never actually wait.
"""

from __future__ import annotations

import re
import shlex
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .script_runner import (
    ScriptNotFoundError,
    available_scripts,
    build_command,
    load_script,
)
from .transport import ExecResult, Transport

MAX_OUTPUT_CHARS: int = 100_000
CAPTURE_HEAD_BYTES: int = 2_000
_CAPTURE_MATCH_WINDOW: int = 8_192


def _cap_stream(text: str) -> tuple[str, bool]:
    """A stream capped to ``MAX_OUTPUT_CHARS``, with an inline marker if cut.

    The marker is appended to the returned text so the agent sees the output is
    partial even if it ignores the structured ``truncated`` flag, and never
    reasons over a truncated result as if it were complete.
    """
    if len(text) <= MAX_OUTPUT_CHARS:
        return text, False

    marker: str = f"\n[truncated: first {MAX_OUTPUT_CHARS} of {len(text)} characters]"
    return text[:MAX_OUTPUT_CHARS] + marker, True


def _exec_payload(result: ExecResult) -> dict[str, object]:
    stdout, stdout_truncated = _cap_stream(result.stdout)
    stderr, stderr_truncated = _cap_stream(result.stderr)
    return {
        "stdout": stdout,
        "stderr": stderr,
        "returncode": result.returncode,
        "truncated": stdout_truncated or stderr_truncated,
    }


@dataclass
class RigTools:
    transport: Transport
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    read_timeout: float = 0.1

    def pi_exec(self, command: str, timeout_s: float = 30.0) -> dict[str, object]:
        result = self.transport.exec(command, timeout_s)
        return _exec_payload(result)

    def list_scripts(self) -> dict[str, object]:
        return {"scripts": available_scripts()}

    def run_script(
        self,
        name: str,
        args: list[str] | None = None,
        timeout_s: float = 30.0,
    ) -> dict[str, object]:
        try:
            body = load_script(name)
        except ScriptNotFoundError as error:
            return {"error": str(error), "scripts": available_scripts()}

        command = build_command(body, args or [])
        result = self.transport.exec(command, timeout_s)
        return _exec_payload(result)

    def uart_send(self, data: str, line_delay_ms: int = 0) -> dict[str, object]:
        """Write to the UART, optionally pacing line by line.

        A bare serial line has no flow control, so a large or multi-line write
        can overrun the DUT's receiver. ``line_delay_ms`` inserts a delay between
        lines so a paste or script lands without dropped characters.
        """
        encoded = data.encode()
        try:
            self._uart_write_paced(encoded, line_delay_ms)
        except OSError as error:
            return {"bytes_written": 0, "error": f"UART unreachable: {error}"}

        return {"bytes_written": len(encoded)}

    def _uart_write_paced(self, data: bytes, line_delay_ms: int) -> None:
        if line_delay_ms <= 0:
            self.transport.uart_write(data)
            return

        delay = line_delay_ms / 1000.0
        for index, line in enumerate(data.splitlines(keepends=True)):
            if index:
                self.sleep(delay)

            self.transport.uart_write(line)

    def uart_expect(self, pattern: str, timeout_s: float) -> dict[str, object]:
        matcher = re.compile(pattern.encode())
        deadline = self.clock() + timeout_s
        buffer = b""
        while self.clock() < deadline and matcher.search(buffer) is None:
            try:
                buffer += self.transport.uart_read(self.read_timeout)
            except OSError as error:
                return {
                    "matched": False,
                    "data": buffer.decode(errors="replace"),
                    "matched_text": None,
                    "error": f"UART unreachable: {error}",
                }

        found = matcher.search(buffer)
        return {
            "matched": found is not None,
            "data": buffer.decode(errors="replace"),
            "matched_text": found.group(0).decode(errors="replace") if found else None,
        }

    def uart_exchange(
        self,
        steps: list[dict[str, object]],
        default_timeout_s: float = 1.0,
        line_delay_ms: int = 0,
    ) -> dict[str, object]:
        """Run a batch of send/expect steps over the one owned UART connection.

        Each step may carry a ``send`` string and an ``expect`` regex with an
        optional ``timeout_s``. Steps run in order and each produces a result, so
        a scan that would be thousands of ``uart_send``/``uart_expect`` round
        trips collapses into one call. A non-match records a result and the batch
        continues; an unreachable UART stops the batch and returns what ran.
        ``line_delay_ms`` paces each send line by line for a DUT with no flow
        control.
        """
        results: list[dict[str, object]] = []
        for step in steps:
            send_value = step.get("send")
            if send_value is not None:
                payload = send_value if isinstance(send_value, str) else str(send_value)
                try:
                    self._uart_write_paced(payload.encode(), line_delay_ms)
                except OSError as error:
                    return {
                        "results": results,
                        "completed": len(results),
                        "error": f"UART unreachable: {error}",
                    }

            expect_value = step.get("expect")
            if expect_value is None:
                results.append({"matched": None, "data": "", "matched_text": None})
                continue

            pattern = expect_value if isinstance(expect_value, str) else str(expect_value)
            matcher = re.compile(pattern.encode())
            timeout_value = step.get("timeout_s", default_timeout_s)
            timeout_s = (
                float(timeout_value)
                if isinstance(timeout_value, int | float)
                else default_timeout_s
            )

            deadline = self.clock() + timeout_s
            buffer = b""
            while self.clock() < deadline and matcher.search(buffer) is None:
                try:
                    buffer += self.transport.uart_read(self.read_timeout)
                except OSError as error:
                    results.append(
                        {
                            "matched": False,
                            "data": buffer.decode(errors="replace"),
                            "matched_text": None,
                        }
                    )
                    return {
                        "results": results,
                        "completed": len(results),
                        "error": f"UART unreachable: {error}",
                    }

            found = matcher.search(buffer)
            results.append(
                {
                    "matched": found is not None,
                    "data": buffer.decode(errors="replace"),
                    "matched_text": found.group(0).decode(errors="replace") if found else None,
                }
            )

        return {"results": results, "completed": len(results)}

    def uart_capture(
        self,
        out_path: Path,
        trigger: str = "",
        until_pattern: str | None = None,
        timeout_s: float = 30.0,
        idle_timeout_s: float | None = None,
    ) -> dict[str, object]:
        """Stream UART output to a file over the owned connection.

        Fires an optional ``trigger`` then records everything the DUT sends to
        ``out_path`` until ``until_pattern`` matches, ``timeout_s`` elapses, or
        the line stays quiet for ``idle_timeout_s``. The bytes go to the file,
        not the response, so a boot log or a memory dump does not flow through the
        agent's context or hit the output cap. The returned ``head`` is the first
        bytes for a quick look; read ``path`` for the whole capture.
        """
        matcher = re.compile(until_pattern.encode()) if until_pattern else None
        out_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = self.clock() + timeout_s
        total = 0
        head = b""
        window = b""
        last_data = self.clock()
        ended_on = "timeout"
        with out_path.open("wb") as handle:
            if trigger:
                try:
                    self.transport.uart_write(trigger.encode())
                except OSError as error:
                    return {
                        "path": str(out_path),
                        "bytes": 0,
                        "head": "",
                        "ended_on": "error",
                        "error": f"UART unreachable: {error}",
                    }

            while self.clock() < deadline:
                try:
                    chunk = self.transport.uart_read(self.read_timeout)
                except OSError as error:
                    return {
                        "path": str(out_path),
                        "bytes": total,
                        "head": head.decode(errors="replace"),
                        "ended_on": "error",
                        "error": f"UART unreachable: {error}",
                    }

                if chunk:
                    handle.write(chunk)
                    total += len(chunk)
                    if len(head) < CAPTURE_HEAD_BYTES:
                        head += chunk[: CAPTURE_HEAD_BYTES - len(head)]
                    last_data = self.clock()
                    if matcher is not None:
                        window = (window + chunk)[-_CAPTURE_MATCH_WINDOW:]
                        if matcher.search(window):
                            ended_on = "pattern"
                            break
                elif idle_timeout_s is not None and self.clock() - last_data >= idle_timeout_s:
                    ended_on = "idle"
                    break

        return {
            "path": str(out_path),
            "bytes": total,
            "head": head.decode(errors="replace"),
            "ended_on": ended_on,
        }

    def uart_configure(
        self, mode: str, flow: str = "none", timeout_s: float = 30.0
    ) -> dict[str, object]:
        """Set the persistent serial line settings the interactive tools use.

        ``mode`` is a ser2net serialdev mode, such as ``115200n81`` or
        ``57600e71``, for a DUT whose console is not the provisioned 115200 8N1.
        The ser2net connector on the Pi is rewritten and the bridge restarted; an
        unusable mode surfaces as a failed restart in the result. The owned socket
        is dropped afterward so the next UART use reconnects to the new bridge.
        """
        command = shlex.join(["sudo", "rig-serial-config", mode, flow])
        result = self.transport.exec(command, timeout_s)
        self.transport.uart_reset()
        payload = _exec_payload(result)
        payload["mode"] = mode
        return payload

    def uart_handoff(
        self,
        command: str,
        timeout_s: float = 120.0,
        baud: int | None = None,
    ) -> dict[str, object]:
        """Lease the raw serial device to a Pi-side command, then reclaim it.

        Stops ser2net so ``command`` owns the raw device (``$RIG_UART_DEVICE``),
        runs it under a timeout, and restarts ser2net from a Pi-side trap so the
        line is reclaimed even on failure or a dropped connection. This is the
        escape hatch for any serial tool the rig does not model directly: a
        transfer protocol (``sz``/``rx``), a flasher (``flashrom``), a one-off
        script. The owned socket is dropped afterward so interactive use
        reconnects.
        """
        argv = ["sudo", "rig-serial-lease", str(int(timeout_s))]
        if baud is not None:
            argv += ["--baud", str(int(baud))]

        argv += ["--", command]
        # Allow for the Pi-side timeout plus ser2net stop/start on reclaim.
        result = self.transport.exec(shlex.join(argv), timeout_s + 30.0)
        self.transport.uart_reset()
        payload = _exec_payload(result)
        payload["reclaimed"] = True
        return payload

    def dut_power(self, state: str) -> dict[str, object]:
        on = state == "on"
        self.transport.set_power(on)

        return {"state": "on" if on else "off"}

    def dut_power_cycle(self, off_ms: int = 2000) -> dict[str, object]:
        self.transport.set_uart_tristate(True)
        self.transport.set_power(False)
        self.sleep(off_ms / 1000)
        self.transport.set_power(True)
        self.transport.set_uart_tristate(False)

        return {"ok": True}
