"""Tests for the Flask application."""

import importlib.metadata
import json
from unittest.mock import MagicMock, patch

import pytest
from requests.exceptions import RequestException

from urlprobe.app import create_app


@pytest.fixture
def client():
    """Create a test client for the Flask application.

    Returns:
        FlaskClient: A test client for making requests
    """
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_health_endpoint(client):
    """Test the health check endpoint returns correct response."""
    version = importlib.metadata.version("urlprobe")

    response = client.get("/health")
    assert response.status_code == 200
    assert response.json == {
        "status": "healthy",
        "version": version,
    }


def test_handle_request_no_url(client):
    """Test handle_request when no URL is provided."""
    response = client.get("/")
    assert response.status_code == 400
    assert response.json == {"error": "Missing or invalid `url` arg:None"}


def test_handle_request_method_not_allowed(client):
    """Test handle_request with invalid HTTP method."""
    response = client.delete("/")
    assert response.status_code == 405


@patch("urlprobe.app.requests.request")
def test_handle_request_with_url(mock_request, client):
    """Test handle_request with a URL parameter."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "Hello, world!"
    mock_response.headers = {"Content-Type": "text/plain"}
    mock_response.elapsed.total_seconds.return_value = 0.123
    mock_response.url = "https://example.com"
    mock_response.json.side_effect = json.JSONDecodeError("msg", "doc", 0)
    mock_request.return_value = mock_response

    response = client.get("/?url=https://example.com")
    assert response.status_code == 200
    data = response.json
    assert isinstance(data, list)
    assert len(data) == 1
    probe = data[0]
    assert probe["url"] == "https://example.com"
    assert probe["status_code"] == 200
    assert probe["body"] == "Hello, world!"
    assert probe["elapsed_ms"] == 0.123


@patch("urlprobe.app.requests.request")
def test_handle_request_chained_url(mock_request, client):
    """Test handle_request with a chained URL parameter."""
    downstream_probe = {
        "url": "https://service-b.com",
        "status_code": 200,
        "body": "Final response",
        "headers": {},
        "elapsed_ms": 0.1,
        "final_url": "https://service-b.com",
    }

    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.text = json.dumps([downstream_probe])
    mock_response.json.return_value = [downstream_probe]
    mock_response.headers = {"Content-Type": "application/json"}
    mock_response.elapsed.total_seconds.return_value = 0.456
    mock_response.url = "https://service-a.com/?url=https://service-b.com"
    mock_request.return_value = mock_response

    response = client.get(
        "/?url=https://service-a.com/?url=https://service-b.com"
    )
    assert response.status_code == 200
    data = response.json
    assert isinstance(data, list)
    assert len(data) == 2

    probe1 = data[0]
    assert probe1["url"] == "https://service-a.com/?url=https://service-b.com"
    assert probe1["status_code"] == 201
    assert probe1["body"] == [downstream_probe]
    assert probe1["elapsed_ms"] == 0.456

    probe2 = data[1]
    assert probe2 == downstream_probe


@patch("urlprobe.app.requests.request")
def test_handle_request_request_exception(mock_request, client):
    """Test handle_request when a request exception occurs."""
    mock_request.side_effect = RequestException("Connection error")

    response = client.get("/?url=https://example.com")
    assert response.status_code == 200  # The endpoint itself returns 200
    data = response.json
    assert isinstance(data, list)
    assert len(data) == 1
    probe = data[0]
    assert probe["url"] == "https://example.com"
    assert probe["status_code"] == 500
    assert "Connection error" in probe["body"]
