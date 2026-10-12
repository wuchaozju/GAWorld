"""
tests/test_i18n_backend.py
==========================
Backend i18n test suite for Social-Sim.

Covers three violation categories found in the codebase:

  1. HARDCODED HTTPException detail strings  (should use T("api.errors.*"))
  2. HARDCODED LLM persona strings           (role_prompt / user_profile / initial_instruction)
  3. T() keys that don't exist in zh.json or en.json (silent fallback to key string)

Run with:
    pytest tests/test_i18n_backend.py -v

Add to CI:
    pytest tests/test_i18n_backend.py --tb=short -q
"""

import ast
import json
import re
from pathlib import Path
from typing import Generator

import pytest

# ── Paths ──────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).parent.parent
SRC        = ROOT / "src" / "fos"
LOCALES    = SRC / "locales"
EN_JSON    = LOCALES / "en.json"
ZH_JSON    = LOCALES / "zh.json"

# ── Safe-string patterns (never flag these even if they look like English) ──
# These are known-OK patterns in this codebase that should not be treated as
# user-visible text. Adjust if your codebase adds more.
SAFE_PATTERNS = [
    re.compile(r"^[A-Z_][A-Z0-9_]*$"),          # ALL_CAPS constants
    re.compile(r"^https?://"),                    # URLs
    re.compile(r"^\d"),                           # starts with digit
    re.compile(r"^[a-z][a-z0-9_.-]+$"),          # snake_case identifiers
    re.compile(r"^\s*$"),                         # whitespace
    re.compile(r"^\{"),                           # f-string already using variable
    re.compile(r"^(GET|POST|PUT|DELETE|PATCH)$"), # HTTP methods
    re.compile(r"^application/"),                 # MIME types
    re.compile(r"^\w+Error$"),                    # exception class names
    re.compile(r"^fos\."),                        # module paths
    re.compile(r"^\w+\.\w+$"),                    # dotted identifiers (config keys)
]

# Files to skip entirely (test fixtures, migration files, etc.)
SKIP_DIRS = {"__pycache__", ".git", "tests", "migrations", "debug_scripts"}
SKIP_FILES = {"i18n.py", "conftest.py"}


def is_safe_string(s: str) -> bool:
    """Return True if this string is known-safe and should never be flagged."""
    s = s.strip()
    if len(s) < 5:
        return True
    return any(p.match(s) for p in SAFE_PATTERNS)


def iter_python_files(base: Path) -> Generator[Path, None, None]:
    """Walk src/ yielding .py files outside skip dirs."""
    for f in base.rglob("*.py"):
        if any(part in SKIP_DIRS for part in f.parts):
            continue
        if f.name in SKIP_FILES:
            continue
        yield f


def load_json_flat(path: Path) -> dict[str, str]:
    """Load a JSON locale file and return a flat {dot.key: value} dict."""
    def _flatten(d: dict, prefix: str = "") -> dict:
        out = {}
        for k, v in d.items():
            full = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                out.update(_flatten(v, full))
            else:
                out[full] = str(v)
        return out

    with open(path, encoding="utf-8") as f:
        return _flatten(json.load(f))


# ═══════════════════════════════════════════════════════════════════════════
# TEST 1 — HTTPException detail strings must use T()
# ═══════════════════════════════════════════════════════════════════════════

class HardcodedHTTPDetailVisitor(ast.NodeVisitor):
    """AST visitor: find HTTPException(detail=<hardcoded string>)."""

    def __init__(self, source_lines: list[str]):
        self.lines = source_lines
        self.violations: list[tuple[int, str]] = []

    def visit_Call(self, node: ast.Call):
        func_name = self._func_name(node.func)
        if func_name in ("HTTPException", "fastapi.HTTPException"):
            for kw in node.keywords:
                if kw.arg == "detail":
                    self._check_value(kw.value, func_name)
        self.generic_visit(node)

    def _check_value(self, node: ast.AST, context: str):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            s = node.value
            if not is_safe_string(s):
                snippet = self.lines[node.lineno - 1].strip() if node.lineno <= len(self.lines) else ""
                self.violations.append((node.lineno, snippet))
        elif isinstance(node, ast.JoinedStr):
            # f-string as detail — collect constant parts
            parts = [v.value for v in node.values if isinstance(v, ast.Constant)]
            combined = "".join(str(p) for p in parts)
            if not is_safe_string(combined) and combined.strip():
                snippet = self.lines[node.lineno - 1].strip() if node.lineno <= len(self.lines) else ""
                self.violations.append((node.lineno, snippet))

    @staticmethod
    def _func_name(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return ""


def collect_http_detail_violations() -> list[tuple[Path, int, str]]:
    all_violations = []
    for pyfile in iter_python_files(SRC):
        source = pyfile.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(source, filename=str(pyfile))
        except SyntaxError:
            continue
        visitor = HardcodedHTTPDetailVisitor(source.splitlines())
        visitor.visit(tree)
        for lineno, snippet in visitor.violations:
            all_violations.append((pyfile.relative_to(ROOT), lineno, snippet))
    return all_violations


@pytest.fixture(scope="session")
def http_detail_violations():
    return collect_http_detail_violations()


def test_no_hardcoded_http_detail_strings(http_detail_violations):
    """
    All HTTPException(detail=...) must use T("api.errors.*") not raw strings.

    WHY: detail strings are returned in API responses and displayed to users.
    If hardcoded in English, Chinese users see English error messages.

    FIX: Replace  detail="Tree node not found"
            with  detail=T("api.errors.tree.node_not_found")
    and add the key to src/fos/locales/en.json + zh.json.
    """
    if not http_detail_violations:
        return

    report = "\n".join(
        f"  {path}:{line}\n    → {snippet}"
        for path, line, snippet in http_detail_violations
    )
    pytest.fail(
        f"{len(http_detail_violations)} hardcoded HTTPException detail string(s) found.\n"
        f"All must be replaced with T(\"api.errors.*\"):\n\n{report}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# TEST 2 — LLM persona/role strings must use T()
# ═══════════════════════════════════════════════════════════════════════════

# Keys in dicts that carry LLM-visible text
LLM_TEXT_KEYS = {
    "role_prompt", "user_profile", "initial_instruction",
    "system_prompt", "persona", "backstory", "description",
}

class HardcodedLLMStringVisitor(ast.NodeVisitor):
    """
    Find dict literals where LLM_TEXT_KEYS map to hardcoded strings.
    E.g.:  {"role_prompt": "You are a Werewolf..."}
    """

    def __init__(self, source_lines: list[str]):
        self.lines = source_lines
        self.violations: list[tuple[int, str]] = []

    def visit_Dict(self, node: ast.Dict):
        for key, value in zip(node.keys, node.values):
            if not isinstance(key, ast.Constant):
                continue
            if key.value not in LLM_TEXT_KEYS:
                continue
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                s = value.value
                if not is_safe_string(s):
                    snippet = self.lines[value.lineno - 1].strip() if value.lineno <= len(self.lines) else ""
                    self.violations.append((value.lineno, snippet))
            elif isinstance(value, ast.JoinedStr):
                parts = [v.value for v in value.values if isinstance(v, ast.Constant)]
                combined = "".join(str(p) for p in parts)
                if not is_safe_string(combined):
                    snippet = self.lines[value.lineno - 1].strip() if value.lineno <= len(self.lines) else ""
                    self.violations.append((value.lineno, snippet))
        self.generic_visit(node)


def collect_llm_string_violations() -> list[tuple[Path, int, str]]:
    all_violations = []
    for pyfile in iter_python_files(SRC):
        source = pyfile.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(source, filename=str(pyfile))
        except SyntaxError:
            continue
        visitor = HardcodedLLMStringVisitor(source.splitlines())
        visitor.visit(tree)
        for lineno, snippet in visitor.violations:
            all_violations.append((pyfile.relative_to(ROOT), lineno, snippet))
    return all_violations


@pytest.fixture(scope="session")
def llm_string_violations():
    return collect_llm_string_violations()


def test_no_hardcoded_llm_persona_strings(llm_string_violations):
    """
    role_prompt / user_profile / initial_instruction dict values must use T().

    WHY: These strings are sent directly to the LLM as part of agent personas.
    A hardcoded English role_prompt means Chinese-locale simulations still
    receive English instructions, causing the LLM to respond in English.

    FIX: Replace  "role_prompt": "You are a Werewolf. Coordinate..."
            with  "role_prompt": T("prompts.werewolf.role", locale=language)
    and add the key pair to both locale JSON files.
    """
    if not llm_string_violations:
        return

    report = "\n".join(
        f"  {path}:{line}\n    → {snippet}"
        for path, line, snippet in llm_string_violations
    )
    pytest.fail(
        f"{len(llm_string_violations)} hardcoded LLM persona string(s) found.\n"
        f"All role_prompt/user_profile/initial_instruction values must use T():\n\n{report}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# TEST 3 — Every T("key") call must exist in BOTH locale JSON files
# ═══════════════════════════════════════════════════════════════════════════

T_CALL_RE = re.compile(r"""T\(\s*["']([^"']+)["']""")


def collect_t_key_violations() -> dict[str, list[tuple[Path, int]]]:
    """
    Find all T("key") calls in Python source and check both locale files.
    Returns {key: [(file, line), ...]} for keys missing from either locale.
    """
    en_flat = load_json_flat(EN_JSON)
    zh_flat = load_json_flat(ZH_JSON)

    missing: dict[str, list[tuple[Path, int]]] = {}

    for pyfile in iter_python_files(SRC):
        source = pyfile.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(source.splitlines(), start=1):
            for m in T_CALL_RE.finditer(line):
                key = m.group(1)
                issues = []
                if key not in en_flat:
                    issues.append("en.json")
                if key not in zh_flat:
                    issues.append("zh.json")
                if issues:
                    label = f"{key} [missing from: {', '.join(issues)}]"
                    missing.setdefault(label, []).append((pyfile.relative_to(ROOT), i))

    return missing


@pytest.fixture(scope="session")
def t_key_violations():
    return collect_t_key_violations()


def test_all_t_keys_exist_in_en_locale(t_key_violations):
    """
    Every T("key") call in Python source must have an entry in en.json.

    WHY: When T() can't find a key it silently returns the key string itself
    (e.g. "api.errors.tree.node_not_found") as user-facing text.

    FIX: Add the missing key to src/fos/locales/en.json.
    """
    missing = {
        label: locs for label, locs in t_key_violations.items()
        if "en.json" in label
    }
    if not missing:
        return

    report = "\n".join(
        f"  {label}\n" + "\n".join(
            f"    used at {path}:{line_number}" for path, line_number in locs
        )
        for label, locs in sorted(missing.items())
    )
    pytest.fail(f"{len(missing)} T() key(s) missing from en.json:\n\n{report}")


def test_all_t_keys_exist_in_zh_locale(t_key_violations):
    """
    Every T("key") call in Python source must have an entry in zh.json.

    WHY: Missing zh.json entries cause T() to fall back to the key string
    when locale='zh', so Chinese users see raw key names instead of text.

    FIX: Add the missing key to src/fos/locales/zh.json.
    """
    missing = {
        label: locs for label, locs in t_key_violations.items()
        if "zh.json" in label
    }
    if not missing:
        return

    report = "\n".join(
        f"  {label}\n" + "\n".join(
            f"    used at {path}:{line_number}" for path, line_number in locs
        )
        for label, locs in sorted(missing.items())
    )
    pytest.fail(f"{len(missing)} T() key(s) missing from zh.json:\n\n{report}")


# ═══════════════════════════════════════════════════════════════════════════
# TEST 4 — zh.json values must actually be Chinese (not untranslated English)
# ═══════════════════════════════════════════════════════════════════════════

ZH_CHAR_RE  = re.compile(r"[\u4e00-\u9fff]")
EN_WORD_RE  = re.compile(r"\b[a-zA-Z]{4,}\b")
# Keys whose values are intentionally English in zh.json (brand names, etc.)
ZH_ENGLISH_ALLOWED = {
    "brand",                      # "FOS" brand name
    "landing.hero.line1",         # "Future of Society" is the brand tagline
    "landing.hero.line2",
    "landing.hero.accent",
}


def test_zh_locale_values_are_chinese():
    """
    Values in zh.json must contain Chinese characters (not plain English).

    WHY: Copy-pasted English values in zh.json mean Chinese users see English.
    A value with no Chinese characters at all is almost certainly untranslated.

    EXCEPTIONS: Brand names and intentionally bilingual strings are whitelisted
    in ZH_ENGLISH_ALLOWED at the top of this file.
    """
    zh_flat = load_json_flat(ZH_JSON)
    suspicious = []

    for key, value in zh_flat.items():
        if key in ZH_ENGLISH_ALLOWED:
            continue
        if not value.strip() or len(value) < 4:
            continue
        # Interpolation placeholders only (like "{name}") — skip
        text_without_vars = re.sub(r"\{[^}]+\}", "", value).strip()
        if not text_without_vars:
            continue
        # Has substantial English words but zero Chinese characters
        en_words = EN_WORD_RE.findall(text_without_vars)
        zh_chars = ZH_CHAR_RE.findall(text_without_vars)
        if len(en_words) >= 3 and len(zh_chars) == 0:
            suspicious.append(f"  {key}: \"{value[:80]}\"")

    if suspicious:
        pytest.fail(
            f"{len(suspicious)} zh.json value(s) appear untranslated (English text, no Chinese):\n"
            + "\n".join(suspicious[:30])
        )


# ═══════════════════════════════════════════════════════════════════════════
# TEST 5 — Locale key parity (extends existing test_i18n_parity.py)
# ═══════════════════════════════════════════════════════════════════════════

def test_backend_locale_key_parity():
    """
    en.json and zh.json must have exactly the same set of keys.
    (This re-runs the existing parity test to keep everything in one place.)
    """
    def get_all_keys(d: dict, prefix: str = "") -> set:
        keys = set()
        for key, value in d.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                keys.update(get_all_keys(value, full_key))
            else:
                keys.add(full_key)
        return keys

    with open(EN_JSON, encoding="utf-8") as f:
        en = json.load(f)
    with open(ZH_JSON, encoding="utf-8") as f:
        zh = json.load(f)

    en_keys = get_all_keys(en)
    zh_keys = get_all_keys(zh)
    missing_in_zh = en_keys - zh_keys
    missing_in_en = zh_keys - en_keys

    errors = []
    if missing_in_zh:
        errors.append("Keys in en.json missing from zh.json:\n" +
                       "\n".join(f"  {k}" for k in sorted(missing_in_zh)))
    if missing_in_en:
        errors.append("Keys in zh.json missing from en.json:\n" +
                       "\n".join(f"  {k}" for k in sorted(missing_in_en)))
    if errors:
        pytest.fail("\n\n".join(errors))


# ═══════════════════════════════════════════════════════════════════════════
# TEST 6 — Interpolation variable parity between en.json and zh.json
# ═══════════════════════════════════════════════════════════════════════════

# Python T() uses {var} single-brace interpolation
PY_VAR_RE = re.compile(r"\{(\w+)\}")


def test_backend_interpolation_variable_parity():
    """
    For every key with interpolation variables, both en.json and zh.json
    must have the same set of {variable} names.

    WHY: If zh.json has "欢迎 {name}" and en.json has "Welcome {name} to {place}",
    calling T("key", name="Alice", place="Lab") will fail silently in Chinese
    and the user sees the raw key string.

    COMMON MISTAKE: Translating "{agent_name} took action" as "执行了动作"
    (dropping the {agent_name} placeholder) — the agent name disappears from
    Chinese log output.
    """
    en_flat = load_json_flat(EN_JSON)
    zh_flat = load_json_flat(ZH_JSON)

    mismatches = []
    for key in en_flat:
        if key not in zh_flat:
            continue
        en_vars = set(PY_VAR_RE.findall(en_flat[key]))
        zh_vars = set(PY_VAR_RE.findall(zh_flat[key]))
        if en_vars != zh_vars:
            mismatches.append(
                f"  {key}\n"
                f"    en vars: {sorted(en_vars)}\n"
                f"    zh vars: {sorted(zh_vars)}"
            )

    if mismatches:
        pytest.fail(
            f"{len(mismatches)} key(s) have mismatched interpolation variables:\n\n"
            + "\n".join(mismatches)
        )
