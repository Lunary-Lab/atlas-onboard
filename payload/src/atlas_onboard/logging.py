# src/atlas_onboard/logging.py
"""Structured JSON logging with redaction."""

import logging
import os
import sys
from typing import Any

from .config import BootstrapConfig

# A set of keys that should be redacted from logs.
# Expanded to cover all secret names used by atlas-onboard so that none
# of the two-gate credentials or token data can leak through log output.
REDACTED_KEYS = {
    "client_secret",
    "token",
    "passphrase",
    "password",
    "master_password",
    "master_key",
    "shared_secret",
    "refresh_token",
    "access_token",
    "secret",
    "api_key",
    "apikey",
    "private_key",
}

# Values whose appearance in a log message should be masked.
# These are the env-var and store key names used throughout the app;
# if the variable's *value* ends up in a message it is replaced.
_SENSITIVE_ENV_VARS = (
    "ATLAS_ONBOARD_PASSWORD",
    "ATLAS_ONBOARD_TWO_FACTOR_SECRET",
    "SB_BOOTSTRAP_CLIENT_SECRET",
    "MASTER_KEY",
)

_REDACTED_PLACEHOLDER = "[REDACTED]"

# Values shorter than this are ignored when scrubbing message text: masking a
# 1-3 character substring would clobber unrelated content for no security gain.
_MIN_SCRUBBABLE_LEN = 4


class RedactingFilter(logging.Filter):
    """A logging filter that redacts sensitive information.

    Two layers of defence:
    1. **Structured args** -- dictionary keys matching ``REDACTED_KEYS`` are
       replaced with the placeholder.
    2. **Message text** -- if the formatted message contains a known secret
       value (e.g. the contents of an environment variable) that substring
       is masked before the record is emitted.  This guards against the
       common pattern of embedding credentials directly in an f-string.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact sensitive data from the log record before emission."""
        if isinstance(record.args, dict):
            record.args = self._redact_dict(record.args)

        # PERF: message-text scrubbing requires rendering the record via
        # ``record.getMessage()`` (which performs ``msg % args`` formatting) and
        # then scanning the result.  That render is redundant work on the logging
        # hot path -- the handler's formatter renders the message again later.
        # When *no* sensitive env var is currently set (the common case), the
        # scrub can never change anything, so we skip the whole render+scan pass
        # entirely.  Collecting the active secret values once here also avoids
        # re-reading the environment inside ``_scrub_message``.
        secret_values = self._active_secret_values()
        if secret_values:
            msg = record.getMessage()
            scrubbed = self._scrub_message(msg, secret_values)
            if scrubbed != msg:
                record.msg = scrubbed
                record.args = None  # msg already rendered
        return True

    @staticmethod
    def _redact_dict(data: dict[str, Any]) -> dict[str, Any]:
        """Recursively redact sensitive keys in a dictionary.

        PERF: this runs on the structured-logging hot path -- ``filter()``
        invokes it for *every* log record whose ``args`` is a dict.  The
        overwhelmingly common record carries **no** sensitive key, yet the
        previous implementation unconditionally allocated a brand-new dict
        (plus a fresh nested dict for every sub-mapping) on each call.
        Redaction is now copy-on-write: the mapping is scanned in place and
        a shallow copy is materialised only once a key actually needs
        redacting (or a nested dict changed).  When nothing needs redacting
        the *original* object is returned untouched, eliminating the
        per-record deep-copy allocation from the no-secret path.  Redaction
        output is identical to the previous behaviour: every sensitive key
        at every nesting level is still replaced with the placeholder.
        """
        result = data
        for key, value in data.items():
            if key.lower() in REDACTED_KEYS:
                new_value: Any = _REDACTED_PLACEHOLDER
            elif isinstance(value, dict):
                new_value = RedactingFilter._redact_dict(value)
                # A nested dict with no sensitive keys is returned as the
                # same object, so there is nothing to copy for this key.
                if new_value is value:
                    continue
            else:
                # Non-sensitive scalar (or non-dict) value: leave as-is.
                continue

            # First actual change for this mapping: copy-on-write once so
            # the caller's object is never mutated, then record the change.
            if result is data:
                result = dict(data)
            result[key] = new_value

        return result

    @staticmethod
    def _active_secret_values() -> list[str]:
        """Return the currently-set sensitive env var values worth scrubbing.

        Only values of at least ``_MIN_SCRUBBABLE_LEN`` characters are returned,
        mirroring the guard previously embedded in ``_scrub_message``.  This is
        computed once per record so ``filter`` can cheaply decide whether the
        (relatively expensive) message render is needed at all.
        """
        values = []
        for var_name in _SENSITIVE_ENV_VARS:
            value = os.environ.get(var_name)
            if value and len(value) >= _MIN_SCRUBBABLE_LEN:
                values.append(value)
        return values

    @staticmethod
    def _scrub_message(msg: str, secret_values: list[str] | None = None) -> str:
        """Replace occurrences of known secret values in a message string.

        ``secret_values`` may be supplied by the caller (see ``filter``) to
        avoid re-reading the environment; when omitted it is resolved lazily so
        the method remains usable on its own.
        """
        if secret_values is None:
            secret_values = RedactingFilter._active_secret_values()

        result = msg
        for value in secret_values:
            result = result.replace(value, _REDACTED_PLACEHOLDER)
        return result


def setup_logging(config: BootstrapConfig):
    """Configure the root logger for the application."""
    log_level = config.logging.level.upper()

    if config.logging.json_format:
        from logging.config import dictConfig

        dictConfig(
            {
                "version": 1,
                "disable_existing_loggers": False,
                "filters": {
                    "redacting": {
                        "()": RedactingFilter,
                    },
                },
                "formatters": {
                    "json": {
                        "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
                        "format": "%(asctime)s %(name)s %(levelname)s %(message)s",
                    },
                },
                "handlers": {
                    "json": {
                        "class": "logging.StreamHandler",
                        "formatter": "json",
                        "filters": ["redacting"],
                    },
                },
                "loggers": {
                    "atlas_onboard": {
                        "handlers": ["json"],
                        "level": log_level,
                        "propagate": False,
                    },
                    "": {  # Root logger
                        "handlers": ["json"],
                        "level": log_level,
                    },
                },
            }
        )
    else:
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            stream=sys.stderr,
        )
        for handler in logging.root.handlers:
            handler.addFilter(RedactingFilter())
