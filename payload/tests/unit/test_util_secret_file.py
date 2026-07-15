# tests/unit/test_util_secret_file.py
"""Unit tests for util.write_secret_file permission hardening.

Regression (CWE-276): secret-bearing files (OAuth tokens, rclone config with
client secret / refresh token) must be created with owner-only (0o600)
permissions, never left world-/group-readable even briefly.
"""

import os
import stat
import sys
from pathlib import Path

import pytest

from atlas_onboard import util

# chmod / POSIX permission bits are not meaningfully enforced on Windows.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX file permissions not enforced on Windows"
)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_write_secret_file_creates_file_owner_only(tmp_path: Path):
    """A freshly created secret file must be 0o600 (owner-only)."""
    target = tmp_path / "nested" / "token.json"
    util.write_secret_file(target, '{"token": "s3cr3t"}')

    assert target.read_text() == '{"token": "s3cr3t"}'
    # Owner-only: no group/other bits set at all.
    assert _mode(target) == 0o600
    assert _mode(target) & 0o077 == 0, "secret file must not be group/world accessible"


def test_write_secret_file_tightens_preexisting_loose_perms(tmp_path: Path):
    """A file that already exists world-readable must end up 0o600."""
    target = tmp_path / "rclone.conf"
    target.write_text("[old]\n")
    os.chmod(target, 0o644)  # simulate the insecure default (world-readable)
    assert _mode(target) & 0o077 != 0  # precondition: currently exposed

    util.write_secret_file(target, "[new]\nrefresh_token = abc\n")

    assert target.read_text() == "[new]\nrefresh_token = abc\n"
    assert _mode(target) == 0o600
    assert _mode(target) & 0o077 == 0


def test_write_secret_file_overwrites_content(tmp_path: Path):
    """Rewriting an existing secret file replaces content and keeps 0o600."""
    target = tmp_path / "token.json"
    util.write_secret_file(target, "first")
    util.write_secret_file(target, "second")
    assert target.read_text() == "second"
    assert _mode(target) == 0o600
