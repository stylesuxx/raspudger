"""Entry point for ``rig-model-proxy``: read the environment, serve, shut down."""

from __future__ import annotations

import os
import signal
import sys
import threading
from collections.abc import Sequence
from types import FrameType

from .config import ProxyConfig
from .errors import ProxyConfigError
from .forwarding import UsageCap
from .server import BIND_HOST, make_server


def main(argv: Sequence[str] | None = None) -> int:
    try:
        config = ProxyConfig.from_env(os.environ)
    except ProxyConfigError as exc:
        print(f"rig-model-proxy: {exc}", file=sys.stderr)
        return 2

    cap = UsageCap(config.max_requests)
    server = make_server(config, cap)

    def _stop(_signum: int, _frame: FrameType | None) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _stop)

    print(
        f"rig-model-proxy listening on {BIND_HOST}:{config.port}, "
        f"upstream {config.upstream_scheme}://{config.upstream_authority}",
        file=sys.stderr,
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
