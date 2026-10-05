"""Comparability epochs: which runs may be compared with which.

Several changes made every earlier run incomparable with every later one —
the currency overhaul, the personality corpus rewrite, anchoring income on the
profile, the vehicle-ownership ladder. Each said so in its proposal or the
changelog, and nothing else: a run carried no mark of which side of those
changes it was on, so nothing could stop an analysis from pooling or
differencing runs across them. The AAAI-27 audit names exactly this as a risk
("code, prompt/provider, population and baseline lineage were not saved
together").

An *epoch* is the span between two such changes. Every run, compare-event
directory and parallel-worlds experiment is stamped with the epoch of the code
that produced it, and the places that combine runs refuse to combine across
epochs:

* parallel-worlds replicate pooling skips seeds from another epoch;
* the research evaluator will not call a hypothesis supported or
  contradicted from seeds of different epochs;
* GAWorld-Bench Track C will not give an OK trust gate to comparisons that
  are not from the current epoch.

**When to add an epoch.** When a change alters what a run with *default
configuration* produces, in a way that makes earlier runs incomparable. An
opt-in switch that defaults off (travel, endogenous congestion) is not one:
the config snapshot in the run manifest already tells such runs apart.
Append an :class:`Epoch` to :data:`EPOCHS`; never renumber or edit old ones.

This module is a stdlib-only leaf so the benchmark harness can load it by
path without importing the simulator.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Epoch:
    number: int
    since: str          # ISO date the change landed
    change: str         # what changed, in one line
    affects: tuple[str, ...]  # which quantities moved
    source: str         # where the change is written up


#: Epoch 0 is everything before the first entry.
EPOCHS: tuple[Epoch, ...] = (
    Epoch(1, "2026-06-18",
          "经济子系统的 hook 注册在失效的模块名下——此前经济模块在仿真里根本没有运行",
          ("economy", "econ_security", "stress"),
          "memory: gaworld-economy-hooks-disabled; tests/test_extension_hooks_resolve.py"),
    Epoch(2, "2026-07-04",
          "货币系统改造：守恒闭环、税与社保真实代扣、现金约束与信贷",
          ("economy",),
          "docs/proposals/2026-07-04-currency-system-panel.md"),
    Epoch(3, "2026-08-21",
          "大五人格插件默认开（含情绪个人基线锚 D6）+ 人格语料重写",
          ("personality", "emotion"),
          "docs/proposals/2026-08-21-personality-corpus-rewrite.md"),
    Epoch(4, "2026-09-19",
          "收入以 profile 声称值为锚（economy.use_profile_income 默认开）",
          ("economy",),
          "docs/proposals/2026-09-19-income-two-sources.md"),
    Epoch(5, "2026-09-25",
          "出行方式阶梯接入拥车与两轮车拥有权（无两轮车者不再一律判 e-bike）",
          ("transport", "commute"),
          "docs/proposals/2026-09-19-endogenous-road-congestion.md §14"),
    Epoch(6, "2026-10-03",
          "信息食谱：「社区医生 / 社区卫生服务」不再被当作社区工作者——综合新闻不再算作他们的本行，专业源排回前面",
          ("infosources",),
          "gaworld/infosources/diet.py PROFESSION_TOPICS; tests/test_infosources.py::TestMediaDiet"),
    Epoch(7, "2026-10-03",
          "加薪 / 裁员概率按月解释（此前按天抽：默认周期一年后中位工资落到最低工资）",
          ("economy", "income", "wealth"),
          "docs/proposals/2026-10-03-monthly-shock-probabilities.md"),
    Epoch(8, "2026-10-03",
          "随机裁员 30–90 天后工资回到裁员前的 85–100%（此前砍掉的 50–85% 是永久的）",
          ("economy", "income", "wealth"),
          "docs/proposals/2026-10-03-layoff-recovery.md"),
    Epoch(9, "2026-10-03",
          "家庭插件（默认开）的周末判断改按仿真日历（此前一律当第 1 天是周一）",
          ("family", "perception"),
          "docs/proposals/2026-10-03-travel-leave-and-cost.md §2.1"),
)

#: The epoch of the code that is running now.
CURRENT_EPOCH: int = EPOCHS[-1].number if EPOCHS else 0


def describe(epoch: int | None) -> str:
    """One line for reports: what the epoch is, or that it is unknown."""
    if epoch is None:
        return "未标版本（在可比性版本标记之前产生）"
    for item in EPOCHS:
        if item.number == epoch:
            return f"版本 {epoch}（{item.since} 起：{item.change}）"
    if epoch == 0:
        return f"版本 0（{EPOCHS[0].since} 之前）" if EPOCHS else "版本 0"
    return f"版本 {epoch}（本代码不认识，可能来自更新的代码）"


def same_epoch(epochs) -> bool:
    """True when every value is the same epoch. ``None`` (unstamped) only
    matches ``None``: an unstamped run can be from any epoch."""
    values = set(epochs)
    return len(values) <= 1


__all__ = ["CURRENT_EPOCH", "EPOCHS", "Epoch", "describe", "same_epoch"]
