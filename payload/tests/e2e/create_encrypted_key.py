#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
from atlasonboard.security import encrypt_data

MASTER_PASSWORD = "test-master-password-12345"
SHARED_SECRET = "test-shared-secret-67890"
AGE_KEY_PLAINTEXT = "AGE-SECRET-KEY-1TESTKEY123456789012345678901234567890123456789012345678901234567890"


def main():
    """Encrypt the age key and write it to a file."""
    output_path = Path("/tmp/age_key.enc")

    # Encrypt using the new 2FA approach
    encrypted_data = encrypt_data(
        AGE_KEY_PLAINTEXT.encode("utf-8"), MASTER_PASSWORD, SHARED_SECRET
    )

    output_path.write_bytes(encrypted_data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
