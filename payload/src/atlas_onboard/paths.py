# src/atlasonboard/paths.py
"""XDG Base Directory Specification compliant path resolution."""

import os
import sys
from functools import lru_cache
from pathlib import Path

from .errors import EnvironmentError


def _get_home_path() -> Path:
    """Get the user's home directory.

    Raises:
        EnvironmentError: If the HOME environment variable is not set.

    """
    home = os.environ.get("HOME")
    if not home:
        # On Windows, HOME might not be set. Try USERPROFILE.
        home = os.environ.get("USERPROFILE")

    if not home:
        raise EnvironmentError(
            "Required environment variable HOME (or USERPROFILE on Windows) is not set."
        )

    path = Path(home).resolve()
    if not path.is_dir():
        raise EnvironmentError(
            f"Home directory '{path}' does not exist or is not a directory."
        )

    return path


HOME: Path = _get_home_path()


@lru_cache(maxsize=1)
def get_xdg_data_home() -> Path:
    """Returns the path to the XDG Data Home directory.

    Defaults to ~/.local/share if XDG_DATA_HOME is not set.
    """
    path = Path(os.environ.get("XDG_DATA_HOME", HOME / ".local" / "share"))
    path.mkdir(parents=True, exist_ok=True)
    return path


@lru_cache(maxsize=1)
def get_xdg_config_home() -> Path:
    """Returns the path to the XDG Config Home directory.

    Defaults to ~/.config if XDG_CONFIG_HOME is not set.
    """
    path = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config"))
    path.mkdir(parents=True, exist_ok=True)
    return path


@lru_cache(maxsize=1)
def get_xdg_state_home() -> Path:
    """Returns the path to the XDG State Home directory.

    Defaults to ~/.local/state if XDG_STATE_HOME is not set.
    """
    path = Path(os.environ.get("XDG_STATE_HOME", HOME / ".local" / "state"))
    path.mkdir(parents=True, exist_ok=True)
    return path


@lru_cache(maxsize=1)
def get_xdg_cache_home() -> Path:
    """Returns the path to the XDG Cache Home directory.

    Defaults to ~/.cache if XDG_CACHE_HOME is not set.
    """
    path = Path(os.environ.get("XDG_CACHE_HOME", HOME / ".cache"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_app_data_dir() -> Path:
    """Get the application's root data directory."""
    path = get_xdg_data_home() / "atlas"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_app_config_dir() -> Path:
    """Get the application's root config directory."""
    path = get_xdg_config_home() / "atlas"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_app_state_dir() -> Path:
    """Get the application's root state directory."""
    path = get_xdg_state_home() / "atlas"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_app_cache_dir() -> Path:
    """Get the application's root cache directory."""
    path = get_xdg_cache_home() / "atlas"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_bootstrap_cache_dir(version: str) -> Path:
    """Get the cache directory for a specific version of the bootstrap payload."""
    path = get_app_cache_dir() / "bootstrap" / version
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_bin_dir() -> Path:
    """Get the directory for storing downloaded binaries (e.g., age, chezmoi)."""
    path = get_app_data_dir() / "bin"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_default_config_path() -> Path:
    """Get the default path for the bootstrap.yaml configuration file."""
    return get_app_config_dir() / "bootstrap.yaml"



def is_windows() -> bool:
    """Check if the current operating system is Windows."""
    return sys.platform == "win32"


def is_macos() -> bool:
    """Check if the current operating system is macOS."""
    return sys.platform == "darwin"
