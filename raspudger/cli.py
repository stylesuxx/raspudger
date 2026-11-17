"""Entry point: parse the invocation, assemble the session, run Docker.

This is the thin shell around the pure core. It performs the real I/O
(subprocess, environment) and is verified by the manual acceptance criterion,
not by unit tests.
"""

from __future__ import annotations

import contextlib
import io
import os
import secrets
import subprocess
import sys
import time
import uuid
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import IO

from .adapters import AgentAdapter, resolve_adapter
from .args import Args, MonitorArgs, parse_args, parse_monitor_args, prepare_paths
from .config import load_credential
from .errors import ReToolingError
from .invocation import build_docker_command
from .monitor import (
    MonitorTarget,
    build_interactive_command,
    build_monitor_command,
    resolve_save_path,
)
from .proxy import PROXY_PORT, ProxyPlan, plan_model_proxy
from .rig import RigLaunch, load_rig_launch

MONITOR_SUBCOMMAND = "monitor"
MONITOR_READ_SIZE = 4096

DEFAULT_IMAGE = "raspudger-agent:latest"
IMAGE_ENV_VAR = "RASPUDGER_IMAGE"
PROXY_READY_ATTEMPTS = 20
PROXY_READY_INTERVAL_S = 0.25


def _image() -> str:
    return os.environ.get(IMAGE_ENV_VAR, DEFAULT_IMAGE)


def _image_available(image: str) -> bool:
    result = subprocess.run(
        ["docker", "image", "inspect", image],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def main(argv: Sequence[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] == MONITOR_SUBCOMMAND:
        return _run_monitor(parse_monitor_args(raw[1:]))

    try:
        args = parse_args(raw)
        prepare_paths(args)
        adapter = resolve_adapter(args.agent)
        credential = load_credential(args.config, adapter.auth_env_vars)
        rig = load_rig_launch(
            args.rig_config,
            args.rig_host,
            args.device,
            require_device=not args.login,
            no_power=args.no_power,
        )
    except ReToolingError as exc:
        print(f"rasp: {exc}", file=sys.stderr)
        return 2

    image = _image()
    if not _image_available(image):
        print(
            f"rasp: image {image!r} not found locally. Build it first:\n  make build-image",
            file=sys.stderr,
        )
        return 2

    session_id = uuid.uuid4().hex[:12]
    proxy = plan_model_proxy(
        credential=credential,
        args=args,
        image=image,
        session_id=session_id,
        auth_token=secrets.token_urlsafe(32),
    )

    if proxy is None:
        invocation = build_docker_command(
            args=args, adapter=adapter, credential=credential, image=image, rig=rig
        )
        completed = subprocess.run(
            invocation.argv, env={**os.environ, **invocation.env}, check=False
        )
        return completed.returncode

    return _run_with_proxy(proxy, args=args, adapter=adapter, image=image, rig=rig)


def _run_with_proxy(
    proxy: ProxyPlan,
    *,
    args: Args,
    adapter: AgentAdapter,
    image: str,
    rig: RigLaunch | None,
) -> int:
    if not _start_proxy(proxy):
        print("rasp: failed to start the model proxy sidecar", file=sys.stderr)
        _teardown_proxy(proxy)
        return 2

    print(
        "rasp: model key held in the proxy sidecar; the agent carries only a placeholder",
        file=sys.stderr,
    )

    try:
        _wait_for_proxy(proxy)
        invocation = build_docker_command(
            args=args,
            adapter=adapter,
            credential=proxy.agent_placeholder,
            image=image,
            rig=rig,
            base_url=proxy.base_url,
            network=proxy.network,
        )
        completed = subprocess.run(
            invocation.argv, env={**os.environ, **invocation.env}, check=False
        )

        return completed.returncode
    finally:
        _teardown_proxy(proxy)


def _run_monitor(monitor_args: MonitorArgs) -> int:
    try:
        target = MonitorTarget.from_rig_config(monitor_args.rig_config, monitor_args.rig_host)
    except ReToolingError as exc:
        print(f"rasp: {exc}", file=sys.stderr)
        return 2

    if monitor_args.interactive:
        return _run_interactive(target, monitor_args.baud)

    save_path = resolve_save_path(
        monitor_args.save,
        monitor_args.no_save,
        monitor_args.device,
        monitor_args.project_folder,
        datetime.now(),
    )
    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"rasp: saving transcript to {save_path}", file=sys.stderr)

    print(
        f"rasp: connecting to {target.user}@{target.host} to watch the UART ...",
        file=sys.stderr,
    )
    return _stream_monitor(build_monitor_command(target), save_path)


def _run_interactive(target: MonitorTarget, baud: int | None) -> int:
    """Open the exclusive interactive console, inheriting the terminal.

    ssh runs with a PTY and the terminal is handed straight to the Pi-side
    console, so keystrokes reach the DUT. ser2net is stopped for the duration, so
    the agent's UART tools pause until the console exits.
    """
    print(
        "rasp: taking exclusive control of the serial line. ser2net stops and the "
        "agent's UART tools pause until you exit.",
        file=sys.stderr,
    )
    print("rasp: exit the console with Ctrl-A Ctrl-X.", file=sys.stderr)
    completed = subprocess.run(build_interactive_command(target, baud), check=False)
    print("rasp: console closed; ser2net resumes.", file=sys.stderr)
    return completed.returncode


def _stream_monitor(argv: list[str], save_path: Path | None) -> int:
    """Run the monitor helper over SSH, stream it to the terminal, and save it.

    The helper emits the UART trace in wire order; this passes those bytes straight
    to the terminal, and to the save file when one is set. The loop ends when the
    helper closes its stream (the SSH channel drops) or Ctrl-C interrupts it.
    """
    out = sys.stdout.buffer
    process = subprocess.Popen(argv, stdout=subprocess.PIPE)
    stream = process.stdout
    # A buffered pipe: read1 returns bytes as they arrive, so a quiet console is
    # not held back waiting to fill a fixed-size read.
    assert isinstance(stream, io.BufferedReader)

    received = 0
    try:
        with contextlib.ExitStack() as stack:
            save_file: IO[bytes] | None = (
                stack.enter_context(open(save_path, "ab")) if save_path is not None else None
            )
            while chunk := stream.read1(MONITOR_READ_SIZE):
                received += len(chunk)
                out.write(chunk)
                out.flush()

                if save_file is not None:
                    save_file.write(chunk)
                    save_file.flush()
    except KeyboardInterrupt:
        pass
    finally:
        process.terminate()
        process.wait()

    if received == 0:
        print(
            "\nrasp: no UART data received. Check that the Pi has the latest "
            "rig-serial-monitor and that a session is driving the UART.",
            file=sys.stderr,
        )

    return process.returncode or 0


def _start_proxy(proxy: ProxyPlan) -> bool:
    if proxy.network_create_argv is not None:
        subprocess.run(
            proxy.network_create_argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    result = subprocess.run(
        proxy.run_argv,
        env={**os.environ, **proxy.env},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        sys.stderr.buffer.write(result.stderr)
        return False

    return True


def _wait_for_proxy(proxy: ProxyPlan) -> None:
    """Poll the proxy's health endpoint from inside its container, best effort.

    The agent retries its first request anyway, so a proxy that is slow to bind
    is not fatal; this just avoids a failed first call in the common case.
    """
    health_url = f"http://127.0.0.1:{PROXY_PORT}/healthz"
    for _ in range(PROXY_READY_ATTEMPTS):
        result = subprocess.run(
            ["docker", "exec", proxy.container_name, "curl", "-sf", health_url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0:
            return

        time.sleep(PROXY_READY_INTERVAL_S)


def _teardown_proxy(proxy: ProxyPlan) -> None:
    for command in proxy.teardown_argv:
        subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


if __name__ == "__main__":
    sys.exit(main())
