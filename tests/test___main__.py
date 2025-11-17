"""Tests for the __main__ module."""

from unittest.mock import MagicMock, patch

import pytest

from urlprobe import __main__


@pytest.fixture
def mock_app():
    """Create a mock Flask app."""
    app = MagicMock()
    app.run = MagicMock()
    return app


def test_main_default_args(mock_app):
    """Test main() with default arguments."""
    with patch("sys.argv", ["urlprobe"]):
        with patch(
            "urlprobe.__main__.create_app", return_value=mock_app
        ) as mock_create_app:
            with patch("urlprobe.__main__.logger") as mock_logger:
                __main__.main()

    mock_create_app.assert_called_once()
    mock_logger.info.assert_called_once_with(
        "Starting urlprobe on host 0.0.0.0, port 8080, debug=False"
    )
    mock_app.run.assert_called_once_with(
        host="0.0.0.0", port=8080, debug=False
    )


def test_main_custom_host(mock_app):
    """Test main() with custom host."""
    with patch("sys.argv", ["urlprobe", "--host", "127.0.0.1"]):
        with patch(
            "urlprobe.__main__.create_app", return_value=mock_app
        ) as mock_create_app:
            with patch("urlprobe.__main__.logger") as mock_logger:
                __main__.main()

    mock_create_app.assert_called_once()
    mock_logger.info.assert_called_once_with(
        "Starting urlprobe on host 127.0.0.1, port 8080, debug=False"
    )
    mock_app.run.assert_called_once_with(
        host="127.0.0.1", port=8080, debug=False
    )


def test_main_custom_port(mock_app):
    """Test main() with custom port."""
    with patch("sys.argv", ["urlprobe", "--port", "9000"]):
        with patch(
            "urlprobe.__main__.create_app", return_value=mock_app
        ) as mock_create_app:
            with patch("urlprobe.__main__.logger") as mock_logger:
                __main__.main()

    mock_create_app.assert_called_once()
    mock_logger.info.assert_called_once_with(
        "Starting urlprobe on host 0.0.0.0, port 9000, debug=False"
    )
    mock_app.run.assert_called_once_with(
        host="0.0.0.0", port=9000, debug=False
    )


def test_main_debug_mode(mock_app):
    """Test main() with debug mode enabled."""
    with patch("sys.argv", ["urlprobe", "--debug"]):
        with patch(
            "urlprobe.__main__.create_app", return_value=mock_app
        ) as mock_create_app:
            with patch("urlprobe.__main__.logger") as mock_logger:
                __main__.main()

    mock_create_app.assert_called_once()
    mock_logger.info.assert_called_once_with(
        "Starting urlprobe on host 0.0.0.0, port 8080, debug=True"
    )
    mock_app.run.assert_called_once_with(host="0.0.0.0", port=8080, debug=True)


def test_main_all_custom_args(mock_app):
    """Test main() with all custom arguments."""
    with patch(
        "sys.argv",
        ["urlprobe", "--host", "192.168.1.1", "--port", "5000", "--debug"],
    ):
        with patch(
            "urlprobe.__main__.create_app", return_value=mock_app
        ) as mock_create_app:
            with patch("urlprobe.__main__.logger") as mock_logger:
                __main__.main()

    mock_create_app.assert_called_once()
    mock_logger.info.assert_called_once_with(
        "Starting urlprobe on host 192.168.1.1, port 5000, debug=True"
    )
    mock_app.run.assert_called_once_with(
        host="192.168.1.1", port=5000, debug=True
    )
