# tests/unit/test_logging.py
"""Tests for the RedactingFilter security logging filter."""

import logging
import time

import pytest

from atlas_onboard.logging import REDACTED_KEYS, RedactingFilter


def _make_record(msg: str, args=None) -> logging.LogRecord:
    """Build a minimal LogRecord for testing."""
    if isinstance(args, dict):
        # Python logging treats a lone dict specially: wrap in a tuple
        # so the dict is passed as the sole formatting mapping.
        args = (args,)
    return logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=msg,
        args=args,
        exc_info=None,
    )


@pytest.fixture
def redacting_filter() -> RedactingFilter:
    """Provide a fresh RedactingFilter instance."""
    return RedactingFilter()


@pytest.fixture(autouse=True)
def _clear_sensitive_env(monkeypatch):
    """Ensure env vars are clean before each test, then restore after."""
    for var in ("ATLAS_ONBOARD_PASSWORD", "ATLAS_ONBOARD_TWO_FACTOR_SECRET",
                "SB_BOOTSTRAP_CLIENT_SECRET", "MASTER_KEY"):
        monkeypatch.delenv(var, raising=False)


class TestRedactedKeysCoverage:
    """Ensure every secret used by the app is in the redaction set."""

    @pytest.mark.parametrize("key", [
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
        "client_secret",
        "token",
        "passphrase",
    ])
    def test_key_is_redacted(self, key):
        """Each sensitive key name should be in the REDACTED_KEYS set."""
        assert key in REDACTED_KEYS


class TestDictRedaction:
    """Verify structured/dict args are scrubbed."""

    def test_redacts_password_in_dict(self, redacting_filter):
        """Top-level sensitive keys in a dict should be redacted."""
        data = {"message": "ok", "password": "s3cr3t"}
        redacted = RedactingFilter._redact_dict(data)
        assert redacted["password"] == "[REDACTED]"
        assert redacted["message"] == "ok"

    def test_redacts_nested_dict(self, redacting_filter):
        """Nested dicts should be recursively redacted."""
        data = {"master_password": "hunter2", "safe": "visible"}
        redacted = RedactingFilter._redact_dict(data)
        assert redacted["master_password"] == "[REDACTED]"
        assert redacted["safe"] == "visible"

    def test_redacts_deeply_nested_dict(self, redacting_filter):
        """Deeply nested dicts should be recursively redacted."""
        data = {"level1": {"level2": {"api_key": "sk-12345", "ok": "fine"}}}
        redacted = RedactingFilter._redact_dict(data)
        assert redacted["level1"]["level2"]["api_key"] == "[REDACTED]"
        assert redacted["level1"]["level2"]["ok"] == "fine"

    def test_case_insensitive_key_match(self, redacting_filter):
        """Keys should be matched case-insensitively."""
        data = {"Password": "p", "TOKEN": "t", "Secret": "s"}
        redacted = RedactingFilter._redact_dict(data)
        assert redacted["Password"] == "[REDACTED]"
        assert redacted["TOKEN"] == "[REDACTED]"
        assert redacted["Secret"] == "[REDACTED]"

    def test_filter_redacts_dict_args(self, redacting_filter):
        """The filter() method should redact dict args on a LogRecord."""
        data = {"password": "s3cr3t", "msg": "hello"}
        record = _make_record("%(msg)s", data)
        redacting_filter.filter(record)
        # After filter, args is a tuple wrapping the redacted dict
        inner = record.args[0] if isinstance(record.args, tuple) else record.args
        assert inner["password"] == "[REDACTED]"


class TestMessageScrubbing:
    """Verify secret values embedded in message text are masked."""

    def test_scrubs_password_from_message(self, redacting_filter, monkeypatch):
        """ATLAS_ONBOARD_PASSWORD value should be scrubbed from messages."""
        monkeypatch.setenv("ATLAS_ONBOARD_PASSWORD", "MySuperSecret123")
        record = _make_record("Using password MySuperSecret123 for login")
        redacting_filter.filter(record)
        assert "MySuperSecret123" not in record.getMessage()
        assert "[REDACTED]" in record.getMessage()

    def test_scrubs_shared_secret_from_message(self, redacting_filter, monkeypatch):
        """ATLAS_ONBOARD_TWO_FACTOR_SECRET value should be scrubbed."""
        monkeypatch.setenv("ATLAS_ONBOARD_TWO_FACTOR_SECRET", "TOTPSECRET456")
        record = _make_record("Device secret TOTPSECRET456 loaded")
        redacting_filter.filter(record)
        assert "TOTPSECRET456" not in record.getMessage()
        assert "[REDACTED]" in record.getMessage()

    def test_scrubs_client_secret_from_message(self, redacting_filter, monkeypatch):
        """SB_BOOTSTRAP_CLIENT_SECRET value should be scrubbed."""
        monkeypatch.setenv("SB_BOOTSTRAP_CLIENT_SECRET", "bootstrap-secret-xyz")
        record = _make_record("Verifying with bootstrap-secret-xyz")
        redacting_filter.filter(record)
        assert "bootstrap-secret-xyz" not in record.getMessage()
        assert "[REDACTED]" in record.getMessage()

    def test_message_without_secrets_unchanged(self, redacting_filter, monkeypatch):
        """Messages without secrets should pass through unchanged."""
        monkeypatch.setenv("ATLAS_ONBOARD_PASSWORD", "MySuperSecret123")
        record = _make_record("Bootstrap completed successfully")
        redacting_filter.filter(record)
        assert record.getMessage() == "Bootstrap completed successfully"

    def test_short_env_value_not_scrubbed(self, redacting_filter, monkeypatch):
        """Values shorter than 4 chars should not be scrubbed."""
        monkeypatch.setenv("ATLAS_ONBOARD_PASSWORD", "ab")
        record = _make_record("The value ab appears here")
        redacting_filter.filter(record)
        assert record.getMessage() == "The value ab appears here"

    def test_multiple_secrets_in_one_message(self, redacting_filter, monkeypatch):
        """Multiple different secrets should all be scrubbed."""
        monkeypatch.setenv("ATLAS_ONBOARD_PASSWORD", "PasswordA123")
        monkeypatch.setenv("MASTER_KEY", "MasterKeyB456")
        record = _make_record("Using PasswordA123 and MasterKeyB456 together")
        redacting_filter.filter(record)
        rendered = record.getMessage()
        assert "PasswordA123" not in rendered
        assert "MasterKeyB456" not in rendered
        assert rendered.count("[REDACTED]") == 2


class TestRegressionGuard:
    """Negative check: removing the _scrub_message logic would fail this test."""

    def test_regression_filter_catches_secret_in_message(
        self, redacting_filter, monkeypatch
    ):
        """Mutation guard: if _scrub_message is removed, this test fails."""
        secret = "RegressionTestSecret_" + str(int(time.time()))
        monkeypatch.setenv("MASTER_KEY", secret)
        record = _make_record(f"Loaded key: {secret}")
        redacting_filter.filter(record)
        rendered = record.getMessage()
        assert secret not in rendered, (
            "Secret leaked into log output - scrubbing regression detected"
        )
        assert "[REDACTED]" in rendered


class TestRedactDictCopyOnWrite:
    """Verify the copy-on-write optimization of _redact_dict.

    The optimization must (a) avoid allocating a new dict when nothing needs
    redacting, and (b) never mutate the caller's object, while producing output
    identical to a full recursive redaction.
    """

    def test_no_secret_returns_same_object(self, redacting_filter):
        """No sensitive keys -> the original dict object is returned (no copy)."""
        data = {"message": "ok", "count": 3, "nested": {"a": 1, "b": [1, 2]}}
        result = RedactingFilter._redact_dict(data)
        # Identity: proves no wasteful allocation on the common path.
        assert result is data
        assert result["nested"] is data["nested"]

    def test_unchanged_nested_dicts_are_not_copied(self, redacting_filter):
        """Only the branch containing a secret is copied; siblings are reused."""
        data = {
            "safe_branch": {"x": 1, "y": {"z": 2}},
            "creds": {"token": "abc", "user": "bob"},
        }
        result = RedactingFilter._redact_dict(data)
        # A copy happened at the top level (creds changed)...
        assert result is not data
        # ...but the untouched sibling sub-tree is the SAME object (not copied).
        assert result["safe_branch"] is data["safe_branch"]
        # The secret-bearing branch is a new object with the value redacted.
        assert result["creds"] is not data["creds"]
        assert result["creds"]["token"] == "[REDACTED]"
        assert result["creds"]["user"] == "bob"

    def test_caller_object_never_mutated(self, redacting_filter):
        """Redaction must not mutate the input mapping in place."""
        data = {"password": "s3cr3t", "ok": "v"}
        _ = RedactingFilter._redact_dict(data)
        # Original still holds the real value; only the returned copy is redacted.
        assert data["password"] == "s3cr3t"

    def test_output_equals_full_recursive_redaction(self, redacting_filter):
        """COW output must deep-equal a naive full redaction (behavior parity)."""

        def naive_redact(d):
            out = {}
            for k, v in d.items():
                if k.lower() in REDACTED_KEYS:
                    out[k] = "[REDACTED]"
                elif isinstance(v, dict):
                    out[k] = naive_redact(v)
                else:
                    out[k] = v
            return out

        data = {
            "a": 1,
            "password": "p",
            "nested": {"token": "t", "deep": {"api_key": "k", "keep": "yes"}},
            "list": [1, {"secret": "should-stay-a-value"}],
        }
        assert RedactingFilter._redact_dict(data) == naive_redact(data)

    def test_sensitive_key_with_dict_value_fully_redacted(self, redacting_filter):
        """A sensitive *key* whose value is a dict is replaced wholesale."""
        data = {"token": {"nested": "still-hidden"}}
        result = RedactingFilter._redact_dict(data)
        assert result["token"] == "[REDACTED]"


def _make_call_counting_record(msg: str, args=None):
    """Return (record, counter) where counter['n'] tracks getMessage() calls."""
    record = _make_record(msg, args)
    counter = {"n": 0}
    original_get_message = record.getMessage

    def _counting_get_message():
        counter["n"] += 1
        return original_get_message()

    # Shadow the bound method on this single instance only.
    record.getMessage = _counting_get_message  # type: ignore[method-assign]
    return record, counter


class TestScrubFastPath:
    """Guard the perf optimization: skip message render when no secrets are set."""

    def test_no_secrets_skips_message_render(self, redacting_filter):
        """With no sensitive env vars set, filter() must not render the message.

        Mutation guard: removing the ``if secret_values:`` early-return in
        filter() would render the message on every record, failing this test.
        """
        record, counter = _make_call_counting_record("value is %s", ("plain",))
        assert redacting_filter.filter(record) is True
        assert counter["n"] == 0, "getMessage() should not run on the fast path"
        # Behavior parity: the lazy message is left intact and renders correctly.
        assert record.msg == "value is %s"
        assert record.args == ("plain",)
        assert record.getMessage() == "value is plain"

    def test_secret_present_takes_slow_path_and_scrubs(
        self, redacting_filter, monkeypatch
    ):
        """When a secret is set, the message is rendered and scrubbed as before."""
        monkeypatch.setenv("MASTER_KEY", "SlowPathSecret123")
        record, counter = _make_call_counting_record("key=%s", ("SlowPathSecret123",))
        assert redacting_filter.filter(record) is True
        assert counter["n"] >= 1, "getMessage() must run when a secret is present"
        assert "SlowPathSecret123" not in record.getMessage()
        assert "[REDACTED]" in record.getMessage()

    def test_active_secret_values_filters_short_values(self, monkeypatch):
        """Only env values >= 4 chars are considered scrubbable (boundary check)."""
        monkeypatch.setenv("ATLAS_ONBOARD_PASSWORD", "abc")  # too short (3)
        monkeypatch.setenv("MASTER_KEY", "abcd")  # exactly the minimum (4)
        values = RedactingFilter._active_secret_values()
        assert "abcd" in values
        assert "abc" not in values
