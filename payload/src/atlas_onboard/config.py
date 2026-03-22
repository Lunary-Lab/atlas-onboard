# src/atlas_onboard/config.py
"""Configuration loading and validation using Pydantic."""

import os
import ssl
from pathlib import Path

import httpx
import truststore
import yaml
from pydantic import BaseModel, Field, HttpUrl, ValidationError

from . import paths
from .errors import ConfigError


class PolicyConfig(BaseModel):
    """Filesystem access policy."""

    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=lambda: ["${HOME}/workspace/**"])




class AgeBinaryConfig(BaseModel):
    """Configuration for the 'age' binary."""

    version: str = "v1.3.1"
    checksums_url: HttpUrl = (
        "https://github.com/FiloSottile/age/releases/download/v1.3.1/sha256sums.txt"
    )


class AgeConfig(BaseModel):
    """Configuration for Age encryption."""

    binary: AgeBinaryConfig = Field(default_factory=lambda: AgeBinaryConfig())
    encrypted_key_path: str | None = None


class GitRepo(BaseModel):
    """Represents a Git repository to be cloned."""

    name: str
    url: str


class GitConfig(BaseModel):
    """Git-related configuration."""

    dotfiles_repo: str | None = None
    extra_repos: list[GitRepo] = Field(default_factory=list)
    branch: str = "main"


class ChezmoiAsset(BaseModel):
    """Represents a downloadable asset for chezmoi."""

    url: HttpUrl
    sha256: str


class ChezmoiConfig(BaseModel):
    """Configuration for the 'chezmoi' dotfiles manager."""

    version: str
    assets: dict[str, ChezmoiAsset]


class LoggingConfig(BaseModel):
    """Logging configuration."""

    level: str = "INFO"
    json_format: bool = Field(True, alias="json")


class BootstrapConfig(BaseModel):
    """Root configuration model."""

    version: int
    profile: str = "work"
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    age: AgeConfig = Field(default_factory=lambda: AgeConfig())
    git: GitConfig
    chezmoi: ChezmoiConfig
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    def get_chezmoi_asset_for_system(self, os_arch: str) -> ChezmoiAsset | None:
        """Get the chezmoi asset for the given OS/architecture string (e.g., 'linux_amd64')."""
        return self.chezmoi.assets.get(os_arch)

    def resolve_path(self, path_str: str) -> Path:
        """Resolve a path string, expanding ${HOME} and making it absolute."""
        expanded_path = os.path.expanduser(path_str.replace("${HOME}", str(paths.HOME)))
        return Path(expanded_path).resolve()


def create_default_config() -> BootstrapConfig:
    """Create a default configuration with smart defaults and prompts.
    Auto-detects platform and prompts for required values.
    """
    import platform

    from rich.console import Console
    from rich.prompt import Prompt

    from . import util

    console = Console(stderr=True)

    # Auto-detect profile: Mac == work, others default to work
    system = platform.system().lower()
    if system == "darwin":
        profile = "work"
        console.print("[cyan]Detected macOS - using 'work' profile[/cyan]")
    else:
        profile = "work"  # Default to work for all platforms


    # Determine system architecture for chezmoi
    machine = platform.machine().lower()
    arch_map = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }
    arch = arch_map.get(machine, "amd64")
    os_arch = f"{system}_{arch}"

    # Default chezmoi version
    chezmoi_version = "v2.48.1"
    version_str = chezmoi_version.replace("v", "")

    # Common platform defaults
    platform_urls = {
        "linux_amd64": f"https://github.com/twpayne/chezmoi/releases/download/{chezmoi_version}/chezmoi_{version_str}_linux_amd64.tar.gz",
        "darwin_amd64": f"https://github.com/twpayne/chezmoi/releases/download/{chezmoi_version}/chezmoi_{version_str}_darwin_amd64.tar.gz",
        "darwin_arm64": f"https://github.com/twpayne/chezmoi/releases/download/{chezmoi_version}/chezmoi_{version_str}_darwin_arm64.tar.gz",
        "windows_amd64": f"https://github.com/twpayne/chezmoi/releases/download/{chezmoi_version}/chezmoi_{version_str}_windows_amd64.zip",
    }

    # Fetch checksums from chezmoi release - FATAL if fails
    console.print(f"\n📦 [bold]Fetching chezmoi checksums for {os_arch}...[/bold]")
    # Chezmoi uses format: chezmoi_{version}_checksums.txt
    checksums_url = f"https://github.com/twpayne/chezmoi/releases/download/{chezmoi_version}/chezmoi_{version_str}_checksums.txt"
    chezmoi_assets = {}

    try:
        # Use truststore to verify certificates using the system's trust store (macOS Keychain, Windows Cert Store)
        # This fixes issues with corporate proxies (Zscaler, etc.) that use custom CAs
        ssl_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        with httpx.Client(
            timeout=10.0, follow_redirects=True, verify=ssl_context
        ) as client:
            response = client.get(checksums_url)
            response.raise_for_status()
            checksums = util.parse_checksum_file(response.text)

            # Add asset for current platform
            if os_arch not in platform_urls:
                raise ConfigError(
                    f"Unsupported platform: {os_arch}. "
                    f"Please create ~/.config/atlas/bootstrap.yaml manually."
                )

            asset_url = platform_urls[os_arch]
            from urllib.parse import urlparse

            asset_filename = urlparse(asset_url).path.split("/")[-1]
            sha256 = checksums.get(asset_filename)

            if not sha256:
                raise ConfigError(
                    f"Could not find checksum for {asset_filename} in chezmoi release {chezmoi_version}. "
                    f"This is a fatal error. Please create ~/.config/atlas/bootstrap.yaml manually."
                )

            chezmoi_assets[os_arch] = ChezmoiAsset(
                url=HttpUrl(asset_url), sha256=sha256
            )
            console.print(f"✅ [green]Found checksum for {asset_filename}[/green]")

    except httpx.HTTPError as e:
        raise ConfigError(
            f"Failed to fetch chezmoi checksums from {checksums_url}: {e}. "
            f"This is a fatal error. Please check your internet connection or create bootstrap.yaml manually."
        ) from e
    except Exception as e:
        raise ConfigError(
            f"Failed to configure chezmoi automatically: {e}. "
            f"This is a fatal error. Please create ~/.config/atlas/bootstrap.yaml manually."
        ) from e

    # Dotfiles repo can be supplied via environment variable
    dotfiles_repo = os.environ.get("ATLAS_DOTFILES_REPO")

    cfg = BootstrapConfig(
        version=1,
        profile=profile,
        git=GitConfig(
            dotfiles_repo=dotfiles_repo,
            branch="main",
        ),
        chezmoi=ChezmoiConfig(
            version=chezmoi_version,
            assets=chezmoi_assets,
        ),
    )

    # Save config to file so user doesn't have to enter it again
    try:
        config_path = paths.get_default_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert config to dict and write as YAML
        config_dict = {
            "version": cfg.version,
            "profile": cfg.profile,
            "age": {
                "binary": {
                    "version": cfg.age.binary.version,
                    "checksums_url": str(cfg.age.binary.checksums_url),
                },
            },
            "git": {
                "dotfiles_repo": cfg.git.dotfiles_repo,
                "branch": cfg.git.branch,
                "extra_repos": [],
            },
            "chezmoi": {
                "version": cfg.chezmoi.version,
                "assets": {
                    arch: {
                        "url": str(asset.url),
                        "sha256": asset.sha256,
                    }
                    for arch, asset in cfg.chezmoi.assets.items()
                },
            },
            "policy": {
                "exclude": cfg.policy.exclude,
            },
            "logging": {
                "level": cfg.logging.level,
                "json": cfg.logging.json_format,
            },
        }

        import yaml

        config_path.write_text(
            yaml.dump(config_dict, default_flow_style=False, sort_keys=False)
        )
        console.print(f"✅ [green]Configuration saved to {config_path}[/green]")
        console.print("   You can edit this file to customize settings.\n")
    except Exception as e:
        console.print(f"[yellow]Warning:[/yellow] Could not save config file: {e}")
        console.print("   Configuration will work for this session only.\n")

    return cfg


def load_config(
    path: Path | None = None, allow_missing: bool = False
) -> BootstrapConfig | None:
    """Load, parse, and validate the bootstrap configuration file.

    Args:
        path: The path to the configuration file. If None, uses the default path.
        allow_missing: If True, return None instead of raising an error when file is missing.

    Returns:
        A validated BootstrapConfig instance, or None if file is missing and allow_missing=True.

    Raises:
        ConfigError: If the file is not found (and allow_missing=False), cannot be read, or fails validation.

    """
    config_path = path or paths.get_default_config_path()
    if not config_path.is_file():
        if allow_missing:
            return None
        raise ConfigError(
            f"Configuration file not found at '{config_path}'. "
            f"Please create it from the example."
        )

    try:
        content = config_path.read_bytes()
        data = yaml.safe_load(content)
        return BootstrapConfig.model_validate(data)
    except (OSError, PermissionError) as e:
        raise ConfigError(
            f"Failed to read configuration file '{config_path}': {e}"
        ) from e
    except yaml.YAMLError as e:
        raise ConfigError(
            f"Failed to parse configuration file '{config_path}': {e}"
        ) from e
    except ValidationError as e:
        raise ConfigError(f"Configuration validation failed:\n{e}") from e


# Global accessor for the loaded config
def get_config() -> BootstrapConfig:
    """Returns the globally loaded application configuration."""
    return load_config()
