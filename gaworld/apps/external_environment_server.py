import argparse
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from gaworld.settings import CONFIG
from gaworld.env.system import EnvironmentSystem
from gaworld.llm.providers import call_llm


def _to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


class EnvironmentBackend:
    def __init__(self, config, state_path, llm_enabled=True):
        self.config = dict(config or {})
        self.state_path = state_path
        self.lock = threading.RLock()
        self.env = EnvironmentSystem(self.config, llm_fn=(call_llm if llm_enabled else None))
        self.latest_day = 0
        self.day_cache = {}
        self.tick_cache = {}
        self._load()

    def _persist(self):
        if not self.state_path:
            return
        directory = os.path.dirname(self.state_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        payload = {
            "latest_day": int(self.latest_day),
            "day_cache": self.day_cache,
            "tick_cache": self.tick_cache,
            "engine_state": self.env.export_runtime_state(),
        }
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def _load(self):
        if not self.state_path or not os.path.exists(self.state_path):
            return
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        self.latest_day = _to_int(payload.get("latest_day", 0), 0)
        raw_day_cache = payload.get("day_cache", {})
        raw_tick_cache = payload.get("tick_cache", {})
        self.day_cache = {str(k): v for k, v in raw_day_cache.items()} if isinstance(raw_day_cache, dict) else {}
        self.tick_cache = {str(k): v for k, v in raw_tick_cache.items()} if isinstance(raw_tick_cache, dict) else {}
        self.env.import_runtime_state(payload.get("engine_state", {}))

    def _default_day_context(self, day):
        return {
            "sim_date": "",
            "weekday_zh": "",
            "day_type_zh": "",
            "day": int(day),
        }

    def _ensure_day(self, day, day_context=None):
        day = _to_int(day, 1)
        key = str(day)
        if key in self.day_cache:
            return

        if self.latest_day and day > self.latest_day + 1:
            for d in range(self.latest_day + 1, day):
                auto_ctx = self._default_day_context(d)
                events = self.env.start_day(d, day_context=auto_ctx, agents=None)
                ctx = self.env.get_day_context_text()
                self.day_cache[str(d)] = {
                    "events": events,
                    "context": ctx,
                    "day_context": auto_ctx,
                }
                self.tick_cache.setdefault(str(d), {})
                self.latest_day = max(self.latest_day, d)

        use_ctx = day_context if isinstance(day_context, dict) and day_context else self._default_day_context(day)
        events = self.env.start_day(day, day_context=use_ctx, agents=None)
        ctx = self.env.get_day_context_text()
        self.day_cache[key] = {
            "events": events,
            "context": ctx,
            "day_context": use_ctx,
        }
        self.tick_cache.setdefault(key, {})
        self.latest_day = max(self.latest_day, day)
        self._persist()

    def start_day(self, day, day_context=None):
        with self.lock:
            self._ensure_day(day, day_context=day_context)
            payload = self.day_cache[str(_to_int(day, 1))]
            return {
                "day": _to_int(day, 1),
                "events": payload.get("events", []),
                "context": payload.get("context", ""),
                "day_context": payload.get("day_context", {}),
            }

    def tick(self, day, time_str):
        with self.lock:
            day = _to_int(day, 1)
            key = str(day)
            self._ensure_day(day)
            time_key = str(time_str)
            day_ticks = self.tick_cache.setdefault(key, {})
            if time_key in day_ticks:
                cached = day_ticks[time_key]
                return {
                    "day": day,
                    "time": time_key,
                    "events": cached.get("events", []),
                    "context": cached.get("context", self.env.get_context_text()),
                }
            events = self.env.tick(day, time_key, agents=None)
            context = self.env.get_context_text()
            day_ticks[time_key] = {
                "events": events,
                "context": context,
            }
            self._persist()
            return {
                "day": day,
                "time": time_key,
                "events": events,
                "context": context,
            }

    def snapshot(self):
        with self.lock:
            return {
                "latest_day": int(self.latest_day),
                "day_count": len(self.day_cache),
                "tick_count": sum(len(v) for v in self.tick_cache.values() if isinstance(v, dict)),
                "engine_state": self.env.export_runtime_state(),
            }


class EnvironmentRequestHandler(BaseHTTPRequestHandler):
    backend = None

    def _read_json(self):
        raw_len = self.headers.get("Content-Length", "0")
        size = _to_int(raw_len, 0)
        if size <= 0:
            return {}
        raw = self.rfile.read(size)
        if not raw:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._write_json(200, {"ok": True})
            return
        if self.path == "/snapshot":
            self._write_json(200, self.backend.snapshot())
            return
        self._write_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/day/start":
            payload = self._read_json()
            day = _to_int(payload.get("day", 1), 1)
            day_context = payload.get("day_context", {})
            data = self.backend.start_day(day, day_context=day_context)
            self._write_json(200, data)
            return
        if self.path == "/tick":
            payload = self._read_json()
            day = _to_int(payload.get("day", 1), 1)
            time_str = str(payload.get("time", "00:00"))
            data = self.backend.tick(day, time_str)
            self._write_json(200, data)
            return
        self._write_json(404, {"error": "not found"})


def _build_arg_parser():
    parser = argparse.ArgumentParser(description="External environment backend server")
    server_cfg = CONFIG.get("environment_server", {})
    default_use_llm = bool(server_cfg.get("use_llm", True))
    parser.add_argument("--host", default=server_cfg.get("host", "0.0.0.0"), help="Bind host")
    parser.add_argument("--port", type=int, default=int(server_cfg.get("port", 8765)), help="Bind port")
    parser.add_argument(
        "--state-path",
        default=server_cfg.get("state_path", "output/environment/server_state.json"),
        help="State persistence path",
    )
    parser.set_defaults(use_llm=default_use_llm)
    parser.add_argument(
        "--use-llm",
        dest="use_llm",
        action="store_true",
        help="Enable LLM-driven environment generation",
    )
    parser.add_argument(
        "--no-llm",
        dest="use_llm",
        action="store_false",
        help="Disable LLM-driven environment generation and use rule fallback only",
    )
    return parser


def main():
    parser = _build_arg_parser()
    args = parser.parse_args()

    backend = EnvironmentBackend(CONFIG, state_path=args.state_path, llm_enabled=bool(args.use_llm))
    EnvironmentRequestHandler.backend = backend

    server = ThreadingHTTPServer((args.host, int(args.port)), EnvironmentRequestHandler)
    print(f"[external-environment-server] listening on http://{args.host}:{args.port}")
    print(f"[external-environment-server] state path: {args.state_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
