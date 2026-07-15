# tests/unit/test_policy.py
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from atlas_onboard import paths
from atlas_onboard.errors import PolicyViolationError
from atlas_onboard.policy import PolicyManager


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


def test_policy_managed_dirs_cached_at_init(mock_config):
    """Managed bootstrap dirs are resolved once at construction.

    They are reused for every check_write() call, avoiding repeated
    stat()/mkdir() syscalls.  This verifies the cache is populated.
    """
    manager = PolicyManager(mock_config)
    assert len(manager._managed_dirs) == 4
    assert len(manager._managed_dir_strs) == 4
    # Every cached string should be an absolute, resolved path.
    for d in manager._managed_dir_strs:
        assert d.startswith("/")


def test_policy_managed_dir_prefix_not_confused_by_sibling(mock_config):
    """A sibling dir sharing a prefix name must not be treated as inside.

    E.g. ~/.local/share/atlas-evil must NOT match managed dir
    ~/.local/share/atlas.  This is a regression guard for the string-prefix
    boundary check used in the optimized _is_path_within_bootstrap_dirs().
    """
    manager = PolicyManager(mock_config)

    # Inject a known managed dir to deterministically test the edge case.
    managed_parent = paths.HOME / ".local" / "share" / "atlas"
    manager._managed_dir_strs = [str(managed_parent.resolve())]

    # Path *inside* the managed dir is allowed.
    inside_path = managed_parent / "bin" / "age"
    manager.check_write(inside_path)  # should not raise

    # Sibling directory that shares a textual prefix but is NOT inside.
    sibling_path = paths.HOME / ".local" / "share" / "atlas-evil" / "payload"
    with pytest.raises(
        PolicyViolationError,
        match="restricted to bootstrap-managed directories",
    ):
        manager.check_write(sibling_path)


def test_policy_all_managed_dir_types_allowed(mock_config, monkeypatch):
    """Each of the four managed directory types must be recognized."""
    monkeypatch.setattr(
        paths, "get_app_data_dir", lambda: paths.HOME / "share" / "atlas"
    )
    monkeypatch.setattr(
        paths, "get_app_cache_dir", lambda: paths.HOME / "cache" / "atlas"
    )
    monkeypatch.setattr(
        paths, "get_app_config_dir", lambda: paths.HOME / "config" / "atlas"
    )
    monkeypatch.setattr(
        paths, "get_app_state_dir", lambda: paths.HOME / "state" / "atlas"
    )

    manager = PolicyManager(mock_config)

    for managed in manager._managed_dirs:
        manager.check_write(managed / "nested" / "file")


def test_policy_glob_matchers_precompiled(mock_config):
    """Include/exclude globs are compiled to regex matchers once at init.

    This guards the performance optimisation that hoists fnmatch pattern
    compilation out of the per-call check_write() hot path.
    """
    import re

    mock_config.policy.include = ["${HOME}/Downloads/safe_dir/**"]
    mock_config.policy.exclude = ["${HOME}/workspace/**"]
    manager = PolicyManager(mock_config)

    assert len(manager._exclude_matchers) == 1
    assert len(manager._include_matchers) == 1
    assert all(isinstance(m, re.Pattern) for m in manager._exclude_matchers)
    assert all(isinstance(m, re.Pattern) for m in manager._include_matchers)


def test_policy_include_matches_non_first_pattern(mock_config, monkeypatch):
    """A path matching a later include glob (not the first) is still allowed.

    Regression guard: the optimised _is_path_included() must iterate *all*
    compiled matchers, not just the first one.
    """
    mock_config.policy.include = [
        "${HOME}/Downloads/first_dir/**",
        "${HOME}/Downloads/second_dir/**",
    ]
    manager = PolicyManager(mock_config)

    monkeypatch.setattr(paths, "get_app_data_dir", lambda: Path())
    monkeypatch.setattr(paths, "get_app_cache_dir", lambda: Path())
    monkeypatch.setattr(paths, "get_app_config_dir", lambda: Path())
    monkeypatch.setattr(paths, "get_app_state_dir", lambda: Path())

    # Matches only the *second* include glob.
    allowed = paths.HOME / "Downloads" / "second_dir" / "installer.sh"
    manager.check_write(allowed)  # must not raise

    disallowed = paths.HOME / "Downloads" / "third_dir" / "file.txt"
    with pytest.raises(
        PolicyViolationError, match="not covered by any 'include' rules"
    ):
        manager.check_write(disallowed)


def test_policy_precompiled_matches_fnmatch_semantics(mock_config, monkeypatch):
    """The precompiled matchers reproduce fnmatch.fnmatch() results exactly.

    Cross-checks a range of representative paths against the reference
    fnmatch implementation to prove the optimisation preserved semantics
    (including single-segment '*' wildcards, which must not match '/').
    """
    import fnmatch
    import os

    mock_config.policy.include = []
    mock_config.policy.exclude = [
        "${HOME}/workspace/**",
        "${HOME}/*.log",
    ]
    manager = PolicyManager(mock_config)

    resolved_excludes = manager._resolved_exclude_globs
    candidates = [
        paths.HOME / "workspace" / "proj" / "main.py",
        paths.HOME / "debug.log",
        paths.HOME / "sub" / "debug.log",  # '*' must NOT cross '/'
        paths.HOME / "Documents" / "notes.txt",
    ]
    for cand in candidates:
        abs_path = str(cand.resolve())
        reference = any(fnmatch.fnmatch(abs_path, p) for p in resolved_excludes)
        optimised = manager._is_path_excluded(os.path.normcase(abs_path))
        assert reference == optimised, (abs_path, reference, optimised)
