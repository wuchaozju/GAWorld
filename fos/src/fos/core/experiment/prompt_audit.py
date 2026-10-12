"""Prompt audit - write one JSON record per prompt built, gated by FOS_PROMPT_AUDIT=<dir>."""

import json
import os

def audit_prompt(
    builder: str,
    prompt: str,
    *,
    agent_name: str = "",
    phase: str = "",
    round_num: int = 0,
    proposal_index: int = 0,
    mode: str = "",
):
    """No-op unless FOS_PROMPT_AUDIT is set to a directory path."""
    audit_dir = os.environ.get("FOS_PROMPT_AUDIT", "").strip()
    if not audit_dir:
        return
    try:
        path = os.path.join(audit_dir, "prompt_audit.jsonl")
        record = {
            "agent": agent_name,
            "phase": phase,
            "round": round_num,
            "proposal": proposal_index,
            "builder": builder,
            "mode": mode,
            "total_chars": len(prompt),
            "full_prompt": prompt,
        }
        with open(path, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass
