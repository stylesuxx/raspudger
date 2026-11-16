"""Rig tools: the logic the MCP server exposes, over a Transport.

The power-cycle interlock lives here (host-side), not in a Pi-side script, so it
is unit-testable: tristate UART TX, cut power, wait, restore power, un-tristate.
Timing uses an injected ``sleep``/``clock`` so tests never actually wait.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass

from .transport import Transport


@dataclass
class RigTools:
    transport: Transport
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    read_timeout: float = 0.1

    def pi_exec(self, command: str, timeout_s: float = 30.0) -> dict[str, object]:
        result = self.transport.exec(command, timeout_s)
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }

    def uart_send(self, data: str) -> dict[str, object]:
        encoded = data.encode()
        try:
            self.transport.uart_write(encoded)
        except OSError as error:
            return {"bytes_written": 0, "error": f"UART unreachable: {error}"}

        return {"bytes_written": len(encoded)}

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
    ) -> dict[str, object]:
        """Run a batch of send/expect steps over the one owned UART connection.

        Each step may carry a ``send`` string and an ``expect`` regex with an
        optional ``timeout_s``. Steps run in order and each produces a result, so
        a scan that would be thousands of ``uart_send``/``uart_expect`` round
        trips collapses into one call. A non-match records a result and the batch
        continues; an unreachable UART stops the batch and returns what ran.
        """
        results: list[dict[str, object]] = []
        for step in steps:
            send_value = step.get("send")
            if send_value is not None:
                payload = send_value if isinstance(send_value, str) else str(send_value)
                try:
                    self.transport.uart_write(payload.encode())
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
