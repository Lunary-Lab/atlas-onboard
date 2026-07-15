# tests/unit/test_paths.py
"""Unit tests for the XDG path helpers in ``atlas_onboard.paths``.

These cover the ``@lru_cache`` optimization applied to the application
directory helpers: repeated calls must be served from the cache and must
not issue redundant ``mkdir()`` syscalls.
"""

from pathlib import Path

import pytest

from atlas_onboard import paths

# All lru_cache-decorated helpers in the module.  lru_cache state persists for
# the whole process, so we reset it around every test to keep them isolated.
_CACHED_HELPERS = (
    paths.get_xdg_data_home,
    paths.get_xdg_config_home,
    paths.get_xdg_state_home,
    paths.get_xdg_cache_home,
    paths.get_app_data_dir,
    paths.get_app_config_dir,
    paths.get_app_state_dir,
    paths.get_app_cache_dir,
    paths.get_bin_dir,
)


def _reset_caches():
    """Clear any lru_cache state, tolerating helpers that are not cached."""
    for fn in _CACHED_HELPERS:
        cache_clear = getattr(fn, "cache_clear", None)
        if cache_clear is not None:
            cache_clear()


@pytest.fixture(autouse=True)
def _clear_path_caches():
    """Start and end each test with cold path caches."""
    _reset_caches()
    yield
    _reset_caches()


def test_get_app_data_dir_returns_expected_path_and_creates_it(tmp_path, monkeypatch):
    """The helper returns ``<XDG_DATA_HOME>/atlas`` and creates the directory."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    result = paths.get_app_data_dir()

    assert result == tmp_path / "atlas"
    assert result.is_dir()


def test_get_bin_dir_returns_expected_path_and_creates_it(tmp_path, monkeypatch):
    """``get_bin_dir`` returns ``<XDG_DATA_HOME>/atlas/bin`` and creates it."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    result = paths.get_bin_dir()

    assert result == tmp_path / "atlas" / "bin"
    assert result.is_dir()


def test_app_dir_helpers_are_cached(tmp_path, monkeypatch):
    """Repeated calls return the identical cached object (one miss, then hits)."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    first = paths.get_app_data_dir()
    second = paths.get_app_data_dir()

    assert first is second
    info = paths.get_app_data_dir.cache_info()
    assert info.misses == 1
    assert info.hits == 1


def test_get_bin_dir_avoids_repeated_mkdir_syscalls(tmp_path, monkeypatch):
    """PERF regression guard: cached helpers must not re-issue ``mkdir()``.

    The first call warms the cache (creating the directories), but every
    subsequent call must be served entirely from cache with zero additional
    ``mkdir()`` syscalls.  If the ``@lru_cache`` optimization is removed this
    assertion fails because each call would issue fresh syscalls.
    """
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    mkdir_calls = {"count": 0}
    real_mkdir = Path.mkdir

    def counting_mkdir(self, *args, **kwargs):
        mkdir_calls["count"] += 1
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", counting_mkdir)

    first = paths.get_bin_dir()
    warm_calls = mkdir_calls["count"]
    assert warm_calls >= 1  # directories are created on first use

    for _ in range(50):
        assert paths.get_bin_dir() is first

    # No further mkdir() syscalls were issued for the 50 cached lookups.
    assert mkdir_calls["count"] == warm_calls
