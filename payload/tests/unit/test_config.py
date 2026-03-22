# tests/unit/test_config.py
from pathlib import Path

import pytest
from pydantic import ValidationError

from atlas_onboard import config, paths
from atlas_onboard.errors import ConfigError

VALID_CONFIG_YAML = """
version: 1
profile: "work"
policy:
  exclude:
    - "${HOME}/workspace/**"
otp_gate:
  url: "http://127.0.0.1:8765/v1/verify"
  client_id: "bootstrap"
  client_secret_env: "SB_BOOTSTRAP_CLIENT_SECRET"
age:
  binary:
    version: "v1.3.1"
    checksums_url: "https://github.com/FiloSottile/age/releases/download/v1.3.1/sha256sums.txt"
  encrypted_key_path: "assets/id_bootstrap.age"
git:
  dotfiles_repo: "git@github.com:you/dotfiles.git"
  branch: "main"
chezmoi:
  version: "v2.48.1"
  assets:
    linux_amd64:
      url: "https://github.com/twpayne/chezmoi/releases/download/v2.48.1/chezmoi_2.48.1_linux_amd64.tar.gz"
      sha256: "aabbcc"
"""

INVALID_CONFIG_YAML = """
version: 1
age:
  binary:
    version: "v1.2.0"
    checksums_url: "invalid-url"
"""


@pytest.fixture
def valid_config_file(tmp_path: Path) -> Path:
    config_path = tmp_path / "bootstrap.yaml"
    config_path.write_text(VALID_CONFIG_YAML)
    return config_path


@pytest.fixture
def invalid_config_file(tmp_path: Path) -> Path:
    config_path = tmp_path / "bootstrap.yaml"
    config_path.write_text(INVALID_CONFIG_YAML)
    return config_path


def test_load_config_success(valid_config_file: Path):
    cfg = config.load_config(valid_config_file)
    assert cfg.version == 1
    assert cfg.profile == "work"
    # assert cfg.otp_gate.client_id == "bootstrap"
    assert cfg.age.binary.version == "v1.3.1"
    assert cfg.chezmoi.assets["linux_amd64"].sha256 == "aabbcc"
    assert "${HOME}/workspace/**" in cfg.policy.exclude


def test_load_config_not_found():
    with pytest.raises(ConfigError, match="Configuration file not found"):
        config.load_config(Path("/non/existent/path/bootstrap.yaml"))


def test_load_config_invalid_yaml(tmp_path: Path):
    config_path = tmp_path / "invalid.yaml"
    config_path.write_text("key: value: another")
    with pytest.raises(ConfigError, match="Failed to parse"):
        config.load_config(config_path)


def test_load_config_validation_error(invalid_config_file: Path):
    with pytest.raises(ConfigError, match="Configuration validation failed"):
        try:
            config.load_config(invalid_config_file)
        except ConfigError as e:
            assert isinstance(e.__cause__, ValidationError)
            raise e


def test_resolve_path(valid_config_file: Path):
    cfg = config.load_config(valid_config_file)
    home_dir = paths.HOME

    resolved_path = cfg.resolve_path("${HOME}/workspace/code")
    assert resolved_path == home_dir / "workspace" / "code"

    resolved_path_simple = cfg.resolve_path("/tmp/somefile")
    assert resolved_path_simple == Path("/tmp/somefile").resolve()
