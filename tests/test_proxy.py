from __future__ import annotations

from collections.abc import Sequence

from raspudger.adapters import resolve_adapter
from raspudger.args import parse_args
from raspudger.config import Credential
from raspudger.invocation import build_docker_command
from raspudger.proxy import (
    AGENT_AUTH_VAR,
    PROXY_AUTH_VAR,
    PROXY_PORT,
    plan_model_proxy,
)

API_CREDENTIAL = Credential("ANTHROPIC_API_KEY", "sk-ant-REAL")
OAUTH_CREDENTIAL = Credential("CLAUDE_CODE_OAUTH_TOKEN", "tok")
SESSION_TOKEN = "session-secret-xyz"


def _args(extra: Sequence[str] = ()) -> object:
    return parse_args(["--agent", "claude", *extra])


def _plan(args: object, session_id: str = "abc"):  # type: ignore[no-untyped-def]
    return plan_model_proxy(
        credential=API_CREDENTIAL,
        args=args,
        image="img",
        session_id=session_id,
        auth_token=SESSION_TOKEN,
    )


def test_no_plan_without_a_credential() -> None:
    plan = plan_model_proxy(
        credential=None, args=_args(), image="img", session_id="s", auth_token=SESSION_TOKEN
    )
    assert plan is None


def test_no_plan_for_subscription_token() -> None:
    plan = plan_model_proxy(
        credential=OAUTH_CREDENTIAL,
        args=_args(),
        image="img",
        session_id="s",
        auth_token=SESSION_TOKEN,
    )
    assert plan is None


def test_no_plan_when_disabled() -> None:
    plan = _plan(_args(["--no-model-proxy"]))
    assert plan is None


def test_plan_creates_its_own_network_without_a_network_flag() -> None:
    plan = _plan(_args())
    assert plan is not None
    assert plan.create_network is True
    assert plan.network == "raspudger-proxy-net-abc"
    assert plan.container_name == "raspudger-proxy-abc"
    assert plan.base_url == f"http://raspudger-proxy-abc:{PROXY_PORT}"
    assert plan.env == {"ANTHROPIC_API_KEY": "sk-ant-REAL", PROXY_AUTH_VAR: SESSION_TOKEN}
    assert plan.agent_placeholder == Credential(AGENT_AUTH_VAR, SESSION_TOKEN)

    assert "-d" in plan.run_argv
    assert plan.run_argv[-2:] == ["img", "rig-model-proxy"]
    assert plan.run_argv.count("--network") == 1
    # The key and the session token ride the environment, never the command line.
    assert "sk-ant-REAL" not in plan.run_argv
    assert SESSION_TOKEN not in plan.run_argv
    assert plan.run_argv.count(PROXY_AUTH_VAR) == 1

    assert plan.network_create_argv == ["docker", "network", "create", "raspudger-proxy-net-abc"]
    assert ["docker", "rm", "-f", "raspudger-proxy-abc"] in plan.teardown_argv
    assert ["docker", "network", "rm", "raspudger-proxy-net-abc"] in plan.teardown_argv


def test_plan_joins_an_existing_network() -> None:
    plan = _plan(_args(["--network", "raspudger_default"]))
    assert plan is not None
    assert plan.create_network is False
    assert plan.network == "raspudger_default"
    assert plan.network_create_argv is None
    assert plan.teardown_argv == [["docker", "rm", "-f", "raspudger-proxy-abc"]]


def test_plan_passes_the_request_cap_to_the_proxy_env() -> None:
    plan = _plan(_args(["--model-proxy-max-requests", "100"]))
    assert plan is not None
    assert "RIG_PROXY_MAX_REQUESTS=100" in plan.run_argv


def test_build_docker_command_applies_base_url_and_network_override() -> None:
    args = parse_args(["--agent", "claude", "--project-folder", "/tmp/p", "--agent-home", "/tmp/h"])
    invocation = build_docker_command(
        args=args,
        adapter=resolve_adapter("claude"),
        credential=Credential(AGENT_AUTH_VAR, SESSION_TOKEN),
        image="img",
        base_url="http://raspudger-proxy-x:8080",
        network="netz",
    )
    argv = invocation.argv
    assert argv[argv.index("--network") + 1] == "netz"
    assert "ANTHROPIC_BASE_URL=http://raspudger-proxy-x:8080" in argv
    assert "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1" in argv
    assert AGENT_AUTH_VAR in argv
    assert invocation.env[AGENT_AUTH_VAR] == SESSION_TOKEN
