# tests/unit/test_policy.py
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from atlasonboard import paths
from atlasonboard.errors import PolicyViolationError
from atlasonboard.policy import PolicyManager


@pytest.fixture
def mock_config() -> MagicMock:
    mock = MagicMock()
    mock.policy.include = []
    mock.policy.exclude = ["${HOME}/workspace/**"]

    def resolve_path_side_effect(p):
        return Path(p.replace("${HOME}", str(paths.HOME))).resolve()

    mock.resolve_path.side_effect = resolve_path_side_effect
    return mock


def test_policy_exclude_workspace(mock_config):
    manager = PolicyManager(mock_config)
    workspace_path = paths.HOME / "workspace" / "some_project"

    with pytest.raises(PolicyViolationError, match="forbidden by an exclude rule"):
        manager.check_write(workspace_path)


def test_policy_allow_bootstrap_dirs(mock_config, monkeypatch):
    manager = PolicyManager(mock_config)

    data_dir = paths.HOME / ".local" / "share" / "atlas"
    cache_dir = paths.HOME / ".cache" / "atlas"

    monkeypatch.setattr(paths, "get_app_data_dir", lambda: data_dir)
    monkeypatch.setattr(paths, "get_app_cache_dir", lambda: cache_dir)
    monkeypatch.setattr(paths, "get_app_config_dir", lambda: Path())
    monkeypatch.setattr(paths, "get_app_state_dir", lambda: Path())

    allowed_path = data_dir / "bin" / "age"
    manager.check_write(allowed_path)

    disallowed_path = paths.HOME / "Documents" / "some_file.txt"
    with pytest.raises(
        PolicyViolationError, match="restricted to bootstrap-managed directories"
    ):
        manager.check_write(disallowed_path)


def test_policy_include_rules(mock_config, monkeypatch):
    mock_config.policy.include = ["${HOME}/Downloads/safe_dir/**"]
    manager = PolicyManager(mock_config)

    monkeypatch.setattr(paths, "get_app_data_dir", lambda: Path())
    monkeypatch.setattr(paths, "get_app_cache_dir", lambda: Path())
    monkeypatch.setattr(paths, "get_app_config_dir", lambda: Path())
    monkeypatch.setattr(paths, "get_app_state_dir", lambda: Path())

    allowed_path = paths.HOME / "Downloads" / "safe_dir" / "installer.sh"
    manager.check_write(allowed_path)

    disallowed_path = paths.HOME / "Downloads" / "another_dir" / "file.txt"
    with pytest.raises(
        PolicyViolationError, match="not covered by any 'include' rules"
    ):
        manager.check_write(disallowed_path)


def test_policy_exclude_overrides_include(mock_config):
    mock_config.policy.include = ["${HOME}/workspace/**"]
    mock_config.policy.exclude = ["${HOME}/workspace/secret/**"]
    manager = PolicyManager(mock_config)

    allowed_path = paths.HOME / "workspace" / "project" / "main.py"
    manager.check_write(allowed_path)

    disallowed_path = paths.HOME / "workspace" / "secret" / "private.key"
    with pytest.raises(PolicyViolationError, match="forbidden by an exclude rule"):
        manager.check_write(disallowed_path)
