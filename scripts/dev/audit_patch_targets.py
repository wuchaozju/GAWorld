#!/usr/bin/env python3
"""Find tests whose ``patch.object(sim, ...)`` can no longer reach its target.

A patch on ``generative_city_sim`` only intercepts a dependency when the
function under test *also* resolves that name from ``generative_city_sim``'s
globals. As functions move into ``gaworld.sim.*`` they start resolving their
dependencies from their own module, and every patch aimed at the re-export
goes quiet -- with no error, because a mock that is never consulted raises
nothing. The test keeps running; it just stops testing what it says it tests.

That is how ``test_memory_recall_and_review`` ended up calling the real vector
DB and the real LLM: two of its cases failed loudly (which is how they were
found), while three cases elsewhere kept passing because the stub's return
value happened to match what the real call produced.

Run this after any refactor that moves a function out of the top-level module::

    python scripts/dev/audit_patch_targets.py

Exit status is 1 when anything is flagged, so it can go in a pre-merge check.
"""

from __future__ import annotations

import ast
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import generative_city_sim as sim  # noqa: E402

SIM_ALIASES = {"sim", "generative_city_sim"}


def _module_of(name: str) -> str | None:
    obj = getattr(sim, name, None)
    return getattr(obj, "__module__", None) if callable(obj) else None


def _scan(path: pathlib.Path) -> list[tuple[str, str, list[str]]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    out = []
    functions = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    for func in functions:
        patched: set[str] = set()
        called: set[str] = set()
        for node in ast.walk(func):
            if not isinstance(node, ast.Call):
                continue
            target = node.func
            if (isinstance(target, ast.Attribute) and target.attr == "object"
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "patch"
                    and len(node.args) >= 2
                    and isinstance(node.args[0], ast.Name)
                    and node.args[0].id in SIM_ALIASES
                    and isinstance(node.args[1], ast.Constant)):
                patched.add(node.args[1].value)
            if (isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id in SIM_ALIASES):
                called.add(target.attr)
        if not patched:
            continue
        # Where do the things this test actually calls live?
        homes = {_module_of(c) for c in called if _module_of(c)}
        if not homes or "generative_city_sim" in homes:
            continue  # something on the path still resolves from sim
        dead = sorted(name for name in patched if _module_of(name))
        if dead:
            out.append((func.name, ", ".join(sorted(h for h in homes if h)), dead))
    return out


def main() -> int:
    findings = []
    for path in sorted((REPO_ROOT / "tests").glob("*.py")):
        for func, homes, dead in _scan(path):
            findings.append((path.relative_to(REPO_ROOT), func, homes, dead))
    if not findings:
        print("没有发现打不中的 patch 目标。")
        return 0
    print(f"发现 {len(findings)} 个测试函数的 patch 目标已经打不中：\n")
    for path, func, homes, dead in findings:
        print(f"  {path}::{func}")
        print(f"      被测函数住在 {homes}")
        for name in dead:
            print(f"      patch.object(sim, {name!r}) → 应改打 {_module_of(name)}")
    print("\n把补丁改打到被测函数查名字的那个模块上；"
          "并在测试里断言桩确实被调用过，否则下次搬家它还会悄悄失效。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
