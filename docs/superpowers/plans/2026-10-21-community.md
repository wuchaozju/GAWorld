# Personal workspaces and public research community implementation plan

> Execution: inline, test-first implementation of the approved design. Request independent code review at the integration checkpoint.

**Goal:** Deliver open registration, private workspaces, versioned research sharing, public discussion, and permission-checked reuse.

**Architecture:** Extend the existing account store with versioned migrations, keeping invite accounts compatible. Keep public snapshots and social records in an independent community store; HTTP delegates never open private output to anonymous visitors. Reuse existing research/world execution and require explicit user starts.

**Tech stack:** Python standard library SQLite/SMTP, existing dashboard routing and OpenAPI, vanilla HTML/CSS/JavaScript, pytest and browser verification. No new frontend build.

## A. Accounts and private workspace

- [x] Add `tests/test_community_accounts.py`: migrate existing accounts; open registration remains disabled by default; verification/recovery tokens expire and are single-use; disabled accounts lose sessions; SMTP failure cannot verify an account; independent display names do not change login identity.
- [x] Run `/Users/cw/dev/venv/bin/python -m pytest tests/test_community_accounts.py -q`; observe failures before implementing.
- [x] Add `gaworld/accounts/community.py` for additive schema/versioning, profile/account states, open registration, hashed action tokens, session revocation, and persisted rate limits. Wire migration through `AccountStore.init_schema()` and augment authenticated identities without exposing emails in public profiles.
- [x] Add `gaworld/accounts/mail.py` for configured SMTP and explicit development outbox, validating public base URL and surfacing unavailable delivery.
- [x] Extend `accounts_api.py`, `policy.py`, and auth UI for register/verify/recover/profile/session/admin operations. Guard writes against foreign Origin and invalid expected-world context.
- [x] Add `gaworld/apps/workspace_api.py`: account-owned overview across worlds with only safe metadata. Existing detail/run APIs retain user/world authorization.
- [x] Add atomic daily call reservations before provider execution, settlement after every attempt, and cross-process account checks. Retain historical JSONL telemetry.

Behavior checks include:

```python
def test_invite_accounts_remain_compatible(store):
    code = store.create_invites(1)[0]
    user = store.register(code, "legacy", "correct horse")
    assert store.authenticate("legacy", "correct horse")["id"] == user["id"]
```

## B. Publishing and discovery

- [x] Add `tests/test_community.py`: two accounts, immutable versions, idempotent publish, withdrawal, public field whitelist, denied private sources, and validated attachment bytes.
- [x] Run the new tests red, then implement `gaworld/community/store.py`, `schema.py`, `publications.py`, and `sources.py` as bounded modules. Use account SQLite transactions and standalone publication/attachment rows to avoid direct private filesystem access.
- [x] Create source adapters for owned research plans, studies, and simulation cases. Hash the source revision and copy only explicitly selected public content. Source changes invalidate publish confirmation.
- [x] Add `gaworld/apps/community_api.py` delegates, precise public-read policy and OpenAPI entries; public reads never widen private `ownership.visible()`.
- [x] Add public discovery/detail/profile views, publish preview and version actions; integrate research-report and simulation-workbench entry points.

Behavior check:

```python
def test_public_read_never_returns_credentials(community, author):
    draft = community.draft(author, {"title": "Study", "body": "Report", "license": "read_only"})
    published = community.publish(author, draft["id"], draft["revision"])
    assert "api_key" not in str(community.publication(published["id"]))
```

## C. Discussion, moderation, and reuse

- [x] Add failing tests for public threads, version-bound replies, deleted-parent placeholders, locks, unauthorized edits, collection uniqueness, notifications after withdrawal, moderator-only actions, and immutable fork provenance.
- [x] Implement `gaworld/community/discussions.py`, `social.py`, and the reuse adapter in `sources.py`; validate every referenced target before writing and reading. Record edit history and management audit. Moderators gain no private research access.
- [x] Fork only allowed public plan data into an owned research draft. Reject unsupported dependencies/licenses, strip providers/credentials/runtime state, retain parent publication/version, and never start tasks.
- [x] Add UI for posts, replies, bookmarks, inbox, reports, moderation, version history and fork-to-workspace, with escaped text and safe URL handling.
- [x] Provide community plugin assembly entry point without adding simulation behavior or CLI inline logic.

## Integration and delivery

- [x] Run account, ownership, research-member, routing, OpenAPI and core suites. Use the existing project interpreter, not an unrelated Python install.
- [x] Run changed-file lint ratchet and formatting; fix new findings without touching unrelated backlog.
- [x] Independent reviewer checks account/public/private boundaries, source/attachment sanitization, and UI completeness. Fix important findings before delivery.
- [x] Browser walkthrough with an isolated temporary account database and deterministic source data: visitor read → account login → workspace → publish → second user comment/bookmark/fork → withdraw → visitor access denied. Check desktop and 390px widths.
- [x] Document SMTP, account initialization, mode switches, backups, moderation, and recovery in `docs/COMMUNITY.md`. Do not initialize production credentials, migrate historical ownership, send real messages, or run paid studies during verification.
- [x] Update verification evidence and task checkboxes with actual results; keep unresolved production configuration visible.

## Completion evidence

Implementation and controlled verification completed. See `docs/reports/2026-10-21-community-verification.md` and `docs/COMMUNITY.md` for actual results, production configuration, and first-release boundaries. No production accounts or real model studies were started.
