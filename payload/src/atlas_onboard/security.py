"""Cryptographic primitives and security logic for Atlas.
Handles Keyring access, Argon2id key derivation, and XChaCha20-Poly1305 encryption/decryption.
"""

import os
import platform

# External dependencies (validated in pyproject.toml)
import keyring
from argon2.low_level import Type, hash_secret_raw
from nacl import utils as nacl_utils
from nacl.bindings import (
    crypto_aead_xchacha20poly1305_ietf_decrypt,
    crypto_aead_xchacha20poly1305_ietf_encrypt,
)
from rich.console import Console
from rich.prompt import Prompt

console = Console(stderr=True)

APP_NAME = "Atlas"
SECRET_KEY_NAME = "DeviceSecret"


class XChaCha20Poly1305:
    """Compatibility wrapper providing the cryptography-style API using libsodium."""

    KEY_SIZE = 32
    NONCE_SIZE = 24

    def __init__(self, key: bytes):
        if not isinstance(key, (bytes, bytearray)):
            raise TypeError("key must be bytes")
        if len(key) != self.KEY_SIZE:
            raise ValueError(f"key must be {self.KEY_SIZE} bytes")
        self._key = bytes(key)

    @staticmethod
    def generate_key() -> bytes:
        return nacl_utils.random(XChaCha20Poly1305.KEY_SIZE)

    def encrypt(self, nonce: bytes, data: bytes, associated_data: bytes | None = None) -> bytes:
        if len(nonce) != self.NONCE_SIZE:
            raise ValueError(f"nonce must be {self.NONCE_SIZE} bytes")
        aad = associated_data or b""
        return crypto_aead_xchacha20poly1305_ietf_encrypt(data, aad, nonce, self._key)

    def decrypt(self, nonce: bytes, data: bytes, associated_data: bytes | None = None) -> bytes:
        if len(nonce) != self.NONCE_SIZE:
            raise ValueError(f"nonce must be {self.NONCE_SIZE} bytes")
        aad = associated_data or b""
        return crypto_aead_xchacha20poly1305_ietf_decrypt(data, aad, nonce, self._key)


def _is_macos() -> bool:
    return platform.system() == "Darwin"


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _should_use_keyring() -> bool:
    """Check if keyring is supported on this platform."""
    # We support macOS (Keychain) and Windows (Credential Manager)
    return _is_macos() or _is_windows()


def get_or_set_device_secret() -> str:
    """Retrieves the Shared Secret from the OS Keychain.
    If missing (First Run), prompts the user and saves it securely.
    
    Note: On macOS, the first time this function accesses the keychain,
    macOS will prompt the user for permission. Users should click
    "Always Allow" to avoid repeated prompts.
    """
    secret = None
    if _should_use_keyring():
        try:
            secret = keyring.get_password(APP_NAME, SECRET_KEY_NAME)
        except Exception as e:
            console.print(f"[yellow]Warning: Could not access keyring: {e}[/yellow]")
            if _is_macos():
                console.print(
                    "[yellow]If you denied keychain access, you'll be prompted again next time.[/yellow]"
                )

    if secret:
        console.print(
            f"[green]\u2713[/green] Device authorized (Secret loaded from {platform.system()} Keychain)"
        )
        return secret

    # Not found - First Run or New Device
    console.print("\n[bold yellow]Device Secret not found in Keychain.[/bold yellow]")
    console.print("This appears to be a new device (or the secret was cleared).")
    console.print(
        "Please input the [bold]Shared Secret[/bold] (from your Password Manager).\n"
    )

    while True:
        secret = Prompt.ask("Input Shared Secret", password=True).strip()
        if secret:
            break
        console.print("[red]Error: Secret cannot be empty.[/red]")

    # Save to Keychain if possible
    if _should_use_keyring():
        try:
            keyring.set_password(APP_NAME, SECRET_KEY_NAME, secret)
            console.print(
                f"[green]\u2713[/green] Secret saved to {platform.system()} Keychain"
            )
        except Exception as e:
            console.print(f"[red]Error saving to keychain: {e}[/red]")
            console.print("Continuing without saving (you will be prompted next time).")

    return secret


def derive_key(master_password: str, shared_secret: str, salt: bytes) -> bytes:
    """Derive a 32-byte key using Argon2id.

    Params:
        master_password: User-provided password
        shared_secret: Device-specific secret
        salt: Random salt from the encrypted file

    Returns:
        32-byte raw key

    """
    # Combine inputs
    combined = master_password.encode("utf-8") + shared_secret.encode("utf-8")

    # Argon2id parameters (High Security)
    # Memory: 64MB (65536 KB)
    # Time: 4 passes
    # Parallelism: 2 threads
    return hash_secret_raw(
        secret=combined,
        salt=salt,
        time_cost=4,
        memory_cost=65536,
        parallelism=2,
        hash_len=32,
        type=Type.ID,
    )


def decrypt_data(
    encrypted_data: bytes, master_password: str, shared_secret: str
) -> bytes:
    """Decrypts data using XChaCha20-Poly1305.

    Format: [Salt (16)] [Nonce (24)] [Ciphertext (...)]
    """
    if len(encrypted_data) < 40:  # 16 + 24
        raise ValueError("Invalid encrypted data format (too short)")

    salt = encrypted_data[:16]
    nonce = encrypted_data[16:40]
    ciphertext = encrypted_data[40:]

    key = derive_key(master_password, shared_secret, salt)
    chacha = XChaCha20Poly1305(key)

    # Decrypt (raises exception on auth failure)
    return chacha.decrypt(nonce, ciphertext, None)


def encrypt_data(plaintext: bytes, master_password: str, shared_secret: str) -> bytes:
    """Encrypts data using XChaCha20-Poly1305.

    Returns: [Salt (16)] [Nonce (24)] [Ciphertext (...)]
    """
    salt = os.urandom(16)
    nonce = os.urandom(24)

    key = derive_key(master_password, shared_secret, salt)
    chacha = XChaCha20Poly1305(key)

    ciphertext = chacha.encrypt(nonce, plaintext, None)

    return salt + nonce + ciphertext
