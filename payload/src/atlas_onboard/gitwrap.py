# src/atlas_onboard/gitwrap.py
"""Wrapper for executing Git commands securely."""

import subprocess
from pathlib import Path

from rich.console import Console

from .config import GitConfig
from .errors import GitError

console = Console(stderr=True)


def clone(repo_url: str, dest_dir: Path, policy_manager, branch: str = "main") -> None:
    """Clones a Git repository."""
    policy_manager.check_write(dest_dir)
    if dest_dir.exists():
        console.log(f"Directory '{dest_dir}' already exists. Skipping clone.")
        return

    console.print(f"Cloning [bold cyan]{repo_url}[/bold cyan] into '{dest_dir}'...")
    try:
        subprocess.run(
            [
                "git",
                "clone",
                "--branch",
                branch,
                "--depth",
                "1",
                repo_url,
                str(dest_dir),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        console.log("Clone successful.")
    except FileNotFoundError:
        raise GitError("`git` command not found. Please install Git.")
    except subprocess.CalledProcessError as e:
        raise GitError(
            f"Failed to clone repository '{repo_url}'.\nStderr: {e.stderr.strip()}"
        )


def apply_dotfiles_repo(config: GitConfig) -> None:
    """Clones the main dotfiles repository."""
    console.log("Git operations for dotfiles will be handled by 'chezmoi init'.")
    pass
