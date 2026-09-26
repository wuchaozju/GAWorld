"""A CA bundle that can verify ``www.legco.gov.hk``.

The Legislative Council's server sends only its leaf certificate and leaves the
client to find the intermediate. Browsers and ``curl`` on macOS cope, because
they chase the ``Authority Information Access`` URL (or already hold the
intermediate in the keychain); ``requests`` does not, and every fetch fails
with ``unable to get local issuer certificate``.

The fix is to *complete the chain*, not to skip verification. The issuing root
— ``Hongkong Post Root CA 3`` — is already in ``certifi``; only the
``Hongkong Post e-Cert SSL CA 3 - 17`` intermediate is missing. Appending that
one certificate to a copy of ``certifi``'s bundle restores a fully verified
connection, with ``verify=`` still on.

The intermediate is fetched once from the AIA URL named in the leaf and cached
under ``output/``. If it cannot be fetched, callers get ``None`` and should
treat the source as unavailable rather than fall back to ``verify=False``.
"""

from __future__ import annotations

import ssl
from pathlib import Path

import certifi

from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.io.legco_ca")

#: The CA Issuers URI carried by the leaf certificate of ``*.legco.gov.hk``.
INTERMEDIATE_URL = "http://www1.eCert.gov.hk/root/ecert_ssl_ca_3-17.crt"

#: Subject CN the downloaded certificate must carry, so a hijacked or changed
#: AIA endpoint cannot quietly add an arbitrary CA to the bundle.
EXPECTED_CN = "Hongkong Post e-Cert SSL CA 3 - 17"

_CACHE = Path(__file__).resolve().parents[2] / "output" / "certs" / "legco_bundle.pem"


def _download_intermediate(timeout: int = 20) -> str | None:
    import requests

    try:
        response = requests.get(INTERMEDIATE_URL, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        _LOG.warning("legco intermediate download failed: %s", exc)
        return None

    raw = response.content
    try:
        pem = ssl.DER_cert_to_PEM_cert(raw) if not raw.lstrip().startswith(b"-----") else raw.decode()
    except (ValueError, UnicodeDecodeError) as exc:
        _LOG.warning("legco intermediate is not a readable certificate: %s", exc)
        return None

    # Refuse anything that is not the certificate the leaf named. Without this
    # a compromised AIA host could append a CA of its choosing to a bundle we
    # then trust for every request made with it.
    try:
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as handle:
            handle.write(pem)
            probe = handle.name
        subject = ssl._ssl._test_decode_cert(probe)  # type: ignore[attr-defined]
        Path(probe).unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001 — any failure here means "do not trust it"
        _LOG.warning("legco intermediate could not be parsed: %s", exc)
        return None

    names = {value for rdn in subject.get("subject", ()) for key, value in rdn if key == "commonName"}
    if EXPECTED_CN not in names:
        _LOG.warning("legco intermediate CN mismatch: %s", names)
        return None
    return pem


def bundle_path(refresh: bool = False) -> str | None:
    """Path to a certifi bundle plus the LegCo intermediate, or ``None``."""
    if _CACHE.exists() and not refresh:
        return str(_CACHE)
    pem = _download_intermediate()
    if pem is None:
        return None
    _CACHE.parent.mkdir(parents=True, exist_ok=True)
    _CACHE.write_text(Path(certifi.where()).read_text() + "\n" + pem, encoding="utf-8")
    _LOG.info("legco CA bundle written: %s", _CACHE)
    return str(_CACHE)
