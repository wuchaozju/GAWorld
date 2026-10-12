"""
URL validation and SSRF (Server-Side Request Forgery) prevention utilities.

Contains:
    - _ALLOWED_URL_SCHEMES: Allowed URL schemes for media content
    - _PRIVATE_NETWORK_PATTERNS: Regex patterns for private/internal networks
    - _is_private_network_url: Check if URL points to private network
    - validate_media_url: Validate media URLs with SSRF prevention

This module prevents vision models from accessing internal resources by:
1. Only allowing http, https, and data URL schemes
2. Blocking private network addresses (127.0.0.0/8, 10.0.0.0/8, etc.)
3. Blocking localhost and cloud metadata addresses
"""

import re
from typing import Literal
from urllib.parse import urlparse


# SSRF prevention: allowed URL schemes for media content
_ALLOWED_URL_SCHEMES = {"http", "https", "data"}

# SSRF prevention: denylist of private/internal network patterns
# These patterns prevent the vision model from accessing internal resources
_PRIVATE_NETWORK_PATTERNS = (
    r"127\.\d+\.\d+\.\d+",  # 127.0.0.0/8
    r"10\.\d+\.\d+\.\d+",  # 10.0.0.0/8
    r"172\.(1[6-9]|2\d|3[01])\.\d+\.\d+",  # 172.16.0.0/12
    r"192\.168\.\d+\.\d+",  # 192.168.0.0/16
    r"169\.254\.\d+\.\d+",  # 169.254.0.0/16 (link-local)
    r"::1$",  # IPv6 localhost
    r"fe80::",  # IPv6 link-local
    r"fc00::",  # IPv6 unique local
    r"localhost",  # localhost hostname
    r"0\.0\.0\.0",  # 0.0.0.0
)


def _is_private_network_url(url: str) -> bool:
    """
    Check if a URL points to a private/internal network (SSRF prevention).

    Args:
        url: The URL string to check

    Returns:
        True if the URL points to a private network, False otherwise
    """
    if url.startswith("data:"):
        return False  # data URLs are safe (embedded content)

    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""

        # Check against private network patterns
        for pattern in _PRIVATE_NETWORK_PATTERNS:
            if re.search(pattern, hostname, re.IGNORECASE):
                return True

        # Block metadata addresses like <metadata> in cloud providers
        if hostname in ("metadata", "169.254.169.254"):
            return True

        return False
    except Exception:
        # If URL parsing fails, treat as potentially unsafe
        return True


def validate_media_url(url: str) -> Literal["valid", "invalid_scheme", "private_network"]:
    """
    Validate a media URL for SSRF prevention.

    Args:
        url: The URL string to validate

    Returns:
        "valid": URL is safe to pass to vision models
        "invalid_scheme": URL uses a disallowed scheme
        "private_network": URL points to a private/internal network
    """
    if not isinstance(url, str):
        return "invalid_scheme"

    # Check scheme
    if not any(url.startswith(f"{scheme}:") for scheme in _ALLOWED_URL_SCHEMES):
        return "invalid_scheme"

    # Check for private network addresses
    if _is_private_network_url(url):
        return "private_network"

    return "valid"
