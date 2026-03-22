# src/atlas_onboard/policy.py
"""Filesystem access policy enforcer."""

import fnmatch
from pathlib import Path

from .config import BootstrapConfig
from .errors import PolicyViolationError


class PolicyManager:
    """Enforces the filesystem access policy defined in the configuration."""

    def __init__(self, config: BootstrapConfig):
        self._config = config
        self._resolved_include_globs = [
            str(config.resolve_path(p)) for p in config.policy.include
        ]
        self._resolved_exclude_globs = [
            str(config.resolve_path(p)) for p in config.policy.exclude
        ]

    def _is_path_excluded(self, path: Path) -> bool:
        """Check if a path matches any of the exclude globs."""
        abs_path = str(path.resolve())
        for pattern in self._resolved_exclude_globs:
            if fnmatch.fnmatch(abs_path, pattern):
                return True
        return False

    def _is_path_included(self, path: Path) -> bool:
        """Check if a path matches any of the include globs."""
        if not self._resolved_include_globs:
            return False

        abs_path = str(path.resolve())
        for pattern in self._resolved_include_globs:
            if fnmatch.fnmatch(abs_path, pattern):
                return True
        return False

    def _is_path_within_bootstrap_dirs(self, path: Path) -> bool:
        """Check if a path is within one of the app's managed XDG directories."""
        from . import paths

        abs_path = path.resolve()
        managed_dirs = [
            paths.get_app_data_dir(),
            paths.get_app_config_dir(),
            paths.get_app_state_dir(),
            paths.get_app_cache_dir(),
        ]
        return any(
            abs_path.is_relative_to(managed_dir.resolve())
            for managed_dir in managed_dirs
        )

    def check_write(self, path: Path) -> None:
        """Verifies that a write to the given path is allowed by the policy."""
        if self._is_path_excluded(path):
            raise PolicyViolationError(
                f"Write to '{path}' is forbidden by an exclude rule in the policy."
            )

        if self._is_path_included(path):
            return

        if self._is_path_within_bootstrap_dirs(path):
            return

        if self._resolved_include_globs:
            raise PolicyViolationError(
                f"Write to '{path}' is forbidden. It is not covered by any "
                f"'include' rules in the policy and is outside standard "
                f"bootstrap directories."
            )
        else:
            raise PolicyViolationError(
                f"Write to '{path}' is forbidden. The policy has no 'include' "
                f"rules, so writes are restricted to bootstrap-managed directories."
            )


_policy_manager = None


def get_policy_manager(config: BootstrapConfig) -> PolicyManager:
    """Returns a singleton instance of the PolicyManager."""
    global _policy_manager
    if _policy_manager is None:
        _policy_manager = PolicyManager(config)
    return _policy_manager
