# Locked RED-phase tests for the uncertainty module (TASK-2054).
#
# WHAT THIS FILE DOES: it pins down, one behaviour per test, how the
# to-be-built module `scripts/r1yesno_v2/uncertainty.py` must put error
# bars on the model-vs-human price comparison:
#   - ols_slope: the straight-line slope of "would you buy it?" answers
#     against price;
#   - collect_clusters: grouping long answer tables into one bundle per
#     (product, persona) pair without losing or mixing any row;
#   - cluster_bootstrap: re-drawing whole persona bundles with replacement
#     (the same bundles for model and human inside one draw) to get a
#     distribution of slopes and of G (model slope divided by human slope);
#   - bayesian_bootstrap: the same idea but every bundle gets a random
#     weight instead of being in-or-out;
#   - summarize: turning a distribution of draws into (point, low, high)
#     with the middle 95% bounds, ignoring broken (NaN) draws;
#   - paired_difference: subtracting two draw arrays draw-by-draw.
#
# Every test imports the module INSIDE the test function on purpose: until
# the module exists each test must FAIL with ModuleNotFoundError (the
# missing feature), never ERROR at collection time (which would mean a
# typo in this file instead).
#
# All data is made up in-file, all seeds are fixed, nothing touches the
# network or the disk.
#
# Functions in this file:
#   _uncertainty — fetch the module under test, imported at call time.
#   _line_cluster — build one bundle of (price, answer) points on a
#     perfect straight line.
#   _clusters — build a whole cluster dict: one bundle per persona, each
#     with its own slope.
#   _cluster_arrays — read (price, answer) columns back out of a bundle,
#     accepting the (n, 2) stacked shape the contract specifies.
#   _long_frame — build a long answer table (product, persona, price,
#     answer rows) for collect_clusters tests.
#   test_* — the locked tests, named so anyone can read what is checked.

import numpy as np
import pandas as pd
import pytest

PRICE_GRID = np.linspace(0.2, 2.0, 10)
INTERCEPT = 0.9


def _uncertainty():
    from scripts.r1yesno_v2 import uncertainty

    return uncertainty


def _line_cluster(slope, intercept=INTERCEPT):
    """One bundle: answers that fall exactly on the line p = intercept + slope*price."""
    p = intercept + slope * PRICE_GRID
    return np.column_stack([PRICE_GRID, p])


def _clusters(slopes, product="prod"):
    """A cluster dict keyed by (product, persona_i), one bundle per given slope."""
    return {
        (product, f"persona_{i}"): _line_cluster(slope)
        for i, slope in enumerate(slopes)
    }


def _cluster_arrays(cluster):
    """Read (price, answer) columns out of one bundle, expecting the (n, 2) stacked shape."""
    arr = np.asarray(cluster, dtype=float)
    if arr.ndim != 2 or arr.shape[1] != 2:
        pytest.fail(f"cluster is not (n, 2) stacked observations, got shape {arr.shape}")
    return arr[:, 0], arr[:, 1]


def _long_frame(products, personas, prices_per_cluster, seed=7):
    """A long table with one row per (product, persona, price); answers follow 0.9 - 0.3*price."""
    rng = np.random.default_rng(seed)
    rows = []
    for product, personas_for_product in zip(products, personas):
        for persona in personas_for_product:
            for price in prices_per_cluster:
                rows.append(
                    {
                        "product": product,
                        "persona": persona,
                        "price_scaled": price,
                        "p": 0.9 - 0.3 * price + rng.normal(0, 0.001),
                    }
                )
    return pd.DataFrame(rows)


# --- 1. ols_slope -----------------------------------------------------------


def test_ols_slope_recovers_exact_negative_slope():
    """On a perfect line p = 0.9 - 0.3*price the fitted slope is exactly -0.3."""
    uncertainty = _uncertainty()
    p = INTERCEPT - 0.3 * PRICE_GRID
    slope = uncertainty.ols_slope(PRICE_GRID, p)
    assert abs(slope - (-0.3)) < 1e-9, f"expected -0.3, got {slope}"


def test_ols_slope_noisy_data_close_to_true_slope():
    """With small seeded noise the fitted slope stays within 0.01 of -0.3."""
    uncertainty = _uncertainty()
    rng = np.random.default_rng(0)
    p = INTERCEPT - 0.3 * PRICE_GRID + rng.normal(0, 0.005, PRICE_GRID.size)
    slope = uncertainty.ols_slope(PRICE_GRID, p)
    assert abs(slope - (-0.3)) < 0.01, f"expected within 0.01 of -0.3, got {slope}"


# --- 2. collect_clusters ----------------------------------------------------


def test_collect_clusters_keeps_every_cluster_and_observation():
    """Four (product, persona) pairs of five rows each come back as four bundles of five."""
    uncertainty = _uncertainty()
    prices = [0.2, 0.4, 0.6, 0.8, 1.0]
    df = _long_frame(
        products=["prod_a", "prod_b"],
        personas=[["p1", "p2"], ["p1", "p2"]],
        prices_per_cluster=prices,
    )
    clusters = uncertainty.collect_clusters(df)
    assert set(clusters.keys()) == {
        ("prod_a", "p1"),
        ("prod_a", "p2"),
        ("prod_b", "p1"),
        ("prod_b", "p2"),
    }
    total_observations = 0
    for key, cluster in clusters.items():
        price, p = _cluster_arrays(cluster)
        total_observations += price.size
        expected = df[(df["product"] == key[0]) & (df["persona"] == key[1])]
        assert price.size == 5, f"cluster {key} should hold 5 rows, got {price.size}"
        np.testing.assert_allclose(
            np.sort(price), np.sort(expected["price_scaled"].to_numpy()),
            err_msg=f"cluster {key} prices do not match its rows",
        )
        order = np.argsort(price)
        np.testing.assert_allclose(
            np.asarray(p)[order],
            expected.sort_values("price_scaled")["p"].to_numpy(),
            err_msg=f"cluster {key} answers do not match their prices",
        )
    assert total_observations == 20, "every observation must be kept exactly once"


def test_collect_clusters_prices_stay_with_their_cluster():
    """A row's price and answer never drift into another cluster's bundle."""
    uncertainty = _uncertainty()
    df = _long_frame(
        products=["prod_a", "prod_b"],
        personas=[["only"], ["only"]],
        prices_per_cluster=[0.2, 2.0],
    )
    clusters = uncertainty.collect_clusters(df)
    price_a, _ = _cluster_arrays(clusters[("prod_a", "only")])
    price_b, _ = _cluster_arrays(clusters[("prod_b", "only")])
    np.testing.assert_allclose(np.sort(price_a), [0.2, 2.0])
    np.testing.assert_allclose(np.sort(price_b), [0.2, 2.0])


# --- 3. cluster_bootstrap mechanics -----------------------------------------


def test_bootstrap_same_seed_gives_identical_draws():
    """Two runs with the same seed produce byte-identical draw arrays."""
    uncertainty = _uncertainty()
    model = _clusters([-0.9, -0.9, -0.3, -0.3])
    human = _clusters([-0.3, -0.3, -0.3, -0.3])
    first = uncertainty.cluster_bootstrap(model, human, n_draws=25, seed=42)
    second = uncertainty.cluster_bootstrap(model, human, n_draws=25, seed=42)
    for key in ("beta_human", "beta_model", "G"):
        np.testing.assert_array_equal(
            np.asarray(first[key]), np.asarray(second[key]),
            err_msg=f"same seed must reproduce {key}",
        )


def test_bootstrap_different_seed_gives_different_draws():
    """Two runs with different seeds produce different draws."""
    uncertainty = _uncertainty()
    model = _clusters([-0.9, -0.9, -0.3, -0.3])
    human = _clusters([-0.3, -0.3, -0.3, -0.3])
    first = uncertainty.cluster_bootstrap(model, human, n_draws=25, seed=42)
    second = uncertainty.cluster_bootstrap(model, human, n_draws=25, seed=43)
    assert not np.array_equal(
        np.asarray(first["beta_model"]), np.asarray(second["beta_model"])
    ), "different seeds must give different resamples"


def test_bootstrap_G_distribution_has_spread_and_brackets_full_sample_G():
    """Mixed steep/flat clusters: G draws vary and their 95% bounds surround the full-sample G."""
    uncertainty = _uncertainty()
    model = _clusters([-0.9, -0.9, -0.3, -0.3])
    human = _clusters([-0.3, -0.3, -0.3, -0.3])
    draws = uncertainty.cluster_bootstrap(model, human, n_draws=400, seed=42)
    g_draws = np.asarray(draws["G"], dtype=float)
    assert np.nanstd(g_draws) > 0, "G draws must vary when clusters differ in slope"
    beta_model_full = uncertainty.ols_slope(
        *_cluster_arrays(np.vstack(list(model.values())))
    )
    beta_human_full = uncertainty.ols_slope(
        *_cluster_arrays(np.vstack(list(human.values())))
    )
    g_full = beta_model_full / beta_human_full
    lo, hi = np.nanpercentile(g_draws, [2.5, 97.5])
    assert lo < g_full < hi, (
        f"full-sample G {g_full} must sit inside the bootstrap "
        f"2.5/97.5 percentiles [{lo}, {hi}]"
    )


# --- 4. point estimate and G ------------------------------------------------


def test_full_sample_G_is_two_when_model_slope_is_double_human_slope():
    """Model slope -0.6 vs human slope -0.3 gives full-sample G = 2.0 exactly."""
    uncertainty = _uncertainty()
    model = _clusters([-0.9, -0.9, -0.3, -0.3])  # pooled slope = -0.6
    human = _clusters([-0.3, -0.3, -0.3, -0.3])  # pooled slope = -0.3
    draws = uncertainty.cluster_bootstrap(model, human, n_draws=400, seed=42)
    beta_model_full = uncertainty.ols_slope(
        *_cluster_arrays(np.vstack(list(model.values())))
    )
    beta_human_full = uncertainty.ols_slope(
        *_cluster_arrays(np.vstack(list(human.values())))
    )
    assert abs(beta_model_full - (-0.6)) < 1e-9
    assert abs(beta_human_full - (-0.3)) < 1e-9
    g_full = beta_model_full / beta_human_full
    assert abs(g_full - 2.0) < 1e-9, f"full-sample G should be 2.0, got {g_full}"
    point, lo, hi = uncertainty.summarize(
        np.asarray(draws["G"], dtype=float), point_estimate=2.0
    )
    assert point == pytest.approx(2.0, abs=1e-12)
    assert lo < point < hi, (
        f"summarize bounds [{lo}, {hi}] must strictly bracket the point 2.0"
    )


# --- 5. bayesian_bootstrap --------------------------------------------------


def test_bayesian_weighted_slope_draws_center_on_full_sample_slope():
    """Weighted draws of a symmetric design cluster around the full-sample slope."""
    uncertainty = _uncertainty()
    model = _clusters([-0.2, -0.4, -0.6, -0.8])  # symmetric around -0.5
    human = _clusters([-0.3, -0.3, -0.3, -0.3])
    draws = uncertainty.bayesian_bootstrap(model, human, n_draws=200, seed=43)
    beta_model = np.asarray(draws["beta_model"], dtype=float)
    beta_human = np.asarray(draws["beta_human"], dtype=float)
    assert np.std(beta_model) > 0, "weighted slope draws must vary"
    assert abs(np.median(beta_model) - (-0.5)) < 0.05, (
        f"median weighted model slope {np.median(beta_model)} must be within "
        f"0.05 of the full-sample slope -0.5"
    )
    assert abs(np.median(beta_human) - (-0.3)) < 0.05, (
        f"median weighted human slope {np.median(beta_human)} must be within "
        f"0.05 of the full-sample slope -0.3"
    )


def test_bayesian_and_cluster_bootstrap_return_arrays_of_length_n_draws():
    """Both bootstrap functions return beta_human, beta_model and G arrays of exactly n_draws."""
    uncertainty = _uncertainty()
    model = _clusters([-0.9, -0.3])
    human = _clusters([-0.3, -0.3])
    n_draws = 30
    for name, bootstrap in (
        ("cluster_bootstrap", uncertainty.cluster_bootstrap),
        ("bayesian_bootstrap", uncertainty.bayesian_bootstrap),
    ):
        draws = bootstrap(model, human, n_draws=n_draws, seed=42)
        assert set(draws.keys()) == {"beta_human", "beta_model", "G"}, (
            f"{name} must return exactly the contract keys"
        )
        for key in ("beta_human", "beta_model", "G"):
            arr = np.asarray(draws[key])
            assert isinstance(arr, np.ndarray), f"{name}.{key} must be an ndarray"
            assert arr.shape == (n_draws,), (
                f"{name}.{key} must have length {n_draws}, got {arr.shape}"
            )


# --- 6. paired_difference ---------------------------------------------------


def test_paired_difference_is_elementwise_subtraction():
    """Equal-length draw arrays subtract draw-by-draw."""
    uncertainty = _uncertainty()
    a = np.array([1.0, 2.0, 3.0])
    b = np.array([0.5, 1.5, 2.0])
    diff = uncertainty.paired_difference(a, b)
    np.testing.assert_allclose(diff, [0.5, 0.5, 1.0])


def test_paired_difference_rejects_unequal_lengths():
    """Arrays of different lengths must raise ValueError, not misalign silently."""
    uncertainty = _uncertainty()
    with pytest.raises(ValueError):
        uncertainty.paired_difference(np.array([1.0, 2.0]), np.array([1.0]))


# --- 7. NaN safety ----------------------------------------------------------


def test_flat_human_clusters_produce_nan_G_draws():
    """Draws that sample only flat human clusters (slope 0) give NaN G, others give finite G."""
    uncertainty = _uncertainty()
    model = _clusters([-0.9, -0.9, -0.3, -0.3])
    human = _clusters([-0.3, -0.3, 0.0, 0.0])  # two flat clusters
    draws = uncertainty.cluster_bootstrap(model, human, n_draws=400, seed=42)
    g_draws = np.asarray(draws["G"], dtype=float)
    assert np.isnan(g_draws).any(), "all-flat human draws must produce NaN G"
    assert not np.isnan(g_draws).all(), "mixed draws must keep finite G values"


def test_summarize_excludes_nan_and_returns_finite_percentiles():
    """summarize ignores NaN draws: with some NaNs present the bounds stay finite."""
    uncertainty = _uncertainty()
    model = _clusters([-0.9, -0.9, -0.3, -0.3])
    human = _clusters([-0.3, -0.3, 0.0, 0.0])
    draws = uncertainty.cluster_bootstrap(model, human, n_draws=400, seed=42)
    g_draws = np.asarray(draws["G"], dtype=float)
    assert np.isnan(g_draws).any(), "this design must contain NaN draws"
    point = float(np.nanmedian(g_draws))
    result = uncertainty.summarize(g_draws, point_estimate=point)
    assert len(result) == 3, "summarize must return (point, lo, hi)"
    lo, hi = float(result[1]), float(result[2])
    assert np.isfinite(lo) and np.isfinite(hi), (
        f"percentiles must be finite after dropping NaN draws, got [{lo}, {hi}]"
    )


# --- integration: collect_clusters output feeds the bootstrap ---------------


def test_collect_clusters_output_works_as_bootstrap_input():
    """Bundles built by collect_clusters can be bootstrapped directly."""
    uncertainty = _uncertainty()
    df = _long_frame(
        products=["prod", "prod", "prod", "prod"],
        personas=[["s0", "s1", "f0", "f1"], ["s0", "s1", "f0", "f1"]],
        prices_per_cluster=[0.2, 0.4, 0.6, 0.8, 1.0],
    )
    clusters = uncertainty.collect_clusters(df)
    draws = uncertainty.cluster_bootstrap(clusters, clusters, n_draws=50, seed=42)
    for key in ("beta_human", "beta_model", "G"):
        assert np.asarray(draws[key]).shape == (50,)
