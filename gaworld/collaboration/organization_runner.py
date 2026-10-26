"""Adapt the shared organization executor to persistent cooperation sessions."""

from __future__ import annotations

import json

from gaworld.collaboration import organization_engine
from gaworld.collaboration.models import SessionStatus
from gaworld.collaboration.organization_methods import method_hash


class Suspended(Exception):
    """Session was paused/cancelled while a model request was in flight."""


class OrganizationRunner:
    def __init__(self, *, store, agent_loader, llm, episode_writer=None, **kwargs):
        self.store, self.agent_loader, self.llm = store, agent_loader, llm

    def run(self, identifier):
        session = self.store.get(identifier)
        chosen = session.organization_method
        if method_hash(chosen["method"]) != chosen["method_hash"]:
            raise ValueError("组织方式快照已改变")
        if session.status in {SessionStatus.COMPLETED, SessionStatus.CANCELLED, SessionStatus.PAUSED}:
            return
        with self.store.session_guard(identifier):
            session = self.store.get(identifier)
            if session.status is not SessionStatus.RUNNING:
                session.transition(SessionStatus.RUNNING)
            session.roles = {
                str(member): role
                for member, role in zip(session.member_ids, chosen["method"]["roles"], strict=True)
            }
            session.leader_id = session.member_ids[0]
            if not session.plan:
                session.plan = [
                    {"agent_id": member, "title": role, "status": "pending"}
                    for member, role in zip(session.member_ids, chosen["method"]["roles"], strict=True)
                ]
                self.store.append_event(
                    identifier, "plan_created", chosen["method"]["name"], metadata={"plan": session.plan}
                )
            self.store.save(session)
        path = self.store._dir(identifier) / "organization-state.json"
        state = json.loads(path.read_text()) if path.exists() else {}
        members = [{"id": i, "identity": self.agent_loader(i) or {}} for i in session.member_ids]
        # Freeze identities on first execution so pause/resume cannot pull changed residents.
        frozen_members = state.setdefault("members", members)

        def check():
            if self.store.get(identifier).status is not SessionStatus.RUNNING:
                raise Suspended()

        def checkpoint(updated, event):
            with self.store.session_guard(identifier):
                self.store._atomic_json(path, updated)
                phase = event.get("phase", "")
                if event.get("status") == "started":
                    self.store.append_event(
                        identifier,
                        "turn_started",
                        phase,
                        agent_id=event["agent_id"],
                        metadata={"phase": phase},
                    )
                elif event.get("status") == "completed":
                    self.store.append_event(
                        identifier,
                        "message",
                        event.get("response", "")[:4000],
                        agent_id=event["agent_id"],
                        metadata={"phase": phase},
                    )

        try:
            outcome = organization_engine.run_method(
                chosen["method"],
                frozen_members,
                {"id": identifier, "prompt": session.task},
                lambda prompt, **kw: self.llm(prompt, task="collaboration.organization", **kw),
                state=state,
                checkpoint=checkpoint,
                before_call=check,
            )
            check()
        except Suspended:
            return
        answer = outcome["answer"].get("answer")
        if answer is None:
            raise ValueError("组织没有提交合法的最终成果")
        text = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False, indent=2)
        with self.store.session_guard(identifier):
            check()
            self.store.write_artifact(
                identifier, "final.md", text, agent_id=session.leader_id, summary=chosen["method"]["name"]
            )
            latest = self.store.get(identifier)
            latest.current_step = len(latest.plan)
            for step in latest.plan:
                step["status"] = "completed"
            latest.transition(SessionStatus.COMPLETED)
            self.store.save(latest)
            self.store.append_event(
                identifier,
                "artifact",
                "final.md",
                agent_id=session.leader_id,
                metadata={
                    "final": True,
                    "excerpt": text[:320],
                    "method_hash": chosen["method_hash"],
                    "engine_version": outcome["engine_version"],
                    "metrics": outcome["metrics"],
                },
            )
            self.store.append_event(identifier, "completed", "组织协作任务已完成")
