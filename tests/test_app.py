"""Tests for the Flask application."""

import importlib.metadata
import json
import socket
import threading
import time
import urllib.parse
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Sequence
from unittest.mock import MagicMock, patch

import pytest
import requests
from requests import exceptions as req_exc
from werkzeug.serving import make_server

from urlprobe import app as app_module
from urlprobe.app import Probe, _is_probe_chain, create_app


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


PROBE_KEYS = {
    "url",
    "status_code",
    "elapsed_ms",
    "final_url",
    "headers",
    "body",
    "error",
}


def assert_probe_shape(probe: dict) -> None:
    """Assert `probe` has every probe field, and exactly one outcome.

    Every probe has the same keys. A probe either got a response (it has
    a status_code and no error) or it didn't (an error and no
    status_code). `body` is text or null, never a nested list of
    downstream probes, which used to double the output per hop.
    """
    assert set(probe) == PROBE_KEYS
    assert (probe["status_code"] is None) != (probe["error"] is None)
    assert probe["body"] is None or isinstance(probe["body"], str)


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
    assert_probe_shape(probe)
    assert probe["url"] == "https://example.com"
    assert probe["status_code"] == 200
    assert probe["body"] == "Hello, world!"
    assert probe["elapsed_ms"] == 123.0
    assert probe["error"] is None


@patch("urlprobe.app.requests.request")
def test_handle_request_chained_url(mock_request, client):
    """Test handle_request with a chained URL parameter."""
    # The shape a urlprobe older than 3.0.0 returns (no error field). It
    # has the six core keys, so it's still recognised as a chain.
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
    assert_probe_shape(probe1)
    assert probe1["error"] is None
    assert probe1["url"] == "https://service-a.com/?url=https://service-b.com"
    assert probe1["status_code"] == 201
    # Not nested in body as well: each probe appears once.
    assert probe1["body"] is None
    assert probe1["elapsed_ms"] == 456.0

    probe2 = data[1]
    assert probe2 == downstream_probe


@pytest.mark.parametrize(
    "error",
    [
        req_exc.RequestException("Connection error"),
        req_exc.ConnectionError("refused"),
        req_exc.ConnectTimeout("connect timed out"),
        req_exc.ReadTimeout("read timed out"),
        req_exc.SSLError("bad certificate"),
        req_exc.TooManyRedirects("Exceeded 30 redirects."),
        req_exc.InvalidURL("bad port"),
        # urllib3's LocationParseError is a ValueError that requests doesn't
        # wrap.
        ValueError("Failed to parse: 'a..b'"),
    ],
    ids=lambda error: type(error).__name__,
)
@patch("urlprobe.app.requests.request")
def test_handle_request_failure(mock_request, client, error):
    """Test a request with no response gives an error probe, not a 500."""
    mock_request.side_effect = error

    response = client.get("/?url=https://example.com")

    assert response.status_code == 200  # The endpoint itself returns 200
    data = response.json
    assert len(data) == 1
    probe = data[0]
    assert_probe_shape(probe)
    assert probe["url"] == "https://example.com"
    assert probe["status_code"] is None
    assert probe["elapsed_ms"] is None
    assert probe["final_url"] is None
    assert probe["headers"] is None
    assert probe["body"] is None
    assert probe["error"]["message"] == str(error)
    assert isinstance(probe["error"]["elapsed_ms"], float)
    assert probe["error"]["elapsed_ms"] >= 0


@patch("urlprobe.app.perf_counter", side_effect=[10.0, 10.0123456])
@patch("urlprobe.app.requests.request")
def test_handle_request_failure_elapsed_ms(mock_request, _, client):
    """Test the time to failure is reported in exact milliseconds."""
    mock_request.side_effect = req_exc.ConnectTimeout("connect timed out")

    response = client.get("/?url=https://example.com")

    # Exact ==, as for successes: timedelta rounds to 12,346 microseconds.
    assert response.json[0]["error"]["elapsed_ms"] == 12.346


@patch("urlprobe.app.requests.request")
def test_handle_request_empty_response_is_not_null(mock_request, client):
    """Test an empty but real response keeps "" and {}, not null."""
    mock_request.return_value = make_response(
        elapsed=timedelta(milliseconds=5), status_code=204
    )

    response = client.get("/?url=https://example.com")

    probe = response.json[0]
    assert_probe_shape(probe)
    assert probe["status_code"] == 204
    assert probe["body"] == ""
    assert probe["headers"] == {}
    assert probe["error"] is None


@patch("urlprobe.app.requests.request")
def test_handle_request_chained_failure_passes_through(mock_request, client):
    """Test a downstream failure probe is passed through unchanged."""
    downstream_probe = Probe.from_error(
        "https://service-b.com",
        req_exc.ConnectionError("refused"),
        timedelta(milliseconds=14),
    ).__dict__
    mock_request.return_value = make_response(
        elapsed=timedelta(milliseconds=20),
        text=json.dumps([downstream_probe]),
        json_body=[downstream_probe],
        url="https://service-a.com/?url=https://service-b.com",
    )

    response = client.get(
        "/?url=https://service-a.com/?url=https://service-b.com"
    )

    data = response.json
    assert len(data) == 2
    for probe in data:
        assert_probe_shape(probe)
    assert data[0]["body"] is None
    assert data[1] == downstream_probe


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


def test_probe_from_error_sets_error_only():
    """Test Probe.from_error sets the error and no response fields."""
    probe = Probe.from_error(
        "https://example.com",
        req_exc.ReadTimeout("Read timed out."),
        timedelta(seconds=10, microseconds=3200),
    )

    assert probe == Probe(
        url="https://example.com",
        status_code=None,
        elapsed_ms=None,
        final_url=None,
        headers=None,
        body=None,
        error={"message": "Read timed out.", "elapsed_ms": 10003.2},
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

    assert_probe_shape(response.json[0])
    elapsed_ms = response.json[0]["elapsed_ms"]
    assert isinstance(elapsed_ms, float)
    assert elapsed_ms == expected_ms


_CORE_PROBE = {
    "url": "https://service-b.com",
    "status_code": 200,
    "elapsed_ms": 1.0,
    "final_url": "https://service-b.com",
    "headers": {},
    "body": "ok",
}

_NOT_CHAINS = [
    pytest.param([], id="empty list"),
    pytest.param([{"url": "https://x"}], id="REST-style list"),
    pytest.param(
        [{k: v for k, v in _CORE_PROBE.items() if k != "final_url"}],
        id="probe missing a core key",
    ),
    pytest.param([_CORE_PROBE, "text"], id="probe and non-dict"),
    pytest.param(_CORE_PROBE, id="single probe, not a list"),
    pytest.param("text", id="JSON string"),
    pytest.param(None, id="JSON null"),
]

_CHAINS = [
    pytest.param([_CORE_PROBE], id="2.x shape"),
    pytest.param([{**_CORE_PROBE, "error": None}], id="3.0.0 shape"),
    pytest.param(
        [
            {
                **_CORE_PROBE,
                "status_code": None,
                "body": None,
                "error": {"message": "refused", "elapsed_ms": 1.0},
            }
        ],
        id="3.0.0 failure",
    ),
    pytest.param(
        [_CORE_PROBE, {**_CORE_PROBE, "extra": 1}], id="extra keys allowed"
    ),
]


@pytest.mark.parametrize("data", _NOT_CHAINS)
def test_is_probe_chain_rejects(data):
    """Test JSON that isn't a downstream urlprobe's probe list."""
    assert _is_probe_chain(data) is False


@pytest.mark.parametrize("data", _CHAINS)
def test_is_probe_chain_accepts(data):
    """Test probe lists from urlprobe 2.x and 3.0.0 are chains."""
    assert _is_probe_chain(data) is True


@pytest.mark.parametrize("data", _NOT_CHAINS)
@patch("urlprobe.app.requests.request")
def test_handle_request_json_that_is_not_a_chain(mock_request, client, data):
    """Test a JSON body that isn't a chain is kept as text, not dropped."""
    text = json.dumps(data)
    mock_request.return_value = make_response(
        elapsed=timedelta(milliseconds=5), text=text, json_body=data
    )

    response = client.get("/?url=https://example.com")

    data_out = response.json
    assert len(data_out) == 1
    assert_probe_shape(data_out[0])
    assert data_out[0]["body"] == text


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
        elif self.path == "/error":
            self._send(500, body=b"boom")
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
    assert_probe_shape(probe)
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

    assert_probe_shape(response.json[0])
    assert response.json[0]["elapsed_ms"] == expected_ms


def test_handle_request_redirect_real_target(client, target_server, no_proxy):
    """Test a real redirect: timing covers both hops, nothing else moves."""
    requested_url = f"{target_server}/redirect"

    response = client.get("/", query_string={"url": requested_url})

    data = response.json
    assert len(data) == 1
    probe = data[0]
    assert_probe_shape(probe)
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
    assert_probe_shape(probe)
    assert probe["url"] == url
    assert probe["status_code"] is None
    assert probe["elapsed_ms"] is None
    assert probe["body"] is None
    assert "Exceeded 30 redirects" in probe["error"]["message"]


def test_handle_request_real_http_500_is_not_an_error(
    client, target_server, no_proxy
):
    """Test a target's real HTTP 500 is a response, not an error."""
    response = client.get("/", query_string={"url": f"{target_server}/error"})

    probe = response.json[0]
    assert_probe_shape(probe)
    assert probe["status_code"] == 500
    assert probe["body"] == "boom"
    assert isinstance(probe["elapsed_ms"], float)
    assert probe["error"] is None


def _closed_port() -> int:
    """Return a localhost port that nothing is listening on."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_handle_request_connection_refused_real(client, no_proxy):
    """Test a refused connection gives an error probe with its timing."""
    url = f"http://127.0.0.1:{_closed_port()}/"

    response = client.get("/", query_string={"url": url})

    assert response.status_code == 200
    probe = response.json[0]
    assert_probe_shape(probe)
    assert probe["status_code"] is None
    assert probe["error"]["message"]
    assert 0 <= probe["error"]["elapsed_ms"] < 5000


def test_handle_request_read_timeout_real(
    client, target_server, no_proxy, monkeypatch
):
    """Test a timeout reports the time spent waiting before it failed."""
    monkeypatch.setattr(app_module, "DEFAULT_TIMEOUT", 0.01)

    response = client.get("/", query_string={"url": f"{target_server}/slow"})

    probe = response.json[0]
    assert_probe_shape(probe)
    assert "Read timed out" in probe["error"]["message"]
    # The timeout is 10 ms, so the failure can't come sooner than that.
    assert 10 <= probe["error"]["elapsed_ms"] < 5000


def test_handle_request_unparseable_host_real(client, no_proxy):
    """Test a host urllib3 can't parse gives an error probe, not a 500."""
    response = client.get("/", query_string={"url": "http://a..b/"})

    assert response.status_code == 200
    data = response.json
    assert len(data) == 1
    probe = data[0]
    assert_probe_shape(probe)
    assert probe["status_code"] is None
    assert "Failed to parse" in probe["error"]["message"]


@pytest.fixture(scope="module")
def urlprobe_servers():
    """Serve three urlprobe apps on free localhost ports.

    Yields:
        list[str]: base URL of each server
    """
    servers = [
        make_server("127.0.0.1", 0, create_app(), threaded=True)
        for _ in range(3)
    ]
    threads = [
        threading.Thread(target=server.serve_forever, daemon=True)
        for server in servers
    ]
    for thread in threads:
        thread.start()
    yield [f"http://127.0.0.1:{server.server_port}" for server in servers]
    for server, thread in zip(servers, threads):
        server.shutdown()
        server.server_close()
        thread.join()


def test_handle_request_real_chain_lists_each_hop_once(
    client, target_server, urlprobe_servers, no_proxy
):
    """Test a real four-hop chain gives one probe per hop, none repeated.

    Before the fix, each hop also nested every downstream probe in its
    body, so these four hops gave 15 probe objects instead of 4.
    """
    # Build the chain from the far end: target <- server 3 <- 2 <- 1,
    # encoding each level's URL as the next level's `url` parameter.
    hop_urls = [f"{target_server}/slow"]
    for base in reversed(urlprobe_servers):
        query = urllib.parse.urlencode({"url": hop_urls[0]})
        hop_urls.insert(0, f"{base}/?{query}")

    response = client.get("/", query_string={"url": hop_urls[0]})

    data = response.json
    assert [probe["url"] for probe in data] == hop_urls
    for probe in data:
        assert_probe_shape(probe)
    assert [probe["body"] for probe in data] == [None, None, None, "ok"]
