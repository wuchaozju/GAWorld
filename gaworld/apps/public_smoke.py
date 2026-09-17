"""Check real public responses, including a two-agent Relay round trip."""

from __future__ import annotations

import argparse
import base64
import json
import os
import uuid
from urllib.request import Request, urlopen


def request_json(url, payload=None, *, username="", password=""):
    headers = {"Accept": "application/json"}
    if username and password:
        credential = base64.b64encode(f"{username}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {credential}"
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    with urlopen(Request(url, data=data, headers=headers), timeout=30) as response:
        if response.headers.get_content_type() != "application/json":
            raise ValueError(f"Expected JSON, got {response.headers.get_content_type()}: {url}")
        return json.load(response)


def check_relay(base_url):
    base = base_url.rstrip("/")
    if request_json(base + "/health").get("ok") is not True:
        raise ValueError("Relay health check failed")
    cluster = "public-smoke-" + uuid.uuid4().hex
    for agent_id in (1, 2):
        result = request_json(base + "/register", {
            "cluster": cluster, "node_id": f"smoke-{agent_id}",
            "agents": [{"id": agent_id, "name": f"Smoke {agent_id}"}],
        })
        if not result.get("ok"):
            raise ValueError("Relay registration failed")
    marker = uuid.uuid4().hex
    sent = request_json(base + "/message/send", {
        "cluster": cluster, "node_id": "smoke-1",
        "message": {"from_agent": 1, "to_agent": 2, "text": marker},
    })
    if not sent.get("ok"):
        raise ValueError("Relay send failed")
    result = request_json(base + "/message/poll", {
        "cluster": cluster, "recipient_ids": [2], "since": {"2": 0}, "limit": 10,
    })
    if not any(message.get("text") == marker for message in result.get("messages", [])):
        raise ValueError("Relay message was not delivered")
    return {"health": "ok", "register": "ok", "send": "ok", "poll": "ok", "cluster": cluster}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--username", default="gaworld")
    parser.add_argument("--password-env", default="GAWORLD_PUBLIC_PASSWORD")
    parser.add_argument("--relay-round-trip", action="store_true",
                        help="write synthetic agents/messages into a unique test cluster")
    args = parser.parse_args(argv)
    base = args.base_url.rstrip("/")
    password = os.environ.get(args.password_env, "")
    result = {}
    for path in ("/api/config", "/api/agents", "/api/run/status", "/api/todos"):
        request_json(base + path, username=args.username, password=password)
        result[path] = "JSON ok"
    if args.relay_round_trip:
        result["relay"] = check_relay(base + "/agent-relay")
    else:
        result["relay"] = request_json(base + "/agent-relay/health")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
