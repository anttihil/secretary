#!/bin/sh
# One-command installer for Secretary.
#
#   curl -LsSf https://raw.githubusercontent.com/anttihil/secretary/main/install.sh | sh
#
# Downloads a release tarball that already contains the built frontend, so
# neither Node.js nor a C compiler is needed — only uv, which this script
# installs for you if it is missing.
#
# Environment overrides:
#   SECRETARY_DIR      install location (default: ./secretary)
#   SECRETARY_VERSION  release tag to install (default: latest)
set -eu

REPO="anttihil/secretary"
TARGET="${SECRETARY_DIR:-./secretary}"
MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf"
MODEL_NAME="qwen2.5-3b-instruct-q4_k_m.gguf"

say() { printf '\n==> %s\n' "$1"; }
die() { printf 'error: %s\n' "$1" >&2; exit 1; }

# When piped from curl, stdin is the script itself, so prompts must go to the
# terminal. /dev/tty can exist yet fail to open when there is no controlling
# terminal, so probe by opening it in a subshell (a failed redirect on the
# special builtin `:` would abort the whole script in dash).
if (exec 3>/dev/tty) 2>/dev/null; then
    HAVE_TTY=1
else
    HAVE_TTY=0
fi

confirm() { # confirm "question" -> 0 for yes
    [ "$HAVE_TTY" = 1 ] || return 1
    printf '%s [Y/n] ' "$1" > /dev/tty
    read -r reply < /dev/tty || reply=n
    case "$reply" in [Nn]*) return 1 ;; *) return 0 ;; esac
}

command -v curl >/dev/null 2>&1 || die "curl is required."
command -v tar  >/dev/null 2>&1 || die "tar is required."

say "Checking for uv"
if command -v uv >/dev/null 2>&1; then
    uv --version
else
    echo "uv is not installed. It manages Python and the dependencies for you."
    if confirm "Install uv from https://astral.sh/uv now?"; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
        # The installer drops uv in ~/.local/bin, which may not be on PATH yet.
        [ -x "$HOME/.local/bin/uv" ] && PATH="$HOME/.local/bin:$PATH" && export PATH
        command -v uv >/dev/null 2>&1 || die "uv installed but not on PATH. Open a new shell and re-run."
    else
        die "uv is required. See https://docs.astral.sh/uv/getting-started/installation/"
    fi
fi

say "Finding a release"
if [ -n "${SECRETARY_VERSION:-}" ]; then
    api="https://api.github.com/repos/$REPO/releases/tags/$SECRETARY_VERSION"
else
    api="https://api.github.com/repos/$REPO/releases/latest"
fi
tarball_url=$(curl -fsSL "$api" 2>/dev/null | grep -oE 'https://[^"]*secretary-[^"]*\.tar\.gz' | head -n 1 || true)
[ -n "$tarball_url" ] || die "No release tarball found for $REPO. Install from source instead:
  git clone https://github.com/$REPO.git && cd secretary && ./setup.sh"
echo "$tarball_url"

say "Installing to $TARGET"
[ -e "$TARGET" ] && die "$TARGET already exists. Remove it or set SECRETARY_DIR."
mkdir -p "$TARGET"
curl -fsSL "$tarball_url" | tar -xz -C "$TARGET" --strip-components=1
cd "$TARGET"
TARGET=$(pwd)

say "Installing dependencies"
uv sync --frozen --no-dev

say "Fetching a language model"
model=""
if confirm "Download Qwen2.5-3B-Instruct (~2 GB)?"; then
    curl -fL "$MODEL_URL" --create-dirs -o "./models/$MODEL_NAME"
    model="./models/$MODEL_NAME"
else
    echo "Skipped. Set LLM_MODEL_PATH in .env to a GGUF model of your choice."
    echo "  curl -L $MODEL_URL --create-dirs -o ./models/$MODEL_NAME"
fi

say "Writing .env"
cp .env.example .env
if [ -n "$model" ]; then
    sed -i.bak "s|^LLM_MODEL_PATH=.*|LLM_MODEL_PATH=$model|" .env && rm -f .env.bak
    echo "LLM_MODEL_PATH=$model"
fi

say "Done."
echo "Start Secretary with:"
echo "  cd $TARGET && uv run fastapi run main.py --port 8000"
echo
echo "Then open http://localhost:8000"
[ -n "$model" ] || echo "Set LLM_MODEL_PATH in $TARGET/.env first."
