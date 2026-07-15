"""Tests for the CLI, focused on the ``doctor`` summary UX."""

from contextlib import contextmanager

import pytest
from typer.testing import CliRunner

from atlas_onboard import cli
from atlas_onboard.cli import app, build_doctor_summary

runner = CliRunner()


def test_summary_all_passed_is_positive_and_has_no_failure_marker():
    msg = build_doctor_summary(0, 5)
    assert "All 5 checks passed" in msg
    assert "\u274c" not in msg  # no red ❌ cross-mark when healthy
    assert "green" in msg


def test_summary_single_failure_uses_singular_and_actionable_next_step():
    msg = build_doctor_summary(1, 5)
    assert "1 of 5 check failed" in msg  # singular, not "checks"
    assert "4 passed" in msg
    assert "re-run" in msg
    assert "atlas_onboard doctor" in msg


def test_summary_multiple_failures_uses_plural():
    msg = build_doctor_summary(2, 5)
    assert "2 of 5 checks failed" in msg  # plural
    assert "3 passed" in msg


def test_summary_distinguishes_healthy_from_unhealthy():
    # Regression/negative guard: a broken implementation returning a constant
    # string would fail here.
    assert build_doctor_summary(0, 5) != build_doctor_summary(1, 5)


@contextmanager
def _fake_agent_ok():
    yield object()


def test_doctor_command_prints_all_passed_summary(monkeypatch):
    # Isolate from the host: no config load, all checks succeed.
    monkeypatch.setattr(cli.config, "load_config", lambda *a, **k: None)
    from atlas_onboard import util, agent

    monkeypatch.setattr(util, "find_in_path", lambda _binary: "/usr/bin/x")
    monkeypatch.setattr(agent, "SshAgentManager", _fake_agent_ok)

    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    out = " ".join(result.output.split())  # collapse rich line-wrapping
    assert "All 5 checks passed" in out


def test_doctor_command_reports_failures_in_summary(monkeypatch):
    monkeypatch.setattr(cli.config, "load_config", lambda *a, **k: None)
    from atlas_onboard import util, agent

    # All three required binaries missing -> 3 failures out of 5 checks.
    monkeypatch.setattr(util, "find_in_path", lambda _binary: None)
    monkeypatch.setattr(agent, "SshAgentManager", _fake_agent_ok)

    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    out = " ".join(result.output.split())  # collapse rich line-wrapping
    assert "3 of 5 checks failed" in out
    assert "re-run" in out
