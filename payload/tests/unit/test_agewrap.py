# tests/unit/test_agewrap.py
from pathlib import Path

import httpx
import pytest
from pytest_mock import MockerFixture

from atlas_onboard import agewrap
from atlas_onboard.config import BootstrapConfig
from atlas_onboard.errors import AgeBinaryError


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
    mocker.patch("atlas_onboard.paths.get_bin_dir", return_value=Path("/fake/bin"))
    mocker.patch("atlas_onboard.paths.is_windows", return_value=False)
    mocker.patch.object(Path, "exists", return_value=True)

    assert agewrap.get_age_binary(mock_bootstrap_config) == Path("/fake/bin/age")


def test_get_age_binary_download_and_verify(
    mocker: MockerFixture, mock_bootstrap_config: "BootstrapConfig", tmp_path: Path
):
    mocker.patch("atlas_onboard.paths.get_bin_dir", return_value=tmp_path)
    mocker.patch("atlas_onboard.paths.is_windows", return_value=False)
    mocker.patch("atlas_onboard.agewrap._get_system_arch", return_value="linux-amd64")

    mocker.patch("atlas_onboard.util.download_file")

    checksums_content = "aabbcc  age-v1.3.1-linux-amd64.tar.gz"
    mock_httpx_get = mocker.patch("httpx.get")
    mock_httpx_get.return_value.text = checksums_content

    mocker.patch("atlas_onboard.util.verify_sha256")
    mocker.patch("atlas_onboard.agewrap._extract_binary")
    mocker.patch.object(Path, "unlink")

    binary_path = agewrap.get_age_binary(mock_bootstrap_config)

    assert binary_path == tmp_path / "age"


def test_get_age_binary_checksum_mismatch(
    mocker: MockerFixture, mock_bootstrap_config: "BootstrapConfig", tmp_path: Path
):
    mocker.patch("atlas_onboard.paths.get_bin_dir", return_value=tmp_path)
    mocker.patch("atlas_onboard.agewrap._get_system_arch", return_value="linux-amd64")
    mocker.patch("atlas_onboard.util.download_file")

    checksums_content = "ddccbb  age-v1.3.1-linux-amd64.tar.gz"
    mocker.patch("httpx.get").return_value.text = checksums_content

    mocker.patch("atlas_onboard.util.verify_sha256", side_effect=AgeBinaryError("mismatch"))

    with pytest.raises(AgeBinaryError):
        agewrap.get_age_binary(mock_bootstrap_config)


def test_get_age_binary_rejects_missing_checksum(
    mocker: MockerFixture, mock_bootstrap_config: "BootstrapConfig", tmp_path: Path
):
    """Security: must fail when the asset has no checksum instead of silently skipping verification."""
    mocker.patch("atlas_onboard.paths.get_bin_dir", return_value=tmp_path)
    mocker.patch("atlas_onboard.paths.is_windows", return_value=False)
    mocker.patch("atlas_onboard.agewrap._get_system_arch", return_value="linux-amd64")

    # checksums file exists but does not contain our asset
    mock_httpx_get = mocker.patch("httpx.get")
    mock_httpx_get.return_value.text = "aabbcc some-other-file.tar.gz"

    with pytest.raises(AgeBinaryError, match="No checksum found"):
        agewrap.get_age_binary(mock_bootstrap_config)


def test_get_age_binary_rejects_checksum_fetch_error(
    mocker: MockerFixture, mock_bootstrap_config: "BootstrapConfig", tmp_path: Path
):
    """Security: must fail when the checksums file cannot be fetched (e.g. 404)."""
    import httpx

    mocker.patch("atlas_onboard.paths.get_bin_dir", return_value=tmp_path)
    mocker.patch("atlas_onboard.paths.is_windows", return_value=False)
    mocker.patch("atlas_onboard.agewrap._get_system_arch", return_value="linux-amd64")

    # Simulate HTTP error when fetching checksums
    mocker.patch(
        "atlas_onboard.agewrap._httpx_get",
        side_effect=httpx.HTTPStatusError(
            "Not Found",
            request=httpx.Request("GET", "https://example.com/checksums.txt"),
            response=httpx.Response(404),
        ),
    )

    with pytest.raises(AgeBinaryError, match="Failed to fetch checksums"):
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


def test_httpx_get_never_disables_tls_verification(mocker: MockerFixture):
    """Security regression test: ensure TLS verification is never downgraded.

    Previously the checksum fetch fell back to verify=False on cert errors,
    allowing MITM. This test asserts no call to httpx.get ever passes
    verify=False.
    """
    mock_get = mocker.patch("httpx.get")
    mock_get.return_value.text = "checksum  file"
    mock_get.return_value.status_code = 200

    agewrap._httpx_get("https://example.com/file.txt", timeout=10.0)

    # Verify the request was made with TLS verification enabled (verify not False)
    assert mock_get.call_count == 1
    call_kwargs = mock_get.call_args.kwargs
    assert call_kwargs.get("verify", True) is not False, (
        "TLS verification must never be disabled"
    )


def test_httpx_get_raises_on_tls_error_no_fallback(mocker: MockerFixture):
    """Security regression test: TLS errors must propagate, not downgrade.

    A certificate verification failure must raise an error, not silently
    retry with verify=False.
    """
    mock_get = mocker.patch("httpx.get")
    mock_get.side_effect = httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED]")

    with pytest.raises(httpx.ConnectError):
        agewrap._httpx_get("https://example.com/file.txt", timeout=10.0)

    # Must NOT have retried -- only one attempt, no insecure fallback
    assert mock_get.call_count == 1, "Must not retry with TLS verification disabled"
