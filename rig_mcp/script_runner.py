"""Shipped bench scripts the agent runs on the Pi by name.

Each file under ``rig_mcp/scripts`` is a reviewed command that the ``run_script``
tool exposes as a guarded alternative to raw ``pi_exec``: the agent names a
script instead of pasting shell, and the catalog is version-controlled and
auditable. Scripts run on the Pi over the exec seam, so the body is loaded as
text and sent over SSH rather than installed on the Pi. Positional arguments
bind to ``$1``..``$n`` through a quoted ``set --`` prefix, so an argument is data
to the script and can never inject shell.

Loading, name validation, and command assembly are pure functions over the
catalog, so tests drive them directly; running a script is the only part that
touches the transport, faked at the seam like the other rig tools.
"""

from __future__ import annotations

import shlex
from importlib import resources
from importlib.resources.abc import Traversable

from .paths import is_safe_path_segment

SCRIPT_SUFFIX: str = ".sh"


class ScriptNotFoundError(ValueError):
    """The named script is not in the shipped catalog."""


def _scripts_root() -> Traversable:
    return resources.files("rig_mcp.scripts")


def canonical_name(name: str) -> str:
    """The catalog name with any ``.sh`` suffix removed and the name validated.

    A name that carries a path separator or a leading dot is rejected, so a
    lookup stays inside the shipped catalog.
    """
    base: str = name[: -len(SCRIPT_SUFFIX)] if name.endswith(SCRIPT_SUFFIX) else name
    if not is_safe_path_segment(base):
        raise ScriptNotFoundError(f"invalid script name: {name!r}")

    return base


def available_scripts() -> list[str]:
    return sorted(
        entry.name[: -len(SCRIPT_SUFFIX)]
        for entry in _scripts_root().iterdir()
        if entry.name.endswith(SCRIPT_SUFFIX)
    )


def load_script(name: str) -> str:
    base: str = canonical_name(name)
    resource: Traversable = _scripts_root().joinpath(base + SCRIPT_SUFFIX)
    if not resource.is_file():
        raise ScriptNotFoundError(f"unknown script: {base!r}")

    return resource.read_text(encoding="utf-8")


def build_command(body: str, args: list[str]) -> str:
    """The command to run on the Pi: the script body with its args bound safely.

    Each argument is shell-quoted into a ``set --`` prefix so the script sees it
    as a positional parameter and never as shell syntax.
    """
    if not args:
        return body

    prefix: str = "set -- " + " ".join(shlex.quote(argument) for argument in args)
    return prefix + "\n" + body
