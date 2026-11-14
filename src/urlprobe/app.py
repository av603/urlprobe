"""Flask application module for URL Probe."""

import importlib.metadata
import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, Optional, TypedDict

import requests
import toml
from flask import Flask, jsonify, request

from urlprobe.utils import is_valid_url

# Configure logging at module level
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10  # seconds
ALLOWED_METHODS = ["GET"]
VERIFY_SSL = True


def _to_ms(elapsed: timedelta) -> float:
    """Return `elapsed` in milliseconds, exact to the microsecond."""
    # Divide the timedelta rather than multiplying total_seconds():
    # timedelta arithmetic is exact, total_seconds() * 1000 is not.
    return elapsed / timedelta(milliseconds=1)


def _elapsed_ms(resp: requests.Response) -> float:
    """Return the time taken for `resp`, including redirects, in ms.

    requests times each redirect separately, and `resp.elapsed` covers
    only the last one, so add the earlier ones from `resp.history`.
    """
    return _to_ms(sum((hop.elapsed for hop in resp.history), resp.elapsed))


# The keys every urlprobe probe has carried since 2.x. Deliberately not
# derived from Probe: a field added later must not become required, or a
# newer urlprobe would stop recognising older ones downstream.
PROBE_CORE_KEYS = frozenset(
    {"url", "status_code", "elapsed_ms", "final_url", "headers", "body"}
)


def _is_probe_chain(data: Any) -> bool:
    """Return whether `data` is the probe list a downstream urlprobe returns.

    That is a non-empty list in which every item is a dict with all of
    PROBE_CORE_KEYS. Extra keys, such as 3.0.0's `error`, are allowed. An
    empty list, or a list of other objects with a `url` key (common in
    REST APIs), isn't a chain, so its body is kept.
    """
    return (
        isinstance(data, list)
        and len(data) > 0
        and all(
            isinstance(item, dict) and PROBE_CORE_KEYS <= item.keys()
            for item in data
        )
    )


class ProbeError(TypedDict):
    """Why a probe got no HTTP response.

    Attributes:
        message: The failure message
        elapsed_ms: Wall-clock time from starting the request until it
            failed, in milliseconds
    """

    message: str
    elapsed_ms: float


@dataclass
class Probe:
    """Probe data structure.

    Fields that come from the response are None when there was no
    response; `error` is None when there was one. `body` is also None
    when the response was a downstream urlprobe's probes, which follow
    this probe in the output instead.

    Attributes:
        url: URL that was probed

        status_code: HTTP status code from the response
        elapsed_ms: Approximate response time in milliseconds (not
            seconds), from sending the first request to receiving the
            final response's headers, summed over any redirects. It
            excludes downloading the body.
        final_url: Final URL after redirects
        headers: Response headers
        body: Response body
        error: Why there was no response
    """

    url: str

    status_code: Optional[int] = None
    elapsed_ms: Optional[float] = None
    final_url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    body: Optional[str] = None
    error: Optional[ProbeError] = None

    @classmethod
    def from_response(cls, url: str, resp: requests.Response) -> "Probe":
        """Build a probe from the response to a request for `url`.

        Args:
            url: URL that was requested
            resp: Response received for that request

        Returns:
            Probe: probe describing the response
        """
        return cls(
            url=url,
            status_code=resp.status_code,
            body=resp.text,
            headers=dict(resp.headers),
            elapsed_ms=_elapsed_ms(resp),
            final_url=resp.url,
        )

    @classmethod
    def from_error(
        cls, url: str, error: Exception, elapsed: timedelta
    ) -> "Probe":
        """Build a probe for a request to `url` that got no response.

        Args:
            url: URL that was requested
            error: Why the request failed
            elapsed: Time from starting the request until it failed

        Returns:
            Probe: probe with the error, and no response fields
        """
        return cls(
            url=url,
            error=ProbeError(message=str(error), elapsed_ms=_to_ms(elapsed)),
        )


def get_version() -> str:
    """Read version from pyproject.toml."""
    try:
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        with open(pyproject_path, "r") as f:
            pyproject = toml.load(f)
            return pyproject["tool"]["poetry"]["version"]
    except Exception as e:
        logger.warning(f"Failed to read version from pyproject.toml: {e}")
        return "unknown"


def handle_invalid_arg(logger, error_msg, code):
    """Handle invalid args."""
    logger.error(error_msg)
    return {"error": error_msg}, code


def handle_request():
    """Handle probe requests.

    Returns:
        list[Probe]: list of probe objects containing response information
    """
    url = request.args.get("url")

    if not is_valid_url(url):
        return handle_invalid_arg(
            logger, f"Missing or invalid `url` arg:{url}", 400
        )

    # send request to the URL and get the response
    logger.info("Probing URL: %s", url)
    start = perf_counter()
    try:
        resp = requests.request(
            method=request.method,
            url=url,
            timeout=DEFAULT_TIMEOUT,
            verify=VERIFY_SSL,
        )
    # ValueError covers urllib3's LocationParseError, which requests doesn't
    # wrap, for hosts such as `a..b` that pass is_valid_url.
    except (requests.exceptions.RequestException, ValueError) as e:
        elapsed = timedelta(seconds=perf_counter() - start)
        logger.error(f"Request to {url} failed: {e}")
        error_probe = Probe.from_error(url, e, elapsed)
        return jsonify([error_probe.__dict__])

    current_probe = Probe.from_response(url, resp)

    try:
        downstream_probes = resp.json()
        if _is_probe_chain(downstream_probes):
            # Each downstream probe appears once, after this one. Nesting
            # them in this probe's body too doubled the output per hop.
            current_probe.body = None
            return jsonify([current_probe.__dict__] + downstream_probes)
    except (ValueError, json.JSONDecodeError):
        # Not a JSON response from a downstream probe,
        # so this is the end of the request chain.
        pass

    return jsonify([current_probe.__dict__])


def health_check():
    """Check the health status and version of the service.

    Returns:
        dict: Health status and version information with format:
            {"status": "healthy", "version": "x.y.z"}
    """
    try:
        version = importlib.metadata.version("urlprobe")
        logger.info("Health check requested, version: %s", version)
    except importlib.metadata.PackageNotFoundError:
        logger.warning(
            "Package 'urlprobe' not found. Unable to determine version."
        )
        version = "unknown"

    return {
        "status": "healthy",
        "version": version,
    }


def create_app():
    """Create and configure the Flask application.

    Returns:
        Flask: Configured Flask application instance
    """
    app = Flask(__name__)
    logger.debug("Creating Flask application")

    app.route("/", methods=ALLOWED_METHODS)(handle_request)
    app.route("/health")(health_check)

    return app
