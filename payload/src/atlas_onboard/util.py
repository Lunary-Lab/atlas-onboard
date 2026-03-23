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
    return "CERTIFICATE_VERIFY_FAILED" in str(exc) or "ssl" in exc.__class__.__name__.lower()


def verify_sha256(file_path: Path, expected_checksum: str) -> None:
    hasher = hashlib.sha256()
    try:
        with file_path.open("rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
    except OSError as e:
        raise AtlasError(
            f"Failed to read file for checksum verification: {file_path}"
        ) from e

    actual_checksum = hasher.hexdigest()
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
        with tempfile.NamedTemporaryFile(delete=False, dir=dest_path.parent) as tmp_file:
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
    """Downloads a file with TLS verification and a fallback that can skip verification on cert failures."""

    insecure_env = os.environ.get("SB_BOOTSTRAP_INSECURE_SKIP_TLS") == "1"
    attempts = [False] if insecure_env else [True, False]

    last_err: Exception | None = None
    for verify in attempts:
        try:
            _stream_download(url, dest_path, policy_manager, verify=verify)
            return
        except httpx.HTTPError as e:
            last_err = e
            if verify is False:
                break
            if not _cert_error(e):
                break
            print(
                f"[atlas-onboard] TLS verification failed for {url}; retrying without verification."
            )
            continue
        except Exception as e:
            last_err = e
            break

    if last_err:
        raise AtlasError(f"Failed to download file from {url}: {last_err}") from last_err


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
