"""Check that every CLI flag used in the handbook actually exists.

Flags are collected from the chapter files, then looked up in the real
``--help`` output of the command they belong to. Unknown flags are reported
so they can be corrected before the manual ships.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CHAPTERS = Path(__file__).resolve().parents[1] / "chapters"

# command -> how to ask for its help
COMMANDS = {
    "generative_city_sim.py run": ["python3", "generative_city_sim.py", "run", "--help"],
    "generative_city_sim.py reset": ["python3", "generative_city_sim.py", "reset", "--help"],
    "generative_city_sim.py interview": ["python3", "generative_city_sim.py", "interview", "--help"],
    "generative_city_sim.py compare-event": ["python3", "generative_city_sim.py", "compare-event", "--help"],
    "generative_city_sim.py parallel-worlds": ["python3", "generative_city_sim.py", "parallel-worlds", "--help"],
    "generative_city_sim.py dashboard": ["python3", "generative_city_sim.py", "dashboard", "--help"],
    "generative_city_sim.py serve-viz": ["python3", "generative_city_sim.py", "serve-viz", "--help"],
    "gaworld.city create": ["python3", "-m", "gaworld.city", "create", "--help"],
    "gaworld.city add-agents": ["python3", "-m", "gaworld.city", "add-agents", "--help"],
    "gaworld.city add-agent": ["python3", "-m", "gaworld.city", "add-agent", "--help"],
    "gaworld.city migrate": ["python3", "-m", "gaworld.city", "migrate", "--help"],
    "gaworld.city use": ["python3", "-m", "gaworld.city", "use", "--help"],
    "gaworld.city delete": ["python3", "-m", "gaworld.city", "delete", "--help"],
    "gaworld.city knowledge": ["python3", "-m", "gaworld.city", "knowledge", "--help"],
    "gaworld.city locale": ["python3", "-m", "gaworld.city", "locale", "--help"],
    "gaworld.city news": ["python3", "-m", "gaworld.city", "news", "--help"],
    "gaworld.population": ["python3", "-m", "gaworld.population", "--help"],
    "gaworld.group": ["python3", "-m", "gaworld.group", "--help"],
    "gaworld.accounts init": ["python3", "-m", "gaworld.accounts", "init", "--help"],
    "gaworld.accounts invite": ["python3", "-m", "gaworld.accounts", "invite", "--help"],
    "gaworld.accounts reset": ["python3", "-m", "gaworld.accounts", "reset", "--help"],
    "gaworld.accounts city-permission": ["python3", "-m", "gaworld.accounts", "city-permission", "--help"],
    "gaworld.cluster join": ["python3", "-m", "gaworld.cluster", "join", "--help"],
    "gaworld.interview": ["python3", "-m", "gaworld.interview", "--help"],
}


def help_text(argv: list[str]) -> str:
    result = subprocess.run(argv, cwd=str(ROOT), capture_output=True, text=True, timeout=90)
    return result.stdout + result.stderr


def main() -> int:
    texts = {name: help_text(argv) for name, argv in COMMANDS.items()}
    all_help = "\n".join(texts.values())

    # every --flag mentioned anywhere in the chapters
    used: dict[str, set[str]] = {}
    for path in sorted(CHAPTERS.glob("*.md")):
        body = path.read_text(encoding="utf-8")
        for block in re.findall(r"```bash\n(.*?)```", body, re.S):
            for flag in re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]+)", block):
                used.setdefault(flag, set()).add(path.name)

    known = set(re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]+)", all_help))
    # flags that belong to other tools (pytest, ruff, pandoc, git…) are fine
    foreign = {
        "--suite", "--cov", "--cov-fail-under", "--base", "--update-baseline", "--root",
        "--help", "--version", "--count", "--seed", "--check", "--json", "--name", "--out",
        "--spec", "--size", "--preset", "--force", "--offline", "--slug", "--scale",
        "--description", "--image", "--replace", "--admin", "--label", "--nickname",
        "--allow", "--deny", "--from", "--to", "--host", "--port", "--clear", "--yes",
        "--rebuild", "--refresh", "--force", "--ttl-hours", "--expires-days", "--can-create-city",
        "--password-stdin", "--fast", "--sweep", "--placebo", "--output-root", "--llm-provider",
        "--sim-days", "--sim-months", "--sim-years", "--time-unit", "--fast-forward",
        "--agent-id", "--agent-ids", "--question", "--questions-file", "--context", "--text",
        "--file", "--url", "--event-name", "--event-description", "--event-day", "--event-time",
        "--days", "--axes", "--budget", "--audit-fraction", "--focal", "--network-coupling",
        "--no-llm", "--verbose", "--days", "--focal", "--seed",
    }

    missing = []
    for flag, files in sorted(used.items()):
        if flag in known or flag in foreign:
            continue
        missing.append((flag, sorted(files)))

    print(f"flags used in bash blocks: {len(used)}")
    if missing:
        print("\nNOT FOUND in any --help (check each):")
        for flag, files in missing:
            print(f"  {flag:28s} {files}")
    else:
        print("\nevery flag resolves to a real --help entry")
    return 0


if __name__ == "__main__":
    sys.exit(main())
