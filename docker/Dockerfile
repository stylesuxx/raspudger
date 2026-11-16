# Agent container for the raspudger rig.
# Node comes from the official Debian-based Node image, so apt stays available.
# Pin to a digest (node:24-trixie-slim@sha256:...) before release; adjust the
# major to the Node version you want (22+ is required by the Claude Code CLI).
FROM node:24-trixie-slim

ENV DEBIAN_FRONTEND=noninteractive

# Base tooling. apt and pip remain available so the agent can pull more at runtime.
# openssh-client: the rig MCP server shells `ssh` to reach the Pi.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        openssh-client \
        python3 \
        python3-venv \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Python virtualenv on PATH so `pip install` works under Debian's PEP 668 rule.
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

# Analysis toolset the agent uses on the host side: firmware extraction, binary
# reverse engineering, and CVE correlation. openjdk is for Ghidra (below).
RUN apt-get update && apt-get install -y --no-install-recommends \
        binwalk \
        binutils \
        file \
        xxd \
        squashfs-tools \
        p7zip-full \
        unzip \
        cpio \
        zstd \
        lz4 \
        lzop \
        device-tree-compiler \
        sleuthkit \
        foremost \
        liblzo2-dev \
        openjdk-21-jdk-headless \
    && rm -rf /var/lib/apt/lists/*

# Python analysis tools in the venv: CVE correlation and filesystem extractors
# that binwalk hands off to (JFFS2, UBI).
RUN pip install --no-cache-dir cve-bin-tool jefferson ubi_reader

# Ghidra headless (analyzeHeadless on PATH) for decompilation and scripted
# analysis. Pin the release; bump GHIDRA_URL to upgrade.
ARG GHIDRA_URL=https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.2_build/ghidra_12.2_PUBLIC_20261016.zip
RUN curl -fsSL -o /tmp/ghidra.zip "$GHIDRA_URL" \
    && unzip -q /tmp/ghidra.zip -d /opt \
    && mv /opt/ghidra_* /opt/ghidra \
    && rm /tmp/ghidra.zip \
    && ln -s /opt/ghidra/support/analyzeHeadless /usr/local/bin/analyzeHeadless

# Agent CLI.
RUN npm install -g @anthropic-ai/claude-code@latest

# Classic inline renderer, not the fullscreen TUI: it draws in the terminal's
# native scrollback, which survives the container's interactive terminal instead
# of taking it over. Override with CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=0.
ENV CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=1

# Rig MCP server, launched inside the container by the agent over stdio. The
# agent reaches the rig's hardware tools through `rig-mcp-server` on PATH.
COPY pyproject.toml /opt/rig-src/pyproject.toml
COPY rig_mcp /opt/rig-src/rig_mcp
COPY raspudger /opt/rig-src/raspudger
RUN pip install /opt/rig-src

# Rig priming, auto-loaded as CLAUDE.md from a parent of the working directory.
COPY priming/AGENTS.md /rig/CLAUDE.md

RUN mkdir -p /rig/work && chown node:node /rig/work
WORKDIR /rig/work

# Run as the unprivileged node user (uid 1000, matching the host user that owns
# the mounted volumes). Non-root is required for the agent's bypassPermissions
# mode and keeps the container off root.
USER node
