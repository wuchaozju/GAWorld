"""
tests/test_i18n_llm_prompts.py
================================
LLM prompt language purity tests for Social-Sim.

These are the MOST CRITICAL tests for this platform. Mixed-language LLM
prompts directly cause mixed-language simulation outputs, breaking the
entire research validity of the system.

Checks:
  1. Python locale keys under "prompts.*" are NOT mixed EN+ZH
  2. T("prompts.*") calls all pass a locale= argument
  3. zh.json prompt values contain no English sentences (only Chinese)
  4. en.json prompt values contain no Chinese characters
  5. LLM context builder doesn't hardcode prompt language
  6. Prompt variables ({name}, {role}, etc.) are identical in en + zh

Run with:
    pytest tests/test_i18n_llm_prompts.py -v
"""

import ast
import json
import re
from pathlib import Path
from typing import Generator

import pytest

ROOT    = Path(__file__).parent.parent
SRC     = ROOT / "src" / "fos"
EN_JSON = SRC / "locales" / "en.json"
ZH_JSON = SRC / "locales" / "zh.json"

ZH_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")
EN_SENT_RE = re.compile(r"\b[A-Z][a-z]{3,}(?:\s+[a-z]{2,}){2,}")  # 3+ word English sentence
EN_WORD_RE = re.compile(r"\b[a-zA-Z]{4,}\b")
VAR_RE     = re.compile(r"\{(\w+)\}")


def load_flat(path: Path) -> dict[str, str]:
    def _flatten(d, prefix=""):
        out = {}
        for k, v in d.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                out.update(_flatten(v, key))
            else:
                out[key] = str(v)
        return out
    with open(path, encoding="utf-8") as f:
        return _flatten(json.load(f))


def iter_py_files() -> Generator[Path, None, None]:
    skip = {"__pycache__", ".git", "tests", "migrations"}
    skip_names = {"i18n.py", "conftest.py"}
    for f in SRC.rglob("*.py"):
        if any(p in skip for p in f.parts):
            continue
        if f.name in skip_names:
            continue
        yield f


# ═══════════════════════════════════════════════════════════════════════════
# TEST 1 — Prompt locale values must be in their declared language only
# ═══════════════════════════════════════════════════════════════════════════

def test_en_prompt_values_have_no_chinese():
    """
    All en.json keys under 'prompts.*' must contain zero Chinese characters.

    WHY: A Chinese character in an "English" prompt means English-locale
    agents receive mixed instructions. Even a single Chinese word can cause
    the LLM to switch response language.
    """
    en_flat = load_flat(EN_JSON)
    violations = []
    for key, value in en_flat.items():
        if not key.startswith("prompts."):
            continue
        if ZH_CHAR_RE.search(value):
            violations.append(f"  {key}: \"{value[:100]}\"")
    assert not violations, (
        f"{len(violations)} en.json prompt value(s) contain Chinese characters:\n"
        + "\n".join(violations)
    )


def test_zh_prompt_values_have_no_english_sentences():
    """
    All zh.json keys under 'prompts.*' must not contain English sentences.

    WHY: An English sentence in a Chinese-locale prompt instructs the LLM
    partly in English. The LLM will likely respond in English or produce
    a language-inconsistent output — making the simulation results invalid.

    NOTE: Short English words (acronyms like "ABM", brand names) are allowed.
    We check for sentences (5+ consecutive English words).
    """
    zh_flat = load_flat(ZH_JSON)
    violations = []
    for key, value in zh_flat.items():
        if not key.startswith("prompts."):
            continue
        # Strip interpolation variables before checking
        text = re.sub(r"\{[^}]+\}", "", value)
        # Strip XML action tags — <Action name="speak" /> must stay English
        text = re.sub(r"<[^>]+>", "", text)
        # Strip code fence blocks — JSON format examples use English key names
        text = re.sub(r"```[\s\S]*?```", "", text)
        # Strip quoted JSON key names — "thoughts", "response", etc. must be English
        text = re.sub(r'"[a-z_]+"', "", text)
        # Look for sequences of multiple English words (sentences)
        en_words = EN_WORD_RE.findall(text)
        zh_chars = ZH_CHAR_RE.findall(text)
        # Flag if there are more English words than Chinese chars AND
        # there's at least one apparent English sentence
        if len(en_words) >= 5 and len(zh_chars) == 0:
            violations.append(f"  {key}: \"{value[:100]}\"")
        elif len(en_words) >= 3 and len(zh_chars) > 0:
            # Mixed — EN sentence mixed into Chinese text
            if EN_SENT_RE.search(text):
                violations.append(f"  {key} [MIXED]: \"{value[:100]}\"")
    assert not violations, (
        f"{len(violations)} zh.json prompt value(s) contain English text:\n"
        + "\n".join(violations)
    )


# ═══════════════════════════════════════════════════════════════════════════
# TEST 2 — T("prompts.*") calls must pass locale=
# ═══════════════════════════════════════════════════════════════════════════

T_PROMPT_RE = re.compile(r'T\(\s*["\']prompts\.[^"\']+["\']\s*([^)]*)\)')


def test_prompt_t_calls_pass_locale():
    """
    Every T("prompts.*") call must include a locale= keyword argument.

    WHY: T() without locale= uses the contextvar default, which is 'en'.
    In an async context (FastAPI), the contextvar may not propagate correctly
    across thread pool executors. The only safe approach for prompt building
    is to pass locale= explicitly.

    CORRECT:    T("prompts.game_theory.intro", locale=language)
    INCORRECT:  T("prompts.game_theory.intro")   ← always returns English
    """
    violations = []
    for pyfile in iter_py_files():
        source = pyfile.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(source.splitlines(), start=1):
            # Class-level attribute assignments (NAME = T(...), DESC = T(...)) are
            # evaluated at import time — no request locale exists then, so locale=
            # is meaningless at class body scope.
            if re.match(r"\s+[A-Z_]+ = T\(", line):
                continue
            for m in T_PROMPT_RE.finditer(line):
                args = m.group(1)
                if "locale=" not in args:
                    rel = pyfile.relative_to(ROOT)
                    violations.append(f"  {rel}:{i}\n    {line.strip()}")
    assert not violations, (
        f"{len(violations)} T('prompts.*') call(s) missing locale= argument:\n\n"
        + "\n".join(violations)
        + "\n\nFIX: Add locale=language (or locale=self.config.locale) to each call."
    )


# ═══════════════════════════════════════════════════════════════════════════
# TEST 3 — Prompt interpolation variables must be identical in en + zh
# ═══════════════════════════════════════════════════════════════════════════

def test_prompt_interpolation_variable_parity():
    """
    For every prompts.* key, en.json and zh.json must have the same {variable} names.

    WHY: If en.json has "You are {name}, {role}" but zh.json has "你是{name}",
    calling T("...", locale='zh', name=n, role=r) partially formats the string —
    the Chinese prompt loses the {role} variable. The agent receives incomplete
    context and produces invalid output.

    MOST COMMON MISTAKE: Dropping a variable when simplifying Chinese phrasing.
    "You must choose between {action_1} and {action_2}." →
    "你必须做出选择。" (dropped both variables — agent has no action names!)
    """
    en_flat = load_flat(EN_JSON)
    zh_flat = load_flat(ZH_JSON)
    mismatches = []

    for key in en_flat:
        if not key.startswith("prompts."):
            continue
        if key not in zh_flat:
            continue
        en_vars = set(VAR_RE.findall(en_flat[key]))
        zh_vars = set(VAR_RE.findall(zh_flat[key]))
        if en_vars != zh_vars:
            missing = en_vars - zh_vars
            extra   = zh_vars - en_vars
            mismatches.append(
                f"  {key}\n"
                f"    en: \"{en_flat[key][:80]}\"\n"
                f"    zh: \"{zh_flat[key][:80]}\"\n"
                + (f"    missing in zh: {{{', '.join(sorted(missing))}}}\n" if missing else "")
                + (f"    extra in zh:   {{{', '.join(sorted(extra))}}}\n" if extra else "")
            )

    assert not mismatches, (
        f"{len(mismatches)} prompt key(s) have mismatched interpolation variables:\n\n"
        + "\n".join(mismatches)
    )


# ═══════════════════════════════════════════════════════════════════════════
# TEST 4 — Hardcoded English strings in LLM generation code
# ═══════════════════════════════════════════════════════════════════════════

class LLMContextVisitor(ast.NodeVisitor):
    """Find string literals that are concatenated into LLM message content."""

    LLM_FUNCS = {
        "create_chat_completion", "chat_completion", "invoke", "predict",
        "generate", "run", "execute", "build_context", "build_prompt",
        "get_context", "get_prompt", "format_prompt",
    }

    def __init__(self, lines: list[str]):
        self.lines = lines
        self.violations: list[tuple[int, str]] = []

    def visit_Return(self, node: ast.Return):
        """Return "hardcoded English string" from a prompt-building function."""
        if node.value and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                s = node.value.value.strip()
                if (len(s) > 20
                        and not ZH_CHAR_RE.search(s)
                        and re.search(r"[A-Z][a-z]{3,}", s)
                        and " " in s):
                    snippet = self.lines[node.lineno - 1].strip()
                    self.violations.append((node.lineno, snippet))
        self.generic_visit(node)


def test_no_hardcoded_english_in_prompt_builders():
    """
    LLM prompt builder functions must not return hardcoded English strings.

    Checks files in core/prompts/, core/experiment/, and services/ for
    plain English string returns that bypass T().

    WHY: A function that returns "You are a Werewolf. Coordinate..."
    is permanently locked to English regardless of the locale parameter
    it receives.
    """
    prompt_dirs = [
        SRC / "core" / "prompts",
        SRC / "core" / "experiment",
        SRC / "core" / "scenes",
        SRC / "services",
    ]
    violations = []
    for d in prompt_dirs:
        if not d.exists():
            continue
        for pyfile in d.rglob("*.py"):
            source = pyfile.read_text(encoding="utf-8", errors="replace")
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            visitor = LLMContextVisitor(source.splitlines())
            visitor.visit(tree)
            for lineno, snippet in visitor.violations:
                violations.append(f"  {pyfile.relative_to(ROOT)}:{lineno}\n    {snippet}")

    assert not violations, (
        f"{len(violations)} hardcoded English string(s) returned from prompt builder code:\n\n"
        + "\n".join(violations)
        + "\n\nFIX: Move the string to en.json and zh.json, then use T(\"key\", locale=language)."
    )


# ═══════════════════════════════════════════════════════════════════════════
# TEST 5 — llm_client_pool.py role_prompt coverage
# ═══════════════════════════════════════════════════════════════════════════

def test_llm_client_pool_role_prompts_use_t():
    """
    llm_client_pool.py is a known offender: it contains 30+ hardcoded
    role_prompt / user_profile strings. This test specifically targets that file.

    Expected fix: Move all persona strings into locale files and call T() with locale.
    """
    pool_file = SRC / "services" / "llm_client_pool.py"
    if not pool_file.exists():
        pytest.skip("llm_client_pool.py not found")

    source = pool_file.read_text(encoding="utf-8", errors="replace")
    lines = source.splitlines()

    # Find all "role_prompt": "..." and "user_profile": "..." assignments
    hardcoded_re = re.compile(r'"(role_prompt|user_profile|initial_instruction)"\s*:\s*"([^"]{5,})"')
    violations = []
    for i, line in enumerate(lines, start=1):
        m = hardcoded_re.search(line)
        if m:
            value = m.group(2)
            # Skip empty strings and strings that are clearly just placeholders
            if value.strip() and not value.startswith("{"):
                violations.append(f"  line {i}: {line.strip()}")

    assert not violations, (
        f"{len(violations)} hardcoded persona string(s) in llm_client_pool.py:\n\n"
        + "\n".join(violations[:20])
        + ("\n  ... and more" if len(violations) > 20 else "")
        + "\n\nFIX: Add locale parameter to scenario config functions and replace with T()."
    )


# ═══════════════════════════════════════════════════════════════════════════
# AST helpers for structural i18n violation detection
# ═══════════════════════════════════════════════════════════════════════════

def _build_parent_map(tree):
    """Build a mapping from each AST node to its parent node."""
    parent_map: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent_map[child] = node
    return parent_map


def _is_inside_i18n_call(node, parent_map):
    """Check whether *node* is nested inside a T(), _tr(), or _localized() call."""
    current = node
    for _ in range(5):
        parent = parent_map.get(current)
        if parent is None:
            return False
        if isinstance(parent, ast.Call):
            func = parent.func
            if isinstance(func, ast.Name) and func.id in ("T", "_tr", "_localized"):
                return True
            if isinstance(func, ast.Attribute) and func.attr in ("T", "_tr", "_localized"):
                return True
        current = parent
    return False


def _joined_str_text(node: ast.JoinedStr) -> str:
    """Extract the concatenated literal parts of an ast.JoinedStr (f-string)."""
    parts: list[str] = []
    for v in node.values:
        if isinstance(v, ast.Constant) and isinstance(v.value, str):
            parts.append(v.value)
    return "".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
# TEST 6 — Action class attributes must use T() for user-facing strings
# ═══════════════════════════════════════════════════════════════════════════

_ACTION_ATTRS = {"NAME", "DESC", "DESCRIPTION", "INSTRUCTION", "STATE_ERROR"}


def test_action_classes_use_T_for_strings():
    """
    Action class attributes like DESC, INSTRUCTION, and STATE_ERROR
    must use T() instead of plain string literals.

    WHY: These strings appear in agent prompts and error messages. Hardcoded
    English strings bypass i18n entirely — agents in Chinese locales still
    receive English action descriptions and instructions.

    Detects: class-level assignments of plain strings or f-strings to
    NAME, DESC, DESCRIPTION, INSTRUCTION, STATE_ERROR (and similar attrs).
    """
    violations: list[str] = []
    actions_dir = SRC / "core" / "actions"

    for pyfile in sorted(actions_dir.glob("*.py")):
        source = pyfile.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                if not isinstance(stmt, ast.Assign):
                    continue
                for target in stmt.targets:
                    if not (isinstance(target, ast.Name) and target.id in _ACTION_ATTRS):
                        continue
                    val = stmt.value
                    rel = pyfile.relative_to(ROOT)
                    if isinstance(val, ast.Constant) and isinstance(val.value, str):
                        s = val.value.strip()
                        violations.append(
                            f"  {rel}:{stmt.lineno} "
                            f"{node.name}.{target.id} = \"{s[:80]}\""
                        )
                    elif isinstance(val, ast.JoinedStr):
                        s = _joined_str_text(val).strip()
                        violations.append(
                            f"  {rel}:{stmt.lineno} "
                            f"{node.name}.{target.id} = f\"\"\"{s[:80]}\"\"\""
                        )

    assert not violations, (
        f"{len(violations)} action class attribute(s) use plain strings "
        f"instead of T():\n\n"
        + "\n".join(violations)
        + "\n\nFIX: Move strings to locale files and use T('key', locale=lang)."
    )


# ═══════════════════════════════════════════════════════════════════════════
# TEST 7 — Scene description methods must use T()
# ═══════════════════════════════════════════════════════════════════════════

_SCENE_DESC_METHODS = {"get_scenario_description", "get_behavior_guidelines"}


def test_scene_descriptions_use_T():
    """
    get_scenario_description() and get_behavior_guidelines() must not
    contain hardcoded string returns that bypass T().

    WHY: These methods feed directly into agent system prompts. Hardcoded
    English means Chinese-locale agents receive English scene descriptions,
    producing English responses in a Chinese simulation.

    Detects: string constants and f-strings (>20 chars) inside the named
    methods that are NOT arguments to T(), _tr(), or _localized().
    """
    violations: list[str] = []
    scenes_dir = SRC / "core" / "scenes"

    for pyfile in sorted(scenes_dir.rglob("*.py")):
        source = pyfile.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue

        parent_map = _build_parent_map(tree)

        for node in ast.walk(tree):
            if not (isinstance(node, ast.FunctionDef)
                    and node.name in _SCENE_DESC_METHODS):
                continue

            for child in ast.walk(node):
                # Plain string constants (skip parts of f-strings)
                if (isinstance(child, ast.Constant)
                        and isinstance(child.value, str)):
                    parent = parent_map.get(child)
                    if isinstance(parent, ast.JoinedStr):
                        continue  # handled via JoinedStr below
                    s = child.value.strip()
                    if len(s) < 20 or _is_inside_i18n_call(child, parent_map):
                        continue
                    rel = pyfile.relative_to(ROOT)
                    violations.append(
                        f"  {rel}:{child.lineno} "
                        f"in {node.name}(): \"{s[:80]}\""
                    )

                # F-strings
                elif isinstance(child, ast.JoinedStr):
                    s = _joined_str_text(child).strip()
                    if len(s) < 20 or _is_inside_i18n_call(child, parent_map):
                        continue
                    rel = pyfile.relative_to(ROOT)
                    violations.append(
                        f"  {rel}:{child.lineno} "
                        f"in {node.name}(): f\"\"\"{s[:80]}\"\"\""
                    )

    assert not violations, (
        f"{len(violations)} hardcoded string(s) in scene description methods:\n\n"
        + "\n".join(violations)
        + "\n\nFIX: Move strings to locale files and use T('key', locale=lang)."
    )


# ═══════════════════════════════════════════════════════════════════════════
# TEST 8 — Agent system_prompt() must use T() for English strings
# ═══════════════════════════════════════════════════════════════════════════

def test_agent_system_prompt_uses_T():
    """
    Agent.system_prompt() must not contain hardcoded English string literals
    that are not wrapped in T() or _tr().

    WHY: The system prompt is the primary instruction the LLM receives.
    Hardcoded English forces the LLM to respond in English regardless of
    the agent's configured language setting.

    Detects: string constants and f-strings (>15 chars, containing English
    words) inside the system_prompt method that are NOT arguments to T()
    or _tr().
    """
    agent_file = SRC / "core" / "agent" / "agent.py"
    if not agent_file.exists():
        pytest.skip("agent.py not found at expected path")

    source = agent_file.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        pytest.skip("agent.py has syntax errors")

    parent_map = _build_parent_map(tree)
    violations: list[str] = []

    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef)
                and node.name == "system_prompt"):
            continue

        for child in ast.walk(node):
            # Plain string constants (skip f-string parts)
            if (isinstance(child, ast.Constant)
                    and isinstance(child.value, str)):
                parent = parent_map.get(child)
                if isinstance(parent, ast.JoinedStr):
                    continue
                s = child.value.strip()
                if len(s) < 15 or not EN_WORD_RE.search(s):
                    continue
                if _is_inside_i18n_call(child, parent_map):
                    continue
                violations.append(
                    f"  line {child.lineno}: \"{s[:100]}\""
                )

            # F-strings
            elif isinstance(child, ast.JoinedStr):
                s = _joined_str_text(child).strip()
                if len(s) < 15 or not EN_WORD_RE.search(s):
                    continue
                if _is_inside_i18n_call(child, parent_map):
                    continue
                violations.append(
                    f"  line {child.lineno}: f\"\"\"{s[:100]}\"\"\""
                )
        break  # only check the first system_prompt method found

    assert not violations, (
        f"{len(violations)} hardcoded English string(s) in system_prompt():\n\n"
        + "\n".join(violations)
        + "\n\nFIX: Move strings to locale files and use "
        "T('key', locale=self.language)."
    )


# ═══════════════════════════════════════════════════════════════════════════
# TEST 9 — Action handle/execute methods must use T() for error strings
# ═══════════════════════════════════════════════════════════════════════════

def test_action_handle_errors_use_T():
    """
    Action handle() and execute() methods must not contain hardcoded
    English error strings.

    WHY: Error messages and feedback are injected into agent context
    windows. Hardcoded English corrupts the context for Chinese-locale
    agents, causing language-switching in responses.

    Detects: string constants and f-strings (>10 chars, containing English
    words) inside handle()/execute() methods that are NOT arguments to
    T(), _tr(), or _localized().
    """
    violations: list[str] = []
    actions_dir = SRC / "core" / "actions"

    for pyfile in sorted(actions_dir.glob("*.py")):
        source = pyfile.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue

        parent_map = _build_parent_map(tree)

        for node in ast.walk(tree):
            if not (isinstance(node, ast.FunctionDef)
                    and node.name in ("handle", "execute")):
                continue

            for child in ast.walk(node):
                # Plain string constants (skip f-string parts)
                if (isinstance(child, ast.Constant)
                        and isinstance(child.value, str)):
                    parent = parent_map.get(child)
                    if isinstance(parent, ast.JoinedStr):
                        continue
                    s = child.value.strip()
                    if len(s) < 10 or not EN_WORD_RE.search(s):
                        continue
                    if _is_inside_i18n_call(child, parent_map):
                        continue
                    rel = pyfile.relative_to(ROOT)
                    violations.append(
                        f"  {rel}:{child.lineno} "
                        f"in {node.name}(): \"{s[:80]}\""
                    )

                # F-strings
                elif isinstance(child, ast.JoinedStr):
                    s = _joined_str_text(child).strip()
                    if len(s) < 10 or not EN_WORD_RE.search(s):
                        continue
                    if _is_inside_i18n_call(child, parent_map):
                        continue
                    rel = pyfile.relative_to(ROOT)
                    violations.append(
                        f"  {rel}:{child.lineno} "
                        f"in {node.name}(): f\"\"\"{s[:80]}\"\"\""
                    )

    assert not violations, (
        f"{len(violations)} hardcoded English error string(s) "
        f"in action handle methods:\n\n"
        + "\n".join(violations)
        + "\n\nFIX: Move error messages to locale files and use "
        "T('key', locale=agent.language)."
    )
