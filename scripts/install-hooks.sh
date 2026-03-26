#!/bin/sh
# Install project git hooks into .git/hooks/.
# Run once after cloning: sh scripts/install-hooks.sh
set -e
REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
SRC="$REPO_ROOT/scripts/hooks"
DST="$REPO_ROOT/.git/hooks"
for hook in "$SRC"/*; do
  name="$(basename "$hook")"
  cp "$hook" "$DST/$name"
  chmod +x "$DST/$name"
  echo "Installed: $name"
done
echo "Hooks installed."
