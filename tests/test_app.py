"""Tests for the Flask application."""

import importlib.metadata
import json
import threading
import time
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
    assert probe["elapsed_ms"] == 123.0


@patch("urlprobe.app.requests.request")
def test_handle_request_chained_url(mock_request, client):
    """Test handle_request with a chained URL parameter."""
    downstream_probe = {
        "url": "https://service-b.com",
        "status_code": 200,
        "body": "Final response",
        "headers": {},
        # Passed through as-is, whatever its unit: a downstream urlprobe
        # older than 3.0.0 reports seconds here.
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
    assert probe1["elapsed_ms"] == 456.0

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
    assert probe["elapsed_ms"] == 0


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
        elapsed_ms=123.0,
        final_url="https://example.com/final",
        headers={"Content-Type": "text/plain"},
        body="Not found",
    )


# Exact == on purpose: these cases exist to catch float artefacts such as
# 0.020999999999999998 from total_seconds() * 1000. pytest.approx would
# hide exactly that regression.
@pytest.mark.parametrize(
    ("elapsed", "expected_ms"),
    [
        (timedelta(milliseconds=123), 123.0),
        (timedelta(microseconds=123456), 123.456),
        (timedelta(microseconds=1), 0.001),
        (timedelta(microseconds=21), 0.021),
        (timedelta(seconds=1, microseconds=234567), 1234.567),
        (timedelta(0), 0.0),
    ],
)
@patch("urlprobe.app.requests.request")
def test_handle_request_elapsed_ms_is_exact_milliseconds(
    mock_request, client, elapsed, expected_ms
):
    """Test elapsed_ms converts the response time to exact milliseconds."""
    mock_request.return_value = make_response(elapsed=elapsed)

    response = client.get("/?url=https://example.com")

    elapsed_ms = response.json[0]["elapsed_ms"]
    assert isinstance(elapsed_ms, float)
    assert elapsed_ms == expected_ms


class _ProbeTargetHandler(BaseHTTPRequestHandler):
    """Real HTTP target for probes, routed on path."""

    SLEEP_S = 0.05

    def do_GET(self):
        """Serve the probe target routes."""
        if self.path in ("/slow", "/final"):
            time.sleep(self.SLEEP_S)
            self._send(200, body=b"ok")
        elif self.path == "/redirect":
            time.sleep(self.SLEEP_S)
            self._send(302, headers={"Location": "/final"})
        elif self.path == "/loop":
            self._send(302, headers={"Location": "/loop"})
        else:
            self._send(404)

    def _send(self, status, body=b"", headers=None):
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """Keep test output quiet."""


@pytest.fixture(scope="module")
def target_server():
    """Serve _ProbeTargetHandler on a free localhost port.

    Yields:
        str: base URL of the server
    """
    # TODO: roadmap item 1 plans to block private and loopback addresses.
    # These tests probe 127.0.0.1, so they'll need an allowlist or an
    # override when that lands.
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ProbeTargetHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.fixture
def no_proxy(monkeypatch):
    """Stop a developer's proxy settings routing localhost probes."""
    for name in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")


def test_handle_request_elapsed_ms_real_target(
    client, target_server, no_proxy
):
    """Test elapsed_ms is in milliseconds against a real, slow target."""
    response = client.get("/", query_string={"url": f"{target_server}/slow"})

    probe = response.json[0]
    assert probe["status_code"] == 200
    # The target sleeps 50 ms. Seconds would give about 0.05. The upper
    # bound is generous to keep slow CI runners from failing.
    assert 50 <= probe["elapsed_ms"] < 5000


# Exact == on purpose, as above. Summing the history as floats gives
# 0.16099999999999998 or 0.16100000000000003 for the second case, so it
# checks the sum stays a timedelta until it's converted.
@pytest.mark.parametrize(
    ("history", "elapsed", "expected_ms"),
    [
        ([timedelta(milliseconds=30)], timedelta(milliseconds=70), 100.0),
        (
            [timedelta(microseconds=35), timedelta(microseconds=42)],
            timedelta(microseconds=84),
            0.161,
        ),
        (
            [timedelta(milliseconds=1), timedelta(seconds=2)],
            timedelta(microseconds=500),
            2001.5,
        ),
    ],
)
@patch("urlprobe.app.requests.request")
def test_handle_request_elapsed_ms_includes_redirects(
    mock_request, client, history, elapsed, expected_ms
):
    """Test elapsed_ms adds the time of every redirect to the final one."""
    mock_request.return_value = make_response(elapsed=elapsed, history=history)

    response = client.get("/?url=https://example.com")

    assert response.json[0]["elapsed_ms"] == expected_ms


def test_handle_request_redirect_real_target(client, target_server, no_proxy):
    """Test a real redirect: timing covers both hops, nothing else moves."""
    requested_url = f"{target_server}/redirect"

    response = client.get("/", query_string={"url": requested_url})

    data = response.json
    assert len(data) == 1
    probe = data[0]
    # Each hop sleeps 50 ms. Timing the last hop only would give about 50.
    assert 100 <= probe["elapsed_ms"] < 5000
    assert probe["url"] == requested_url
    assert probe["final_url"] == f"{target_server}/final"
    assert probe["status_code"] == 200
    assert probe["body"] == "ok"


def test_handle_request_redirect_loop_real_target(
    client, target_server, no_proxy
):
    """Test a redirect loop gives one error probe, as other failures do."""
    url = f"{target_server}/loop"

    response = client.get("/", query_string={"url": url})

    assert response.status_code == 200
    data = response.json
    assert len(data) == 1
    probe = data[0]
    # TODO: roadmap item 6 changes the error probe (status_code 0 plus an
    # error field); update these assertions with it.
    assert probe["url"] == url
    assert probe["status_code"] == 500
    assert probe["elapsed_ms"] == 0
    assert "Exceeded 30 redirects" in probe["body"]
