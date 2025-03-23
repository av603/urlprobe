"""Tests for the Flask application."""

import importlib.metadata
from unittest.mock import patch

import pytest

from urlprobe.app import create_app


@pytest.fixture
def client():
    """Create a test client for the Flask application.

    Returns:
        FlaskClient: A test client for making requests
    """
    app = create_app()
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


def test_handle_request_method_not_allowed(client):
    """Test handle_request with invalid HTTP method."""
    response = client.delete("/")
    assert response.status_code == 405


def test_handle_request_with_url(client):
    """Test handle_request with a URL parameter."""
    with patch("urlprobe.app.handle_request"):
        response = client.get("/?url=https://example.com")
    assert response.status_code == 200
