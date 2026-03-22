#!/bin/bash
set -e

# --- E2E Test Environment Setup ---

# 1. Install 'age' binary
AGE_VERSION="v1.3.1"
AGE_ARCH="linux-amd64"
AGE_ASSET="age-${AGE_VERSION}-${AGE_ARCH}.tar.gz"
AGE_URL="https://github.com/FiloSottile/age/releases/download/${AGE_VERSION}/${AGE_ASSET}"
CHECKSUMS_URL="https://github.com/FiloSottile/age/releases/download/${AGE_VERSION}/sha256sums.txt"

echo "Downloading age binary..."
curl -fL -o "/tmp/${AGE_ASSET}" "${AGE_URL}"

echo "Verifying age checksum..."
curl -fL -o "/tmp/sha256sums.txt" "${CHECKSUMS_URL}"
grep "${AGE_ASSET}" "/tmp/sha256sums.txt" | sha256sum -c -

echo "Installing age binary..."
tar -C /usr/local/bin -xzf "/tmp/${AGE_ASSET}" age/age --strip-components=1
rm "/tmp/${AGE_ASSET}" "/tmp/sha256sums.txt"

# 2. Create mock dotfiles git repository
echo "Creating mock dotfiles repository..."
git init --bare /tmp/dotfiles.git
git clone /tmp/dotfiles.git /tmp/dotfiles-clone
cd /tmp/dotfiles-clone
mkdir -p source
echo "atlas-e2e-test-successful" > source/dot_test-file
git add .
git config user.email "tester@atlas.dev"
git config user.name "E2E Tester"
git commit -m "Add test file for e2e verification"
git push origin main
cd /
rm -rf /tmp/dotfiles-clone

# 3. Generate and encrypt test key
echo "Generating encrypted test key..."
AGE_KEY_PLAINTEXT="AGE-SECRET-KEY-1TESTKEY123456789012345678901234567890123456789012345678901234567890"
# Use Python to encrypt it with the new 2FA method (master password + shared secret)
# Note: We need to set up the Python environment first
# Note: Key creation will happen during Docker build after venv is set up
# The create_encrypted_key.py script will be run in the Dockerfile

# If the Python script couldn't import (venv not ready), create a helper script
# that will be run after the venv is set up
cat > /tmp/create_encrypted_key.py << 'PYEOF'
#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path("/app/payload/src")))
from atlasonboard.security import encrypt_data

MASTER_PASSWORD = "test-master-password-12345"
SHARED_SECRET = "test-shared-secret-67890"
AGE_KEY_PLAINTEXT = "AGE-SECRET-KEY-1TESTKEY123456789012345678901234567890123456789012345678901234567890\n"

encrypted_data = encrypt_data(
    AGE_KEY_PLAINTEXT.encode('utf-8'),
    MASTER_PASSWORD,
    SHARED_SECRET
)

Path("/tmp/age_key.enc").write_bytes(encrypted_data)
print("✅ Created encrypted age key")
PYEOF
chmod +x /tmp/create_encrypted_key.py

echo "E2E environment setup complete."
