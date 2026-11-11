# LLM transport performance implementation plan

**Goal:** Reuse model HTTP connections without sharing request state or changing inference retry semantics.

**Architecture:** Thread-owned bounded HTTPAdapter, fresh per-request Session and CookieJar. Keep providers._post as the ledger boundary and inject a package-owned http_post transport below it.

**Tech Stack:** requests, threading, weakref, HTTP/1.1 loopback test servers, pytest.

- [x] Add failing real-HTTP tests in tests/test_llm_http_transport.py for connection reuse, request-state isolation, stream handling, retries and lifecycle.
- [x] Implement gaworld/llm/http_transport.py, then integrate with providers._post. Update existing mocks to the transport seam without changing assertions about payloads, private keys and research HTTP attempts.
- [x] Run targeted transport/provider/credential/ledger tests; fix any regression before broadening checks.
- [x] Run core suite, lint ratchet and independent code review. Preserve existing working-tree changes.
- [x] Measure loopback TLS connection counts and record a bounded performance claim in docs/reports/2026-10-30-llm-transport-performance.md. Leave changes uncommitted.
