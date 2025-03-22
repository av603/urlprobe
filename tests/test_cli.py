"""Tests for the CLI module."""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from urlprobe import cli


@pytest.fixture
def mock_app():
    """Create a mock Flask app."""
    app = MagicMock()
    app.run = MagicMock()
    return app


@pytest.fixture
def runner():
    """Create a Click test runner."""
    return CliRunner()


def test_cli_group(runner):
    """Test that the CLI group is accessible."""
    # Click groups require a subcommand, so invoking without one shows help
    result = runner.invoke(cli.cli, [])
    # Exit code 2 is expected when no subcommand is provided
    assert result.exit_code == 2
    assert "Usage:" in result.output


def test_serve_command_default_args(runner, mock_app):
    """Test serve command with default arguments."""
    with patch("urlprobe.cli.create_app", return_value=mock_app):
        result = runner.invoke(cli.serve, [])

    assert result.exit_code == 0
    mock_app.run.assert_called_once_with(
        host="127.0.0.1", port=8080, debug=False
    )


def test_serve_command_custom_host(runner, mock_app):
    """Test serve command with custom host."""
    with patch("urlprobe.cli.create_app", return_value=mock_app):
        result = runner.invoke(cli.serve, ["--host", "0.0.0.0"])

    assert result.exit_code == 0
    mock_app.run.assert_called_once_with(
        host="0.0.0.0", port=8080, debug=False
    )


def test_serve_command_custom_port(runner, mock_app):
    """Test serve command with custom port."""
    with patch("urlprobe.cli.create_app", return_value=mock_app):
        result = runner.invoke(cli.serve, ["--port", "9000"])

    assert result.exit_code == 0
    mock_app.run.assert_called_once_with(
        host="127.0.0.1", port=9000, debug=False
    )


def test_serve_command_debug_flag(runner, mock_app):
    """Test serve command with debug flag."""
    with patch("urlprobe.cli.create_app", return_value=mock_app):
        result = runner.invoke(cli.serve, ["--debug"])

    assert result.exit_code == 0
    mock_app.run.assert_called_once_with(
        host="127.0.0.1", port=8080, debug=True
    )


def test_serve_command_all_options(runner, mock_app):
    """Test serve command with all options."""
    with patch("urlprobe.cli.create_app", return_value=mock_app):
        result = runner.invoke(
            cli.serve, ["--host", "192.168.1.1", "--port", "5000", "--debug"]
        )

    assert result.exit_code == 0
    mock_app.run.assert_called_once_with(
        host="192.168.1.1", port=5000, debug=True
    )


def test_serve_command_help(runner):
    """Test serve command help output."""
    result = runner.invoke(cli.serve, ["--help"])
    assert result.exit_code == 0
    assert "Start the Flask server" in result.output
    assert "--host" in result.output
    assert "--port" in result.output
    assert "--debug" in result.output


def test_main_function(runner):
    """Test the main() function."""
    with patch("urlprobe.cli.cli") as mock_cli:
        cli.main()
        mock_cli.assert_called_once()


def test_cli_main_entry_point(runner):
    """Test CLI main entry point through the group."""
    result = runner.invoke(cli.cli, ["serve", "--help"])
    assert result.exit_code == 0
    assert "Start the Flask server" in result.output
