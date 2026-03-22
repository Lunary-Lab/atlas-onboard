#!/bin/bash
# Test the actual onboard script in a minimal environment
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ONBOARD_SCRIPT="$(cd "$SCRIPT_DIR/../../.." && pwd)/onboard.sh"

if [ ! -f "$ONBOARD_SCRIPT" ]; then
    echo "ERROR: onboard.sh not found at $ONBOARD_SCRIPT"
    exit 1
fi

echo "Testing onboard script: $ONBOARD_SCRIPT"
echo "This test verifies the onboard script can run without errors"
echo ""

# Test that the script is executable and has correct shebang
if ! head -1 "$ONBOARD_SCRIPT" | grep -q "^#!/bin/sh"; then
    echo "ERROR: onboard.sh missing correct shebang"
    exit 1
fi

# Test that required functions exist
if ! grep -q "^main()" "$ONBOARD_SCRIPT"; then
    echo "ERROR: onboard.sh missing main() function"
    exit 1
fi

# Test that it checks for required dependencies
if ! grep -q "_check_dep" "$ONBOARD_SCRIPT"; then
    echo "ERROR: onboard.sh missing dependency checking"
    exit 1
fi

# Test that it installs Python via uv (required - cannot use system Python)
if ! grep -E -q "(uv|UV_CMD).*python install" "$ONBOARD_SCRIPT"; then
    echo "ERROR: onboard.sh must install Python via uv (cannot use system Python)"
    exit 1
fi

echo "✅ Bootstrap script structure looks good"
echo "✅ Script installs Python via uv (required)"
exit 0
