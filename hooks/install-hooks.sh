#!/usr/bin/env bash
# Run once after cloning to wire up all repo hooks.
set -euo pipefail
HOOK_DIR="$(git rev-parse --git-dir)/hooks"
mkdir -p "$HOOK_DIR"
for hook in hooks/*; do
  [[ "$hook" == hooks/install-hooks.sh ]] && continue
  [[ -f "$hook" ]] || continue
  name="$(basename "$hook")"
  ln -sf "../../$hook" "$HOOK_DIR/$name"
  chmod +x "$HOOK_DIR/$name"
  echo "installed: $HOOK_DIR/$name → $hook"
done
echo "All hooks installed."
