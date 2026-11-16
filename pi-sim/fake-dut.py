#!/usr/bin/env python3
"""A minimal fake device-under-test serial console for the dev sim.

Creates a pty, holds the master open for the life of the process, and publishes
the slave device under a stable symlink that ser2net opens as its serial
connector. Runs a small line-oriented command loop so the rig's ``uart_send`` /
``uart_expect`` can be exercised end to end over the ser2net TCP bridge. On the
real rig this role is played by the actual device under test on ``/dev/serial0``.

Holding the master for the whole process life keeps the slave device and its
symlink stable as ser2net opens and closes the slave across client connects; a
read with no slave open returns ``EIO``, which is treated as idle.
"""

from __future__ import annotations

import contextlib
import errno
import os
import sys
import time
import tty

PROMPT = b"pi-sim-dut> "

RESPONSES: dict[bytes, bytes] = {
    b"id": b"pi-sim-dut v0.1",
    b"help": b"commands: id help ping",
    b"ping": b"pong",
}

IDLE_SLEEP_S = 0.05


def respond(command: bytes) -> bytes:
    if not command:
        return b"\r\n" + PROMPT

    reply: bytes = RESPONSES.get(command, b"unknown: " + command)
    return b"\r\n" + reply + b"\r\n" + PROMPT


def publish_symlink(link_path: str, target: str) -> None:
    temporary_path: str = f"{link_path}.new"
    with contextlib.suppress(FileNotFoundError):
        os.remove(temporary_path)

    os.symlink(target, temporary_path)
    os.replace(temporary_path, link_path)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: fake-dut.py <symlink-path>", file=sys.stderr)
        return 2

    link_path: str = sys.argv[1]
    master_fd, slave_fd = os.openpty()
    tty.setraw(slave_fd)
    publish_symlink(link_path, os.ttyname(slave_fd))
    os.close(slave_fd)

    line_buffer = bytearray()
    while True:
        try:
            chunk: bytes = os.read(master_fd, 256)
        except OSError as error:
            if error.errno == errno.EIO:
                time.sleep(IDLE_SLEEP_S)
                continue

            raise

        if not chunk:
            time.sleep(IDLE_SLEEP_S)
            continue

        for byte_value in chunk:
            if byte_value in (10, 13):
                command: bytes = bytes(line_buffer).strip()
                line_buffer.clear()
                os.write(master_fd, respond(command))
            else:
                line_buffer.append(byte_value)
                os.write(master_fd, bytes([byte_value]))


if __name__ == "__main__":
    raise SystemExit(main())
