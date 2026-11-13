"""Tests for the Flask application."""

import importlib.metadata
import json
from datetime import timedelta
from typing import Any, Sequence
from unittest.mock import MagicMock, patch

import pytest
import requests
from requests.exceptions import RequestException

from urlprobe.app import Probe, create_app


def make_response(
    *,
    elapsed: timedelta,
    history: Sequence[timedelta] = (),
    status_code: int = 200,
    text: str = "",
    json_body: Any = None,
    headers: dict[str, str] | None = None,
    url: str = "https://example.com",
) -> MagicMock:
    """Build a mock `requests.Response`.

    `history` is always set, from the elapsed time of each earlier
    redirect. A bare MagicMock's `history` iterates as empty, which would
    let redirect handling pass untested. `json()` raises JSONDecodeError
    when `json_body` is None, as it does for a non-JSON body.
    """
    resp = MagicMock(spec=requests.Response)
    resp.elapsed = elapsed
    resp.history = [
        make_response(elapsed=hop_elapsed, status_code=302)
        for hop_elapsed in history
    ]
    resp.status_code = status_code
    resp.text = text
    resp.headers = headers if headers is not None else {}
    resp.url = url
    if json_body is None:
        resp.json.side_effect = json.JSONDecodeError("msg", "doc", 0)
    else:
        resp.json.return_value = json_body
    return resp


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
    mock_request.return_value = make_response(
        elapsed=timedelta(milliseconds=123),
        text="Hello, world!",
        headers={"Content-Type": "text/plain"},
    )

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

    mock_request.return_value = make_response(
        elapsed=timedelta(milliseconds=456),
        status_code=201,
        text=json.dumps([downstream_probe]),
        json_body=[downstream_probe],
        headers={"Content-Type": "application/json"},
        url="https://service-a.com/?url=https://service-b.com",
    )

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


def test_probe_from_response_maps_every_field():
    """Test Probe.from_response maps each response field onto the probe."""
    resp = make_response(
        elapsed=timedelta(milliseconds=123),
        status_code=404,
        text="Not found",
        headers={"Content-Type": "text/plain"},
        url="https://example.com/final",
    )

    probe = Probe.from_response("https://example.com/start", resp)

    assert probe == Probe(
        url="https://example.com/start",
        status_code=404,
        elapsed_ms=0.123,
        final_url="https://example.com/final",
        headers={"Content-Type": "text/plain"},
        body="Not found",
    )
