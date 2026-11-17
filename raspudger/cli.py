"""Entry point: parse the invocation, assemble the session, run Docker.

This is the thin shell around the pure core. It performs the real I/O
(subprocess, environment) and is verified by the manual acceptance criterion,
not by unit tests.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import time
import uuid
from collections.abc import Sequence

from .adapters import AgentAdapter, resolve_adapter
from .args import Args, parse_args, prepare_paths
from .config import load_credential
from .errors import ReToolingError
from .invocation import build_docker_command
from .proxy import PROXY_PORT, ProxyPlan, plan_model_proxy
from .rig import RigLaunch, load_rig_launch

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
    try:
        args = parse_args(raw)
        prepare_paths(args)
        adapter = resolve_adapter(args.agent)
        credential = load_credential(args.config, adapter.auth_env_vars)
        rig = load_rig_launch(
            args.rig_config, args.rig_host, args.device, require_device=not args.login
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
