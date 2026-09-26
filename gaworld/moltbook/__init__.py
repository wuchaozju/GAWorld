"""Moltbook integration — a resident can hold an account on the agent social
network, and everything it does there is recorded.

Four pieces, one job each:

- ``accounts``: the per-agent switch and credentials (``data/moltbook_accounts.json``).
- ``client``: a thin HTTP client over Moltbook's ``/api/v1``.
- ``log``: the per-agent action record (``output/moltbook/agent_<id>/actions.jsonl``).
- ``plugin``: the kernel plugin that turns a simulated day into a post.

The switch is flipped from Agent Studio (``gaworld/apps/moltbook_api.py``);
the plugin only reads it.
"""
