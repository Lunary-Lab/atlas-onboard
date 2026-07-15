"""Unit tests for atlas_onboard.gitwrap.

Focus: the clone() command must be immune to git argument injection
(CWE-88) via a repository URL or destination path that begins with "-".
"""

from pathlib import Path

import pytest

from atlas_onboard import gitwrap
from atlas_onboard.errors import GitError


class _FakePolicy:
    """Minimal policy manager stub that permits writes."""

    def __init__(self):
        self.checked = []

    def check_write(self, path):  # noqa: D102
        self.checked.append(Path(path))


class _CompletedOK:
    returncode = 0
    stdout = ""
    stderr = ""


def _capture_run(monkeypatch):
    """Patch subprocess.run in gitwrap and capture the argv it receives."""
    captured = {}

    def fake_run(cmd, *args, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _CompletedOK()

    monkeypatch.setattr(gitwrap.subprocess, "run", fake_run)
    return captured


def test_clone_inserts_end_of_options_separator(tmp_path, monkeypatch):
    """`--` must appear immediately before the positional URL and dest."""
    captured = _capture_run(monkeypatch)
    dest = tmp_path / "repo"

    gitwrap.clone("https://example.com/repo.git", dest, _FakePolicy(), "main")

    cmd = captured["cmd"]
    assert "--" in cmd, "clone must terminate option parsing with '--'"
    sep = cmd.index("--")
    # Everything after '--' is positional: exactly [repo_url, dest].
    assert cmd[sep + 1 :] == ["https://example.com/repo.git", str(dest)]
    # The separator must come after all real options.
    assert "--depth" in cmd[:sep] and "--branch" in cmd[:sep]


def test_clone_neutralizes_option_like_repo_url(tmp_path, monkeypatch):
    """A repo_url beginning with '-' is treated as a path, not a git option.

    Regression guard: without the '--' separator git would parse
    ``--upload-pack=...`` as an option, enabling arbitrary command
    execution. With the separator it is a trailing positional argument.
    """
    captured = _capture_run(monkeypatch)
    dest = tmp_path / "repo"
    malicious = "--upload-pack=touch /tmp/pwned"

    gitwrap.clone(malicious, dest, _FakePolicy(), "main")

    cmd = captured["cmd"]
    sep = cmd.index("--")
    # The malicious value must live strictly after '--', so git cannot
    # interpret it as an option.
    assert cmd[sep + 1] == malicious
    assert malicious not in cmd[:sep]


def test_clone_skips_when_destination_exists(tmp_path, monkeypatch):
    """Existing destinations short-circuit without invoking git."""
    called = {"run": False}

    def fake_run(*a, **k):
        called["run"] = True
        return _CompletedOK()

    monkeypatch.setattr(gitwrap.subprocess, "run", fake_run)
    dest = tmp_path / "existing"
    dest.mkdir()

    gitwrap.clone("https://example.com/repo.git", dest, _FakePolicy(), "main")
    assert called["run"] is False


def test_clone_raises_git_error_on_missing_git(tmp_path, monkeypatch):
    """A missing git binary surfaces as a GitError, not a raw OSError."""

    def fake_run(*a, **k):
        raise FileNotFoundError("git")

    monkeypatch.setattr(gitwrap.subprocess, "run", fake_run)
    with pytest.raises(GitError):
        gitwrap.clone("https://example.com/repo.git", tmp_path / "r", _FakePolicy())
