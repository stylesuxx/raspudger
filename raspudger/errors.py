"""Exception types raised by the wrapper's pure core."""

from __future__ import annotations


class ReToolingError(Exception):
    """Base class for errors the wrapper reports to the operator."""


class ConfigError(ReToolingError):
    """The secrets or configuration file is missing or malformed."""


class UsageError(ReToolingError):
    """The invocation refers to a path or value that does not hold."""


class AdapterError(ReToolingError):
    """The requested agent has no known adapter."""
