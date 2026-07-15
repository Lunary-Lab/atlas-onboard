# tests/e2e/test_onboard_flow.py
import os
import tempfile
from pathlib import Path

import docker
import pytest

pytestmark = pytest.mark.e2e

# Test credentials (FAKE - only for e2e testing)
TEST_MASTER_PASSWORD = "test-master-password-12345"
TEST_SHARED_SECRET = "test-shared-secret-67890"


@pytest.fixture(scope="module")
def docker_client():
    try:
        client = docker.from_env()
        client.ping()
        return client
    except Exception as e:
        pytest.skip(f"Docker is not available: {e}")


@pytest.fixture(scope="module")
def onboard_image(docker_client):
    image_tag = "atlas-onboard-e2e:latest"
    # Path to repo root (3 levels up from test file)
    repo_root = Path(__file__).parent.parent.parent.parent.parent
    dockerfile_path = (
        repo_root
        / "atlas-onboard"
        / "payload"
        / "tests"
        / "e2e"
        / "Dockerfile.ubuntu"
    )

    try:
        image, logs = docker_client.images.build(
            path=str(repo_root),
            dockerfile=str(dockerfile_path.relative_to(repo_root)),
            tag=image_tag,
            rm=True,
        )
        yield image_tag
    finally:
        try:
            docker_client.images.remove(image_tag, force=True)
        except docker.errors.ImageNotFound:
            pass


def test_onboard_flow(docker_client, onboard_image):
    """Test the onboard flow using 2FA approach."""
    container = None
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
        config_path = f.name
        f.write("""
version: 1
profile: "work"
age:
  binary:
    version: "v1.3.1"
    checksums_url: "https://github.com/FiloSottile/age/releases/download/v1.3.1/sha256sums.txt"
  encrypted_key_path: "/tmp/age_key.enc"
git:
  dotfiles_repo: "ssh://tester@127.0.0.1:/tmp/dotfiles.git"
  branch: "main"
  extra_repos: []  # Explicitly empty - no real repos
chezmoi:
  version: "v2.48.1"
  assets:
    linux_amd64:
      url: "https://github.com/twpayne/chezmoi/releases/download/v2.48.1/chezmoi_2.48.1_linux_amd64.tar.gz"
      sha256: "ab61698359b203701cabc08e062efdca595954b7e24c59547c979c377eb5a4da"
        """)

    try:
        test_script = f"""#!/bin/bash
set -e

# Clear all environment variables for isolation
env -i bash -c '
export HOME=/home/tester
export XDG_CONFIG_HOME=/home/tester/.config
export XDG_DATA_HOME=/home/tester/.local/share
export XDG_STATE_HOME=/home/tester/.local/state
export XDG_CACHE_HOME=/home/tester/.cache
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
cd /app/payload
source .venv/bin/activate
echo -e "{TEST_SHARED_SECRET}\\n{TEST_MASTER_PASSWORD}\\n" | atlas_onboard run --config /tmp/config.yaml
'
"""

        container = docker_client.containers.run(
            onboard_image,
            command=["/bin/bash", "-c", test_script],
            detach=True,
            volumes={config_path: {"bind": "/tmp/config.yaml", "mode": "ro"}},
            stdin_open=False,
            tty=False,
            network_mode="bridge",
            # No environment variables passed - complete isolation
        )

        # Wait for completion
        result = container.wait(timeout=300)
        logs = container.logs().decode("utf-8")

        # Check for successful completion indicators
        assert result["StatusCode"] == 0, (
            f"Bootstrap failed with exit code {result['StatusCode']}. Logs: {logs}"
        )

        # Verify no external services accessed
        if "github.com" in logs.lower() and "127.0.0.1" not in logs:
            pytest.fail("External repository accessed")

        # Check logs for success indicators
        success_indicators = [
            "Bootstrap complete",
            "onboard complete",
            "Age identity written",
            "Age key file should exist",
        ]
        assert any(
            indicator.lower() in logs.lower() for indicator in success_indicators
        ), f"Bootstrap completion not found in logs: {logs}"

        # Verify age key was decrypted and written
        key_file_check = container.exec_run(
            "test -f /home/tester/.config/chezmoi/key.txt"
        )
        assert key_file_check.exit_code == 0, (
            "Age key file should exist after onboard"
        )

        # Verify the key file contains the expected age key format
        key_content = container.exec_run(
            "cat /home/tester/.config/chezmoi/key.txt"
        ).output.decode("utf-8")
        assert "AGE-SECRET-KEY-1" in key_content, (
            f"Decrypted key should contain age key format. Got: {key_content[:50]}"
        )

    finally:
        if container:
            container.remove(force=True)
        os.unlink(config_path)
