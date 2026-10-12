"""
Tests for fos.core.llm.validation — SSRF prevention for media URLs.

Validates that the URL validation correctly blocks private network
addresses, disallowed schemes, and cloud metadata endpoints while
allowing legitimate public URLs and data URIs.

Contains: test_valid_public_urls, test_invalid_schemes,
          test_private_network_blocked, test_localhost_blocked,
          test_data_uri_allowed, test_cloud_metadata_blocked,
          test_non_string_input
"""

from fos.core.llm.validation import (
    _is_private_network_url,
    validate_media_url,
)


# ── Valid public URLs ─────────────────────────────────────────────────────

class TestValidPublicUrls:
    def test_https_url_is_valid(self):
        assert validate_media_url("https://example.com/image.png") == "valid"

    def test_http_url_is_valid(self):
        assert validate_media_url("http://cdn.example.org/photo.jpg") == "valid"

    def test_data_uri_is_valid(self):
        assert validate_media_url("data:image/png;base64,abc123") == "valid"

    def test_url_with_port_is_valid(self):
        assert validate_media_url("https://example.com:8443/img.png") == "valid"


# ── Invalid schemes ───────────────────────────────────────────────────────

class TestInvalidSchemes:
    def test_ftp_scheme_rejected(self):
        assert validate_media_url("ftp://files.example.com/img.png") == "invalid_scheme"

    def test_javascript_scheme_rejected(self):
        assert validate_media_url("javascript:alert(1)") == "invalid_scheme"

    def test_file_scheme_rejected(self):
        assert validate_media_url("file:///etc/passwd") == "invalid_scheme"

    def test_ssh_scheme_rejected(self):
        assert validate_media_url("ssh://evil.com") == "invalid_scheme"


# ── Private network addresses ─────────────────────────────────────────────

class TestPrivateNetworkBlocked:
    def test_127_0_0_1_blocked(self):
        assert validate_media_url("http://127.0.0.1/admin") == "private_network"

    def test_10_network_blocked(self):
        assert validate_media_url("http://10.0.0.1/internal") == "private_network"

    def test_172_16_network_blocked(self):
        assert validate_media_url("http://172.16.0.1/internal") == "private_network"

    def test_172_31_network_blocked(self):
        assert validate_media_url("http://172.31.255.254/internal") == "private_network"

    def test_192_168_network_blocked(self):
        assert validate_media_url("http://192.168.1.1/router") == "private_network"

    def test_link_local_blocked(self):
        assert validate_media_url("http://169.254.1.1/link") == "private_network"


# ── Localhost ─────────────────────────────────────────────────────────────

class TestLocalhostBlocked:
    def test_localhost_hostname_blocked(self):
        assert validate_media_url("http://localhost:8080/api") == "private_network"

    def test_0_0_0_0_blocked(self):
        assert validate_media_url("http://0.0.0.0/") == "private_network"


# ── Cloud metadata ────────────────────────────────────────────────────────

class TestCloudMetadata:
    def test_aws_metadata_blocked(self):
        assert validate_media_url("http://169.254.169.254/latest/meta-data/") == "private_network"

    def test_metadata_hostname_blocked(self):
        assert validate_media_url("http://metadata/credentials") == "private_network"


# ── Data URIs ─────────────────────────────────────────────────────────────

class TestDataUri:
    def test_data_uri_not_private(self):
        assert _is_private_network_url("data:image/png;base64,abc") is False


# ── Non-string input ──────────────────────────────────────────────────────

class TestNonStringInput:
    def test_none_returns_invalid_scheme(self):
        assert validate_media_url(None) == "invalid_scheme"  # type: ignore

    def test_integer_returns_invalid_scheme(self):
        assert validate_media_url(12345) == "invalid_scheme"  # type: ignore

    def test_list_returns_invalid_scheme(self):
        assert validate_media_url(["http://example.com"]) == "invalid_scheme"  # type: ignore
