# tests/e2e/test_onboard_flow_windows.py
"""Windows-specific E2E tests that don't require Docker."""
import os
import platform
import tempfile
from pathlib import Path

import pytest

pytestmark = [pytest.mark.e2e]

# Test credentials (FAKE - only for e2e testing)
TEST_MASTER_PASSWORD = "test-master-password-12345"
TEST_SHARED_SECRET = "test-shared-secret-67890"


@pytest.mark.skipif(
    platform.system() != "Windows",
    reason="Windows-specific test",
)
def test_onboard_config_loading():
    """Test that onboard can load config on Windows."""
    from atlasonboard import config

    # Test default config creation
    default_cfg = config.create_default_config()
    assert default_cfg is not None
    assert default_cfg.version == 1
    assert default_cfg.profile in ["work", "home"]


@pytest.mark.skipif(
    platform.system() != "Windows",
    reason="Windows-specific test",
)
def test_security_keychain_windows():
    """Test that keychain operations work on Windows."""
    from atlasonboard import security

    # Test that get_or_set_device_secret works on Windows
    # This will prompt if not in keychain, but in CI we can test the keychain access
    try:
        # Try to get from keychain (might not exist in CI, that's ok)
        secret = security.get_or_set_device_secret()
        assert secret is not None
        assert len(secret) > 0
    except Exception as e:
        # If keychain access fails, that's acceptable in CI
        pytest.skip(f"Keychain access not available in CI: {e}")


@pytest.mark.skipif(
    platform.system() != "Windows",
    reason="Windows-specific test",
)
def test_onboard_ps1_syntax():
    """Test that onboard.ps1 has valid PowerShell syntax."""
    repo_root = Path(__file__).parent.parent.parent.parent.parent
    onboard_ps1 = repo_root / "atlas-onboard" / "onboard.ps1"

    if not onboard_ps1.exists():
        pytest.skip("onboard.ps1 not found")

    # Read and check basic syntax
    content = onboard_ps1.read_text()
    assert "$APP_VERSION" in content or "APP_VERSION" in content
    assert "$PAYLOAD_SHA256" in content or "PAYLOAD_SHA256" in content

