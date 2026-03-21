#!/usr/bin/env bash
# DEPRECATED — use bootstrap.sh instead
echo "⚠  setup.sh is deprecated. Running bootstrap.sh..."
exec bash "$(dirname "$0")/bootstrap.sh" "$@"
