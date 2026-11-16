"""Entry point: parse the invocation, assemble the session, run Docker.

This is the thin shell around the pure core. It performs the real I/O
(subprocess, environment) and is verified by the manual acceptance criterion,
not by unit tests.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence

from .adapters import resolve_adapter
from .args import parse_args, prepare_paths
from .config import load_credential
from .errors import ReToolingError
from .invocation import build_docker_command
from .rig import load_rig_launch

DEFAULT_IMAGE = "raspudger-agent:latest"
IMAGE_ENV_VAR = "RASPUDGER_IMAGE"


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
        rig = load_rig_launch(args.rig_config, args.rig_host)
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

    invocation = build_docker_command(
        args=args, adapter=adapter, credential=credential, image=image, rig=rig
    )
    env = {**os.environ, **invocation.env}
    completed = subprocess.run(invocation.argv, env=env, check=False)

    return completed.returncode


if __name__ == "__main__":
    sys.exit(main())
