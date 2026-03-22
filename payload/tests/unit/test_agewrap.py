# tests/unit/test_agewrap.py
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from atlasonboard import agewrap
from atlasonboard.config import BootstrapConfig
from atlasonboard.errors import AgeBinaryError


@pytest.fixture
def mock_bootstrap_config(mocker: MockerFixture) -> "BootstrapConfig":
    mock_config = mocker.MagicMock(spec=BootstrapConfig)
    mock_config.age = mocker.MagicMock()
    mock_config.age.binary = mocker.MagicMock()
    mock_config.age.binary.version = "v1.3.1"
    mock_config.age.binary.checksums_url = (
        "https://example.com/age/v1.3.1/sha256sums.txt"
    )
    mock_config.policy = mocker.MagicMock()
    return mock_config


def test_get_age_binary_found(
    mocker: MockerFixture, mock_bootstrap_config: "BootstrapConfig"
):
    mocker.patch("atlasonboard.paths.get_bin_dir", return_value=Path("/fake/bin"))
    mocker.patch("atlasonboard.paths.is_windows", return_value=False)
    mocker.patch.object(Path, "exists", return_value=True)

    assert agewrap.get_age_binary(mock_bootstrap_config) == Path("/fake/bin/age")


def test_get_age_binary_download_and_verify(
    mocker: MockerFixture, mock_bootstrap_config: "BootstrapConfig", tmp_path: Path
):
    mocker.patch("atlasonboard.paths.get_bin_dir", return_value=tmp_path)
    mocker.patch("atlasonboard.paths.is_windows", return_value=False)
    mocker.patch("atlasonboard.agewrap._get_system_arch", return_value="linux-amd64")

    mocker.patch("atlasonboard.util.download_file")

    checksums_content = "aabbcc  age-v1.3.1-linux-amd64.tar.gz"
    mock_httpx_get = mocker.patch("httpx.get")
    mock_httpx_get.return_value.text = checksums_content

    mocker.patch("atlasonboard.util.verify_sha256")
    mocker.patch("atlasonboard.agewrap._extract_binary")
    mocker.patch.object(Path, "unlink")

    binary_path = agewrap.get_age_binary(mock_bootstrap_config)

    assert binary_path == tmp_path / "age"


def test_get_age_binary_checksum_mismatch(
    mocker: MockerFixture, mock_bootstrap_config: "BootstrapConfig", tmp_path: Path
):
    mocker.patch("atlasonboard.paths.get_bin_dir", return_value=tmp_path)
    mocker.patch("atlasonboard.agewrap._get_system_arch", return_value="linux-amd64")
    mocker.patch("atlasonboard.util.download_file")

    checksums_content = "ddccbb  age-v1.3.1-linux-amd64.tar.gz"
    mocker.patch("httpx.get").return_value.text = checksums_content

    mocker.patch("atlasonboard.util.verify_sha256", side_effect=AgeBinaryError("mismatch"))

    with pytest.raises(AgeBinaryError):
        agewrap.get_age_binary(mock_bootstrap_config)


def test_get_system_arch_all_platforms(mocker: MockerFixture):
    """Test that all supported platforms are correctly identified."""
    import platform

    # Test Linux platforms
    mocker.patch.object(platform, "system", return_value="Linux")
    mocker.patch.object(platform, "machine", return_value="x86_64")
    assert agewrap._get_system_arch() == "linux-amd64"

    mocker.patch.object(platform, "machine", return_value="amd64")
    assert agewrap._get_system_arch() == "linux-amd64"

    mocker.patch.object(platform, "machine", return_value="aarch64")
    assert agewrap._get_system_arch() == "linux-arm64"

    mocker.patch.object(platform, "machine", return_value="arm")
    assert agewrap._get_system_arch() == "linux-arm"

    mocker.patch.object(platform, "machine", return_value="armv7l")
    assert agewrap._get_system_arch() == "linux-arm"

    # Test Windows
    mocker.patch.object(platform, "system", return_value="Windows")
    mocker.patch.object(platform, "machine", return_value="x86_64")
    assert agewrap._get_system_arch() == "windows-amd64"

    mocker.patch.object(platform, "machine", return_value="AMD64")
    assert agewrap._get_system_arch() == "windows-amd64"

    # Test macOS
    mocker.patch.object(platform, "system", return_value="Darwin")
    mocker.patch.object(platform, "machine", return_value="arm64")
    assert agewrap._get_system_arch() == "darwin-arm64"

    mocker.patch.object(platform, "machine", return_value="x86_64")
    assert agewrap._get_system_arch() == "darwin-amd64"
