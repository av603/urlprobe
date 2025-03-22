"""Tests for URL Probe utility functions."""

import pytest

from urlprobe.utils import is_valid_url


@pytest.mark.parametrize(
    "url,expected",
    [
        # Valid URLs
        ("https://www.example.com", True),
        ("http://example.com", True),
        ("https://sub.domain.com/path", True),
        ("https://example.com:8080", True),
        ("https://example.com/path?query=1", True),
        ("http://localhost:8080", True),
        ("http://127.0.0.1:8080", True),
        # Invalid URLs
        ("", False),
        ("not_a_url", False),
        ("http://", False),
        ("https://", False),
        ("ftp://example.com", False),  # if we only want http(s)
        ("http:/example.com", False),
        ("https:example.com", False),
        ("example.com", False),
    ],
)
def test_is_valid_url(url: str, expected: bool):
    """Test URL validation with various inputs.

    Args:
        url: URL string to test
        expected: Expected validation result
    """
    assert is_valid_url(url) == expected
