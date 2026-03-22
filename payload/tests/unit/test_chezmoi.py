# tests/unit/test_chezmoi.py
import types
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from atlas_onboard import chezmoi
from atlas_onboard.config import BootstrapConfig


@pytest.fixture
def mock_bootstrap_config(mocker: MockerFixture) -> BootstrapConfig:
    mock_config = types.SimpleNamespace()
    mock_config.chezmoi = types.SimpleNamespace()
    mock_config.chezmoi.version = "v2.48.1"
    mock_config.profile = "work"
    mock_config.git = types.SimpleNamespace()
    mock_config.git.dotfiles_repo = "git@github.com:user/dots.git"

    mock_asset = types.SimpleNamespace()
    mock_asset.url = types.SimpleNamespace(path="/chezmoi.tar.gz")
    mock_asset.sha256 = "aabbcc"

    mock_config.get_chezmoi_asset_for_system = mocker.Mock(return_value=mock_asset)

    return mock_config


def test_get_chezmoi_binary_found(
    mocker: MockerFixture, mock_bootstrap_config: BootstrapConfig
):
    mocker.patch("atlas_onboard.paths.get_bin_dir", return_value=Path("/fake/bin"))
    mocker.patch("atlas_onboard.paths.is_windows", return_value=False)

    mocker.patch.object(Path, "exists", return_value=True)

    binary_path = chezmoi.get_chezmoi_binary(mock_bootstrap_config)
    assert binary_path == Path("/fake/bin/chezmoi")


def test_get_chezmoi_binary_download_and_verify(
    mocker: MockerFixture, mock_bootstrap_config: BootstrapConfig, tmp_path: Path
):
    mocker.patch("atlas_onboard.paths.get_bin_dir", return_value=tmp_path)
    mocker.patch("atlas_onboard.paths.is_windows", return_value=False)
    mocker.patch("atlas_onboard.chezmoi._get_system_arch", return_value="linux_amd64")

    mocker.patch("atlas_onboard.util.download_file")
    mocker.patch("atlas_onboard.util.verify_sha256")
    mocker.patch("zipfile.ZipFile")
    mocker.patch("tarfile.open")
    mocker.patch.object(Path, "unlink")

    dummy_binary = tmp_path / "chezmoi"
    dummy_binary.touch()

    binary_path = chezmoi.get_chezmoi_binary(mock_bootstrap_config)

    assert binary_path == tmp_path / "chezmoi"


def test_apply_dotfiles(mocker: MockerFixture, mock_bootstrap_config: BootstrapConfig):
    mock_popen = mocker.patch("subprocess.Popen")
    mock_proc = mocker.Mock()
    mock_proc.wait.return_value = 0
    mock_proc.stdout.readline.return_value = ""
    mock_popen.return_value = mock_proc

    chezmoi.apply_dotfiles(
        mock_bootstrap_config, Path("/fake/bin/chezmoi"), profile=None
    )

    called_args, called_kwargs = mock_popen.call_args
    command = called_args[0]
    env = called_kwargs.get("env", {})

    assert command == [
        "/fake/bin/chezmoi",
        "init",
        "--apply",
        "git@github.com:user/dots.git",
    ]
    assert env.get("DOTFILES_PROFILE") == "work"
    assert env.get("CONSENT_INSTALL") == "1"


def test_apply_dotfiles_with_profile_override(
    mocker: MockerFixture, mock_bootstrap_config: BootstrapConfig
):
    mock_popen = mocker.patch("subprocess.Popen")
    mock_proc = mocker.Mock()
    mock_proc.wait.return_value = 0
    mock_proc.stdout.readline.return_value = ""
    mock_popen.return_value = mock_proc

    chezmoi.apply_dotfiles(
        mock_bootstrap_config, Path("/fake/bin/chezmoi"), profile="home"
    )

    env = mock_popen.call_args.kwargs.get("env", {})
    assert env.get("DOTFILES_PROFILE") == "home"
