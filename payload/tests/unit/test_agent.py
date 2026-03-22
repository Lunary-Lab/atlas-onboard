# tests/unit/test_agent.py
import os

from pytest_mock import MockerFixture

from atlasonboard import agent


def test_agent_manager_posix_existing(mocker: MockerFixture):
    mocker.patch.dict(os.environ, {"SSH_AUTH_SOCK": "/tmp/agent.sock"})
    mocker.patch("atlasonboard.paths.is_windows", return_value=False)
    mock_popen = mocker.patch("subprocess.Popen")

    with agent.SshAgentManager():
        pass

    mock_popen.assert_not_called()


def test_agent_manager_posix_start_new(mocker: MockerFixture, monkeypatch):
    monkeypatch.delenv("SSH_AUTH_SOCK", raising=False)
    mocker.patch("atlasonboard.paths.is_windows", return_value=False)

    mock_proc = mocker.Mock()
    mock_proc.communicate.return_value = (
        "SSH_AUTH_SOCK=/tmp/agent.sock; export SSH_AUTH_SOCK;\nSSH_AGENT_PID=1234; export SSH_AGENT_PID;\necho Agent pid 1234;",
        "",
    )
    mock_proc.returncode = 0
    mock_popen = mocker.patch("subprocess.Popen", return_value=mock_proc)

    with agent.SshAgentManager():
        assert os.environ["SSH_AUTH_SOCK"] == "/tmp/agent.sock"
        assert os.environ["SSH_AGENT_PID"] == "1234"

    assert "SSH_AUTH_SOCK" not in os.environ

    mock_popen.assert_called_once()
    mock_proc.terminate.assert_called_once()


def test_agent_manager_windows_running(mocker: MockerFixture):
    mocker.patch("atlasonboard.paths.is_windows", return_value=True)
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value.stdout = "Running"

    with agent.SshAgentManager():
        pass

    mock_run.assert_called_once()


def test_agent_manager_windows_start_service(mocker: MockerFixture):
    mocker.patch("atlasonboard.paths.is_windows", return_value=True)
    mock_run = mocker.patch("subprocess.run")
    mock_run.side_effect = [
        mocker.Mock(stdout="Stopped"),
        mocker.Mock(),
        mocker.Mock(stdout="Running"),
    ]

    with agent.SshAgentManager():
        pass

    assert mock_run.call_count == 3
    assert "Start-Service ssh-agent" in mock_run.call_args_list[1].args[0]


def test_agent_add_key(mocker: MockerFixture):
    mocker.patch("atlasonboard.paths.is_windows", return_value=False)
    mock_run = mocker.patch("subprocess.run")

    manager = agent.SshAgentManager()
    manager.add_key(b"PRIVATE KEY DATA")

    mock_run.assert_called_once_with(
        ["ssh-add", "-"], input=b"PRIVATE KEY DATA", capture_output=True, check=True
    )
