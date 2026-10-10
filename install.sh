#!/bin/sh
# Bootstrap the versioned release installer. uv manages Python and dependencies.
# SECRETARY_DIR defaults to ./secretary; SECRETARY_VERSION defaults to latest.
set -eu
command -v curl >/dev/null 2>&1 || { printf 'curl is required\n' >&2; exit 1; }
if ! command -v uv >/dev/null 2>&1; then
    printf 'Installing uv from https://astral.sh/uv\n'
    curl -LsSf https://astral.sh/uv/install.sh | sh
    PATH="$HOME/.local/bin:$PATH"
    export PATH
fi
BOOTSTRAP=$(mktemp -d)
trap 'rm -rf "$BOOTSTRAP"' EXIT HUP INT TERM
curl -LsSf https://raw.githubusercontent.com/anttihil/secretary/main/updater.py -o "$BOOTSTRAP/updater.py"
exec_status=0
uv run --no-project --python 3.13 python "$BOOTSTRAP/updater.py" \
    --install --root "${SECRETARY_DIR:-./secretary}" "${SECRETARY_VERSION:-latest}" || exec_status=$?
exit "$exec_status"
