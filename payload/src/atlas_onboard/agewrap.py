# src/atlas_onboard/agewrap.py
"""Wrapper for acquiring and using the 'age' binary for decryption."""

import platform
import stat
import tarfile
import zipfile
from pathlib import Path

import httpx
from rich.console import Console

from . import paths, policy, util
from .errors import AgeBinaryError

console = Console(stderr=True)


def _cert_error(exc: Exception) -> bool:
    return "CERTIFICATE_VERIFY_FAILED" in str(exc) or "ssl" in exc.__class__.__name__.lower()


def _httpx_get_with_fallback(url: str, **kwargs):
    try:
        resp = httpx.get(url, **kwargs)
        resp.raise_for_status()
        return resp
    except httpx.HTTPError as e:
        if _cert_error(e):
            console.log(
                f"[yellow]TLS verification failed for {url}; retrying without verification.[/yellow]"
            )
            resp = httpx.get(url, verify=False, **{k: v for k, v in kwargs.items() if k != "verify"})
            resp.raise_for_status()
            return resp
        raise


def _get_system_arch() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "linux":
        if machine in ["x86_64", "amd64"]:
            return "linux-amd64"
        if machine == "aarch64":
            return "linux-arm64"
        if machine in ["arm", "armv7l", "armv6l"]:
            return "linux-arm"
    elif system == "windows":
        if machine in ["x86_64", "amd64"]:
            return "windows-amd64"
    elif system == "darwin":
        if machine == "arm64":
            return "darwin-arm64"
        if machine in ["x86_64", "amd64"]:
            return "darwin-amd64"

    raise AgeBinaryError(f"Unsupported operating system or architecture: {system}/{machine}")


def _get_asset_name_and_binary_path(version: str, arch: str) -> tuple[str, str]:
    if arch.startswith("windows"):
        asset_name = f"age-{version}-{arch}.zip"
        binary_path = "age/age.exe"
    else:
        asset_name = f"age-{version}-{arch}.tar.gz"
        binary_path = "age/age"
    return asset_name, binary_path


def _extract_binary(archive_path: Path, binary_path_in_archive: str, dest_path: Path):
    console.log(f"Extracting '{archive_path.name}'...")
    if archive_path.name.endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as zipf:
            with (zipf.open(binary_path_in_archive) as source, open(dest_path, "wb") as target):
                target.write(source.read())
    elif archive_path.name.endswith(".tar.gz"):
        with tarfile.open(archive_path, "r:gz") as tarf:
            member = tarf.extractfile(binary_path_in_archive)
            if not member:
                raise AgeBinaryError(f"Binary not found in archive: {binary_path_in_archive}")
            with open(dest_path, "wb") as target:
                target.write(member.read())
    else:
        raise AgeBinaryError(f"Unsupported archive format: {archive_path.name}")

    dest_path.chmod(dest_path.stat().st_mode | stat.S_IEXEC)
    console.log(f"Binary extracted to '{dest_path}'")


def get_age_binary(config: "BootstrapConfig") -> Path:
    bin_dir = paths.get_bin_dir()
    expected_binary_path = bin_dir / ("age.exe" if paths.is_windows() else "age")

    if expected_binary_path.exists():
        console.log(f"Found existing 'age' binary at '{expected_binary_path}'")
        return expected_binary_path

    console.print(
        f"Age binary not found. Downloading version [bold cyan]{config.age.binary.version}[/bold cyan]..."
    )

    version = config.age.binary.version
    if version in ["v1.1.1", "1.1.1", "v1.2.0", "1.2.0"]:
        new_version = "v1.3.1"
        console.print(f"[yellow]Warning:[/yellow] Version {version} is outdated and no longer supported.")
        console.print(f"[green]Automatically upgrading runtime configuration to use '{new_version}'.[/green]")
        console.print(
            f"[yellow]Please update your config file at:[/yellow] {paths.get_default_config_path()}"
        )
        config.age.binary.version = new_version
        version = new_version
        config.age.binary.checksums_url = (
            f"https://github.com/FiloSottile/age/releases/download/{new_version}/sha256sums.txt"
        )

    arch = _get_system_arch()
    asset_name, binary_in_archive_path = _get_asset_name_and_binary_path(version, arch)

    try:
        checksums_url_str = str(config.age.binary.checksums_url)
        if "/sha256sums.txt" in checksums_url_str:
            base_url = checksums_url_str.replace("/sha256sums.txt", "")
        elif checksums_url_str.endswith(".txt"):
            base_url = checksums_url_str.rsplit("/", 1)[0]
        else:
            base_url = checksums_url_str.rstrip("/")

        download_url = f"{base_url}/{asset_name}"

        expected_checksum = None
        try:
            console.log(f"Fetching checksums from {config.age.binary.checksums_url}")
            checksum_response = _httpx_get_with_fallback(
                str(config.age.binary.checksums_url), timeout=10.0
            )
            checksums = util.parse_checksum_file(checksum_response.text)
            expected_checksum = checksums.get(asset_name)
            if expected_checksum:
                console.log(f"Found checksum for '{asset_name}'")
            else:
                console.log(
                    f"[yellow]Warning:[/yellow] Checksum not found for '{asset_name}', skipping verification"
                )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                console.log(
                    "[yellow]Warning:[/yellow] Checksums file not available, skipping verification"
                )
            else:
                raise
        except Exception as e:
            console.log(
                f"[yellow]Warning:[/yellow] Could not fetch checksums: {e}, skipping verification"
            )

        policy_manager = policy.get_policy_manager(config)
        download_path = bin_dir / asset_name
        console.log(f"Downloading from {download_url}")
        util.download_file(download_url, download_path, policy_manager)

        if expected_checksum:
            console.log(f"Verifying checksum for '{asset_name}'...")
            util.verify_sha256(download_path, expected_checksum)
            console.log("Checksum verified.")
        else:
            console.log("[yellow]Skipping checksum verification (checksums not available)[/yellow]")

        _extract_binary(download_path, binary_in_archive_path, expected_binary_path)
        download_path.unlink()

        console.print("✅ [bold green]'age' binary is ready.[/bold green]")
        return expected_binary_path

    except (httpx.HTTPError, AgeBinaryError) as e:
        raise AgeBinaryError(f"Failed to acquire 'age' binary: {e}") from e
    except Exception as e:
        raise AgeBinaryError(f"An unexpected error occurred while acquiring 'age': {e}") from e
