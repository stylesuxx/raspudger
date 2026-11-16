"""The launch plan for the model egress proxy sidecar (pure, no Docker calls).

When the chosen credential is an ``ANTHROPIC_API_KEY`` and the proxy is enabled,
the session runs a ``rig-model-proxy`` container that holds the key and forwards
to the upstream Anthropic API. The agent then carries only a placeholder
credential and an ``ANTHROPIC_BASE_URL`` pointed at the proxy, so the real key
never enters the agent container.
"""

from __future__ import annotations

from dataclasses import dataclass

from .args import Args
from .config import Credential

API_KEY_VAR = "ANTHROPIC_API_KEY"
# The agent authenticates to the proxy with a bearer token, the documented
# variable for a gateway. Its value is a random per-session secret the proxy
# checks before injecting the real key, so a sibling container that can reach the
# proxy's port but cannot read the agent's environment is rejected.
AGENT_AUTH_VAR = "ANTHROPIC_AUTH_TOKEN"
PROXY_AUTH_VAR = "RIG_PROXY_AUTH_TOKEN"
PROXY_PORT = 8080
PROXY_COMMAND = "rig-model-proxy"


@dataclass(frozen=True)
class ProxyPlan:
    """Everything the shell needs to run and tear down the proxy sidecar."""

    container_name: str
    network: str
    create_network: bool
    run_argv: list[str]
    env: dict[str, str]
    base_url: str
    agent_placeholder: Credential

    @property
    def network_create_argv(self) -> list[str] | None:
        """The ``docker network create`` command, when the proxy owns its network."""
        if not self.create_network:
            return None

        return ["docker", "network", "create", self.network]

    @property
    def teardown_argv(self) -> list[list[str]]:
        """Commands to remove the proxy container and any network it created."""
        commands = [["docker", "rm", "-f", self.container_name]]
        if self.create_network:
            commands.append(["docker", "network", "rm", self.network])

        return commands


def plan_model_proxy(
    *,
    credential: Credential | None,
    args: Args,
    image: str,
    session_id: str,
    auth_token: str,
    port: int = PROXY_PORT,
) -> ProxyPlan | None:
    """Plan the proxy sidecar, or None when it does not apply.

    The proxy applies only to an ``ANTHROPIC_API_KEY`` credential with the proxy
    enabled. The subscription token and browser-login paths cannot be proxied out
    of the CLI, so they return None. ``auth_token`` is the per-session secret the
    agent presents and the proxy checks; the caller generates a fresh one.
    """
    if not args.model_proxy:
        return None

    if credential is None or credential.env_var != API_KEY_VAR:
        return None

    container_name = f"raspudger-proxy-{session_id}"

    if args.network is not None:
        network = args.network
        create_network = False
    else:
        network = f"raspudger-proxy-net-{session_id}"
        create_network = True

    run_argv = ["docker", "run", "--rm", "-d", "--network", network, "--name", container_name]
    run_argv += ["-e", API_KEY_VAR, "-e", PROXY_AUTH_VAR]
    if args.model_proxy_max_requests is not None:
        run_argv += ["-e", f"RIG_PROXY_MAX_REQUESTS={args.model_proxy_max_requests}"]

    run_argv += [image, PROXY_COMMAND]

    return ProxyPlan(
        container_name=container_name,
        network=network,
        create_network=create_network,
        run_argv=run_argv,
        env={API_KEY_VAR: credential.value, PROXY_AUTH_VAR: auth_token},
        base_url=f"http://{container_name}:{port}",
        agent_placeholder=Credential(env_var=AGENT_AUTH_VAR, value=auth_token),
    )
