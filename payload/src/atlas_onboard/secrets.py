# src/atlas_onboard/secrets.py
"""Cross-platform secret storage using keyring (macOS) with .env fallback (Windows/Linux)."""

import platform

try:
    import keyring

    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False

from .paths import HOME


class SecretError(Exception):
    """Exception for secret storage errors."""

    pass


class SecretStore:
    """Unified secret storage that uses keyring on macOS, .env file on Windows/Linux.

    Strategy Pattern:
    - macOS: Uses keyring (Keychain) - OS-managed, encrypted
    - Windows/Linux: Uses .env file - fallback for compatibility

    Service name: "atlas"
    Keys: "MASTER_KEY", "SB_BOOTSTRAP_CLIENT_SECRET", etc.
    """

    SERVICE_NAME = "atlas"
    ENV_FILE = HOME / ".env"

    @classmethod
    def _is_macos(cls) -> bool:
        """Check if running on macOS."""
        return platform.system() == "Darwin"

    @classmethod
    def _is_windows(cls) -> bool:
        """Check if running on Windows."""
        return platform.system() == "Windows"

    @classmethod
    def _should_use_keyring(cls) -> bool:
        """Determine if we should use keyring (macOS and Windows)."""
        return KEYRING_AVAILABLE and (cls._is_macos() or cls._is_windows())

    @classmethod
    def get_secret(cls, key: str) -> str | None:
        """Get a secret value, trying keyring first (macOS), then .env file.

        Args:
            key: The secret key name (e.g., "MASTER_KEY")

        Returns:
            The secret value, or None if not found.

        """
        # Try keyring first (macOS only)
        if cls._should_use_keyring():
            try:
                value = keyring.get_password(cls.SERVICE_NAME, key)
                if value:
                    return value
            except Exception:
                # Keyring might not be available (no backend, locked, etc.)
                pass

        # Fallback to .env file (Windows/Linux, or if keyring unavailable)
        if cls.ENV_FILE.exists():
            try:
                for line in cls.ENV_FILE.read_text().splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        env_key, env_value = line.split("=", 1)
                        if env_key.strip() == key:
                            return env_value.strip()
            except Exception:
                pass

        return None

    @classmethod
    def set_secret(cls, key: str, value: str, prefer_keyring: bool = True) -> None:
        """Store a secret, preferring keyring on macOS, .env on Windows/Linux.

        Args:
            key: The secret key name
            value: The secret value
            prefer_keyring: If True and on macOS, store in keyring; otherwise use .env

        """
        # Try keyring first if on macOS and preferred
        if cls._should_use_keyring() and prefer_keyring:
            try:
                keyring.set_password(cls.SERVICE_NAME, key, value)
                return
            except Exception:
                # If keyring fails, fall back to .env
                pass

        # Fallback to .env file (Windows/Linux, or if keyring unavailable)
        cls._write_to_env_file(key, value)

    @classmethod
    def _write_to_env_file(cls, key: str, value: str) -> None:
        """Write a key-value pair to .env file."""
        # Read existing .env file
        env_lines = []
        key_found = False

        if cls.ENV_FILE.exists():
            for line in cls.ENV_FILE.read_text().splitlines():
                if line.strip() and not line.strip().startswith("#"):
                    if "=" in line:
                        env_key = line.split("=", 1)[0].strip()
                        if env_key == key:
                            # Update existing key
                            env_lines.append(f"{key}={value}")
                            key_found = True
                            continue
                env_lines.append(line)

        # Add new key if not found
        if not key_found:
            env_lines.append(f"{key}={value}")

        # Write back to file
        cls.ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
        cls.ENV_FILE.write_text("\n".join(env_lines) + "\n")
        cls.ENV_FILE.chmod(0o600)  # Restrict permissions

    @classmethod
    def migrate_master_key_to_keyring(cls) -> bool:
        """Migrate MASTER_KEY from .env file to keyring (macOS only).

        Returns:
            True if migration successful, False otherwise.

        """
        if not cls._should_use_keyring():
            return False

        master_key = cls.get_secret("MASTER_KEY")
        if not master_key:
            return False

        # If already in keyring, skip
        if keyring.get_password(cls.SERVICE_NAME, "MASTER_KEY"):
            return True

        try:
            keyring.set_password(cls.SERVICE_NAME, "MASTER_KEY", master_key)
            return True
        except Exception:
            return False
