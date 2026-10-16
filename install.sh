#!/bin/sh
set -eu

REPOSITORY="https://github.com/mugendi/stumble-radio.git"
UV_INSTALLER="https://astral.sh/uv/install.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' 0

fail() {
    printf 'Stumble Radio installer: %s\n' "$1" >&2
    exit 1
}

as_root() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        fail "sudo is required to install system audio dependencies."
    fi
}

install_system_dependencies() {
    case "$(uname -s)" in
        Darwin)
            command -v brew >/dev/null 2>&1 || fail "Install Homebrew first: https://brew.sh"
            brew install mpv ffmpeg git
            ;;
        Linux)
            if command -v apt-get >/dev/null 2>&1; then
                as_root apt-get update
                as_root apt-get install -y mpv ffmpeg git
            elif command -v dnf >/dev/null 2>&1; then
                as_root dnf install -y mpv ffmpeg git
            elif command -v pacman >/dev/null 2>&1; then
                as_root pacman -S --needed --noconfirm mpv ffmpeg git
            else
                fail "Supported Linux package managers: apt, dnf, and pacman. Install mpv, FFmpeg, and git, then retry."
            fi
            ;;
        *)
            fail "Stumble Radio supports Linux and macOS. On Windows, use WSL."
            ;;
    esac
}

install_system_dependencies

if ! command -v uv >/dev/null 2>&1; then
    mkdir -p "$HOME/.local/bin"
    curl -fsSL "$UV_INSTALLER" -o "$TMP_DIR/uv-install.sh"
    env UV_INSTALL_DIR="$HOME/.local/bin" sh "$TMP_DIR/uv-install.sh"
    PATH="$HOME/.local/bin:$PATH"
    export PATH
fi

if command -v uv >/dev/null 2>&1; then
    UV="$(command -v uv)"
elif [ -x "$HOME/.local/bin/uv" ]; then
    UV="$HOME/.local/bin/uv"
else
    fail "uv installation did not produce a usable command."
fi

"$UV" tool install --upgrade --python 3.11 "git+$REPOSITORY"
"$UV" tool update-shell
TOOL_BIN="$("$UV" tool dir --bin)"
PATH="$TOOL_BIN:$PATH"
export PATH

command -v stumble-radio >/dev/null 2>&1 || fail "Installation completed, but stumble-radio is not on PATH yet. Open a new terminal and run it there."
stumble-radio --version
printf '\nInstalled. Start the app with: stumble-radio\n'
