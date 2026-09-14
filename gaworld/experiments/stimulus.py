"""Stimuli for the demand-estimation prompt experiment: products and prices.

The design follows Gui & Toubia (2025), *The Challenge of Using LLMs to
Simulate Human Behavior* (arXiv:2312.15524): a catalog of everyday
packaged goods, each priced at 11 points from 0% to 200% of its regular
price in 20% steps. Working in *relative* price is what makes results
aggregable across products with wildly different absolute prices.

The catalog is Chinese-market (the residents GAWorld simulates shop in
Hangzhou), so absolute prices are not comparable with the paper's US
figures — the relative-price axis is the bridge.

``competitor_price`` and ``shelf_life_days`` are carried on the product
rather than invented at prompt time on purpose: they are exactly the
variables the paper shows an LLM will silently correlate with the
treatment when they are left unspecified.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

#: Repo-root-relative default catalog.
DEFAULT_CATALOG = Path(__file__).resolve().parents[2] / "data" / "experiments" / "products_cn.csv"

#: Price levels as a fraction of the regular price: 0%, 20%, ..., 200%.
RELATIVE_PRICE_GRID: tuple[float, ...] = tuple(round(step * 0.2, 2) for step in range(11))


@dataclass(frozen=True)
class Product:
    """One item in the stimulus catalog."""

    id: int
    group: str
    category: str
    name: str
    spec: str
    regular_price: float
    competitor: str
    competitor_price: float
    shelf_life_days: int

    @property
    def label(self) -> str:
        return f"{self.name}（{self.spec}）"


@dataclass(frozen=True)
class Treatment:
    """A product shown at one point on the price grid — the randomized arm."""

    product: Product
    relative_price: float

    @property
    def price(self) -> float:
        return round(self.product.regular_price * self.relative_price, 2)

    @property
    def id(self) -> str:
        return f"p{self.product.id}@{int(round(self.relative_price * 100))}"


def load_catalog(
    path: str | Path | None = None,
    *,
    groups: list[str] | None = None,
    limit: int | None = None,
) -> list[Product]:
    """Read the product catalog.

    ``groups`` filters to category families (the unit of the paper's
    leave-one-category-out design); ``limit`` truncates for smoke runs.
    """
    catalog_path = Path(path) if path else DEFAULT_CATALOG
    if not catalog_path.exists():
        raise FileNotFoundError(f"Product catalog not found: {catalog_path}")

    products: list[Product] = []
    with open(catalog_path, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if groups and row["group"] not in groups:
                continue
            products.append(
                Product(
                    id=int(row["id"]),
                    group=row["group"],
                    category=row["category"],
                    name=row["name"],
                    spec=row["spec"],
                    regular_price=float(row["regular_price"]),
                    competitor=row["competitor"],
                    competitor_price=float(row["competitor_price"]),
                    shelf_life_days=int(row["shelf_life_days"]),
                )
            )
    if not products:
        raise ValueError(f"No products matched (path={catalog_path}, groups={groups}).")
    return products[:limit] if limit else products


def price_grid(
    products: list[Product],
    grid: tuple[float, ...] = RELATIVE_PRICE_GRID,
) -> list[Treatment]:
    """Cross every product with every price level."""
    return [Treatment(product=product, relative_price=level) for product in products for level in grid]
