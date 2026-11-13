"""Flask application module for URL Probe."""

import importlib.metadata
import json
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict

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


def _elapsed_ms(resp: requests.Response) -> float:
    """Return the time taken for `resp`, including redirects, in ms.

    requests times each redirect separately, and `resp.elapsed` covers
    only the last one, so add the earlier ones from `resp.history`.
    """
    elapsed = sum((hop.elapsed for hop in resp.history), resp.elapsed)
    # Divide the timedelta rather than multiplying total_seconds():
    # timedelta arithmetic is exact, total_seconds() * 1000 is not.
    return elapsed / timedelta(milliseconds=1)


@dataclass
class Probe:
    """Probe data structure.

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
    """

    url: str

    status_code: int = 0
    elapsed_ms: float = 0
    final_url: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    body: Any = ""

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
    try:
        resp = requests.request(
            method=request.method,
            url=url,
            timeout=DEFAULT_TIMEOUT,
            verify=VERIFY_SSL,
        )
    except requests.exceptions.RequestException as e:
        logger.error(f"Request to {url} failed: {e}")
        error_probe = Probe(url=url, body=str(e), status_code=500)
        return jsonify([error_probe.__dict__])

    current_probe = Probe.from_response(url, resp)

    try:
        downstream_probes = resp.json()
        if isinstance(downstream_probes, list) and all(
            isinstance(p, dict) and "url" in p for p in downstream_probes
        ):
            current_probe.body = downstream_probes
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
