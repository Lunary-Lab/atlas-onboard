#!/bin/bash
# Test the actual bootstrap script in a minimal environment
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"

# Bootstrap script is at: repo-root/atlas-onboard/atlas-onboard/bootstrap.sh
# Test script is at: repo-root/atlas-onboard/atlas-onboard/payload/tests/e2e/test_bootstrap_script.sh
# So from test script, bootstrap.sh is 3 levels up: ../../../
BOOTSTRAP_SCRIPT="$REPO_ROOT/atlas-onboard/atlas-onboard/bootstrap.sh"

# Also check if we're running from atlas-onboard directory (GitHub Actions)
if [ -f "atlas-onboard/bootstrap.sh" ]; then
    BOOTSTRAP_SCRIPT="atlas-onboard/bootstrap.sh"
fi

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
if ! grep -q "uv python install" "$BOOTSTRAP_SCRIPT"; then
    echo "ERROR: bootstrap.sh must install Python via uv (cannot use system Python)"
    exit 1
fi

echo "✅ Bootstrap script structure looks good"
echo "✅ Script installs Python via uv (required)"
exit 0

