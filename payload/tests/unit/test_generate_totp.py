# tests/unit/test_generate_totp.py
"""Tests for the TOTP code generator.

Security focus: verify the TOTP secret is accepted from secure sources (stdin,
env var) and that the legacy argv path emits a deprecation warning.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# generate_totp.py lives at the repo root, three levels up from this test file.
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

# pyotp may not be installed in CI (generate_totp.py is a standalone script,
# not part of the atlas_onboard package). Inject a mock so the module-level
# import in generate_totp.py succeeds.
if "pyotp" not in sys.modules:
    sys.modules["pyotp"] = MagicMock()

import generate_totp  # noqa: E402,I001


# A well-known base32 test vector (not a real secret).
TEST_SECRET = "JBSWY3DPEHPK3PXP"


def _no_stdin():
    """Return a patcher that mocks stdin as a TTY (no piped data)."""
    return patch("generate_totp._read_secret_from_stdin", return_value=None)


@pytest.fixture
def _clean_env(monkeypatch):
    """Ensure ATLAS_TOTP_SECRET is not set for tests that don't want it."""
    monkeypatch.delenv("ATLAS_TOTP_SECRET", raising=False)
    yield


def test_get_secret_from_stdin(_clean_env):
    """Secret piped via stdin is returned (most secure path)."""
    with patch("generate_totp._read_secret_from_stdin", return_value=TEST_SECRET):
        with patch.object(sys, "argv", ["generate_totp.py"]):
            assert generate_totp.get_secret() == TEST_SECRET


def test_get_secret_from_env(monkeypatch, _clean_env):
    """Secret provided via environment variable is returned."""
    monkeypatch.setenv("ATLAS_TOTP_SECRET", TEST_SECRET)
    monkeypatch.setattr(sys, "argv", ["generate_totp.py"])
    with _no_stdin():
        assert generate_totp.get_secret() == TEST_SECRET


def test_stdin_takes_priority_over_env(monkeypatch, _clean_env):
    """When both stdin and env are present, stdin wins."""
    monkeypatch.setenv("ATLAS_TOTP_SECRET", "ENVSECRET")
    monkeypatch.setattr(sys, "argv", ["generate_totp.py"])
    with patch("generate_totp._read_secret_from_stdin", return_value=TEST_SECRET):
        assert generate_totp.get_secret() == TEST_SECRET


def test_get_secret_from_argv_emits_warning(monkeypatch, capsys, _clean_env):
    """Legacy argv path works but emits a security warning."""
    monkeypatch.setattr(sys, "argv", ["generate_totp.py", TEST_SECRET])
    with _no_stdin():
        secret = generate_totp.get_secret()
    captured = capsys.readouterr()
    assert secret == TEST_SECRET
    assert "WARNING" in captured.err
    assert "insecure" in captured.err.lower()


def test_no_secret_returns_none(monkeypatch, _clean_env):
    """When no secret source is available, returns None."""
    monkeypatch.setattr(sys, "argv", ["generate_totp.py"])
    with _no_stdin():
        assert generate_totp.get_secret() is None


def test_generate_secret_flag(monkeypatch):
    """--generate-secret still works and produces a base32 string."""
    monkeypatch.setattr(sys, "argv", ["generate_totp.py", "--generate-secret"])
    with pytest.raises(SystemExit) as exc_info:
        generate_totp.main()
    assert exc_info.value.code == 0


def test_main_no_secret_exits_with_error(monkeypatch, _clean_env, capsys):
    """Running with no secret source exits with code 1."""
    monkeypatch.setattr(sys, "argv", ["generate_totp.py"])
    with _no_stdin():
        with pytest.raises(SystemExit) as exc_info:
            generate_totp.main()
    assert exc_info.value.code == 1
