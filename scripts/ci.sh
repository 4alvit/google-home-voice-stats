#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mode="${1:-all}"
case "$mode" in syntax|unit|config|all) ;; *) echo 'Usage: scripts/ci.sh [syntax|unit|config|all]' >&2; exit 2 ;; esac
if [[ "$mode" == syntax || "$mode" == all ]]; then
  python3 scripts/validate-source.py
fi
if [[ "$mode" == unit || "$mode" == all ]]; then
  python3 -m unittest discover -s tests -v
fi
if [[ "$mode" == config || "$mode" == all ]]; then
  command -v docker >/dev/null || { echo 'Docker is required for HA configuration validation.' >&2; exit 2; }
  stage=$(mktemp -d)
  trap 'rm -rf "$stage"' EXIT
  for adapter in tts cast; do
    for reports in default flow; do
      flow_args=()
      if [[ "$reports" == flow ]]; then flow_args=(--include-flow); fi
      python3 tests/make_ha_fixture.py --adapter "$adapter" "${flow_args[@]}" "$stage/$adapter-$reports-check"
      docker run --rm --entrypoint python \
        -v "$stage/$adapter-$reports-check:/config" \
        ghcr.io/home-assistant/home-assistant:2026.9.2 \
        -m homeassistant --script check_config --config /config
    done
  done
fi
