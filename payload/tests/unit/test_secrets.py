# tests/unit/test_secrets.py
"""Security-focused tests for the .env fallback secret store.

These verify that plaintext secrets are never written to a world/group
readable file (CWE-276/CWE-377).
"""

import os
import stat
from pathlib import Path

import pytest

from atlas_onboard.secrets import SecretStore

# POSIX permission bits are only meaningful on POSIX platforms.
posix_only = pytest.mark.skipif(
    os.name != "posix", reason="POSIX file permission semantics required"
)


@pytest.fixture
def env_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point SecretStore at a temporary .env and force the file backend."""
    env_file = tmp_path / ".env"
    monkeypatch.setattr(SecretStore, "ENV_FILE", env_file)
    # Force the .env fallback path regardless of the host OS/keyring backend.
    monkeypatch.setattr(
        SecretStore, "_should_use_keyring", classmethod(lambda cls: False)
    )
    return env_file


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@posix_only
def test_new_env_file_created_with_0600(env_store: Path) -> None:
    """A freshly created secret file must not be readable by group/other."""
    SecretStore.set_secret("MASTER_KEY", "s3cr3t", prefer_keyring=False)

    assert env_store.exists()
    mode = _mode(env_store)
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"
    # Explicitly assert no group/other access to the plaintext secret.
    assert mode & (stat.S_IRWXG | stat.S_IRWXO) == 0


@posix_only
def test_existing_permissive_env_file_is_tightened(env_store: Path) -> None:
    """A pre-existing, overly permissive file gets locked down on write."""
    env_store.write_text("OLD=1\n")
    env_store.chmod(0o644)
    assert _mode(env_store) == 0o644  # regression guard: start permissive

    SecretStore.set_secret("MASTER_KEY", "s3cr3t", prefer_keyring=False)

    assert _mode(env_store) == 0o600


def test_secret_roundtrip_via_env_file(env_store: Path) -> None:
    """Functionality is preserved: written secrets are read back verbatim."""
    SecretStore.set_secret("MASTER_KEY", "value-with-spaces = ok", prefer_keyring=False)
    SecretStore.set_secret("OTHER", "second", prefer_keyring=False)

    assert SecretStore.get_secret("MASTER_KEY") == "value-with-spaces = ok"
    assert SecretStore.get_secret("OTHER") == "second"
    assert SecretStore.get_secret("MISSING") is None


def test_env_file_written_with_owner_only_permissions(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    monkeypatch.setattr(SecretStore, "ENV_FILE", env_file)

    SecretStore._write_to_env_file("MASTER_KEY", "super-secret-value")

    assert env_file.exists()
    # Owner read/write only; no group/other bits.
    assert _mode(env_file) == 0o600
    # Round-trip: the secret is retrievable.
    assert SecretStore.get_secret("MASTER_KEY") == "super-secret-value"


def test_preexisting_loose_permissions_are_tightened(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    # Simulate a legacy world-readable .env file.
    env_file.write_text("OLD=1\n")
    os.chmod(env_file, 0o644)
    assert _mode(env_file) == 0o644

    monkeypatch.setattr(SecretStore, "ENV_FILE", env_file)
    SecretStore._write_to_env_file("SB_BOOTSTRAP_CLIENT_SECRET", "abc123")

    assert _mode(env_file) == 0o600
    assert SecretStore.get_secret("SB_BOOTSTRAP_CLIENT_SECRET") == "abc123"


def test_env_file_created_atomically_with_restrictive_mode(tmp_path, monkeypatch):
    """The file must be created via os.open() with O_CREAT and mode 0o600.

    This is the actual TOCTOU fix: writing first and chmod()-ing afterwards
    (the previous behaviour) would never call os.open() with an explicit mode,
    so this test fails against the vulnerable implementation.
    """
    env_file = tmp_path / ".env"
    monkeypatch.setattr(SecretStore, "ENV_FILE", env_file)

    recorded = {}
    real_open = os.open

    def spy_open(path, flags, mode=0o777, *args, **kwargs):
        if os.fspath(path) == os.fspath(env_file):
            recorded["flags"] = flags
            recorded["mode"] = mode
        return real_open(path, flags, mode, *args, **kwargs)

    monkeypatch.setattr(os, "open", spy_open)
    SecretStore._write_to_env_file("MASTER_KEY", "secret")

    assert recorded, "secret file was not created via os.open() with an explicit mode"
    assert recorded["mode"] == 0o600
    assert recorded["flags"] & os.O_CREAT
    assert recorded["flags"] & os.O_TRUNC
