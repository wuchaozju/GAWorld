# RED-phase tests (TASK-1483) that pin the FOS unblinding kit to the
# paper-fidelity spec approved after the 2026-09-08 fidelity audit (Gui &
# Toubia 2025, arXiv:2312.15524v3). Every drift test FAILS on today's code
# for the right reason (the drift it encodes is still present); the GREEN
# phase must make them pass without editing this file.
#   PAPER_TABLE_A1  - Table A.1's 40 {category, product, regular_price} rows,
#       verbatim from the ground-truth extraction RESULT-1474 §3.1.4
#       (ASCII apostrophes; PDF quirks kept, e.g. "Cold Remedies -Adult").
#   TestPaperRegistryMatchesTableA1 - the product registry the sweeps run by
#       default is EXACTLY those 40 rows, and no other products file lists a
#       product outside the table (the old 7/10-product sets must be gone).
#   TestDoritosSinglePrice - all product files agree on the ONE Doritos row
#       (Party 14.5 oz @ $5.94) - never 4.79 vs 4.99.
#   TestPrompt10PersonaPrompt - persona-generation prompt is paper Prompt 10
#       (Appendix D): opens "You are a consumer with the following
#       characteristics:", lists the 11 demographic fill-ins, ends with the
#       purchase question, and never asks the model to invent behavioural
#       scores. The old opener ("Write the profile of a person who would buy
#       this product") must appear nowhere.
#   TestPrompt2SystemLine - the blinded system used with the purchase survey
#       is the paper Prompt 2 system line verbatim.
#   TestIncomeProbe - a diagnostic fill-in probe asks for the consumer's
#       total family income as a whole number.
#   TestProbeSentenceOrder - competing-price (Prompt 7) and expiry-days
#       (Prompt 8) probes state the focal price BEFORE the fill-in sentence
#       and use the paper's wording.
#   TestDepthLadderTwoLevels - the depth ladder has EXACTLY the two paper
#       levels (none = bare survey, demographics = 11 fields); tiers
#       tightwad/time_preference/risk_preference are gone everywhere.
#   TestSampleSizeDefaults - default draws per (product x level) = 50;
#       personas per product = 500.
# Appendix E covariate stages are intentionally NOT tested (they await the
# Twin-2K-500 dataset verification).

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from fos.experiments import personas as personas_mod
from fos.experiments import sweep_kit as sweep_kit_mod
from fos.experiments.randomization import (
    COVARIATE_COUNT_FOR_DEPTH,
    RandomizationDesign,
    covariate_count_for_depth,
)
from fos.experiments.sweep_kit import (
    build_blinded_system_prompt,
    build_covariate_fillin_prompt,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SWEEP_SCRIPT_PATH = REPO_ROOT / "scripts" / "unblinding_sweep.py"
GEN_PERSONAS_SCRIPT_PATH = REPO_ROOT / "scripts" / "generate_personas.py"

# The five behavioural measures whose model-invented blanks must vanish
# (names pinned from RESULT-1475 §1d / deviations.md row 3).
_BEHAVIORAL_MEASURE_NAMES = (
    "tightwad_spendthrift",
    "discount_rate",
    "present_bias",
    "risk_aversion",
    "loss_aversion",
)

# The paper's verbatim Prompt 2 / Prompt 10 system line (RESULT-1474 §1).
PROMPT2_SYSTEM = (
    "You, AI, are a customer. Your task is to fill in the blanks. "
    "Return the completed information in comma-separated values, without any "
    "extra text."
)

# The 11 Appendix D demographic labels, verbatim order (Prompt 10).
_PROMPT10_DEMOGRAPHIC_LABELS = [
    "Age", "Gender", "Education level", "Household income", "Occupation",
    "Ethnicity", "Marital status", "Household size", "Number of children",
    "State of residence", "Home ownership",
]

# Category/product used whenever a probe or prompt needs concrete inputs.
_CATEGORY = "Soft Drinks - Carbonated"
_PRODUCT = "Coca-Cola Soda Pop, 12 fl oz, 12 Pack Cans"

# Table A.1 rows: (row number, category, product, regular price in dollars).
PAPER_TABLE_A1 = [
    (1, "Fruit Juice", "Capri Sun Variety Pack with Fruit Punch, Strawberry Kiwi & Pacific Cooler Juice Box Pouches, 30 ct Box, 6 fl oz Pouches", 9.43),
    (2, "Fruit Drinks", "Kool Aid Jammers Variety Pack with Tropical Punch, Grape & Cherry Kids Drink 0% Juice Box Pouches, 30 Ct Box, 6 fl oz Pouches", 7.27),
    (3, "Baby Milk and Milk Flavoring", "Horizon Organic Shelf-Stable Whole Milk Boxes, 8 oz., 12 Pack", 13.98),
    (4, "Soup", "Maruchan Ramen Noodle Chicken Flavor Soup, 3 Oz, 12 Count Shelf Stable Package", 9.97),
    (5, "Cat Food - Wet Type", "Purina Fancy Feast Chicken Feast Classic Grain Free Wet Cat Food Pate - 3 oz. Can", 0.88),
    (6, "Pet Supplies - Dog Food", "Purina Dog Chow Complete, Dry Dog Food for Adult Dogs High Protein, Real Chicken, 44 lb Bag", 29.17),
    (7, "Snacks - Potato Chips", "Lay's Classic Potato Snack Chips, Party Size, 13 oz Bag", 5.44),
    (8, "Snacks - Tortilla Chips", "Doritos Nacho Cheese Tortilla Snack Chips, Party Size, 14.5 oz Bag", 5.94),
    (9, "Cereal - Ready to Eat", "Cinnamon Toast Crunch Breakfast Cereal, Crispy Cinnamon Cereal, Family Size, 18.8 oz", 4.93),
    (10, "Cookies", "Little Debbie Oatmeal Creme Pies, 12 ct, 16.2 oz", 2.68),
    (11, "Ground and Whole Bean Coffee", "Folgers Classic Roast Ground Coffee, Medium Roast, 40.3-Ounce Canister", 13.24),
    (12, "Soft Drinks - Carbonated", "Coca-Cola Soda Pop, 12 fl oz, 12 Pack Cans", 8.26),
    (13, "Bottled Water", "OZARKA Brand 100% Natural Spring Water, 16.9-ounce plastic bottles (Pack of 35)", 19.96),
    (14, "Candy - Chocolate", "Hershey's Milk Chocolate Candy, Bars 1.55 oz, 6 Count", 6.48),
    (15, "Candy - Non-Chocolate", "HARIBO Goldbears Original Gummy Bears, 28.8oz Stand Up Bag", 6.48),
    (16, "Soft Drinks - Low Calorie", "Coca-Cola Zero Sugar Soda Pop, 16.9 fl oz, 6 Pack Cans", 5.18),
    (17, "Frozen Italian Entrees", "Smart Ones Three Cheese Ziti Marinara Frozen Meal, 9 Oz Box", 2.26),
    (18, "Frozen Foods", "Great Value All Natural Chicken Wing Sections, 4 lb (Frozen)", 12.98),
    (19, "Ice Cream", "Haagen Dazs Coffee Ice Cream, Gluten Free, Kosher, 14.0 oz", 4.18),
    (20, "Frozen Novelties", "Pop-Ice Assorted Fruit Freezer Ice Pops, Gluten-Free Snack, 1.5 oz, 80 Count Fruit Pops", 6.17),
    (21, "Lunchmeat - Sliced - Refrigerated", "Oscar Mayer Chopped Ham & Water product Deli Lunch Meat, 16 Oz Package", 4.33),
    (22, "Frankfurters - Refrigerated", "Oscar Mayer Classic Uncured Beef Franks Hot Dogs, 10 ct Pack", 3.94),
    (23, "Refrigerated Bacon", "Oscar Mayer Fully Cooked Original Bacon, 2.52 oz Box", 4.27),
    (24, "Refrigerated Entrees", "John Soules Foods Chicken Breast Fajita Strips, Refrigerated, 16oz, 18g Protein per 3oz Serving Size", 5.98),
    (25, "Dairy Products", "Land O Lakes Salted Stick Butter, 16 oz, 4 Sticks", 5.28),
    (26, "Yogurt - Refrigerated", "Chobani Non-Fat Greek Yogurt, Vanilla Blended 32 oz, Plastic", 5.58),
    (27, "Refrigerated Deli Meats", "Goya Cooked Ham 16 oz", 29.99),
    (28, "Dairy - Milk - Refrigerated", "Great Value Milk Whole Vitamin D Gallon", 3.92),
    (29, "Bakery - Fresh Cakes", "Little Debbie Zebra Cakes, 13 oz", 2.68),
    (30, "Fresh Eggs", "Eggland's Best Classic Extra Large White Eggs, 12 count", 3.18),
    (31, "Fresh Fruit", "Fresh Raspberries, 12 oz Container", 4.74),
    (32, "Beer", "Stella Artois Lager, 12 Pack, 11.2 fl oz Glass Bottles, 5% ABV, Domestic Beer", 15.73),
    (33, "Light Beer (Low Calorie/Alcohol)", "Bud Light Beer, 24 Pack, 12 fl oz Aluminum Cans, 4.2% ABV, Domestic Lager", 20.98),
    (34, "Detergents - Heavy Duty - Liquid", "Purex Liquid Laundry Detergent Plus OXI, Stain Defense Technology, 128 Fluid Ounces, 85 Wash Loads", 9.97),
    (35, "Cleaning Supplies", "ARM & HAMMER Pure Baking Soda, For Baking, Cleaning & Deodorizing, 1 lb Box", 1.54),
    (36, "Toilet Tissue", "Angel Soft Toilet Paper, 9 Mega Rolls, Soft and Strong Toilet Tissue", 6.68),
    (37, "Paper Towels", "Bounty Select-a-Size Paper Towels, 12 Double Rolls, White", 22.18),
    (38, "Batteries", "Duracell Coppertop AA Battery, Long Lasting Double A Batteries, 16 Pack", 15.97),
    (39, "Pain Remedies - Headache", "Tylenol Extra Strength Caplets with 500 mg Acetaminophen, 100 Ct", 10.97),
    (40, "Cold Remedies -Adult", "Equate Value Size Honey Lemon Cough Drops with Menthol, 160 Count", 4.68),
]
# The one Doritos row the paper's table carries (row 8).
_DORITOS_ROW = next(row for row in PAPER_TABLE_A1 if "Doritos" in row[2])

def _canonical_row(row): return (row[1], row[2], row[3])
def _registry_paths():
    """Every products config file shipped under data/configs."""
    return sorted((REPO_ROOT / "data" / "configs").glob("unblinding_products*.json"))
def _load_product_rows(path):
    """Read a products file (object or bare-list shape) into row dicts."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data["products"]) if isinstance(data, dict) else list(data)
def _load_script(path, name):
    """Import a repo script by path without opening any socket."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"no loader for {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[module.__name__] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module.__name__, None)
    return module
def _persona_prompt():
    """The persona-generation (Prompt 10) user prompt for the Coke fixture."""
    return personas_mod.build_persona_elicitation_prompt(_CATEGORY, _PRODUCT)
class _RecordingChat:
    """Injected chat seam: records every call, never touches a network."""
    def __init__(self): self.calls = []
    def __call__(self, messages, temperature):
        self.calls.append((messages, temperature))
        return "no usable persona here"

# 1. The product registry is exactly Table A.1 (40 rows, no extras).
class TestPaperRegistryMatchesTableA1:
    def test_the_paper_table_has_40_verbatim_rows(self):
        """Sanity-check the embedded fixture before it locks anything."""
        assert len(PAPER_TABLE_A1) == 40, "Table A.1 fixture must hold 40 rows"
        names = [row[2] for row in PAPER_TABLE_A1]
        assert len(set(names)) == 40, "Table A.1 product names must be unique"
        for number, _category, product, price in PAPER_TABLE_A1:
            assert number >= 1 and product and price > 0.0
    def test_the_default_registry_is_exactly_the_40_table_a1_products(self):
        """The registry the sweeps run by default lists the 40 rows, no more."""
        default_path = REPO_ROOT / "data" / "configs" / "unblinding_products.json"
        assert default_path.exists(), "default products registry file is missing"
        actual = {(row["category"], row["product"], float(row["regular_price"]))
                  for row in _load_product_rows(default_path)}
        expected = {_canonical_row(row) for row in PAPER_TABLE_A1}
        assert actual == expected, (
            f"registry has {len(actual)} products, paper table has "
            f"{len(expected)}; missing={sorted(expected - actual)} "
            f"extras={sorted(actual - expected)}")
    def test_no_products_file_lists_anything_outside_table_a1(self):
        """The old 7- and 10-product sets (non-table SKUs) must be gone."""
        expected = {_canonical_row(row) for row in PAPER_TABLE_A1}
        offenders = []
        for path in _registry_paths():
            for row in _load_product_rows(path):
                key = (row["category"], row["product"], float(row["regular_price"]))
                if key not in expected:
                    offenders.append(f"{path.name}: {key!r}")
        assert not offenders, (
            "products outside Table A.1 still configured: " + "; ".join(offenders))

# 2. Doritos: one row, one price, the Table A.1 one.
class TestDoritosSinglePrice:
    def test_default_registry_has_exactly_one_doritos_row_at_the_table_price(self):
        """The default registry's Doritos row is Table A.1's (Party 14.5 oz)."""
        path = REPO_ROOT / "data" / "configs" / "unblinding_products.json"
        doritos_rows = [row for row in _load_product_rows(path)
                        if "Doritos" in row["product"]]
        assert len(doritos_rows) == 1, f"expected one Doritos row, got {doritos_rows}"
        row = doritos_rows[0]
        assert row["category"] == _DORITOS_ROW[1]
        assert row["product"] == _DORITOS_ROW[2]
        assert float(row["regular_price"]) == pytest.approx(_DORITOS_ROW[3])
    def test_all_products_files_agree_on_the_single_doritos_price(self):
        """The 4.79-vs-4.99 disagreement must be impossible after the fix."""
        for path in _registry_paths():
            doritos = [row for row in _load_product_rows(path)
                       if "Doritos" in row["product"]]
            for row in doritos:
                assert row["product"] == _DORITOS_ROW[2], (
                    f"{path.name}: non-table Doritos SKU {row['product']!r}")
                assert float(row["regular_price"]) == pytest.approx(_DORITOS_ROW[3]), (
                    f"{path.name}: Doritos priced {row['regular_price']}, "
                    f"paper price is {_DORITOS_ROW[3]}")

# 3. Persona-generation prompt is paper Prompt 10 (verbatim structure).
class TestPrompt10PersonaPrompt:
    def test_prompt_opens_with_the_paper_consumer_line(self):
        """First line: 'You are a consumer with the following characteristics:'."""
        first = _persona_prompt().lstrip().splitlines()[0].strip()
        assert first == "You are a consumer with the following characteristics:", (
            f"persona prompt must open with the paper's consumer line, got {first!r}")
    def test_demographic_block_is_the_11_paper_fields_in_order(self):
        """Lines 2-12 carry the 11 Appendix D fields, verbatim labels, in order."""
        lines = [line.strip() for line in _persona_prompt().splitlines() if line.strip()]
        block = lines[1:12]
        assert len(block) == 11, (
            f"demographic block must have 11 fill-in lines, got {len(block)}")
        for label, line in zip(_PROMPT10_DEMOGRAPHIC_LABELS, block):
            assert line.startswith(f"{label}:"), (
                f"expected '{label}:' as a fill-in line, got {line!r}")
    def test_prompt_ends_with_the_purchase_question_as_the_final_field(self):
        """The last completion is the purchase question (paper Prompt 10)."""
        lines = [line.strip() for line in _persona_prompt().splitlines() if line.strip()]
        purchase_lines = [i for i, line in enumerate(lines)
                          if line.startswith("Would you or would you not purchase")]
        assert purchase_lines, "persona prompt must ask the purchase question"
        purchase_index = purchase_lines[-1]
        assert '["purchase" or "not purchase"]' in lines[purchase_index]
        price_index = next(i for i, line in enumerate(lines)
                           if line.startswith("The product is currently priced at"))
        assert price_index < purchase_index, (
            "the store price line must precede the purchase question")
        tail = lines[purchase_index + 1:]
        assert len(tail) <= 1 and (not tail or tail[0].startswith("Return example")), (
            f"nothing but an optional Return example may follow the purchase "
            f"question, got {tail!r}")
    def test_category_and_store_paragraphs_follow_the_demographic_block(self):
        """Block order matches the paper: demographics, then category/store."""
        lines = [line.strip() for line in _persona_prompt().splitlines() if line.strip()]
        category_index = next(i for i, line in enumerate(lines)
                              if line.startswith("Please consider the following product category:"))
        assert category_index > 11, (
            "the category line must come after the 11 demographic fill-ins")
        store_index = next(i for i, line in enumerate(lines)
                           if line.startswith("Suppose you are in a grocery store"))
        assert store_index > category_index
    def test_old_outcome_selecting_opener_appears_nowhere(self):
        """The drift opener, WTP slot and fill-every-blank order are gone."""
        prompt = _persona_prompt()
        for drifted in ("Write the profile of a person who would buy this product",
                        "Price this person would pay",
                        "Reply with the completed template below in a single message"):
            assert drifted not in prompt, f"drift text still present: {drifted!r}"
    def test_no_model_invented_behavioural_blanks_in_the_prompt(self):
        """The persona prompt must not ask the model to invent scores."""
        prompt = _persona_prompt()
        for measure in _BEHAVIORAL_MEASURE_NAMES:
            assert measure not in prompt, (
                f"model-invented measure blank still asked: {measure!r}")
        assert "percentile" not in prompt, "score/percentile blanks must be gone"
    def test_persona_generation_system_is_the_paper_customer_system(self):
        """The system used to generate personas is Prompt 10's own system line."""
        chat = _RecordingChat()
        personas_mod.generate_personas(_CATEGORY, _PRODUCT, n=2, chat_fn=chat,
                                       temperature=1.0)
        assert chat.calls, "generate_personas must call the chat function"
        system = chat.calls[0][0][0]["content"]
        assert system == PROMPT2_SYSTEM, (
            f"persona generation system must be the paper Prompt 2/10 system "
            f"line, got {system!r}")
        assert "market study" not in system

# 4. The purchase survey's system line is paper Prompt 2 verbatim.
class TestPrompt2SystemLine:
    def test_blinded_system_prompt_is_the_verbatim_prompt2_system(self):
        """No more Prompt-5 shortening in the purchase condition."""
        assert build_blinded_system_prompt() == PROMPT2_SYSTEM, (
            f"blinded system prompt must equal paper Prompt 2's system line: "
            f"{PROMPT2_SYSTEM!r}")

# 5. The income probe exists among the diagnostic fill-ins.
class TestIncomeProbe:
    def _income_kinds(self, script):
        """Kinds whose machine name mentions income, in kit and CLI."""
        kit_kinds = list(getattr(sweep_kit_mod, "_COVARIATE_PROBES", {}))
        cli_kinds = list(script.COVARIATE_KINDS)
        return [k for k in kit_kinds + cli_kinds if "income" in k.lower()]
    def test_an_income_fill_in_kind_is_registered(self):
        """The sweep kit and CLI must both know an income probe kind."""
        script = _load_script(SWEEP_SCRIPT_PATH, "unblinding_sweep")
        assert self._income_kinds(script), (
            "no diagnostic fill-in probe for the consumer's income is registered")
    def test_the_income_probe_asks_for_total_family_income_as_a_whole_number(self):
        """The income fill-in names the total family income, whole-number blank."""
        script = _load_script(SWEEP_SCRIPT_PATH, "unblinding_sweep")
        kinds = self._income_kinds(script)
        assert kinds, "no income probe kind registered"
        kind = kinds[0]
        prompt = build_covariate_fillin_prompt(kind, _CATEGORY, _PRODUCT, 8.26)
        assert "total family income" in prompt.lower(), (
            f"income probe {kind!r} must ask for the total family income, "
            f"got: {prompt!r}")
        assert "[a whole number]" in prompt, (
            f"income probe {kind!r} must use a whole-number blank")
        assert kind in script.COVARIATE_KINDS, (
            f"income kind {kind!r} must be selectable on the sweep CLI")

# 6. Probe sentence order matches Prompts 7 and 8 (focal price first).
class TestProbeSentenceOrder:
    def test_competing_price_probe_states_the_focal_price_first(self):
        """Paper Prompt 7: focal price sentence, then the competing-price fill-in."""
        prompt = build_covariate_fillin_prompt("competing_price", _CATEGORY, _PRODUCT, 8.26)
        price_index = prompt.index("The product is currently priced at")
        fill_index = prompt.index(
            "The price of a similar competing product from a different brand is")
        assert price_index < fill_index, (
            "competing-price probe must state the focal price before the "
            "competing-price fill-in (paper Prompt 7 order)")
    def test_expiry_days_probe_uses_the_paper_sentence_in_the_paper_order(self):
        """Paper Prompt 8 wording and order, with no added premise."""
        prompt = build_covariate_fillin_prompt("expiry_days", _CATEGORY, _PRODUCT, 8.26)
        assert ("The expiration date of the product is [a whole number] days from now."
                in prompt), "expiry probe must use the paper's sentence verbatim"
        price_index = prompt.index("The product is currently priced at")
        expiry_index = prompt.index("The expiration date of the product is")
        assert price_index < expiry_index, (
            "expiry probe must state the focal price before the expiration "
            "fill-in (paper Prompt 8 order)")
        assert "Suppose you purchase this product today." not in prompt, (
            "the invented 'Suppose you purchase this product today.' preamble "
            "must be gone")
        assert "It will expire" not in prompt, (
            "the rephrased 'It will expire' fill-in must be gone")

# 7. Depth ladder: exactly the two paper levels (bare, demographics).
class TestDepthLadderTwoLevels:
    def test_depth_budget_map_defines_exactly_the_two_paper_levels(self):
        """Levels {1, 2} stay none -> 0 / demographics -> 11; the map also
        holds the Appendix E stage2..stage12 names (Table E.1 counts 15..30;
        stage1 is a Table E.1 stage, not a depth name)."""
        expected = {
            "none": 0,
            "demographics": 11,
            "stage2": 15,
            "stage3": 17,
            "stage4": 18,
            "stage5": 19,
            "stage6": 20,
            "stage7": 21,
            "stage8": 22,
            "stage9": 23,
            "stage10": 24,
            "stage11": 25,
            "stage12": 30,
        }
        assert COVARIATE_COUNT_FOR_DEPTH == expected, (
            f"depth map must keep none/demographics at 0/11 and add the "
            f"Appendix E stage2..stage12 cumulative counts, got "
            f"{COVARIATE_COUNT_FOR_DEPTH}"
        )
    def test_removed_behavioural_tiers_are_no_longer_supported(self):
        """tightwad/time_preference/risk_preference must raise ValueError."""
        for depth in ("tightwad", "time_preference", "risk_preference"):
            with pytest.raises(ValueError):
                covariate_count_for_depth(depth)
    def test_design_rejects_the_removed_behavioural_tiers(self):
        """RandomizationDesign must refuse the removed tiers at construction."""
        for depth in ("tightwad", "time_preference", "risk_preference"):
            with pytest.raises(ValueError):
                RandomizationDesign(variable="price", label="the price of the product",
                                    min_value=0.0, max_value=200.0, persona_depth=depth)
    def test_persona_renderer_rejects_the_removed_behavioural_tiers(self):
        """No renderer may still draw the model-invented score tiers."""
        render = getattr(personas_mod, "render_persona_fields", None)
        if render is None:
            return  # renderer removed outright - nothing can draw the tiers
        for depth in ("tightwad", "time_preference", "risk_preference"):
            with pytest.raises(ValueError):
                render({"age": 35}, depth)
    def test_cli_expands_all_to_only_the_two_paper_levels(self):
        """--persona-depth all and PERSONA_TIERS hold the two paper levels
        followed by the Appendix E stage2..stage12 ladder in order."""
        script = _load_script(SWEEP_SCRIPT_PATH, "unblinding_sweep")
        expected = (
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
        )
        assert script.PERSONA_TIERS == expected, (
            f"CLI tier list must hold none/demographics followed by the "
            f"Appendix E stage names in order, got {script.PERSONA_TIERS}"
        )
        assert script.expand_depths("all") == list(expected)
        for depth in ("tightwad", "time_preference", "risk_preference"):
            with pytest.raises(ValueError):
                script.expand_depths(depth)

# 8. Sample sizes: 50 draws per cell, 500 personas per product.
class TestSampleSizeDefaults:
    def test_sweep_cli_default_draws_is_50(self):
        """The paper's default: 50 draws per (product x price level)."""
        script = _load_script(SWEEP_SCRIPT_PATH, "unblinding_sweep")
        args = script._parse_args(["--model", "qwen"])
        assert args.draws == 50, (
            f"CLI --draws default must be 50 (paper default), got {args.draws}")
    def test_personas_per_product_default_is_500(self):
        """Both the sweep loader and the generator default to 500 personas."""
        script = _load_script(SWEEP_SCRIPT_PATH, "unblinding_sweep")
        assert script.DEFAULT_PERSONAS_PER_PRODUCT == 500
        args = script._parse_args(["--model", "qwen"])
        assert args.personas_per_product == 500
        gen = _load_script(GEN_PERSONAS_SCRIPT_PATH, "generate_personas")
        assert gen.DEFAULT_N == 500
