# src/atlasonboard/logging.py
"""Structured JSON logging with redaction."""

import logging
import sys
from typing import Any

from .config import BootstrapConfig

# A set of keys that should be redacted from logs.
REDACTED_KEYS = {"client_secret", "token", "passphrase"}


class RedactingFilter(logging.Filter):
    """A logging filter that redacts sensitive information."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, dict):
            record.args = self._redact_dict(record.args)
        return True

    def _redact_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        """Recursively redact sensitive keys in a dictionary."""
        redacted_data = {}
        for key, value in data.items():
            if key in REDACTED_KEYS:
                redacted_data[key] = "[REDACTED]"
            elif isinstance(value, dict):
                redacted_data[key] = self._redact_dict(value)
            else:
                redacted_data[key] = value
        return redacted_data


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
                    "atlasonboard": {
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
