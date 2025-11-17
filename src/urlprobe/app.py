"""Flask application module for URL Probe."""

import importlib.metadata
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

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


@dataclass
class Probe:
    """Probe data structure.

    Attributes:
        url: URL that was probed

        status_code: HTTP status code from the response
        elapsed_ms: Response time in milliseconds
        final_url: Final URL after redirects
        headers: Response headers
        body: Response body
    """

    url: str

    status_code: int = 0
    elapsed_ms: int = 0
    final_url: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    body: str = ""

    def to_json(self):
        """Convert Probe to json."""
        return jsonify(self.__dict__)


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
        Probe: Object containing response information
    """
    url = request.args.get("url")

    if not is_valid_url(url):
        return handle_invalid_arg(
            logger, f"Missing or invalid `url` arg:{url}", 400
        )

    # send request to the URL and get the response
    logger.info("Probing URL: %s", url)
    resp = requests.request(
        method=request.method,
        url=url,
        timeout=DEFAULT_TIMEOUT,
        verify=VERIFY_SSL,
    )

    probe_response = Probe(
        url=url,
        status_code=resp.status_code,
        body=resp.text,
        headers=dict(resp.headers),
        elapsed_ms=resp.elapsed.total_seconds(),
        final_url=resp.url,
    )

    return probe_response.to_json()


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
