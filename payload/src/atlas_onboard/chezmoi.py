# src/atlas_onboard/chezmoi.py
"""Wrapper for acquiring and using the 'chezmoi' binary."""

import os
import platform
import stat
import subprocess
import tarfile
import zipfile
from pathlib import Path

from rich.console import Console

from . import paths, policy, util
from .config import BootstrapConfig
from .errors import ChezmoiError

console = Console(stderr=True)


def _is_within_directory(directory: Path, target: Path) -> bool:
    """Return True if *target* resolves inside *directory* (no path traversal)."""
    try:
        return _resolved_is_within(directory.resolve(), target)
    except (OSError, ValueError):
        return False


def _resolved_is_within(directory_resolved: Path, target: Path) -> bool:
    """Return True if *target* resolves inside an already-resolved directory.

    Perf: archive-extraction loops check every member against the *same*
    target directory. Resolving that directory once in the caller and reusing
    the result here avoids a redundant ``Path.resolve()`` realpath syscall per
    archive entry, turning O(N) directory resolutions into O(1).
    """
    try:
        return target.resolve().is_relative_to(directory_resolved)
    except (OSError, ValueError):
        return False


def _safe_extract_zip(zipf: zipfile.ZipFile, extract_dir: Path) -> None:
    """Extract a zip archive, rejecting members that escape *extract_dir*.

    Security: prevents Zip Slip (path traversal) attacks where a malicious
    archive entry uses absolute paths or "../" sequences to write outside the
    intended directory.
    """
    # Resolve the target directory once: it is constant for the whole archive,
    # so re-resolving it per member would waste one realpath syscall per entry.
    extract_dir_resolved = extract_dir.resolve()
    for member in zipf.infolist():
        member_path = extract_dir / member.filename
        if not _resolved_is_within(extract_dir_resolved, member_path):
            raise ChezmoiError(
                f"Refusing to extract zip entry outside target directory: "
                f"{member.filename}"
            )
        zipf.extract(member, path=extract_dir)


def _safe_extract_tar(tarf: tarfile.TarFile, extract_dir: Path) -> None:
    """Extract a tar archive, rejecting members that escape *extract_dir*.

    Security: prevents Tar Slip (CVE-2007-4559) where crafted archive entries
    use absolute paths, ".." sequences, or symlinks to write or link outside
    the intended extraction directory.
    """
    # Resolve the target directory once (see _safe_extract_zip): avoids a
    # redundant realpath syscall per member for archives with many entries.
    extract_dir_resolved = extract_dir.resolve()
    for member in tarf.getmembers():
        member_path = extract_dir / member.name
        if not _resolved_is_within(extract_dir_resolved, member_path):
            raise ChezmoiError(
                f"Refusing to extract tar entry outside target directory: "
                f"{member.name}"
            )
        # Reject dangerous member types (links pointing outside target)
        if member.issym() or member.islnk():
            link_path = (extract_dir / member.name).parent / member.linkname
            if not _resolved_is_within(extract_dir_resolved, link_path):
                raise ChezmoiError(
                    f"Refusing to extract tar entry with unsafe link target: "
                    f"{member.name} -> {member.linkname}"
                )
    # Use built-in filter for Python 3.12+; fall back to manual check above
    try:
        tarf.extractall(
            path=extract_dir,
            filter="data" if hasattr(tarfile, "tar_filter") else None,
        )
    except TypeError:
        tarf.extractall(path=extract_dir)


def _get_system_arch() -> str:
    """Determine the system architecture in a format compatible with chezmoi assets."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    arch_map = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }

    if system not in ["linux", "windows", "darwin"] or machine not in arch_map:
        raise ChezmoiError(
            f"Unsupported operating system or architecture: {system}/{machine}"
        )

    return f"{system}_{arch_map[machine]}"


def get_chezmoi_binary(config: "BootstrapConfig") -> Path:
    """Ensures the 'chezmoi' binary is available, downloading and verifying it if necessary."""
    bin_dir = paths.get_bin_dir()
    expected_binary_path = bin_dir / (
        "chezmoi.exe" if paths.is_windows() else "chezmoi"
    )

    if expected_binary_path.exists():
        console.log(f"Found existing 'chezmoi' binary at '{expected_binary_path}'")
        return expected_binary_path

    console.print(
        f"Chezmoi binary not found. Downloading version [bold cyan]{config.chezmoi.version}[/bold cyan]..."
    )

    try:
        arch = _get_system_arch()
        policy_manager = policy.get_policy_manager(config)
        asset = config.get_chezmoi_asset_for_system(arch)
        if not asset:
            raise ChezmoiError(
                f"No chezmoi asset found for system '{arch}' in configuration."
            )

        asset_filename = Path(asset.url.path).name
        download_path = bin_dir / asset_filename
        util.download_file(str(asset.url), download_path, policy_manager)

        console.log(f"Verifying checksum for '{asset_filename}'...")
        util.verify_sha256(download_path, asset.sha256)
        console.log("Checksum verified.")

        console.log(f"Extracting '{asset_filename}'...")
        executable_name = "chezmoi.exe" if arch.startswith("windows") else "chezmoi"

        if asset_filename.endswith(".zip"):
            with zipfile.ZipFile(download_path, "r") as zipf:
                _safe_extract_zip(zipf, bin_dir)
        elif asset_filename.endswith(".tar.gz"):
            with tarfile.open(download_path, "r:gz") as tarf:
                _safe_extract_tar(tarf, bin_dir)
        else:
            raise ChezmoiError(f"Unsupported archive format: {asset_filename}")

        if paths.is_windows() and not expected_binary_path.exists():
            extracted_path = bin_dir / executable_name
            if extracted_path.exists():
                extracted_path.rename(expected_binary_path)

        download_path.unlink()

        if not paths.is_windows():
            expected_binary_path.chmod(
                expected_binary_path.stat().st_mode | stat.S_IEXEC
            )

        console.print("✅ [bold green]'chezmoi' binary is ready.[/bold green]")
        return expected_binary_path

    except (ValueError, ChezmoiError) as e:
        raise ChezmoiError(f"Failed to acquire 'chezmoi' binary: {e}") from e
    except Exception as e:
        raise ChezmoiError(
            f"An unexpected error occurred while acquiring 'chezmoi': {e}"
        ) from e


def apply_dotfiles(
    config: BootstrapConfig, chezmoi_bin: Path, profile: str | None = None
):
    """Runs `chezmoi init --apply` to provision the dotfiles."""
    target_profile = profile or config.profile
    dotfiles_repo = config.git.dotfiles_repo
    if not dotfiles_repo:
        raise ChezmoiError(
            "No dotfiles repository configured. Set 'git.dotfiles_repo' in bootstrap.yaml."
        )

    console.print(
        f"Applying dotfiles from [bold cyan]{dotfiles_repo}[/bold cyan] "
        f"with profile [bold magenta]{target_profile}[/bold magenta]..."
    )

    env = os.environ.copy()
    env["DOTFILES_PROFILE"] = target_profile
    env["CONSENT_INSTALL"] = "1"

    command = [
        str(chezmoi_bin),
        "init",
        "--apply",
        dotfiles_repo,
    ]

    try:
        process = subprocess.Popen(
            command,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        with console.status(
            "[bold yellow]Running chezmoi...[/bold yellow]", spinner="dots"
        ):
            if process.stdout:
                for line in iter(process.stdout.readline, ""):
                    console.log(line.strip())

        return_code = process.wait()
        if return_code != 0:
            raise ChezmoiError(f"'chezmoi init' failed with exit code {return_code}.")

        console.print("✅ [bold green]Dotfiles applied successfully.[/bold green]")

    except FileNotFoundError:
        raise ChezmoiError(f"Chezmoi binary not found at '{chezmoi_bin}'.")
    except subprocess.SubprocessError as e:
        raise ChezmoiError(f"An error occurred while running chezmoi: {e}")
