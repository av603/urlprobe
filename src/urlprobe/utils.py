"""Utility functions for URL Prober."""

from urllib.parse import urlparse


def is_valid_url(url: str) -> bool:
    """Check if a given string is a valid URL.

    Args:
        url: The URL string to validate

    Returns:
        bool: True if URL is valid, False otherwise

    Examples:
        >>> is_valid_url("https://example.com")
        True
        >>> is_valid_url("not_a_url")
        False
    """
    if not url:
        return False

    try:
        result = urlparse(url)
        return all(
            [
                result.scheme in ("http", "https"),
                result.netloc,
            ]
        )
    except (AttributeError, ValueError):
        return False
