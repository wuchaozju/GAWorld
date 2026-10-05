"""Resident-facing facts derived from executed state, never narrative claims."""

from __future__ import annotations


def perception(store, agent):
    lines = []
    number = agent["id"]
    for org in store.list_organizations():
        member = store.get("members", f"{org['organization_id']}:{number}")
        if member and member["left_day"] is None:
            role = "负责人" if org["leader_id"] == number else ("员工" if member.get("job_id") else "成员")
            lines.append(
                f"你是{org['name']}的{role}；组织可用资金{org['balance_cents'] / 100:.2f}元，规则{org['rule']}（第{org['rule_version']}版），状态{org['status']}。"
            )
        if org["kind"] == "company" and org["status"] == "open":
            for job in store.rows("jobs", org["organization_id"]):
                available = job["vacancies"] - job["occupied"]
                if available:
                    lines.append(
                        f"{org['name']}招聘{job['occupation']}，空缺{available}人，月工资{job['monthly_salary_cents'] / 100:.2f}元。"
                    )
        for app in store.rows("applications", org["organization_id"]):
            if app["agent_id"] == number:
                lines.append(
                    f"你向{org['name']}的申请状态：{app['status']}；原因：{app['reason']}；实际收到{app['paid_cents'] / 100:.2f}元。"
                )
        debt = sum(
            t.get("arrears_remaining_cents", 0)
            for t in store.rows("transactions", org["organization_id"])
            if t.get("agent_id") == number
        )
        if debt:
            lines.append(f"{org['name']}尚欠你工资或雇佣款项{debt / 100:.2f}元，到账前不可当作已有收入。")
        for proposal in store.rows("proposals", org["organization_id"]):
            if number not in proposal["electorate"]:
                continue
            lines.append(
                f"{org['name']}提案{proposal['proposal_id']}：{proposal['before']} → {proposal['after']}；理由：{proposal['reason'] or '未提供'}；截止 Day {proposal['closing_day']} 日边界，状态 {proposal['status']}。"
            )
            ballot = store.get("ballots", f"{org['organization_id']}:{proposal['proposal_id']}:{number}")
            if ballot:
                lines.append(f"你对此提案的选择：{ballot['choice']}。")
            if proposal["status"] != "open" and proposal.get("tally"):
                t = proposal["tally"]
                lines.append(
                    f"总票数：赞成{t['yes']}，反对{t['no']}，弃权{t['abstain']}，参与{t['participation']}/{t['eligible']}；决议{proposal['decision_outcome']}，执行状态{proposal['status']}。"
                )
    return "\n".join(lines)
