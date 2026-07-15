# src/atlas_onboard/util.py
"""Utility functions for checksumming, downloading, and file operations."""

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

import httpx
from rich.progress import Progress

from .errors import ChecksumMismatchError, AtlasError


def _cert_error(exc: Exception) -> bool:
    return (
        "CERTIFICATE_VERIFY_FAILED" in str(exc)
        or "ssl" in exc.__class__.__name__.lower()
    )



def write_secret_file(path: Path, content: str) -> None:
    """Atomically write *content* to *path* with owner-only (0o600) permissions.

    SECURITY (CWE-276): files that hold plaintext secrets (OAuth tokens, client
    secrets, refresh tokens, ...) must never be world- or group-readable, even
    briefly.  Writing with ``Path.write_text()`` and chmod()-ing afterwards
    leaves a TOCTOU window in which the freshly created file carries the
    default, umask-derived (often world-readable) permissions.  ``os.open`` with
    mode ``0o600`` guarantees the file is created owner-only *before* any secret
    bytes are written; the trailing chmod re-asserts the mode for files that
    already existed with looser permissions.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    # Enforce 0o600 even if the file pre-existed with looser permissions.
    path.chmod(0o600)


def verify_sha256(file_path: Path, expected_checksum: str) -> None:
    try:
        with file_path.open("rb") as f:
            digest = hashlib.file_digest(f, "sha256")
    except OSError as e:
        raise AtlasError(
            f"Failed to read file for checksum verification: {file_path}"
        ) from e

    actual_checksum = digest.hexdigest()
    if actual_checksum.lower() != expected_checksum.lower():
        raise ChecksumMismatchError(
            f"Checksum mismatch for {file_path.name}.\n"
            f"  Expected: {expected_checksum}\n"
            f"  Actual:   {actual_checksum}"
        )


def _stream_download(url: str, dest_path: Path, policy_manager, verify: bool) -> None:
    policy_manager.check_write(dest_path)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            delete=False, dir=dest_path.parent
        ) as tmp_file:
            tmp_path = Path(tmp_file.name)
            with httpx.stream(
                "GET", url, follow_redirects=True, timeout=30.0, verify=verify
            ) as response:
                response.raise_for_status()
                total = int(response.headers.get("Content-Length", 0))

                with Progress(transient=True) as progress:
                    task = progress.add_task(
                        f"Downloading {dest_path.name}...", total=total
                    )
                    for chunk in response.iter_bytes():
                        tmp_file.write(chunk)
                        progress.update(task, advance=len(chunk))

        shutil.move(tmp_path, dest_path)
    except Exception:
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
        raise


def download_file(url: str, dest_path: Path, policy_manager) -> None:
    """Download a file with TLS verification.

    SECURITY: TLS verification is *always* enabled.  A certificate-validation
    failure used to trigger an automatic retry with ``verify=False`` (silent
    downgrade), which exposed every binary download (chezmoi, age, …) to
    man-in-the-middle attacks.  That behaviour has been removed.

    Operators who genuinely need to bypass verification (e.g. an internal CA
    not present in the trust store) may still set
    ``SB_BOOTSTRAP_INSECURE_SKIP_TLS=1`` **explicitly** – the failure will never
    be silent again.
    """
    # Only skip TLS when explicitly requested by the operator.
    insecure_env = os.environ.get("SB_BOOTSTRAP_INSECURE_SKIP_TLS") == "1"
    verify = not insecure_env

    try:
        _stream_download(url, dest_path, policy_manager, verify=verify)
    except httpx.HTTPError as e:
        if insecure_env and _cert_error(e):
            # Already attempted without verification and still failed.
            raise AtlasError(f"Failed to download file from {url}: {e}") from e
        if _cert_error(e) and not insecure_env:
            raise AtlasError(
                f"TLS verification failed for {url}: {e}. "
                "The download was aborted to prevent a man-in-the-middle attack. "
                "If you are behind a corporate proxy with a custom CA, install the "
                "root certificate into the system trust store instead of disabling "
                "verification."
            ) from e
        raise AtlasError(f"Failed to download file from {url}: {e}") from e
    except Exception as e:
        raise AtlasError(f"Failed to download file from {url}: {e}") from e


def find_in_path(name: str) -> Path | None:
    return shutil.which(name)


def parse_checksum_file(content: str) -> dict[str, str]:
    checksums = {}
    for line in content.splitlines():
        parts = line.strip().split()
        if len(parts) == 2:
            checksum, filename = parts
            checksums[filename.lstrip("*")] = checksum
    return checksums


def write_secret_file(path: Path, content: str | bytes) -> None:
    """Atomically create *path* with owner-only (0o600) perms and write *content*.

    SECURITY (CWE-276 / CWE-377): callers used to write sensitive material
    (decrypted age private keys, OAuth tokens, ...) with ``Path.write_text`` and
    only ``chmod(0o600)`` *afterwards*.  That left a brief window during which the
    file existed with the default, umask-derived permissions (frequently group-
    or world-readable), exposing the secret to other local users.  Opening the
    file with an explicit 0o600 mode closes that window; the trailing ``chmod``
    also tightens a file that happened to pre-exist with looser permissions.
    """
    data = content.encode("utf-8") if isinstance(content, str) else content
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
    finally:
        # Enforce owner-only perms even if the file pre-existed with looser bits.
        os.chmod(path, 0o600)
