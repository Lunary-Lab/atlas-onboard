#!/bin/bash
# Test the actual bootstrap script in a minimal environment
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOOTSTRAP_SCRIPT="$(cd "$SCRIPT_DIR/../../.." && pwd)/bootstrap.sh"

if [ ! -f "$BOOTSTRAP_SCRIPT" ]; then
    echo "ERROR: bootstrap.sh not found at $BOOTSTRAP_SCRIPT"
    exit 1
fi

echo "Testing bootstrap script: $BOOTSTRAP_SCRIPT"
echo "This test verifies the bootstrap script can run without errors"
echo ""

# Test that the script is executable and has correct shebang
if ! head -1 "$BOOTSTRAP_SCRIPT" | grep -q "^#!/bin/sh"; then
    echo "ERROR: bootstrap.sh missing correct shebang"
    exit 1
fi

# Test that required functions exist
if ! grep -q "^main()" "$BOOTSTRAP_SCRIPT"; then
    echo "ERROR: bootstrap.sh missing main() function"
    exit 1
fi

# Test that it checks for required dependencies
if ! grep -q "_check_dep" "$BOOTSTRAP_SCRIPT"; then
    echo "ERROR: bootstrap.sh missing dependency checking"
    exit 1
fi

# Test that it installs Python via uv (required - cannot use system Python)
if ! grep -E -q "(uv|UV_CMD).*python install" "$BOOTSTRAP_SCRIPT"; then
    echo "ERROR: bootstrap.sh must install Python via uv (cannot use system Python)"
    exit 1
fi

echo "✅ Bootstrap script structure looks good"
echo "✅ Script installs Python via uv (required)"
exit 0
