#!/usr/bin/env bash
# Build and start the dev-sim Pi container. Ensures the dedicated SSH key exists
# and injects its public half into the image, then runs docker compose. Extra
# args pass through (e.g. `-d` to detach, `--build` is always applied).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/.." && pwd)"
cd "$repo"

key="data/pi-sim/id_ed25519"
mkdir -p data/pi-sim
[ -f "$key" ] || ssh-keygen -t ed25519 -N '' -f "$key" -C rig@pi-sim >/dev/null

RIG_PUBKEY="$(cat "$key.pub")" exec docker compose up --build "$@"
