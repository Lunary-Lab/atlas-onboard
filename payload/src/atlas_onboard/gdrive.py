# src/atlas_onboard/gdrive.py
"""Google Drive sync setup for Atlas Bootstrap."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

from rich.console import Console

from . import paths
from .errors import AtlasError

console = Console()


def install_rclone(policy_manager) -> Path:
    """Install rclone if not already installed."""
    rclone_path = _find_rclone()
    if rclone_path:
        console.print(f"✅ [green]rclone found at {rclone_path}[/green]")
        return rclone_path

    console.print("[yellow]Installing rclone...[/yellow]")

    # Install rclone using official installer
    # Download installer script first, then execute separately to avoid shell=True
    try:
        # Download installer script
        install_script_path = Path(tempfile.gettempdir()) / "rclone-install.sh"
        download_result = subprocess.run(
            ["curl", "-fsSL", "https://rclone.org/install.sh"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if download_result.returncode != 0:
            raise AtlasError(
                f"Failed to download rclone installer: {download_result.stderr}"
            )

        # Write to temp file
        install_script_path.write_text(download_result.stdout)
        install_script_path.chmod(0o755)  # Make executable

        # Execute installer with sudo bash
        result = subprocess.run(
            ["sudo", "bash", str(install_script_path)],
            capture_output=True,
            text=True,
            timeout=60,
        )

        # Clean up temp file
        install_script_path.unlink(missing_ok=True)
        if result.returncode != 0:
            raise AtlasError(f"Failed to install rclone: {result.stderr}")

        # Find rclone after installation
        rclone_path = _find_rclone()
        if not rclone_path:
            raise AtlasError("rclone installed but not found in PATH")

        console.print(f"✅ [green]rclone installed at {rclone_path}[/green]")
        return rclone_path
    except subprocess.TimeoutExpired:
        raise AtlasError("rclone installation timed out")
    except Exception as e:
        raise AtlasError(f"Failed to install rclone: {e}")


def _find_rclone() -> Path | None:
    """Find rclone in PATH."""
    rclone_path = subprocess.run(
        ["which", "rclone"],
        capture_output=True,
        text=True,
    )
    if rclone_path.returncode == 0:
        return Path(rclone_path.stdout.strip())
    return None


def setup_google_drive_sync(
    config: dict,
    token_data: dict,
    policy_manager,
) -> None:
    """Set up Google Drive bidirectional sync using rclone bisync.

    Args:
        config: Google Drive configuration from bootstrap.yaml
        token_data: Decrypted Google Drive OAuth token (token.json content)
        policy_manager: Policy manager for filesystem access

    """
    if not config.get("enabled", False):
        console.print("[yellow]Google Drive sync is disabled, skipping setup[/yellow]")
        return

    if config.get("sync_mode") != "bidirectional":
        console.print(
            f"[yellow]Sync mode '{config.get('sync_mode')}' not supported, skipping[/yellow]"
        )
        return

    console.print("\n[bold]Setting up Google Drive bidirectional sync...[/bold]")

    # Install rclone
    rclone_path = install_rclone(policy_manager)

    # Set up paths
    sync_path = Path(
        os.path.expandvars(config.get("sync_path", "${HOME}/workspace/gdrive"))
    )
    token_file = Path(
        os.path.expandvars(
            config.get(
                "token_file", "${HOME}/.config/atlas/google-drive/token.json"
            )
        )
    )
    rclone_config_dir = paths.get_xdg_config_home() / "rclone"
    rclone_config_file = rclone_config_dir / "rclone.conf"

    # Ensure directories exist
    sync_path.mkdir(parents=True, exist_ok=True)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    rclone_config_dir.mkdir(parents=True, exist_ok=True)

    # Save token file
    console.print("[yellow]Saving Google Drive token...[/yellow]")
    token_file.write_text(json.dumps(token_data, indent=2))
    token_file.chmod(0o600)  # Secure permissions
    console.print(f"✅ [green]Token saved to {token_file}[/green]")

    # Configure rclone remote
    remote_name = config.get("remote_name", "gdrive")
    console.print(f"[yellow]Configuring rclone remote '{remote_name}'...[/yellow]")

    # Create rclone config
    rclone_config = f"""[{remote_name}]
type = drive
client_id = {token_data.get("client_id", "")}
client_secret = {token_data.get("client_secret", "")}
token = {json.dumps(token_data.get("token", {}))}
refresh_token = {token_data.get("refresh_token", "")}
"""

    # Append to existing config or create new
    if rclone_config_file.exists():
        existing = rclone_config_file.read_text()
        if f"[{remote_name}]" not in existing:
            rclone_config_file.write_text(existing + "\n" + rclone_config)
    else:
        rclone_config_file.write_text(rclone_config)

    rclone_config_file.chmod(0o600)
    console.print(f"✅ [green]rclone config saved to {rclone_config_file}[/green]")

    # Verify remote configuration
    result = subprocess.run(
        [str(rclone_path), "listremotes", "--config", str(rclone_config_file)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode == 0 and remote_name in result.stdout:
        console.print(
            f"✅ [green]rclone remote '{remote_name}' configured successfully[/green]"
        )
    else:
        console.print(
            f"[yellow]Warning:[/yellow] Could not verify rclone remote: {result.stderr}"
        )

    # Set up bidirectional sync using rclone bisync
    folders = config.get("folders", [])
    if not folders:
        # Sync entire Google Drive
        console.print(
            "[yellow]Setting up full Google Drive bidirectional sync...[/yellow]"
        )
        _setup_bisync_service(
            rclone_path,
            rclone_config_file,
            remote_name,
            "",  # Empty path = root
            sync_path,
            config.get("sync_interval_minutes", 15),
        )
    else:
        # Sync specific folders
        for folder_id in folders:
            folder_path = sync_path / folder_id
            folder_path.mkdir(parents=True, exist_ok=True)
            console.print(f"[yellow]Setting up sync for folder {folder_id}...[/yellow]")
            _setup_bisync_service(
                rclone_path,
                rclone_config_file,
                remote_name,
                folder_id,
                folder_path,
                config.get("sync_interval_minutes", 15),
            )

    console.print(
        "✅ [bold green]Google Drive bidirectional sync configured![/bold green]"
    )


def _setup_bisync_service(
    rclone_path: Path,
    rclone_config: Path,
    remote_name: str,
    remote_path: str,
    local_path: Path,
    interval_minutes: int,
) -> None:
    """Set up systemd service and timer for rclone bisync."""
    if paths.is_windows():
        console.print(
            "[yellow]Windows detected - systemd services not available[/yellow]"
        )
        console.print(
            "[yellow]Google Drive sync will need to be set up manually on Windows[/yellow]"
        )
        return

    service_name = (
        f"rclone-bisync-{remote_path.replace('/', '-') if remote_path else 'root'}"
    )
    remote_full = f"{remote_name}:{remote_path}" if remote_path else f"{remote_name}:"

    # Create systemd service
    service_content = f"""[Unit]
Description=rclone bisync {remote_full} <-> {local_path}
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart={rclone_path} bisync {remote_full} {local_path} --config {rclone_config} --resync
StandardOutput=journal
StandardError=journal
"""

    # Create systemd timer
    timer_content = f"""[Unit]
Description=Run rclone bisync {remote_full} <-> {local_path} every {interval_minutes} minutes
Requires={service_name}.service

[Timer]
OnBootSec=5min
OnUnitActiveSec={interval_minutes}min
RandomizedDelaySec=2min

[Install]
WantedBy=timers.target
"""

    service_file = (
        paths.get_xdg_config_home() / "systemd" / "user" / f"{service_name}.service"
    )
    timer_file = (
        paths.get_xdg_config_home() / "systemd" / "user" / f"{service_name}.timer"
    )

    service_file.parent.mkdir(parents=True, exist_ok=True)
    service_file.write_text(service_content)
    timer_file.write_text(timer_content)

    # Enable and start timer
    try:
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            check=True,
            timeout=10,
        )
        subprocess.run(
            ["systemctl", "--user", "enable", f"{service_name}.timer"],
            check=True,
            timeout=10,
        )
        subprocess.run(
            ["systemctl", "--user", "start", f"{service_name}.timer"],
            check=True,
            timeout=10,
        )
        console.print(
            f"✅ [green]Systemd timer '{service_name}.timer' enabled and started[/green]"
        )
    except subprocess.CalledProcessError as e:
        console.print(f"[yellow]Warning:[/yellow] Failed to enable systemd timer: {e}")
        console.print("[yellow]You may need to enable it manually:[/yellow]")
        console.print(f"  systemctl --user enable {service_name}.timer")
        console.print(f"  systemctl --user start {service_name}.timer")
