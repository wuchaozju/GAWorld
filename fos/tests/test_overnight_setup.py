# Contract tests (RED phase) for three overnight-readiness changes to the
# Gui & Toubia (2025) unblinding kit: the two depth levels / many products in
# one unattended invocation, plus a standalone chat-server pilot. After the
# paper-fidelity drift fix (TASK-1483) the depth ladder holds exactly the two
# paper levels {1, 2} (none, demographics); the behavioural tiers of the
# pre-drift five-tier ladder (tightwad, time_preference, risk_preference)
# are gone everywhere.
#
# 1. scripts/unblinding_sweep.py. expand_depths(spec) maps "all" -> the two
#    tiers (none, demographics), one tier -> [tier], a comma list -> its
#    members in order; unknown names AND the removed behavioural tiers raise
#    ValueError. --persona-depth accepts "all", the two tiers AND comma
#    lists, keeping the raw string typed (single tiers and the default
#    "none" stay strings - locked by test_persona_depth.py); an invalid tier
#    inside a comma list is rejected at parse time.
# 2. scripts/generate_personas.py batch mode + safety. --products-file reads
#    {"products": [{category, product, regular_price}]} and generates for
#    EVERY product into {out}/{safe_product}/personas.jsonl + summary.json
#    (safe name = non-alphanumerics -> "_", case kept; summary carries
#    regular_price). COMPLETION GATE: under --min-personas (default same as
#    --n; parsed default is a falsy sentinel) parsed personas -> loud stderr
#    line (product, got, expected) per short product and exit 3; fully
#    supplied exits 0. INCREMENTAL WRITES: each parsed persona is appended +
#    flushed immediately (a kill mid-run loses nothing) via module-level
#    _generate_for_product(category, product, n, chat_fn, out_dir,
#    temperature=1.0, seed=None) -> (personas, skipped). --timeout (default
#    120 s) is plumbed into the chat transport; a raising transport yields
#    skipped personas, never a crash.
# 3. scripts/pilot_model.py (NEW file). main(argv=None) behind a __main__
#    guard; flags --model (required), --base-url (http://127.0.0.1:8080),
#    --out (results/pilots/<safe_model>/), --depth1-calls 20, --depth2-calls
#    20, --persona-gen-calls 5, --timeout 120, --seed 42. Phases depth1,
#    depth2, persona-gen in that order, each cycling the 11-level price grid
#    (0..200% step 20) from 0%: (a) build_purchase_user_prompt + blinded
#    system prompt; (b) same survey but the user prompt embeds a FIXED
#    synthetic demographics persona (module.PILOT_PERSONA: the 11 demographic
#    fields, no invented behavioural measures) rendered via
#    render_persona_fields(persona, "demographics"), product data from
#    module.PILOT_PRODUCT; (c) build_persona_elicitation_prompt with
#    max_tokens 128. Transport = chat_fn(messages, max_tokens), built only
#    in main (socket-free import; injectable via module._build_chat_fn).
#    Report {out}/pilot_report.json: {model, base_url, generated_at} +
#    per-phase depth1/depth2/persona_gen, each {"calls", "parse_rate",
#    "latency": {"mean_s", "median_s", "p95_s"}, "distinct_raw": [...]
#    capped at 20}; parse_rate = purchase answers parsed via parse_purchase,
#    persona-gen answers carrying all 11 fields. Summary table printed; main
#    exits 0 even on all-garbage answers, exits 2 when the transport raises.
import importlib.util
import inspect
import json
import re
import socket
import sys
from pathlib import Path
import pytest
from fos.experiments import personas
from fos.experiments.sweep_kit import (
    build_blinded_system_prompt,
    build_purchase_user_prompt,
)
REPO_ROOT = Path(__file__).resolve().parent.parent
SWEEP_SCRIPT = REPO_ROOT / "scripts" / "unblinding_sweep.py"
GENERATE_SCRIPT = REPO_ROOT / "scripts" / "generate_personas.py"
PILOT_SCRIPT = REPO_ROOT / "scripts" / "pilot_model.py"
TIERS = ["none", "demographics"]
PRICE_GRID = list(range(0, 201, 20))  # the 11-level grid the pilot phases cycle
# Two verbatim Table A.1 rows (TASK-1483 fixture): the pre-drift product
# set's drifted SKUs (e.g. "Lay's Classic Potato Chips, 8 oz Bag" @ 4.99)
# must not appear in any fixture here.
PRODUCTS = [
    {"category": "Soft Drinks - Carbonated",
     "product": "Coca-Cola Soda Pop, 12 fl oz, 12 Pack Cans", "regular_price": 8.26},
    {"category": "Snacks - Potato Chips",
     "product": "Lay's Classic Potato Snack Chips, Party Size, 13 oz Bag",
     "regular_price": 5.44},
]
SAFE_PRODUCTS = [re.sub(r"[^0-9A-Za-z]+", "_", p["product"]) for p in PRODUCTS]
CANNED_RAW = "\n".join([
    "age: 35", "gender: female", "education: college", "household_income: $86,500",
    "occupation: teacher", "ethnicity: white", "marital_status: married",
    "household_size: 4", "number_of_children: 2", "state: CA", "home_ownership: own",
])
CANNED_PERSONA = {
    "age": 35, "gender": "female", "education": "college", "household_income": 86500,
    "occupation": "teacher", "ethnicity": "white", "marital_status": "married",
    "household_size": 4, "number_of_children": 2, "state": "CA", "home_ownership": "own",
}
# The 11-field reply above is the persona answer the persona-gen phase
# counts as parseable (the pre-drift "all 16 fields" reply that added five
# model-invented behavioural measures is gone with the drift fix).

def _load_script(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"no loader for {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module

def _run_main(module, argv):
    try:
        return module.main(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

def _products_file(tmp_path):
    path = tmp_path / "products.json"
    path.write_text(json.dumps({"products": PRODUCTS}), encoding="utf-8")
    return path

def _persona_lines(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

class _ValidChat:
    """Chat that answers every call with one canned valid persona answer."""
    def __call__(self, messages, temperature):
        return CANNED_RAW

class _RecordingChat:
    """Records every (messages, max_tokens) call; answers via a responder."""

    def __init__(self, responder=lambda m, t: ""):
        self.responder = responder
        self.calls = []

    def __call__(self, messages, max_tokens):
        self.calls.append((messages, max_tokens))
        return self.responder(messages, max_tokens)

class TestExpandDepths:

    def test_all_single_tiers_and_comma_lists_expand_in_order(self):
        """expand_depths("all") now expands to the 13-name ladder: none,
        demographics, then stage2..stage12 (Appendix E); single tiers and
        two-name comma lists still expand in order."""
        module = _load_script(SWEEP_SCRIPT, "unblinding_sweep")
        expected = [
            "none",
            "demographics",
            "stage2",
            "stage3",
            "stage4",
            "stage5",
            "stage6",
            "stage7",
            "stage8",
            "stage9",
            "stage10",
            "stage11",
            "stage12",
        ]
        assert module.expand_depths("all") == expected
        for tier in TIERS:
            assert module.expand_depths(tier) == [tier]
        assert module.expand_depths("none,demographics") == TIERS
        assert module.expand_depths("demographics,none") == TIERS[::-1]

    def test_an_unknown_or_removed_name_anywhere_raises_value_error(self):
        module = _load_script(SWEEP_SCRIPT, "unblinding_sweep")
        for bad in (
            "bananas",
            "extended",
            "deep",
            "none,extended",
            "demographics,bananas",
            "tightwad",
            "time_preference",
            "risk_preference",
            "none,tightwad",
        ):
            with pytest.raises(ValueError):
                module.expand_depths(bad)

class TestUnblindingSweepAllDepthSpec:

    def test_parser_accepts_all_and_comma_lists_keeping_the_raw_text(self):
        module = _load_script(SWEEP_SCRIPT, "unblinding_sweep")
        for spec in ("all", "none,demographics", "demographics,none"):
            args = module._parse_args(["--model", "qwen3-8b", "--persona-depth", spec])
            assert args.persona_depth == spec

    def test_parser_rejects_an_invalid_or_removed_tier_inside_a_comma_list(self):
        module = _load_script(SWEEP_SCRIPT, "unblinding_sweep")
        for bad in (
            "none,extended",
            "demographics,bananas",
            "none,tightwad",
            "demographics,risk_preference",
        ):
            with pytest.raises(SystemExit):
                module._parse_args(["--model", "qwen3-8b", "--persona-depth", bad])

class TestGeneratePersonasBatchFlags:

    def test_help_lists_the_new_batch_and_safety_flags(self, capsys):
        module = _load_script(GENERATE_SCRIPT, "generate_personas")
        with pytest.raises(SystemExit) as excinfo:
            module.main(["--help"])
        assert excinfo.value.code == 0
        help_text = capsys.readouterr().out
        for option in ("--products-file", "--min-personas", "--timeout"):
            assert option in help_text, f"missing option {option}"

    def test_parser_reads_the_new_flags_with_sane_defaults(self):
        module = _load_script(GENERATE_SCRIPT, "generate_personas")
        args = module._parse_args(["--category", "Snacks", "--product", "Chips",
                                   "--products-file", "p.json",
                                   "--min-personas", "7", "--timeout", "9"])
        assert args.products_file == "p.json"
        assert args.min_personas == 7 and args.timeout == 9
        defaults = module._parse_args(["--category", "Snacks", "--product", "Chips"])
        assert not defaults.products_file
        assert not defaults.min_personas  # "same as --n" fills it in later
        assert defaults.timeout == 120

class TestGeneratePersonasBatchRun:

    def _run(self, monkeypatch, module, out, chat, extra, tmp_path):
        monkeypatch.setattr(module, "_build_chat_fn", lambda *a, **k: chat)
        argv = ["--model", "qwen3-8b", "--products-file", str(_products_file(tmp_path)),
                "--out", str(out), *extra]
        return _run_main(module, argv)

    def test_batch_mode_writes_every_product_into_its_own_safe_directory(self, tmp_path, monkeypatch):
        module = _load_script(GENERATE_SCRIPT, "generate_personas")
        out = tmp_path / "out"
        assert self._run(monkeypatch, module, out, _ValidChat(),
                         ["--n", "2", "--seed", "1"], tmp_path) == 0
        for safe, product in zip(SAFE_PRODUCTS, PRODUCTS):
            folder = out / safe
            assert _persona_lines(folder / "personas.jsonl") == [
                CANNED_PERSONA, CANNED_PERSONA]
            summary = json.loads((folder / "summary.json").read_text())
            assert summary["product"] == product["product"]
            assert summary["category"] == product["category"]
            assert summary["regular_price"] == pytest.approx(product["regular_price"])
            assert summary["n_requested"] == summary["n_personas"] == 2

    def test_batch_mode_reports_short_products_and_exits_three(self, tmp_path, monkeypatch, capsys):
        def chat(messages, temperature):
            return CANNED_RAW if "Lay's" in messages[1]["content"] else "nonsense"
        module = _load_script(GENERATE_SCRIPT, "generate_personas")
        assert self._run(monkeypatch, module, tmp_path / "out", chat,
                         ["--n", "3"], tmp_path) == 3
        stderr = capsys.readouterr().err
        short = [line for line in stderr.splitlines() if PRODUCTS[0]["product"] in line]
        assert short and "0" in short[0] and "3" in short[0]
        assert PRODUCTS[1]["product"] not in stderr

    def test_default_min_personas_tracks_the_requested_n(self, tmp_path, monkeypatch, capsys):
        counts = {}
        def chat(messages, temperature):
            key = "lays" if "Lay's" in messages[1]["content"] else "cola"
            counts[key] = counts.get(key, 0) + 1
            if key == "lays" and counts[key] == 1:
                return CANNED_RAW
            return CANNED_RAW if key == "cola" else "nonsense"
        module = _load_script(GENERATE_SCRIPT, "generate_personas")
        assert self._run(monkeypatch, module, tmp_path / "out", chat,
                         ["--n", "2"], tmp_path) == 3
        stderr = capsys.readouterr().err
        short = [line for line in stderr.splitlines() if PRODUCTS[1]["product"] in line]
        assert short and PRODUCTS[0]["product"] not in stderr

    def test_batch_mode_keeps_personas_written_before_a_mid_run_kill(self, tmp_path, monkeypatch):
        counts = {}
        def chat(messages, temperature):
            key = "lays" if "Lay's" in messages[1]["content"] else "cola"
            counts[key] = counts.get(key, 0) + 1
            if key == "lays" and counts[key] == 3:
                raise RuntimeError("process killed mid-run")
            return CANNED_RAW
        module = _load_script(GENERATE_SCRIPT, "generate_personas")
        out = tmp_path / "out"
        try:
            self._run(monkeypatch, module, out, chat, ["--n", "3"], tmp_path)
        except RuntimeError:
            pass  # a kill may abort the run; the flushed personas must survive it
        assert _persona_lines(out / SAFE_PRODUCTS[0] / "personas.jsonl") == [
            CANNED_PERSONA] * 3
        lays = out / SAFE_PRODUCTS[1] / "personas.jsonl"
        assert _persona_lines(lays) == [CANNED_PERSONA] * 2  # flushed before the kill

class TestGenerateForProductHook:

    def _chat(self, answer, raise_on=None):
        calls = {"n": 0}
        def chat(messages, temperature):
            calls["n"] += 1
            if raise_on is not None and calls["n"] == raise_on:
                raise RuntimeError("process killed mid-run")
            return answer.pop(0) if isinstance(answer, list) else answer
        return chat

    def test_hook_appends_each_parsed_persona_before_the_run_finishes(self, tmp_path):
        module = _load_script(GENERATE_SCRIPT, "generate_personas")
        with pytest.raises(RuntimeError):
            module._generate_for_product("Snacks", "Chips", 3,
                                         self._chat(CANNED_RAW, raise_on=3),
                                         out_dir=tmp_path)
        assert _persona_lines(tmp_path / "personas.jsonl") == [
            CANNED_PERSONA, CANNED_PERSONA]

    def test_hook_returns_parsed_and_skipped_counts(self, tmp_path):
        module = _load_script(GENERATE_SCRIPT, "generate_personas")
        personas_out, skipped = module._generate_for_product(
            "Snacks", "Chips", 3, self._chat([CANNED_RAW, CANNED_RAW, "no profile"]),
            out_dir=tmp_path)
        assert personas_out == [CANNED_PERSONA, CANNED_PERSONA]
        assert skipped == 1
        assert _persona_lines(tmp_path / "personas.jsonl") == [CANNED_PERSONA] * 2

class TestGeneratePersonasTimeout:

    def _legacy(self, out, n, timeout):
        return ["--category", "Snacks", "--product", "Chips", "--model", "qwen3-8b",
                "--out", str(out), "--n", str(n), "--timeout", str(timeout)]

    def test_main_plumbs_the_timeout_into_every_chat_post(self, tmp_path, monkeypatch):
        module = _load_script(GENERATE_SCRIPT, "generate_personas")
        seen = []
        body = json.dumps({"choices": [{"message": {"content": CANNED_RAW}}]})
        def _fake_post(url, payload, timeout):
            seen.append(timeout)
            return 200, body
        monkeypatch.setattr(module, "_post_json", _fake_post)
        out = tmp_path / "out"
        assert _run_main(module, self._legacy(out, 2, 7)) == 0
        assert seen and all(t == 7 for t in seen)
        assert _persona_lines(out / "personas.jsonl") == [CANNED_PERSONA, CANNED_PERSONA]

    def test_a_transport_timeout_yields_skipped_personas_without_crashing(self, tmp_path, monkeypatch):
        def _raise_timeout(url, payload, timeout):
            raise OSError(f"timed out after {timeout}s")
        module = _load_script(GENERATE_SCRIPT, "generate_personas")
        monkeypatch.setattr(module, "_post_json", _raise_timeout)
        out = tmp_path / "out"
        assert _run_main(module, self._legacy(out, 3, 5)) == 0
        summary = json.loads((out / "summary.json").read_text())
        assert summary["n_personas"] == 0 and summary["n_skipped"] == 3

def _pilot_argv(out=None, **flags):
    argv = ["--model", "qwen3-8b"]
    if out is not None:
        argv += ["--out", str(out)]
    for name, value in flags.items():
        argv += [f"--{name}", str(value)]
    return argv

def _inject_chat(monkeypatch, module, chat=None):
    """Patch the pilot's chat builder with a recording chat; return it."""
    chat = chat if chat is not None else _RecordingChat()
    monkeypatch.setattr(module, "_build_chat_fn", lambda *a, **k: chat)
    return chat

class TestPilotModelScript:

    def test_main_takes_optional_argv_behind_a_main_guard(self):
        module = _load_script(PILOT_SCRIPT, "pilot_model")
        assert callable(module.main)
        assert 'if __name__ == "__main__":' in PILOT_SCRIPT.read_text()
        params = inspect.signature(module.main).parameters
        assert list(params) == ["argv"] and params["argv"].default is None

    def test_importing_the_pilot_script_never_opens_a_socket(self):
        def _forbid_socket(*_args, **_kwargs):
            raise AssertionError("importing pilot_model must not open a socket")
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(socket, "socket", _forbid_socket)
        try:
            module = _load_script(PILOT_SCRIPT, "pilot_model")
        finally:
            monkeypatch.undo()
        assert callable(module.main)

    def test_help_exits_zero_and_lists_every_flag(self, capsys):
        module = _load_script(PILOT_SCRIPT, "pilot_model")
        with pytest.raises(SystemExit) as excinfo:
            module.main(["--help"])
        assert excinfo.value.code == 0
        help_text = capsys.readouterr().out
        for option in ("--model", "--base-url", "--out", "--depth1-calls",
                       "--depth2-calls", "--persona-gen-calls", "--timeout", "--seed"):
            assert option in help_text, f"missing option {option}"

    def test_parser_requires_model_and_applies_the_documented_defaults(self):
        module = _load_script(PILOT_SCRIPT, "pilot_model")
        with pytest.raises(SystemExit):
            module._parse_args([])
        args = module._parse_args(["--model", "qwen3/8b"])
        assert args.base_url == "http://127.0.0.1:8080"
        # The second phase is the demographics tier of the two-level ladder
        # (depth 2), so the flag is --depth2-calls, never --depth5-calls.
        depth2_calls = getattr(args, "depth2_calls", None)
        assert depth2_calls == 20, "pilot parser must default --depth2-calls to 20"
        assert (args.depth1_calls, depth2_calls,
                args.persona_gen_calls, args.timeout, args.seed) == (20, 20, 5, 120, 42)

    def test_parser_reads_every_explicit_option(self):
        module = _load_script(PILOT_SCRIPT, "pilot_model")
        args = module._parse_args(
            ["--model", "qwen3-8b", "--base-url", "http://localhost:4321/v1",
             "--out", "results/x", "--depth1-calls", "5", "--depth2-calls", "7",
             "--persona-gen-calls", "3", "--timeout", "9", "--seed", "1"])
        depth2_calls = getattr(args, "depth2_calls", None)
        assert depth2_calls == 7, "pilot parser must read --depth2-calls"
        assert (args.base_url, args.out, args.depth1_calls, depth2_calls,
                args.persona_gen_calls, args.timeout, args.seed) == (
            "http://localhost:4321/v1", "results/x", 5, 7, 3, 9, 1)

    def test_default_out_dir_holds_the_safe_model_name(self, tmp_path, monkeypatch):
        module = _load_script(PILOT_SCRIPT, "pilot_model")
        _inject_chat(monkeypatch, module)
        monkeypatch.chdir(tmp_path)
        assert _run_main(module, ["--model", "qwen3/8b", "--depth1-calls", "1",
                                  "--depth2-calls", "1", "--persona-gen-calls", "1"]) == 0
        assert (tmp_path / "results" / "pilots" / "qwen3_8b"
                / "pilot_report.json").exists()

    def test_the_pilot_exposes_fixed_product_and_demographics_persona_fixtures(self):
        module = _load_script(PILOT_SCRIPT, "pilot_model")
        assert set(module.PILOT_PRODUCT) >= {"category", "product", "regular_price"}
        persona = module.PILOT_PERSONA
        # The fixed persona is the demographics-tier persona: the 11
        # demographic fields. Model-invented behavioural measures are gone.
        assert set(persona) >= set(personas.PERSONA_FIELDS)

class TestPilotDepthProtocol:

    def _structure_run(self, tmp_path, monkeypatch):
        module = _load_script(PILOT_SCRIPT, "pilot_model")
        chat = _inject_chat(monkeypatch, module)
        rc = _run_main(module, _pilot_argv(tmp_path / "pilot", depth1_calls=3,
                                           depth2_calls=2, persona_gen_calls=1))
        return rc, module, chat

    def test_depth1_calls_cycle_the_blinded_survey_across_the_price_grid(self, tmp_path, monkeypatch):
        rc, module, chat = self._structure_run(tmp_path, monkeypatch)
        assert rc == 0
        product, blinded = module.PILOT_PRODUCT, build_blinded_system_prompt()
        for index in range(3):
            messages, _tokens = chat.calls[index]
            price = round(product["regular_price"] * PRICE_GRID[index] / 100.0, 2)
            assert messages == [{"role": "system", "content": blinded},
                                {"role": "user", "content": build_purchase_user_prompt(
                                    product["category"], product["product"], price)}]

    def test_depth1_cycles_to_reach_exactly_the_requested_count(self, tmp_path, monkeypatch):
        module = _load_script(PILOT_SCRIPT, "pilot_model")
        chat = _inject_chat(monkeypatch, module)
        assert _run_main(module, _pilot_argv(tmp_path / "pilot", depth1_calls=25,
                                             depth2_calls=1,
                                             persona_gen_calls=1)) == 0
        assert len(chat.calls) == 27
        product, blinded = module.PILOT_PRODUCT, build_blinded_system_prompt()
        for index in range(25):
            messages, _tokens = chat.calls[index]
            assert messages[0]["content"] == blinded
            level = PRICE_GRID[index % len(PRICE_GRID)]
            price = round(product["regular_price"] * level / 100.0, 2)
            assert messages[1]["content"] == build_purchase_user_prompt(
                product["category"], product["product"], price)

    def test_depth2_calls_embed_the_fixed_demographics_persona(self, tmp_path, monkeypatch):
        rc, module, chat = self._structure_run(tmp_path, monkeypatch)
        assert rc == 0, "pilot main must exit 0 on a clean run"
        product = module.PILOT_PRODUCT
        # The persona phase renders the fixed demographics persona. Either the
        # depth renderer at the "demographics" tier or the demographics block
        # renderer may back it; the block must be non-empty and measure-free.
        render = getattr(personas, "render_persona_fields", None)
        if render is not None:
            block = render(module.PILOT_PERSONA, "demographics")
        else:
            block_render = getattr(personas, "render_demographics_block", None)
            assert block_render is not None, (
                "pilot persona phase needs a demographics renderer"
            )
            block = block_render(module.PILOT_PERSONA)
        assert block
        for index in range(3, 5):
            messages, _tokens = chat.calls[index]
            assert messages[0]["content"] == build_blinded_system_prompt()
            user = messages[1]["content"]
            level = PRICE_GRID[index - 3]
            price = round(product["regular_price"] * level / 100.0, 2)
            survey = build_purchase_user_prompt(product["category"],
                                                product["product"], price)
            assert block in user and survey in user and user != survey

    def test_persona_gen_calls_send_the_elicitation_prompt_with_max_tokens_128(self, tmp_path, monkeypatch):
        rc, module, chat = self._structure_run(tmp_path, monkeypatch)
        assert rc == 0, "pilot main must exit 0 on a clean run"
        product = module.PILOT_PRODUCT
        messages, max_tokens = chat.calls[-1]
        assert messages[1]["content"] == personas.build_persona_elicitation_prompt(
            product["category"], product["product"])
        assert max_tokens == 128

class TestPilotReport:

    def _responder(self):
        counters = {}
        def responder(messages, max_tokens):
            user = messages[1]["content"]
            # persona-gen = the paper Prompt 10 consumer opener; depth2 =
            # the embedded demographics block ("age: " line); the rest is
            # the bare depth1 survey.
            if "You are a consumer with the following characteristics:" in user:
                phase = "persona_gen"
            elif "age: " in user:
                phase = "depth2"
            else:
                phase = "depth1"
            counters[phase] = counters.get(phase, 0) + 1
            if phase == "persona_gen":
                return CANNED_RAW if counters[phase] == 1 else "no profile"
            if phase == "depth2":
                return "not purchase"
            return "purchase" if counters[phase] <= 2 else "nonsense"
        return responder

    def _run(self, tmp_path, monkeypatch, responder, **flags):
        module = _load_script(PILOT_SCRIPT, "pilot_model")
        _inject_chat(monkeypatch, module, _RecordingChat(responder))
        out = tmp_path / "pilot"
        return _run_main(module, _pilot_argv(out, **flags)), out / "pilot_report.json"

    def test_report_records_counts_parse_rates_latency_and_distinct_raw(self, tmp_path, monkeypatch, capsys):
        rc, report_path = self._run(
            tmp_path, monkeypatch, self._responder(), base_url="http://localhost:9000",
            depth1_calls=4, depth2_calls=3, persona_gen_calls=2)
        assert rc == 0, "pilot main must exit 0 on a clean run"
        report = json.loads(report_path.read_text())
        assert report["model"] == "qwen3-8b"
        assert report["base_url"] == "http://localhost:9000"
        assert isinstance(report["generated_at"], str) and report["generated_at"]
        for phase in ("depth1", "depth2", "persona_gen"):
            entry = report.get(phase)
            assert entry is not None, f"report must carry a {phase!r} phase entry"
            assert set(entry) >= {"calls", "parse_rate", "latency", "distinct_raw"}
            assert 0.0 <= entry["parse_rate"] <= 1.0
            assert set(entry["latency"]) == {"mean_s", "median_s", "p95_s"}
            assert all(v >= 0 for v in entry["latency"].values())
        assert report["depth1"]["calls"] == 4
        assert report["depth1"]["parse_rate"] == pytest.approx(0.5)
        assert set(report["depth1"]["distinct_raw"]) == {"purchase", "nonsense"}
        assert report["depth2"]["calls"] == 3
        assert report["depth2"]["parse_rate"] == pytest.approx(1.0)
        assert report["persona_gen"]["calls"] == 2
        assert report["persona_gen"]["parse_rate"] == pytest.approx(0.5)
        table = capsys.readouterr().out
        for word in ("depth1", "depth2", "persona_gen", "parse_rate"):
            assert word in table, f"summary table must mention {word!r}"

    def test_distinct_raw_is_capped_at_twenty(self, tmp_path, monkeypatch):
        counters = {"depth1": 0}
        def responder(messages, max_tokens):
            user = messages[1]["content"]
            if "You are a consumer with the following characteristics:" in user:
                return CANNED_RAW
            if "age: " in user:
                return "purchase"
            counters["depth1"] += 1
            return f"unique-answer-{counters['depth1']}"
        rc, report_path = self._run(
            tmp_path, monkeypatch, responder, depth1_calls=25, depth2_calls=1,
            persona_gen_calls=1)
        assert rc == 0, "pilot main must exit 0 on a clean run"
        report = json.loads(report_path.read_text())
        assert report["depth1"]["calls"] == 25
        assert len(report["depth1"]["distinct_raw"]) == 20

    def test_pilot_exits_zero_even_when_every_answer_is_unparseable(self, tmp_path, monkeypatch):
        rc, report_path = self._run(
            tmp_path, monkeypatch, lambda m, t: "???",
            depth1_calls=3, depth2_calls=3, persona_gen_calls=2)
        assert rc == 0, "pilot main must exit 0 even on all-garbage answers"
        report = json.loads(report_path.read_text())
        for phase in ("depth1", "depth2", "persona_gen"):
            entry = report.get(phase)
            assert entry is not None, f"report must carry a {phase!r} phase entry"
            assert entry["parse_rate"] == pytest.approx(0.0)

    def test_pilot_exits_two_on_a_transport_level_failure(self, tmp_path,
                                                          monkeypatch, capsys):
        def _die(messages, max_tokens):
            raise OSError("connection refused")
        module = _load_script(PILOT_SCRIPT, "pilot_model")
        _inject_chat(monkeypatch, module, _die)
        rc = _run_main(module, _pilot_argv(tmp_path / "pilot", depth1_calls=2))
        assert rc == 2
        assert "error" in capsys.readouterr().err.lower()
