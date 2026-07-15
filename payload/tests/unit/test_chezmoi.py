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


# --- Security tests for safe archive extraction (path traversal prevention) ---

def test_safe_extract_tar_rejects_path_traversal(tmp_path: Path):
    """A tar entry using ../ to escape the target dir must be rejected."""
    import io
    import tarfile

    # Build a malicious tar with a path-traversal entry in memory
    data = b"malicious content"
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="../../../tmp/atlas_evil_file")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))

    tar_buf.seek(0)
    with tarfile.open(fileobj=tar_buf, mode="r:gz") as tarf:
        from atlas_onboard.errors import ChezmoiError

        with pytest.raises(ChezmoiError, match="outside target directory"):
            chezmoi._safe_extract_tar(tarf, tmp_path)

    # Verify nothing was written outside the target directory
    assert not Path("/tmp/atlas_evil_file").exists()


def test_safe_extract_zip_rejects_path_traversal(tmp_path: Path):
    """A zip entry using ../ to escape the target dir must be rejected."""
    import io
    import zipfile

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zipf:
        zipf.writestr("../../atlas_evil_zip.txt", "malicious content")

    zip_buf.seek(0)
    with zipfile.ZipFile(zip_buf, "r") as zipf:
        from atlas_onboard.errors import ChezmoiError

        with pytest.raises(ChezmoiError, match="outside target directory"):
            chezmoi._safe_extract_zip(zipf, tmp_path)


def test_safe_extract_tar_accepts_benign_entry(tmp_path: Path):
    """A normal tar entry inside the target dir must extract successfully."""
    import io
    import tarfile

    data = b"chezmoi binary placeholder"
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="chezmoi")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))

    tar_buf.seek(0)
    with tarfile.open(fileobj=tar_buf, mode="r:gz") as tarf:
        chezmoi._safe_extract_tar(tarf, tmp_path)

    assert (tmp_path / "chezmoi").exists()
    assert (tmp_path / "chezmoi").read_bytes() == data


def test_safe_extract_tar_rejects_symlink_escape(tmp_path: Path):
    """A tar symlink whose target escapes the extract dir must be rejected.

    Regression guard for the extraction perf refactor: the symlink branch now
    uses the pre-resolved directory (_resolved_is_within) instead of resolving
    the target directory per member, so it must still catch unsafe links.
    """
    import io
    import tarfile

    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="evil_link")
        info.type = tarfile.SYMTYPE
        info.linkname = "../../../../etc/passwd"
        tar.addfile(info)

    tar_buf.seek(0)
    with tarfile.open(fileobj=tar_buf, mode="r:gz") as tarf:
        from atlas_onboard.errors import ChezmoiError

        with pytest.raises(ChezmoiError, match="unsafe link target"):
            chezmoi._safe_extract_tar(tarf, tmp_path)


def test_safe_extract_tar_accepts_multiple_benign_entries(tmp_path: Path):
    """Multiple benign entries all extract correctly.

    Exercises the extraction loop that now resolves the target directory a
    single time (cached) rather than once per member.
    """
    import io
    import tarfile

    names = ["a.txt", "sub/b.txt", "sub/deep/c.txt"]
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w:gz") as tar:
        for name in names:
            data = name.encode()
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

    tar_buf.seek(0)
    with tarfile.open(fileobj=tar_buf, mode="r:gz") as tarf:
        chezmoi._safe_extract_tar(tarf, tmp_path)

    for name in names:
        assert (tmp_path / name).read_bytes() == name.encode()


def test_resolved_is_within_matches_is_within_directory(tmp_path: Path):
    """_resolved_is_within must agree with _is_within_directory for the same dir."""
    inside = tmp_path / "sub" / "file.txt"
    outside = tmp_path.parent / "escape.txt"
    resolved = tmp_path.resolve()

    assert chezmoi._resolved_is_within(resolved, inside) is True
    assert chezmoi._is_within_directory(tmp_path, inside) is True

    assert chezmoi._resolved_is_within(resolved, outside) is False
    assert chezmoi._is_within_directory(tmp_path, outside) is False
