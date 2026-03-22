# src/atlas_onboard/agent.py
"""Manages the SSH agent (ssh-agent on POSIX, OpenSSH Agent on Windows)."""

import os
import subprocess
import tempfile
from pathlib import Path

from rich.console import Console

from . import paths
from .errors import SshAgentError

console = Console(stderr=True)


class SshAgentManager:
    """Context manager for ensuring SSH agent is running and cleaning it up if we started it."""

    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._original_env: dict[str, str] = {}
        self._temp_sock_dir: tempfile.TemporaryDirectory | None = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    def _is_windows_agent_running(self) -> bool:
        """Check if the Windows OpenSSH Agent service is running."""
        try:
            result = subprocess.run(
                ["powershell", "-Command", "(Get-Service ssh-agent).Status"],
                capture_output=True,
                text=True,
                check=True,
            )
            return "running" in result.stdout.lower()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def _start_windows_agent(self) -> None:
        """Attempt to start the Windows OpenSSH Agent service."""
        console.log("Attempting to start Windows OpenSSH Agent service...")
        try:
            subprocess.run(
                ["powershell", "-Command", "Start-Service ssh-agent"],
                capture_output=True,
                check=True,
            )
            console.log("Service started successfully.")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            raise SshAgentError(
                f"Failed to start ssh-agent service. Please start it manually (as Administrator). Error: {e.stderr}"
            )

    def start(self) -> None:
        """Ensure the SSH agent is running. Starts a new one if necessary."""
        if paths.is_windows():
            if not self._is_windows_agent_running():
                self._start_windows_agent()
                if not self._is_windows_agent_running():
                    raise SshAgentError(
                        "OpenSSH Authentication Agent service is not running and could not be started."
                    )
            console.log("Windows OpenSSH Agent is running.")
            return

        # POSIX systems
        if "SSH_AUTH_SOCK" in os.environ:
            console.log(f"Existing SSH agent found at {os.environ['SSH_AUTH_SOCK']}")
            return

        console.log("No existing SSH agent found. Starting a temporary one...")
        try:
            self._temp_sock_dir = tempfile.TemporaryDirectory()
            sock_path = Path(self._temp_sock_dir.name) / "agent.sock"

            self._proc = subprocess.Popen(
                ["ssh-agent", "-s", "-a", str(sock_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            stdout, stderr = self._proc.communicate()
            if self._proc.returncode != 0:
                raise SshAgentError(f"Failed to start ssh-agent: {stderr}")

            for line in stdout.splitlines():
                if "=" in line and "echo" not in line:
                    key, value = line.split(";", 1)[0].split("=", 1)
                    if key in os.environ:
                        self._original_env[key] = os.environ[key]
                    os.environ[key] = value

            if "SSH_AUTH_SOCK" not in os.environ:
                raise SshAgentError("Failed to parse ssh-agent output.")

            console.log(
                f"Temporary SSH agent started (PID: {os.environ['SSH_AGENT_PID']})"
            )

        except FileNotFoundError:
            raise SshAgentError(
                "`ssh-agent` command not found. Please install OpenSSH."
            )
        except Exception as e:
            self.stop()
            raise SshAgentError(
                f"An unexpected error occurred while starting ssh-agent: {e}"
            )

    def stop(self) -> None:
        """Stops the SSH agent if it was started by this manager."""
        if self._proc:
            console.log(f"Stopping temporary SSH agent (PID: {self._proc.pid})...")
            self._proc.terminate()
            self._proc = None

            # Get the keys that were set by the agent
            agent_keys = set(self._original_env.keys()) | {
                "SSH_AUTH_SOCK",
                "SSH_AGENT_PID",
            }

            for key, value in self._original_env.items():
                os.environ[key] = value

            # Remove keys that were not present before
            for key in agent_keys:
                if key not in self._original_env:
                    if key in os.environ:
                        del os.environ[key]

        if self._temp_sock_dir:
            self._temp_sock_dir.cleanup()
            self._temp_sock_dir = None

    def add_key(self, private_key_bytes: bytes) -> None:
        """Adds a private key to the running SSH agent."""
        console.log("Adding decrypted key to SSH agent in memory...")
        try:
            # On macOS, use -K flag (or --apple-use-keychain) to add key to keychain
            # This ensures keys persist across reboots and are available to all applications
            if paths.is_macos():
                # Try --apple-use-keychain first (macOS 12.2+), fall back to -K
                try:
                    subprocess.run(
                        ["ssh-add", "--apple-use-keychain", "-"],
                        input=private_key_bytes,
                        capture_output=True,
                        check=True,
                    )
                except (subprocess.CalledProcessError, FileNotFoundError):
                    # Fall back to -K flag for older macOS versions
                    subprocess.run(
                        ["ssh-add", "-K", "-"],
                        input=private_key_bytes,
                        capture_output=True,
                        check=True,
                    )
            else:
                subprocess.run(
                    ["ssh-add", "-"],
                    input=private_key_bytes,
                    capture_output=True,
                    check=True,
                )
            console.log("Key added successfully to agent.")
        except FileNotFoundError:
            raise SshAgentError("`ssh-add` command not found. Please install OpenSSH.")
        except subprocess.CalledProcessError as e:
            raise SshAgentError(
                f"Failed to add key to ssh-agent. Error: {e.stderr.decode(errors='ignore')}"
            )

    def list_keys(self) -> str:
        """Lists the keys currently in the agent."""
        try:
            result = subprocess.run(
                ["ssh-add", "-l"], capture_output=True, text=True, check=True
            )
            return result.stdout
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            console.log(f"Could not list SSH keys: {e}")
            return ""
