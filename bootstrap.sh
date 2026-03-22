#!/bin/sh
#
# Atlas Bootstrap - POSIX Entrypoint Stub
#
# sh -c "$(curl -fsSL https://.../bootstrap.sh)"
#
set -euf

# --- Configuration ---
APP_VERSION="0.1.26"
PAYLOAD_URL="https://github.com/Lunary-Lab/atlas-onboard/releases/download/v0.1.28/payload.tar.gz"
PAYLOAD_SHA256="7c8aaf68707d86f41d55968416af9810867df9bbb62e9910863b3e60360637a1"
# ---

_info() {
    printf "atlas-onboard: %s\\n" "$@" >&2
}

_warn() {
    printf "atlas-onboard: WARNING: %s\\n" "$@" >&2
}

_err() {
    printf "atlas-onboard: ERROR: %s\\n" "$@" >&2
    exit 1
}

_check_dep() {
    command -v "$1" >/dev/null 2>&1 || _err "'$1' is required but not found in PATH."
}

_get_sha256_cmd() {
    if command -v "sha256sum" >/dev/null 2>&1; then
        echo "sha256sum"
    elif command -v "shasum" >/dev/null 2>&1; then
        echo "shasum -a 256"
    else
        _err "Could not find 'sha256sum' or 'shasum' for checksum verification."
    fi
}

_add_bin_to_path() {
    # Only add to PATH if dotfiles are not configured (dotfiles will handle PATH)
    XDG_CONFIG_HOME=${XDG_CONFIG_HOME:-"$HOME/.config"}
    CONFIG_FILE="$XDG_CONFIG_HOME/atlas/bootstrap.yaml"
    
    # Check if dotfiles_repo is configured (not null or empty)
    if [ -f "$CONFIG_FILE" ]; then
        # Check if dotfiles_repo exists and has a non-null, non-empty value
        # YAML format: dotfiles_repo: "value" or dotfiles_repo: value (not null or empty string)
        if grep -q "^[[:space:]]*dotfiles_repo:" "$CONFIG_FILE" 2>/dev/null; then
            # Extract the value after the colon
            set +e
            DOTFILES_REPO=$(grep "^[[:space:]]*dotfiles_repo:" "$CONFIG_FILE" | sed 's/.*dotfiles_repo:[[:space:]]*//' | sed 's/^"//' | sed 's/"$//' | sed "s/^'//" | sed "s/'$//")
            DOTFILES_EXTRACT_EXIT=$?
            set -e
            if [ $DOTFILES_EXTRACT_EXIT -ne 0 ]; then
                DOTFILES_REPO=""
            fi
            
            # Validate extracted value (prevent command injection)
            # Check for dangerous characters that could be used in command injection
            if echo "$DOTFILES_REPO" | grep -qE '[;&|`$(){}]'; then
                _err "Invalid characters in dotfiles_repo value. Potential security risk."
            fi
            
            # Check if it's not null, not empty, and not just whitespace
            if [ -n "$DOTFILES_REPO" ] && [ "$DOTFILES_REPO" != "null" ] && [ "$DOTFILES_REPO" != "~" ]; then
                _info "Dotfiles repository configured - skipping PATH modification (dotfiles will handle it)"
                return 0
            fi
        fi
    fi
    
    # Determine bin directory
    XDG_DATA_HOME=${XDG_DATA_HOME:-"$HOME/.local/share"}
    BIN_DIR="$XDG_DATA_HOME/atlas/bin"
    
    # Validate bin directory path to prevent path traversal
    EXPECTED_BIN_DIR="$XDG_DATA_HOME/atlas/bin"
    set +e
    BIN_DIR_RESOLVED=$(cd "$BIN_DIR" 2>/dev/null && pwd)
    BIN_DIR_CD_EXIT=$?
    EXPECTED_RESOLVED=$(cd "$EXPECTED_BIN_DIR" 2>/dev/null && pwd)
    EXPECTED_CD_EXIT=$?
    set -e
    if [ $BIN_DIR_CD_EXIT -ne 0 ]; then
        BIN_DIR_RESOLVED=""
    fi
    if [ $EXPECTED_CD_EXIT -ne 0 ]; then
        EXPECTED_RESOLVED=""
    fi
    
    if [ -n "$BIN_DIR_RESOLVED" ] && [ -n "$EXPECTED_RESOLVED" ] && [ "$BIN_DIR_RESOLVED" != "$EXPECTED_RESOLVED" ]; then
        _err "Invalid bin directory path: $BIN_DIR (resolved to $BIN_DIR_RESOLVED, expected $EXPECTED_RESOLVED)"
    fi
    
    mkdir -p "$BIN_DIR"
    
    # Detect shell and add to appropriate profile
    SHELL_NAME=$(basename "$SHELL" 2>/dev/null || echo "bash")
    PROFILE_FILE=""
    
    case "$SHELL_NAME" in
        bash)
            if [ -f "$HOME/.bashrc" ]; then
                PROFILE_FILE="$HOME/.bashrc"
            elif [ -f "$HOME/.bash_profile" ]; then
                PROFILE_FILE="$HOME/.bash_profile"
            fi
            ;;
        zsh)
            if [ -f "$HOME/.zshrc" ]; then
                PROFILE_FILE="$HOME/.zshrc"
            else
                # Create .zshrc if it doesn't exist on macOS (zsh is default shell)
                if [ "$(uname)" = "Darwin" ]; then
                    touch "$HOME/.zshrc"
                    PROFILE_FILE="$HOME/.zshrc"
                fi
            fi
            ;;
        fish)
            if [ -d "$HOME/.config/fish" ]; then
                PROFILE_FILE="$HOME/.config/fish/config.fish"
            fi
            ;;
    esac
    
    if [ -z "$PROFILE_FILE" ]; then
        # Fallback to .profile
        PROFILE_FILE="$HOME/.profile"
    fi
    
    # Check if already in PATH
    if grep -q "$BIN_DIR" "$PROFILE_FILE" 2>/dev/null; then
        _info "Atlas bin directory already in PATH"
        return 0
    fi
    
    # Validate BIN_DIR one more time before writing
    if [ ! -d "$BIN_DIR" ]; then
        _err "Bin directory does not exist: $BIN_DIR"
    fi
    
    # Ensure BIN_DIR is within expected XDG directory (prevent path traversal)
    if ! echo "$BIN_DIR" | grep -q "^$XDG_DATA_HOME/atlas/bin"; then
        _err "Bin directory path validation failed: $BIN_DIR (must be within $XDG_DATA_HOME/atlas/bin)"
    fi
    
    # Add to PATH
    _info "Adding Atlas bin directory to PATH in $PROFILE_FILE..."
    {
        echo ""
        echo "# Atlas bin directory (added by bootstrap.sh)"
        # Escape the path properly to prevent injection
        ESCAPED_BIN_DIR=$(printf '%s\n' "$BIN_DIR" | sed 's/[[\.*^$()+?{|]/\\&/g')
        echo "export PATH=\"\$PATH:$ESCAPED_BIN_DIR\""
    } >> "$PROFILE_FILE"
    
    _info "✅ Added $BIN_DIR to PATH in $PROFILE_FILE"
    _info "Note: You may need to restart your shell or run: source $PROFILE_FILE"
}

main() {
    _check_dep "curl"
    _check_dep "tar"

    SHA256_CMD=$(_get_sha256_cmd)

    XDG_CACHE_HOME=${XDG_CACHE_HOME:-"$HOME/.cache"}
    APP_CACHE_DIR="$XDG_CACHE_HOME/atlas/bootstrap/$APP_VERSION"
    mkdir -p "$APP_CACHE_DIR"

    TMP_DIR=$(mktemp -d 2>/dev/null || mktemp -d -t 'sb-bootstrap')
    PAYLOAD_PATH="$TMP_DIR/payload.tar.gz"

    _info "Downloading payload from $PAYLOAD_URL..."
    curl -fsSL --retry 3 -o "$PAYLOAD_PATH" "$PAYLOAD_URL"

    _info "Verifying payload checksum..."
    CHECKSUM=$($SHA256_CMD "$PAYLOAD_PATH" | cut -d' ' -f1)
    if [ "$CHECKSUM" != "$PAYLOAD_SHA256" ]; then
        _err "Checksum mismatch! Aborting."
    fi

    _info "Extracting payload to $APP_CACHE_DIR..."
    tar -xzf "$PAYLOAD_PATH" -C "$APP_CACHE_DIR"

    cd "$APP_CACHE_DIR"

    # Check for existing uv installation (common locations)
    UV_CMD=""
    for uv_path in \
        "$HOME/.local/bin/uv" \
        "$HOME/.cargo/bin/uv" \
        "/usr/local/bin/uv" \
        "/opt/homebrew/bin/uv"; do
        if [ -x "$uv_path" ]; then
            UV_CMD="$uv_path"
            _info "Found existing uv at $uv_path"
            export PATH="$(dirname "$uv_path"):$PATH"
            break
        fi
    done
    
    # If not found, check PATH
    if [ -z "$UV_CMD" ] && command -v "uv" >/dev/null 2>&1; then
        UV_CMD="uv"
        _info "Found uv in PATH"
    fi
    
    # Install uv if not found
    if [ -z "$UV_CMD" ]; then
        _info "Installing 'uv'..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        # Add cargo bin to PATH if it exists (uv installer places uv in ~/.cargo/bin)
        if [ -d "$HOME/.cargo/bin" ]; then
            export PATH="$HOME/.cargo/bin:$PATH"
        fi
        # Also check ~/.local/bin (newer uv installers)
        if [ -d "$HOME/.local/bin" ]; then
            export PATH="$HOME/.local/bin:$PATH"
        fi
        # Source cargo env if it exists (uv installer may add uv to PATH directly)
        if [ -f "$HOME/.cargo/env" ]; then
            . "$HOME/.cargo/env"
        fi
        # Verify uv is now available
        if ! command -v "uv" >/dev/null 2>&1; then
            _err "uv installation failed. Please install uv manually: https://github.com/astral-sh/uv"
        fi
        UV_CMD="uv"
    fi

    # Install Python 3.11 via uv (required - cannot use system Python)
    _info "Installing Python 3.11 via uv..."
    
    # Check if Python 3.11 is already installed via uv
    # Temporarily disable exit on error for this check
    set +e
    # Use --native-tls for network operations on macOS to handle corporate proxies
    PYTHON_CHECK_OUTPUT="$("$UV_CMD" python list 3.11 --installed 2>&1)"
    PYTHON_CHECK_EXIT=$?
    set -e
    
    if [ $PYTHON_CHECK_EXIT -eq 0 ] && echo "$PYTHON_CHECK_OUTPUT" | grep -q "3.11"; then
        _info "Python 3.11 already installed via uv"
        PYTHON_SPEC="3.11"
    else
        # Try to install Python 3.11 via uv
        # On macOS with corporate proxies, uv may fail due to SSL certificate issues
        # uv uses rustls which may not use the macOS system certificate store
        _info "Downloading Python 3.11 (this may take a moment)..."
        
        # Try to install Python via uv with native-tls
        # Temporarily disable exit on error to capture the error
        set +e
        UV_OUTPUT="$("$UV_CMD" python install 3.11 --native-tls 2>&1)"
        UV_EXIT=$?
        set -e
        
        if [ $UV_EXIT -eq 0 ]; then
            PYTHON_SPEC="3.11"
            _info "Python 3.11 installed successfully"
        else
            _err "Failed to install Python 3.11 via uv: $UV_OUTPUT"
        fi
    fi
    
    _info "Creating Python virtual environment with Python $PYTHON_SPEC..."
    
    # Try to create venv - use --native-tls to work around SSL certificate issues with corporate proxies
    # Temporarily disable exit on error to capture the error
    set +e
    VENV_OUTPUT="$("$UV_CMD" venv --python "$PYTHON_SPEC" --native-tls 2>&1)"
    VENV_EXIT=$?
    set -e
    
    # Debug: show what happened
    if [ $VENV_EXIT -ne 0 ]; then
        _warn "uv venv command failed with exit code $VENV_EXIT"
        _warn "Output: $VENV_OUTPUT"
    fi
    
    if [ $VENV_EXIT -ne 0 ]; then
        # Check if it's an SSL certificate error
        if echo "$VENV_OUTPUT" | grep -qi "certificate\|SSL\|TLS\|peer certificate"; then
            _warn "uv venv failed due to SSL certificate issues when verifying Python 3.11"
            _warn "Attempting to use Python 3.11 directly from uv cache..."
            
            # Find Python 3.11 in uv's cache
            UV_PYTHON_BASE="$HOME/.local/share/uv/python"
            PYTHON_PATH=""
            if [ -d "$UV_PYTHON_BASE" ]; then
                # Find Python 3.11 executable
                PYTHON_PATH=$(find "$UV_PYTHON_BASE" -name "python3.11" -type f -executable 2>/dev/null | head -1)
                if [ -z "$PYTHON_PATH" ]; then
                    # Try to find in a 3.11 directory
                    PYTHON_DIR=$(find "$UV_PYTHON_BASE" -type d -name "*3.11*" 2>/dev/null | head -1)
                    if [ -n "$PYTHON_DIR" ]; then
                        for py_name in "python3.11" "python3" "python"; do
                            if [ -x "$PYTHON_DIR/$py_name" ]; then
                                PYTHON_PATH="$PYTHON_DIR/$py_name"
                                break
                            fi
                        done
                    fi
                fi
            fi
            
            if [ -n "$PYTHON_PATH" ] && [ -x "$PYTHON_PATH" ]; then
                _info "Using Python directly from cache: $PYTHON_PATH"
                "$UV_CMD" venv --python "$PYTHON_PATH" --native-tls || _err "Failed to create virtual environment with Python from cache"
            else
                _err "Failed to create virtual environment. Python 3.11 is installed but cannot be accessed due to SSL certificate issues."
            fi
        else
            _err "Failed to create virtual environment: $VENV_OUTPUT"
        fi
    fi

    _info "Installing dependencies..."
    "$UV_CMD" pip sync requirements.lock --native-tls || _err "Failed to install dependencies"

    _info "Installing atlasonboard package..."
    "$UV_CMD" pip install -e . --native-tls || _err "Failed to install atlasonboard package"
    
    # Verify PyNaCl is properly installed and can import crypto_aead functions
    _info "Verifying PyNaCl installation..."
    set +e
    NACL_CHECK="$(".venv/bin/python" -c "from nacl.bindings import crypto_aead_xchacha20poly1305_ietf_encrypt, crypto_aead_xchacha20poly1305_ietf_decrypt; print('OK')" 2>&1)"
    NACL_CHECK_EXIT=$?
    set -e
    if [ $NACL_CHECK_EXIT -ne 0 ]; then
        _warn "PyNaCl import check failed, attempting to reinstall..."
        set +e
        "$UV_CMD" pip install --force-reinstall --no-cache 'PyNaCl>=1.5.0' --native-tls 2>&1
        NACL_INSTALL_EXIT=$?
        set -e
        
        if [ $NACL_INSTALL_EXIT -eq 0 ]; then
            # Verify installation works
            set +e
            NACL_CHECK="$(".venv/bin/python" -c "from nacl.bindings import crypto_aead_xchacha20poly1305_ietf_encrypt, crypto_aead_xchacha20poly1305_ietf_decrypt; print('OK')" 2>&1)"
            NACL_CHECK_EXIT=$?
            set -e
            if [ $NACL_CHECK_EXIT -eq 0 ]; then
                _info "PyNaCl installed and verified successfully"
            fi
        fi
        
        # Final check - if still failing, show debug info
        if [ $NACL_CHECK_EXIT -ne 0 ]; then
            _warn "PyNaCl debug info:"
            ".venv/bin/python" -c "import nacl; print(f'Version: {nacl.__version__}')" 2>&1 || true
            ".venv/bin/python" -c "import nacl.bindings; print(f'Available: {[x for x in dir(nacl.bindings) if \"xchacha20\" in x.lower()]}')" 2>&1 || true
            _err "PyNaCl installation is broken. XChaCha20Poly1305 functions not available. Error: $NACL_CHECK"
        fi
    fi

    # Ensure XDG directories exist
    XDG_DATA_HOME=${XDG_DATA_HOME:-"$HOME/.local/share"}
    XDG_CONFIG_HOME=${XDG_CONFIG_HOME:-"$HOME/.config"}
    XDG_CACHE_HOME=${XDG_CACHE_HOME:-"$HOME/.cache"}
    XDG_STATE_HOME=${XDG_STATE_HOME:-"$HOME/.local/state"}
    mkdir -p "$XDG_DATA_HOME" "$XDG_CONFIG_HOME" "$XDG_CACHE_HOME" "$XDG_STATE_HOME"

    # Add bin directory to PATH if dotfiles are not configured
    _add_bin_to_path

    _info "Starting Atlas Bootstrap application..."
    # Environment variables are automatically inherited by Python subprocess
    .venv/bin/python -m atlasonboard.cli run "$@"

    _info "Cleaning up..."
    rm -rf "$TMP_DIR"

    _info "Done."
}

main "$@"
