# Hosting GAWorld under /GAWorld/

This opt-in mount serves the same application and data at both the existing
root paths and `/GAWorld/`. It does not change account registration, roles,
simulation models, personal provider keys, or existing root sessions.

## Application Operator

1. Deploy the code containing `gaworld/apps/subpath.py` and `site/url.js`.
2. Back up the account database with SQLite's backup API, private credentials,
   runtime settings and research output. Check for live experiments before
   restarting. Stop the automatic deployment watcher during the release.
3. Install `subpath.conf` as the dashboard's user-systemd drop-in. Keep all
   existing account/security environment settings. Do not set
   `GAWORLD_PUBLIC_URL` just to enable this mount: it also controls mail URLs
   and secure cookies in the existing root deployment.
4. Run `systemctl --user daemon-reload` and restart only
   `gaworld-dashboard.service`. Do not restart Relay, mobile or the tunnel.
5. Verify both `/api/health` and `/GAWorld/api/health` return GAWorld JSON with
   accounts required. Both anonymous `/api/config` endpoints must return 401.
   Then test login, world selection, a board submission and a report download.
6. Update the deployment marker and resume the watcher only after release
   verification. Keep the old entry point until the company ingress is verified.

The prefix is configured by the environment, not `X-Forwarded-Prefix`. Path
segments are case-sensitive ASCII letters, digits, underscores or hyphens.
Cookie names and paths are isolated between the root and mounted deployments;
users log in once at the new address using their existing credentials. The old
address remains usable. No account migration or password reset is needed.

## Company Ingress Operator

Include `mo-subpath.locations.conf` in the existing HTTPS server block, then
validate with `nginx -t` before loading it. Do not use
`mo-gaworld.locations.conf`, the legacy root-route example, for this new mount.
Do not rewrite the entire site's `/api/`, `/site/`, cookies, or response HTML.

`proxy_pass http://10.72.74.13:8766;` deliberately has no URI suffix. The backend
must receive `/GAWorld/...`, not have that prefix removed. Nginx terminates TLS
and sets `X-Forwarded-Proto`; if TLS terminates further upstream, configure the
trusted proxy chain instead. Preserve methods, bodies, authorization, cookies,
query strings and upstream error statuses. Disable private-response caching.

Check connectivity from the actual proxy container/host:

```sh
curl --fail --connect-timeout 5 --max-time 10 http://10.72.74.13:8766/GAWorld/api/health
curl -i --max-time 10 http://10.72.74.13:8766/GAWorld/api/config
```

Expected: first 200 JSON (`service=gaworld-dashboard`), second 401 JSON. The
same checks must pass at `https://mo.zju.edu.cn/GAWorld` after configuration.
Then verify login/logout, navigation, downloads, two-account isolation and Mo's
existing pages on desktop and mobile from outside the campus network.

This is not Mo SSO. Only the platform on port 8766 is in scope. Mobile (8767)
and Relay (8877) still use their existing deployment; do not disable the old
tunnel merely because the main platform can be accessed on Mo.

## Regression And Rollback

Run `pytest tests/test_subpath.py tests/test_auth_frontend.py` and
`node --test site/url.test.js tests/test_workspace_context.test.js`, followed
by the full suites. Browser verification must block same-origin requests
outside the configured mount to detect root-path leaks.

To disable the mount while retaining the new compatible code, remove only the
`subpath.conf` drop-in, reload user-systemd and restart the dashboard after
checking active jobs. Restore/remove only the new Mo location block. Existing
root access works without the environment variable. Never restore an old
account database as a code rollback: that would erase new users and invites.
