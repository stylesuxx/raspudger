"""Model egress proxy: holds the Anthropic API key so the agent never does.

The agent container points ``ANTHROPIC_BASE_URL`` at this proxy and carries only
a placeholder credential. The proxy strips the inbound auth, injects the real
``x-api-key``, and forwards to the upstream Anthropic API, so the paid key lives
only here.
"""
