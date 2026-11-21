#!/usr/bin/env bash
# Downloads the shared Claude client into scripts/ai/ (gitignored). Used by CI and local dev.
set -euo pipefail
base="https://raw.githubusercontent.com/Lascade-Co/actions/main/scripts/ai"
dir="$(cd "$(dirname "$0")" && pwd)/ai"
mkdir -p "$dir"
for f in claude_api.py requirements.txt; do
  curl -fsSL --retry 3 -o "$dir/$f" "$base/$f"
done
