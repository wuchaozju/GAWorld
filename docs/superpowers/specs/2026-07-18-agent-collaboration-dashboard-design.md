# Agent Collaboration Dashboard Design

**Date:** 2026-07-18

**Status:** Approved

**Scope:** Dashboard-managed friendships, observable multi-agent discussions, and collaborative team tasks

## 1. Goal

Add three user-facing capabilities to the GAWorld console:

1. Select two or more agents and immediately establish reciprocal friendship relationships.
2. Start a free-form or topic-driven discussion between two or more agents, observe the conversation as it develops, and pause, resume, or stop it.
3. Add a top-level **合作任务** tab where a user can define a task, assemble an agent team, optionally choose a leader or roles, and observe the team plan, execution, review, artifacts, and final result.

Discussions and collaborative tasks must run without the main city simulation being active. When the simulation is active, the subsystem may also publish lifecycle events to the kernel event bus.

## 2. Existing-System Fit

The design reuses:

- agent profiles, state, memory snapshots, capabilities, and private skills exposed by the Dashboard application;
- relationship records under the configured memory directory;
- the existing LLM provider and task-routing infrastructure;
- the kernel plugin and event-bus extension model;
- the existing console shell, which hosts Dashboard, Simulation, and Agent Studio views as persistent same-origin tabs.

The new subsystem lives under `gaworld/` and is assembled as a `gaworld.kernel.Plugin`. Business logic does not live in `generative_city_sim.py` or in the HTTP handler.

## 3. Selected Architecture

Use a unified, plugin-backed collaboration session engine.

### 3.1 Components

`CollaborationPlugin`

- Registers the subsystem through the existing built-in plugin assembly.
- Owns optional integration with the kernel event bus when a simulation controller is available.
- Does not require the simulation clock for Dashboard-created sessions.

`CollaborationService`

- Validates members and commands.
- Creates discussion and cooperation sessions.
- Applies pause, resume, and cancel transitions.
- Exposes session history, snapshots, events, and artifacts to the Dashboard API.

`RelationshipService`

- Creates reciprocal in-simulation friendship records for every pair in the selected group.
- Uses deterministic pair ordering, per-group locking, and atomic file replacement.
- Makes repeated requests idempotent.

`DiscussionRunner`

- Builds each speaker's context from the profile, capabilities, relevant memory, the topic, and recent session events.
- Gives members turns in stable round-robin order.
- Supports free discussion when the topic is empty.
- Stops at the configured round limit or after an explicit convergence signal.
- Produces a final summary and member-specific experience records.

`CooperationRunner`

- Analyzes member capabilities and creates a task plan.
- Assigns roles automatically unless the user provided a leader or role overrides.
- Executes bounded subtasks, records progress, and captures artifacts.
- Adds a cross-review phase before a leader or designated synthesizer creates the final deliverable.

`SessionStore`

- Persists the current session snapshot atomically.
- Appends immutable, monotonically sequenced events to JSONL.
- Stores produced artifacts in a session-scoped directory.
- Recovers interrupted sessions after a server restart.

`SessionWorker`

- Runs independent sessions outside HTTP request threads.
- Checks pause and cancellation commands between bounded LLM or artifact steps.
- Prevents two workers from advancing the same session simultaneously.

## 4. Data Model and Persistence

### 4.1 Session

A session contains:

- `id`
- `kind`: `discussion` or `cooperation`
- `title`
- `topic` or `task`
- ordered `member_ids`
- optional `leader_id`
- optional per-member role overrides
- resolved roles
- `max_rounds` for discussions
- current round or task phase
- `status`
- timestamps
- current plan
- artifact metadata
- error and recovery metadata

Supported statuses:

`queued -> running <-> paused -> completed`

From `queued`, `running`, or `paused`, a session may become `cancelled`. A step failure changes it to `failed`; a failed session may be resumed from its last completed step. On process restart, sessions left in `running` become the additional non-terminal status `interrupted`, which is resumable but never advances automatically without an explicit resume command.

### 4.2 Event

Each append-only event contains:

- `seq`
- `type`
- `timestamp`
- optional `agent_id`
- human-readable `content`
- structured `metadata`

Event types cover creation, role assignment, planning, messages, progress, artifact creation, review, pause, resume, completion, cancellation, and errors.

### 4.3 Artifact

Artifact metadata contains:

- safe relative filename
- media type
- owning or producing agent
- summary
- size
- creation time

Artifact paths are confined to the session's artifact directory. Absolute paths and traversal segments are rejected.

### 4.4 Files

```text
output/collaboration/
└── sessions/
    └── <session-id>/
        ├── session.json
        ├── events.jsonl
        └── artifacts/
            └── ...
```

Relationships remain in the configured memory directory:

```text
output/memory/
├── agent_<id>_relationships.json
└── agent_<id>_episodes.jsonl
```

Generated collaboration files remain local runtime output and are not committed.

## 5. Friendship Behavior

The Dashboard accepts two or more unique, existing agent IDs. For a group, the service applies friendship to every unordered pair.

For each pair:

- both agents receive reciprocal records keyed by the other agent's ID;
- new records use role `friend`, kind `agent`, the peer's current name, closeness `0.65`, trust `0.60`, obligation `0.40`, friction `0.10`, and Dashboard provenance;
- existing stronger values and more specific roles are preserved;
- existing records are promoted to at least those closeness, trust, and obligation values, while friction is reduced to at most `0.10`;
- `social_neighbors` compatibility is maintained where that field is represented;
- `last_interaction` and relationship schema fields are normalized;
- repeating the same operation does not duplicate or weaken the relationship.

The API returns the pairs created, pairs updated, and pairs already present.

## 6. Discussion Flow

1. Validate two or more members and a round limit between 3 and 20.
2. Create and persist the queued session.
3. The worker marks it running and emits a start event.
4. For each turn, load the speaker's stable identity context and only the bounded recent session context.
5. Call the configured LLM with a dedicated discussion task route.
6. Append the complete response as a message event.
7. Check pause, cancellation, round completion, and explicit convergence.
8. On normal completion, generate a concise discussion summary.
9. Append a reference and summary to each member's episode history.
10. Update recent interaction metadata for member relationship pairs without automatically creating friendship when none existed.

The user may leave the topic blank for free discussion. The UI still supplies a neutral opening instruction so the first speaker can begin naturally.

## 7. Collaborative Task Flow

1. Validate the task text and selected members.
2. Read current agent capabilities, skills, interests, and cognition summaries.
3. Generate a bounded plan with named stages, deliverables, role assignments, and completion criteria.
4. Apply user-selected leader and role overrides after automatic planning.
5. Execute member subtasks and append progress and artifact events.
6. Run at least one cross-review step by a member other than the artifact author.
7. Give revision feedback to the responsible member when needed.
8. Have the leader or synthesizer produce the final deliverable and summary.
9. Store final artifacts and write a collaboration experience reference for every member.

An individual step may be retried twice. The third failure emits an error event and marks the session failed at that step. Resuming continues from the last completed step instead of regenerating the entire session.

## 8. API

### Relationships

`POST /api/relationships/friends`

```json
{
  "agent_ids": [1, 2, 3]
}
```

### Sessions

- `POST /api/collaboration/sessions`
- `GET /api/collaboration/sessions?kind=<kind>&status=<status>`
- `GET /api/collaboration/sessions/<id>`
- `GET /api/collaboration/sessions/<id>/events?after=<seq>`
- `POST /api/collaboration/sessions/<id>/pause`
- `POST /api/collaboration/sessions/<id>/resume`
- `POST /api/collaboration/sessions/<id>/cancel`

Discussion creation accepts member IDs, an optional topic, and `max_rounds`.

Cooperation creation accepts member IDs, task text, an optional leader ID, and optional role overrides.

Invalid JSON, duplicate or unknown members, insufficient members, invalid transitions, and unsafe artifact paths return client errors. Internal exceptions are logged with tracebacks while the API returns a concise error message.

## 9. Dashboard Design

### 9.1 Intelligent Interaction Panel

The existing Dashboard gains an **智能体互动** panel near the agent and interview controls.

It contains:

- multi-select agent chips with ID and name;
- a relationship action showing an explicit success summary;
- an optional topic field;
- a discussion round selector;
- a start button;
- a live transcript with speaker identity, round progress, and status;
- pause, resume, cancel, and full-history controls.

The transcript incrementally polls the events endpoint once per second while a session is active. Polling stops when the page is hidden or the session reaches a terminal state and resumes when the view becomes active.

### 9.2 Cooperation Tab

The console shell adds the top-level tab **合作任务**, loading a same-origin collaboration page and preserving it when the user switches tabs.

The page has three primary areas:

- **Team builder:** task description, member selection, capability hints, leader selection, and optional role overrides.
- **Task workspace:** current phase, progress, plan, member role cards, subtask status, and final summary.
- **Activity and artifacts:** ordered event stream, pause/resume/cancel controls, artifact list, and links to view or download safe local artifacts.

The page also shows prior sessions and allows the user to reopen completed, failed, cancelled, or interrupted work.

### 9.3 Visual and Accessibility Constraints

- Reuse the console's established green, paper, steel, and status colors.
- Preserve the current typography and panel vocabulary.
- Keep controls keyboard accessible and expose status updates through live regions.
- Do not communicate status by color alone.
- Collapse the three-column cooperation workspace into a single readable flow on narrow screens.

## 10. Concurrency and Error Handling

- HTTP requests never wait for a complete discussion or task.
- Session commands are serialized per session.
- Relationship writes lock all affected agent files in sorted ID order.
- Session snapshots use temporary-file replacement.
- Events are append-only and flushed after each event.
- LLM calls use the existing provider routing and never expose credentials in events or responses.
- Missing provider configuration produces a visible failed event and a resumable session.
- A malformed persisted session is skipped, logged, and surfaced in a health summary rather than preventing other sessions from loading.

## 11. Testing

All production behavior is introduced test-first.

### Unit tests

- reciprocal friendship creation;
- idempotent repeated friendship requests;
- preservation of stronger or more specific existing relationships;
- all-pairs creation for groups;
- member validation and atomic failure behavior;
- session serialization and monotonically increasing events;
- allowed and rejected state transitions;
- restart interruption and explicit resume;
- safe artifact path enforcement;
- discussion ordering, round limits, convergence, pause, and cancellation;
- capability-based role assignment, user overrides, cross-review, retries, and final artifact creation.

### API tests

- relationship, creation, list, detail, event polling, and command endpoints;
- client errors for invalid payloads and transitions;
- incremental event retrieval using `after`.

### Frontend tests

- console tab registration and activation;
- multi-agent selection;
- relationship request rendering;
- discussion and cooperation payload construction;
- incremental polling and terminal-state shutdown;
- pause, resume, and cancel controls;
- safe rendering of agent and LLM-provided text.

### Verification

- Run focused tests during each red-green-refactor cycle.
- Run the complete `pytest tests` suite.
- Run `ruff check .` and relevant formatting checks.
- Exercise friendship, discussion, pause/resume, and collaboration flows in a local browser using mocked LLM responses.
- Confirm no test makes real network calls.

## 12. Acceptance Criteria

- Two or more selected agents can become reciprocal friends from the Dashboard.
- A free or topic-driven multi-agent discussion can run with the main simulation stopped.
- The transcript remains observable during execution and persists across page refreshes.
- Discussions can pause, resume, cancel, and finish with a summary.
- The console contains a working **合作任务** tab.
- A selected team receives a plan and roles, executes subtasks, performs cross-review, and produces a final downloadable artifact.
- Cooperation progress and events remain observable and persistent.
- Interrupted or failed sessions are visible and can be resumed intentionally.
- Existing Dashboard behavior remains working.
- Existing unrelated worktree changes are not overwritten or included in the feature commits.

## 13. Deliberate Non-Goals

- Real-time peer-to-peer audio or video.
- Remote multi-user access control.
- Running unlimited autonomous sessions.
- Automatically making discussion participants friends.
- Replacing the existing real-work marketplace.
- Embedding collaboration business logic directly in the CLI entrypoint or Dashboard HTTP handler.
