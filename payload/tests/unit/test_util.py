# tests/unit/test_util.py
"""Unit tests for util.download_file TLS security fix.

Regression: download_file must NEVER silently retry without TLS verification.
"""

import os
import hashlib
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from pytest_mock import MockerFixture

from atlas_onboard import util
from atlas_onboard.errors import AtlasError, ChecksumMismatchError


def _make_cert_error() -> httpx.HTTPError:
    """Build an httpx error whose message looks like a TLS/cert failure."""
    return httpx.ConnectError(
        "[Errno 1] _ssl.c: CERTIFICATE_VERIFY_FAILED "
        "certificate verify failed: self signed certificate"
    )


@pytest.fixture
def mock_policy():
    pm = MagicMock()
    pm.check_write.return_value = None
    return pm


def test_download_does_not_downgrade_tls_on_cert_error(
    mocker: MockerFixture, mock_policy, monkeypatch
):
    """SECURITY: A certificate error must NOT trigger an automatic retry
    with TLS verification disabled."""
    monkeypatch.delenv("SB_BOOTSTRAP_INSECURE_SKIP_TLS", raising=False)

    call_count = mocker.patch(
        "atlas_onboard.util._stream_download",
        side_effect=_make_cert_error(),
    )

    with pytest.raises(AtlasError, match="TLS verification failed"):
        util.download_file(
            "https://example.com/file.bin",
            Path("/tmp/out"),
            mock_policy,
        )

    # Must have been called exactly ONCE with verify=True.
    assert call_count.call_count == 1
    assert call_count.call_args.kwargs.get("verify") is True


def test_download_succeeds_with_tls(mock_stream_download, mock_policy, monkeypatch):
    """Normal download with valid TLS works as before."""
    monkeypatch.delenv("SB_BOOTSTRAP_INSECURE_SKIP_TLS", raising=False)

    mock_stream_download.return_value = None
    util.download_file(
        "https://example.com/file.bin",
        Path("/tmp/out"),
        mock_policy,
    )
    mock_stream_download.assert_called_once()
    assert mock_stream_download.call_args.kwargs["verify"] is True


def test_download_insecure_env_still_works(
    mock_stream_download, mock_policy, monkeypatch
):
    """When SB_BOOTSTRAP_INSECURE_SKIP_TLS=1, verify is False but no silent retry."""
    monkeypatch.setenv("SB_BOOTSTRAP_INSECURE_SKIP_TLS", "1")

    mock_stream_download.return_value = None
    util.download_file(
        "https://example.com/file.bin",
        Path("/tmp/out"),
        mock_policy,
    )
    mock_stream_download.assert_called_once()
    assert mock_stream_download.call_args.kwargs["verify"] is False


def test_download_insecure_env_cert_failure_no_retry(
    mocker: MockerFixture, mock_policy, monkeypatch
):
    """Even in insecure mode, there must be exactly ONE attempt."""
    monkeypatch.setenv("SB_BOOTSTRAP_INSECURE_SKIP_TLS", "1")

    call_count = mocker.patch(
        "atlas_onboard.util._stream_download",
        side_effect=_make_cert_error(),
    )

    with pytest.raises(AtlasError):
        util.download_file(
            "https://example.com/file.bin",
            Path("/tmp/out"),
            mock_policy,
        )

    assert call_count.call_count == 1


def test_download_non_cert_error_raises_atlas_error(
    mocker: MockerFixture, mock_policy, monkeypatch
):
    """Non-TLS errors should also raise AtlasError, but with a generic message."""
    monkeypatch.delenv("SB_BOOTSTRAP_INSECURE_SKIP_TLS", raising=False)

    mocker.patch(
        "atlas_onboard.util._stream_download",
        side_effect=httpx.ConnectError("connection refused"),
    )

    with pytest.raises(AtlasError) as exc_info:
        util.download_file(
            "https://example.com/file.bin",
            Path("/tmp/out"),
            mock_policy,
        )

    # Non-cert errors should NOT mention TLS/MITM guidance.
    assert "TLS verification failed" not in str(exc_info.value)


@pytest.fixture
def mock_stream_download(mocker: MockerFixture):
    return mocker.patch("atlas_onboard.util._stream_download")


def _write_file(path: Path, data: bytes) -> str:
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def test_verify_sha256_correct_checksum(tmp_path: Path):
    f = tmp_path / "binary"
    digest = _write_file(f, b"hello world")

    util.verify_sha256(f, digest)


def test_verify_sha256_case_insensitive(tmp_path: Path):
    f = tmp_path / "binary"
    digest = _write_file(f, b"hello world")

    util.verify_sha256(f, digest.upper())
    util.verify_sha256(f, digest.lower())


def test_verify_sha256_mismatch_raises(tmp_path: Path):
    f = tmp_path / "binary"
    _write_file(f, b"hello world")

    with pytest.raises(ChecksumMismatchError, match="Checksum mismatch"):
        util.verify_sha256(f, "0" * 64)


def test_verify_sha256_empty_file(tmp_path: Path):
    f = tmp_path / "empty"
    f.write_bytes(b"")
    util.verify_sha256(f, hashlib.sha256(b"").hexdigest())


def test_verify_sha256_large_multibuffer_file_matches_reference(tmp_path: Path):
    # File larger than hashlib.file_digest's internal read buffer (256 KiB) so
    # the multi-read streaming path is exercised.  The digest computed by
    # verify_sha256 must be byte-for-byte identical to the canonical
    # hashlib.sha256 of the same data.
    data = b"\x00\x01\x02\x03" * (300 * 1024)  # ~1.2 MiB, not buffer-aligned
    f = tmp_path / "large"
    digest = _write_file(f, data)

    util.verify_sha256(f, digest)


def test_verify_sha256_large_file_detects_single_byte_change(tmp_path: Path):
    # Regression guard: a one-byte modification well past the first internal
    # read buffer must be detected.  This proves the *entire* file is hashed
    # rather than only the leading buffer.
    data = bytearray(b"\xaa" * (512 * 1024 + 123))
    f = tmp_path / "large"
    good_digest = _write_file(f, bytes(data))

    data[400 * 1024] ^= 0xFF
    f.write_bytes(bytes(data))
    with pytest.raises(ChecksumMismatchError):
        util.verify_sha256(f, good_digest)


def test_verify_sha256_read_error(tmp_path: Path):
    f = tmp_path / "missing"
    with pytest.raises(AtlasError, match="Failed to read file"):
        util.verify_sha256(f, "0" * 64)


# ---------------------------------------------------------------------------
# write_secret_file: secrets must never touch disk with loose permissions.
# Regression for CWE-276 (write_text + chmod left a world-readable window).
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.name == "nt", reason="POSIX file-mode semantics")
def test_write_secret_file_creates_owner_only(tmp_path: Path, monkeypatch):
    """A brand-new secret file must be *created* with 0o600 atomically, not
    fixed up afterwards.

    We neutralise ``os.chmod`` and force a fully permissive umask so the only
    way the file can end up at 0o600 is if it was opened with that mode from the
    start.  This kills the classic insecure pattern (``write_text`` then
    ``chmod``), which would leave the secret briefly world-readable on disk.
    """
    monkeypatch.setattr(os, "chmod", lambda *a, **k: None)
    target = tmp_path / "nested" / "key.txt"
    old_umask = os.umask(0o000)
    try:
        util.write_secret_file(target, "AGE-SECRET-KEY-EXAMPLE")
    finally:
        os.umask(old_umask)

    assert target.read_text() == "AGE-SECRET-KEY-EXAMPLE"
    mode = target.stat().st_mode & 0o777
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


@pytest.mark.skipif(os.name == "nt", reason="POSIX file-mode semantics")
def test_write_secret_file_tightens_preexisting_loose_perms(tmp_path: Path):
    """If the file already exists with world-readable perms, they must be
    tightened to 0o600 and the content replaced."""
    target = tmp_path / "key.txt"
    target.write_text("stale")
    target.chmod(0o644)

    util.write_secret_file(target, b"AGE-SECRET-KEY-NEW")

    assert target.read_bytes() == b"AGE-SECRET-KEY-NEW"
    assert target.stat().st_mode & 0o777 == 0o600


# Additional checksum/parsing coverage from PR #12.

def test_verify_sha256_success(tmp_path: Path):
    data = b"hello world"
    f = tmp_path / "file.txt"
    f.write_bytes(data)
    expected = hashlib.sha256(data).hexdigest()

    # Should not raise
    util.verify_sha256(f, expected)


def test_verify_sha256_uppercase_checksum_matches(tmp_path: Path):
    data = b"binary blob"
    f = tmp_path / "blob.bin"
    f.write_bytes(data)
    expected_upper = hashlib.sha256(data).hexdigest().upper()

    util.verify_sha256(f, expected_upper)


def test_verify_sha256_missing_file_raises(tmp_path: Path):
    missing = tmp_path / "does_not_exist"

    with pytest.raises(AtlasError, match="Failed to read file"):
        util.verify_sha256(missing, "a" * 64)


def test_parse_checksum_file_standard_format():
    content = "aabbccdd  file1.txt\neeff0011  file2.txt\n"
    result = util.parse_checksum_file(content)
    assert result == {"file1.txt": "aabbccdd", "file2.txt": "eeff0011"}


def test_parse_checksum_file_binary_star_prefix():
    """sha256sum binary mode marks filenames with a leading * (e.g. ``hash *file``)."""
    content = "aabbccdd *binary_file.tar.gz\n"
    result = util.parse_checksum_file(content)
    assert result == {"binary_file.tar.gz": "aabbccdd"}


def test_parse_checksum_file_empty_content():
    assert util.parse_checksum_file("") == {}


def test_parse_checksum_file_skips_blank_and_malformed_lines():
    content = "\n  \nonlyoneword\naabb valid.txt\ntoo many parts here\n"
    result = util.parse_checksum_file(content)
    assert result == {"valid.txt": "aabb"}


def test_cert_error_detects_certificate_verify_failed():
    exc = Exception("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
    assert util._cert_error(exc) is True


def test_cert_error_detects_ssl_exception_class():
    exc = httpx.ConnectError("connection failed")  # not an SSL error
    assert util._cert_error(exc) is False


def test_cert_error_false_for_generic_exception():
    assert util._cert_error(ValueError("something else")) is False
