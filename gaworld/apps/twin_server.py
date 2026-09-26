"""Public-facing HTTP server for the mobile digital twin.

Deliberately a SEPARATE process from ``dashboard_server``. The dashboard
accepts unauthenticated POSTs to ``/api/config`` (writes global config) and
``/api/run/start`` (spawns simulation subprocesses); exposing that process
publicly would hand config-write and process-spawn capability to anyone who
scans the port. This server exposes five authenticated endpoints and the
mobile static bundle, and nothing else.

Routing and authentication only — all behaviour lives in
:class:`gaworld.twin.backend.TwinBackend`.
"""

from __future__ import annotations

import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from gaworld.settings import CONFIG
from gaworld.twin.backend import TwinBackend


REPO_ROOT = str(Path(__file__).resolve().parents[2])
MAX_BODY_BYTES = 1_000_000
MOBILE_ASSETS = frozenset({
    "index.html", "styles.css", "app.js", "core.js", "sw.js", "manifest.webmanifest",
})


def make_handler(backend):
    """Build a request handler class bound to ``backend``."""

    class TwinHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=REPO_ROOT, **kwargs)

        # -- helpers ----------------------------------------------------

        def _json(self, payload, status=200):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _reply(self, result):
            """Send a backend result, using its own status field."""
            status = int(result.get("status", 200 if result.get("ok") else 400))
            self._json(result, status=status)

        def _redirect(self, location):
            self.send_response(302)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _token(self):
            header = self.headers.get("Authorization", "")
            if header.startswith("Bearer "):
                return header[len("Bearer "):].strip()
            return ""

        def _body(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return None
            if length > MAX_BODY_BYTES:
                raise ValueError("request body too large")
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def log_message(self, fmt, *args):
            # Default logging writes the full request line to stderr. This
            # server is internet-facing, so keep tokens out of the logs.
            return

        # -- routing ----------------------------------------------------

        def _static(self, path, *, head_only=False):
            if path in ("/", "/m", "/m/", "/site/mobile"):
                return self._redirect("/site/mobile/")
            asset = "index.html" if path == "/site/mobile/" else path.removeprefix("/site/mobile/")
            mobile_root = (Path(REPO_ROOT) / "site/mobile").resolve()
            target = (mobile_root / asset).resolve()
            # Serve only the PWA bundle, never repository data or symlink targets.
            if (not path.startswith("/site/mobile/") or asset not in MOBILE_ASSETS
                    or target.parent != mobile_root or not target.is_file()):
                return self._json({"error": "not found"}, status=404)
            if head_only:
                return super().do_HEAD()
            return super().do_GET()

        def do_HEAD(self):
            return self._static(unquote(urlparse(self.path).path), head_only=True)

        def do_GET(self):
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            query = parse_qs(parsed.query)

            if path == "/api/twin/snapshot":
                return self._reply(backend.snapshot(self._token()))
            if path == "/api/twin/profile":
                return self._reply(backend.profile(self._token()))
            if path == "/api/twin/trail":
                since = query.get("since_ts", [None])[0]
                return self._reply(
                    backend.trail(self._token(), since_ts=float(since) if since else None)
                )
            if path == "/api/twin/agents":
                return self._reply(backend.agents(self._token()))
            if path == "/api/twin/life":
                return self._reply(backend.life(self._token()))
            if path == "/api/twin/reports":
                since = query.get("since_ts", [None])[0]
                return self._reply(
                    backend.reports(self._token(), since_ts=float(since) if since else None)
                )
            if path == "/api/twin/places":
                return self._reply(backend.places(
                    self._token(),
                    query=query.get("q", [""])[0],
                    limit=int(query.get("limit", ["40"])[0] or 40),
                ))
            if path.startswith("/api/"):
                return self._json({"error": "not found"}, status=404)

            # Redirect rather than rewrite the path. The client's HTML, its
            # manifest `start_url`, and its service-worker scope are all
            # relative, so the browser's base URL must actually be
            # /site/mobile/ — rewriting to the index while leaving the URL at
            # "/" makes every relative asset resolve to the wrong path.
            return self._static(path)

        def do_POST(self):
            parsed = urlparse(self.path)
            path = unquote(parsed.path)

            try:
                body = self._body()
            except (ValueError, json.JSONDecodeError) as exc:
                return self._json({"ok": False, "error": str(exc)}, status=400)

            if path == "/api/twin/auth":
                code = (body or {}).get("code", "") if isinstance(body, dict) else ""
                return self._reply(backend.authenticate(code))
            if path == "/api/twin/report":
                return self._reply(backend.submit(self._token(), body))
            if path == "/api/twin/bind":
                payload = body if isinstance(body, dict) else {}
                return self._reply(backend.bind(self._token(), payload.get("agent_id")))
            if path == "/api/twin/amend":
                payload = body if isinstance(body, dict) else {}
                return self._reply(backend.amend(
                    self._token(),
                    payload.get("target"),
                    payload.get("op"),
                    patch=payload.get("patch"),
                    amend_id=payload.get("amend_id"),
                ))
            return self._json({"error": "not found"}, status=404)

    return TwinHandler


def build_backend(config=None):
    """Build a backend from CONFIG, loading the city map for node snapping."""
    cfg = dict((config or CONFIG).get("twin") or {})
    city_map = None
    try:
        from gaworld.world.city_map import load_city_map_cached

        map_path = os.path.join(REPO_ROOT, (config or CONFIG).get("map_path", "data/citymap.md"))
        city_map = load_city_map_cached(map_path)
    except Exception:
        # Without a map every fix is reported out of map, which is the correct
        # conservative behaviour: better than snapping to a fabricated node.
        city_map = {"nodes": {}}
    base = config or CONFIG
    return TwinBackend(
        root=cfg.get("root", "output/twin"),
        bindings_path=cfg.get("bindings_path", "data/twin_bindings.json"),
        city_map=city_map,
        snapshot_ttl_minutes=cfg.get("snapshot_ttl_minutes", 30),
        max_snap_km=cfg.get("max_snap_km", 3.0),
        # The life card reads what the simulator writes, so these must track
        # the simulator's own output paths rather than being hardcoded.
        diary_dir=base.get("diary_output_dir", "output/diaries"),
        state_dir=base.get("state_output_dir", "output/state"),
        memory_dir=base.get("memory_dir", "output/memory"),
        # The picker reads the simulator's own seed CSV, so it always offers
        # exactly the residents of the selected city.
        roster_path=base.get("csv_path", ""),
        simulated_ids=base.get("agent_ids", ()),
    )


def run_server(host="127.0.0.1", port=8767, backend=None):
    backend = backend or build_backend()
    server = ThreadingHTTPServer((host, int(port)), make_handler(backend))
    print(f"GAWorld twin server: http://{host}:{int(port)}/")
    print("Expose it over HTTPS (Cloudflare Tunnel); Geolocation needs TLS.")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Serve the GAWorld mobile twin API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--issue-code", nargs="?", type=int, const=-1,
                        metavar="AGENT_ID",
                        help="print a new invite code and exit; with no AGENT_ID "
                             "the code is unbound and the phone picks the agent")
    parser.add_argument("--label", default="", help="display label for --issue-code")
    args = parser.parse_args()

    if args.issue_code is not None:
        from gaworld.twin import binding

        cfg = CONFIG.get("twin") or {}
        # `--issue-code` with no value lands as the -1 sentinel: an unbound
        # code, redeemed by a phone that then picks its own agent.
        agent_id = None if args.issue_code == -1 else args.issue_code
        code = binding.issue_code(
            agent_id=agent_id,
            label=args.label,
            path=cfg.get("bindings_path", "data/twin_bindings.json"),
        )
        print(code)
    else:
        run_server(host=args.host, port=args.port)
