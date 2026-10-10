#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec uv run --no-project --python 3.13 python "$ROOT/updater.py" --root "$ROOT" "$@"
