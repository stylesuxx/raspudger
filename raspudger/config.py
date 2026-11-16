"""Loading the operator's optional credentials file.

Authentication defaults to a persisted browser login (see the auth volume), so
this file is optional. When present it is a dotenv file (KEY=VALUE lines) holding
one credential for non-interactive use, for example:

    CLAUDE_CODE_OAUTH_TOKEN=...   # from `claude setup-token`, uses the subscription
    ANTHROPIC_API_KEY=sk-ant-...  # billed per token, separate from the subscription
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError


@dataclass(frozen=True)
class Credential:
    """A single auth credential: the env var to set and its value."""

    env_var: str
    value: str


def parse_env_file(text: str) -> dict[str, str]:
    """Parse dotenv-style KEY=VALUE lines into a mapping.

    Blank lines and lines beginning with '#' are ignored. A leading 'export ' is
    allowed. Surrounding single or double quotes on the value are stripped.
    """
    result: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if name:
            result[name] = value
    return result


def load_credential(path: Path, accepted_vars: Sequence[str]) -> Credential | None:
    """Return the first accepted credential in the dotenv file, or None.

    None means no credential was supplied, so the session relies on the persisted
    browser login in the auth volume. A present but unreadable file raises
    ConfigError.
    """
    if not path.is_file():
        return None
    try:
        text = path.read_text()
    except OSError as exc:
        raise ConfigError(f"could not read credentials file {path}: {exc}") from exc

    env = parse_env_file(text)
    for var in accepted_vars:
        value = env.get(var, "")
        if value.strip():
            return Credential(env_var=var, value=value)
    return None
