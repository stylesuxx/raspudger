"""Errors raised by the model egress proxy."""

from __future__ import annotations


class ProxyConfigError(Exception):
    """The proxy's environment configuration is missing or invalid."""
