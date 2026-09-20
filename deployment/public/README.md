# GAWorld public gateway

The gateway on port 8780 is separate from the Mo ingress. Installing it does not
change `mo.zju.edu.cn`; the domain administrator must apply the Nginx fragment.

## Routes and authentication

| Public path | Local upstream | Access |
| --- | --- | --- |
| `/console`, `/dashboard`, dashboard assets/APIs | `127.0.0.1:8766` | HTTP Basic |
| `/board`, `/api/todos*` through this gateway | `127.0.0.1:8766` | HTTP Basic |
| `/agent-relay/health`, `/agent-relay/register`, message/profile routes | `127.0.0.1:8877` | Relay's own authorization policy |
| `/site/mobile/`, `/api/twin/*` | `127.0.0.1:8767` | Mobile API bearer token |

Relay's prefix is removed by Caddy, not Nginx. `/auth/token` is deliberately not
published. A healthy Relay is a JSON service, not a separate web homepage.
On the current test server Relay registration is open: do not use it for private
conversations or treat cluster names as access-control credentials. Restrict
access or enable Relay authentication before a production release.

Never forward `/api/` or `/site/` globally on Mo: those namespaces are shared.
Never expose dashboard config-write/run-start endpoints without authentication.
The existing Mo board routes can remain unchanged; they are not covered by the
new dashboard authentication unless their upstream is changed to this gateway.

## Server installation

Prerequisites: the three application services above, Caddy 2 with `basic_auth`,
cloudflared at `~/.local/bin/cloudflared`, user systemd and linger enabled.
The unit templates assume the application checkout is `~/GAWorld`.

1. Copy `Caddyfile` to `~/.config/gaworld/Caddyfile`.
2. Generate a strong password privately. Run `caddy hash-password` interactively.
   Store only `GAWORLD_PUBLIC_PASSWORD_HASH=<bcrypt hash>` in
   `~/.config/gaworld/public-gateway.env`, mode 0600. Do not commit this file.
3. Copy both `.service` files to `~/.config/systemd/user/`.
4. Validate with `caddy validate --config ~/.config/gaworld/Caddyfile --adapter caddyfile`
   in an environment containing the hash, then:

```bash
systemctl --user daemon-reload
systemctl --user enable --now gaworld-public-gateway gaworld-public-tunnel
systemctl --user status gaworld-public-gateway gaworld-public-tunnel
journalctl --user -u gaworld-public-tunnel --no-pager
```

The temporary HTTPS hostname appears in the tunnel log. It can change if the
tunnel is recreated; do not restart the tunnel just to update Python code.
For a stable hostname use the existing Mo ingress or a managed named tunnel.

## Mo ingress handoff

Give the administrator `mo-gaworld.locations.conf`. It belongs inside the
existing HTTPS `server` block. Replace overlapping locations; an existing exact
`location = /dashboard` or a `^~ /api/` catch-all can prevent a regex from matching.
Keep the original URI in `proxy_pass http://10.72.74.13:8780;` (no URI suffix).
Preserve `Authorization`; do not substitute the Mo login credentials upstream.
First confirm the Mo host can reach `10.72.74.13:8780`, then run `nginx -t` and
reload using its existing deployment procedure. Keep a backup of the old config.

## Acceptance checks

```bash
curl -i https://mo.zju.edu.cn/agent-relay/health
curl -i https://mo.zju.edu.cn/api/twin/snapshot
curl -i https://mo.zju.edu.cn/api/config
```

Expected: Relay is **200 JSON**; unauthenticated twin is **401 JSON**;
unauthenticated dashboard is **401**, not the Mo HTML homepage.
With the Basic password supplied privately via `GAWORLD_PUBLIC_PASSWORD`:

```bash
python -m gaworld.apps.public_smoke \
  --base-url https://mo.zju.edu.cn --relay-round-trip
```

This verifies JSON responses and a real two-agent message delivery in a unique
test cluster. It does not certify every simulation plugin or long-running LLM
experiment. Afterwards open the console, Studio, settings, city and collaboration
tabs in a browser and check their API/asset requests, not only the initial HTML.

## Application updates

The existing `scripts/deploy_services.py` CLI supports `deploy`, `watch` and
`status`. Use the exact virtualenv interpreter path with `--python`; resolving
its symlink bypasses the virtual environment. The watcher currently updates and
restarts dashboard and Relay; the separate twin worktree requires an explicit
update preserving `output/twin/` and `data/twin_bindings.json`.
