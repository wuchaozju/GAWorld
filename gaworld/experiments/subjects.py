"""Simulated subjects and the world state they carry into an experiment.

Two things live here, and the distinction between them is the whole point
of the agent-based arm:

* :class:`Subject` — *who* is answering. Loaded from the same resident
  state CSV and profile Markdown the simulator runs on, so an experiment
  subject and a simulated resident are the same person.
* :class:`WorldContext` — *what is already true* for that person and that
  product before the experimenter touches anything: what they paid last
  time, what the competing product costs on that shelf, how much of the
  month's grocery budget is left.

Gui & Toubia (2025) show that when these are left unspecified, the LLM
back-fills them *from the treatment* — a higher price makes it imagine a
higher past price and a higher competitor price — which breaks
unconfoundedness. Here they are drawn once per ``(subject, product)``
from a seed that **does not include the price**, so they are invariant
across the price grid by construction. That is the do-operator
implemented as state rather than as a sentence asking the model to
please hold everything else constant.
"""

from __future__ import annotations

import csv
import random
import re
from dataclasses import dataclass
from pathlib import Path

from gaworld.economy.finance import _engel_params, _job_income_band
from gaworld.settings import CONFIG
from gaworld.sim.agents_loader import parse_profile
from gaworld.experiments.stimulus import Product

_PROFILE_BLOCK = re.compile(r"## Profile (\d+)｜.*?(?=\n## Profile |\Z)", re.S)


@dataclass(frozen=True)
class Subject:
    """A resident, as seen by a one-shot experiment (no memory dir needed)."""

    id: int
    name: str
    gender: str
    age: int
    residence: str
    job: str
    personality: str
    daily_life: str
    state: dict[str, float]
    monthly_income: float

    @property
    def job_title(self) -> str:
        """Just the occupation.

        The profile's ``job`` field is a whole sentence — title plus work
        rhythm — so splicing it into a clause produces "。，". The rhythm
        is still worth showing, just on a line of its own.
        """
        return self.job.split("，")[0].rstrip("。 ")

    @property
    def work_rhythm(self) -> str:
        """The rest of the ``job`` sentence, minus the title already used."""
        _, _, rest = self.job.partition("，")
        return rest.strip()

    @property
    def demographics(self) -> str:
        """The covariate block the paper's §3 arm writes into the prompt."""
        return (
            f"{self.age}岁{self.gender}性，居住在{self.residence}，"
            f"职业是{self.job_title}，月收入约{self.monthly_income:.0f}元"
        )


@dataclass(frozen=True)
class WorldContext:
    """Pre-treatment covariates that the world — not the prompt — fixes."""

    last_paid: float
    competitor_price: float
    shelf_life_days: int
    store: str
    monthly_food_budget: float
    #: Share of this month's grocery budget still unspent. This — not any
    #: comparison against the item's price — is what the prompt renders,
    #: because the price is the treatment and must not reach a covariate.
    budget_left_ratio: float


_STORES = ("小区楼下的便利店", "常去的社区超市", "地铁站边的连锁生鲜超市", "周末去的大卖场")


def _resolve(path_value: str) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else Path(__file__).resolve().parents[2] / path


def _profile_blocks(md_path: Path) -> dict[int, str]:
    text = md_path.read_text(encoding="utf-8")
    return {int(match.group(1)): match.group(0) for match in _PROFILE_BLOCK.finditer(text)}


def _monthly_income(job: str, econ_security: float, rng: random.Random) -> float:
    """A stable monthly income for a job, drawn once per subject.

    Reuses the simulator's own job→hourly bands so an experiment subject
    is not richer or poorer than the same resident would be in a run.
    ``econ_security`` stands in for the income-skill term.
    """
    low, high = _job_income_band(job)
    hourly = rng.uniform(low, high) * (0.75 + 0.55 * max(0.0, min(1.0, econ_security)))
    return round(hourly * 8 * 21.75, 2)


def load_subjects(
    *,
    limit: int | None = None,
    ids: list[int] | None = None,
    seed: int = 42,
    csv_path: str | None = None,
    md_path: str | None = None,
) -> list[Subject]:
    """Load residents as experiment subjects, in id order."""
    state_csv = _resolve(csv_path or CONFIG["csv_path"])
    profile_md = _resolve(md_path or CONFIG["md_path"])
    blocks = _profile_blocks(profile_md)

    subjects: list[Subject] = []
    with open(state_csv, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            agent_id = int(row["id"])
            if ids is not None and agent_id not in ids:
                continue
            block = blocks.get(agent_id)
            if block is None:
                continue
            profile = parse_profile(block)
            state = {
                key: float(value)
                for key, value in row.items()
                if key not in {"id", "name", "gender", "age", "hukou", "residence"} and value
            }
            econ_security = state.get("econ_security", 0.5)
            # Per-subject stream: income must not shift when the catalog or
            # the price grid changes, only when the seed does.
            rng = random.Random(f"{seed}:income:{agent_id}")
            subjects.append(
                Subject(
                    id=agent_id,
                    name=row["name"],
                    gender=row.get("gender", ""),
                    age=int(profile["age"]),
                    residence=row.get("residence", "") or profile.get("living", ""),
                    job=profile.get("job", ""),
                    personality=profile.get("personality", ""),
                    daily_life=profile.get("daily_life", ""),
                    state=state,
                    monthly_income=_monthly_income(profile.get("job", ""), econ_security, rng),
                )
            )
    if ids is not None:
        order = {agent_id: index for index, agent_id in enumerate(ids)}
        subjects.sort(key=lambda item: order.get(item.id, len(order)))
    return subjects[:limit] if limit else subjects


def world_context(subject: Subject, product: Product, *, seed: int = 42) -> WorldContext:
    """Pre-treatment state for one ``(subject, product)`` pair.

    The RNG stream is keyed on subject and product **only**. Adding the
    treatment price to this key would reintroduce exactly the confounding
    the experiment is built to measure.
    """
    rng = random.Random(f"{seed}:ctx:{subject.id}:{product.id}")

    # What they paid last time: the regular price jittered by the ordinary
    # promo/store spread, independent of what we are about to charge them.
    last_paid = round(product.regular_price * rng.uniform(0.85, 1.10), 2)
    # The shelf next to it. Real dispersion across stores, still price-blind.
    competitor_price = round(product.competitor_price * rng.uniform(0.95, 1.05), 2)

    engel, savings_rate = _engel_params(subject.monthly_income, CONFIG.get("economy", {}))
    monthly_food_budget = round(subject.monthly_income * (1 - savings_rate) * engel, 2)

    return WorldContext(
        last_paid=last_paid,
        competitor_price=competitor_price,
        shelf_life_days=product.shelf_life_days,
        store=rng.choice(_STORES),
        monthly_food_budget=monthly_food_budget,
        budget_left_ratio=round(rng.uniform(0.15, 0.85), 3),
    )
