# tests/unit/test_gdrive.py
"""Unit tests for gdrive.install_rclone temp-file security fix.

Regression (CWE-377): the rclone installer must be written to a securely
created temporary file (unpredictable name, owner-only permissions) and
never to a fixed, predictable path such as ``/tmp/rclone-install.sh``.
Because the script is executed with ``sudo bash``, a predictable/world-
accessible path was a local privilege-escalation vector.
"""

import os
import stat
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from atlas_onboard import gdrive
from atlas_onboard.errors import AtlasError


def _curl_result() -> MagicMock:
    res = MagicMock()
    res.returncode = 0
    res.stdout = "#!/bin/sh\necho installed\n"
    res.stderr = ""
    return res


def test_install_rclone_uses_secure_tempfile(mocker: MockerFixture):
    """Installer must use mkstemp (random name, 0o600), not a fixed /tmp path."""
    mocker.patch.object(
        gdrive,
        "_find_rclone",
        side_effect=[None, Path("/usr/bin/rclone")],
    )

    captured = {}

    def fake_run(args, **kwargs):
        if args[0] == "curl":
            return _curl_result()
        if args[0] == "sudo":
            script_path = Path(args[2])
            captured["path"] = script_path
            # Record the on-disk state at execution time.
            captured["exists_at_exec"] = script_path.exists()
            captured["mode"] = stat.S_IMODE(os.stat(script_path).st_mode)
            res = MagicMock()
            res.returncode = 0
            res.stdout = ""
            res.stderr = ""
            return res
        raise AssertionError(f"unexpected command: {args!r}")

    mocker.patch.object(gdrive.subprocess, "run", side_effect=fake_run)

    result = gdrive.install_rclone(policy_manager=MagicMock())
    assert result == Path("/usr/bin/rclone")

    path = captured["path"]
    # Must have actually existed when handed to `sudo bash`.
    assert captured["exists_at_exec"] is True
    # NOT the old predictable fixed name.
    assert path.name != "rclone-install.sh"
    assert str(path) != "/tmp/rclone-install.sh"
    # mkstemp naming contract.
    assert path.name.startswith("rclone-install-")
    assert path.name.endswith(".sh")
    # Owner-only permissions: no group/other bits set.
    assert captured["mode"] & 0o077 == 0, oct(captured["mode"])
    # Cleaned up afterwards.
    assert not path.exists()


def test_install_rclone_cleans_up_tempfile_on_failure(mocker: MockerFixture):
    """On installer failure the temp script must still be removed."""
    mocker.patch.object(gdrive, "_find_rclone", return_value=None)

    captured = {}

    def fake_run(args, **kwargs):
        if args[0] == "curl":
            return _curl_result()
        if args[0] == "sudo":
            captured["path"] = Path(args[2])
            res = MagicMock()
            res.returncode = 1
            res.stdout = ""
            res.stderr = "boom"
            return res
        raise AssertionError(f"unexpected command: {args!r}")

    mocker.patch.object(gdrive.subprocess, "run", side_effect=fake_run)

    with pytest.raises(AtlasError):
        gdrive.install_rclone(policy_manager=MagicMock())

    assert "path" in captured
    assert not captured["path"].exists()
