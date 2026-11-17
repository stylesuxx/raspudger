"""The rule for a name that is allowed to index a filesystem path.

One home for the "cannot escape its directory" invariant: a capture filename and
a script name both pass through here, so a hole fixed once is fixed for both.
"""

from __future__ import annotations


def is_safe_path_segment(name: str) -> bool:
    """Whether ``name`` is a single path segment that stays inside its directory.

    False when the name is empty, starts with a dot, or contains a path separator
    or a NUL byte, so a name used to build a path cannot traverse out of the
    directory it is joined to.
    """
    return (
        bool(name)
        and not name.startswith(".")
        and "/" not in name
        and "\\" not in name
        and "\0" not in name
    )
