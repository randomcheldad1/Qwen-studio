#!/bin/sh
set -eu
APP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -x "$APP_DIR/.venv/bin/python" ]; then
  exec "$APP_DIR/.venv/bin/python" "$APP_DIR/qwen_studio.py" "$@"
fi
exec python3 "$APP_DIR/qwen_studio.py" "$@"
