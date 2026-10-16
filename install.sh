#!/bin/sh
set -eu

REPOSITORY_ARCHIVE="https://github.com/mugendi/stumble-radio/archive/refs/heads/master.tar.gz"
UV_INSTALL_COMMAND="curl -LsSf https://astral.sh/uv/install.sh | sh"

fail() {
    printf 'Stumble Radio installer: %s\n' "$1" >&2
    exit 1
}

install_hint() {
    package="$1"
    case "$(uname -s)" in
        Darwin)
            if command -v brew >/dev/null 2>&1; then
                printf '  Install manually: brew install %s\n' "$package"
            else
                printf '  Install Homebrew first (https://brew.sh), then run: brew install %s\n' "$package"
            fi
            ;;
        Linux)
            if command -v apt-get >/dev/null 2>&1; then
                printf '  Debian / Ubuntu: sudo apt install %s\n' "$package"
            elif command -v dnf >/dev/null 2>&1; then
                printf '  Fedora: sudo dnf install %s\n' "$package"
            elif command -v pacman >/dev/null 2>&1; then
                printf '  Arch: sudo pacman -S %s\n' "$package"
            else
                printf '  Install the "%s" package with your Linux distribution package manager.\n' "$package"
            fi
            ;;
        *)
            fail "Stumble Radio supports Linux and macOS. On Windows, use WSL."
            ;;
    esac
}

find_tool() {
    FOUND_TOOL="$(command -v "$1" 2>/dev/null || true)"
    if [ -z "$FOUND_TOOL" ] && [ "$1" = "uv" ]; then
        for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
            if [ -x "$candidate" ]; then
                FOUND_TOOL="$candidate"
                break
            fi
        done
    fi
    [ -n "$FOUND_TOOL" ]
}

wait_for_tool() {
    executable="$1"
    package="$2"
    purpose="$3"
    required="$4"

    if find_tool "$executable"; then
        printf '✓ %s is installed — %s.\n' "$package" "$purpose"
        return
    fi

    while :; do
        printf '\nMissing: %s — %s.\n' "$package" "$purpose"
        if [ "$executable" = "uv" ]; then
            printf '  Install for your user with: %s\n' "$UV_INSTALL_COMMAND"
        else
            install_hint "$package"
        fi
        if [ "$required" = "optional" ]; then
            printf 'Install it and press Enter to check again, or type s to continue without recording: '
        else
            printf 'Install it and press Enter to check again: '
        fi
        IFS= read -r answer </dev/tty || fail "This installer needs an interactive terminal to check prerequisites."
        if [ "$required" = "optional" ] && [ "$answer" = "s" ]; then
            printf 'Skipping %s. Recording will not be available.\n' "$package"
            return
        fi
        if find_tool "$executable"; then
            printf '✓ %s is installed — %s.\n' "$package" "$purpose"
            return
        fi
    done
}

case "$(uname -s)" in
    Linux|Darwin) ;;
    *) fail "Stumble Radio supports Linux and macOS. On Windows, use WSL." ;;
esac

wait_for_tool curl curl "downloads the Stumble Radio source archive" required
wait_for_tool tar tar "unpacks the source archive for installation" required
wait_for_tool mpv mpv "plays radio stations" required
wait_for_tool ffmpeg ffmpeg "records radio streams" optional
wait_for_tool uv uv "installs Stumble Radio and manages its isolated Python runtime" required

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' 0
curl -fsSL "$REPOSITORY_ARCHIVE" -o "$TMP_DIR/stumble-radio.tar.gz"
tar -xzf "$TMP_DIR/stumble-radio.tar.gz" -C "$TMP_DIR"
UV_BIN="$FOUND_TOOL"
"$UV_BIN" tool install --upgrade --python 3.11 "$TMP_DIR/stumble-radio-master"
"$UV_BIN" tool update-shell

TOOL_BIN=$("$UV_BIN" tool dir --bin)
PATH="$TOOL_BIN:$PATH"
export PATH
command -v stumble-radio >/dev/null 2>&1 || fail "Installation completed. Open a new terminal and run stumble-radio."
stumble-radio --version
printf '\nInstalled in your user environment. Start the app with: stumble-radio\n'
