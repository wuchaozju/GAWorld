"""CLI: inspect the registry, refresh the feed, preview a media diet.

    python -m gaworld.infosources list [--kind news|social|professional]
    python -m gaworld.infosources refresh [--force] [--ttl-hours 6]
    python -m gaworld.infosources show <source_id> [--limit 10]
    python -m gaworld.infosources diet --job "社区医生" [--interests 跑步,理财] [--openness 1.0]
"""

from __future__ import annotations

import argparse
import sys

from gaworld.infosources import channels, diet, feed, registry
from gaworld.infosources.schema import KIND_LABELS_ZH


def _settings() -> dict:
    from gaworld.settings import CONFIG

    news_cfg = CONFIG.get("news", {}) or {}
    return dict(news_cfg.get("sources", {}) or {})


def _sources(cfg: dict):
    return registry.load_registry(cfg.get("registry_path", registry.DEFAULT_REGISTRY_PATH))


def _cmd_list(args: argparse.Namespace) -> int:
    cfg = _settings()
    sources = _sources(cfg)
    cache = feed.load(cfg.get("feed_cache_path", "output/infosources/feed.json"))
    counts = cache.counts()
    for source in sources:
        if args.kind and source.kind != args.kind:
            continue
        flag = "" if source.enabled else " (disabled)"
        print(
            f"{source.id:<22} {KIND_LABELS_ZH.get(source.kind, source.kind):<5} {source.channel:<17} "
            f"{source.lang:<3} cached={counts.get(source.id, 0):<3} {source.name}{flag}  "
            f"[{'/'.join(source.topics)}]"
        )
    print(f"\n{len(sources)} source(s); cache: {cfg.get('feed_cache_path', 'output/infosources/feed.json')}")
    return 0


def _cmd_refresh(args: argparse.Namespace) -> int:
    cfg = _settings()
    sources = _sources(cfg)
    if not sources:
        print("registry is empty", file=sys.stderr)
        return 1
    timeout = int(cfg.get("timeout", 10))
    limit = int(cfg.get("per_source_limit", feed.DEFAULT_PER_SOURCE_LIMIT))
    ttl = float(cfg.get("ttl_hours", feed.DEFAULT_TTL_HOURS))
    if args.ttl_hours is not None:
        ttl = args.ttl_hours
    before = feed.load(cfg.get("feed_cache_path", "output/infosources/feed.json")).counts()
    cache = feed.refresh(
        sources,
        cfg.get("feed_cache_path", "output/infosources/feed.json"),
        fetch_fn=lambda s: channels.fetch_source(s, timeout=timeout, limit=limit),
        ttl_hours=ttl,
        per_source_limit=limit,
        force=args.force,
    )
    after = cache.counts()
    for source in sources:
        if not source.enabled:
            continue
        print(f"{source.id:<22} {before.get(source.id, 0):>3} → {after.get(source.id, 0):<3} {source.name}")
    empty = [s.id for s in sources if s.enabled and not after.get(s.id)]
    if empty:
        print(f"\nno items for: {', '.join(empty)} (blocked on this network, dead feed, or still fresh)")
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    cfg = _settings()
    cache = feed.load(cfg.get("feed_cache_path", "output/infosources/feed.json"))
    items = cache.items_for(args.source_id)
    if not items:
        print(f"nothing cached for {args.source_id!r}; run `refresh` first", file=sys.stderr)
        return 1
    print(f"last fetch: {cache.last_fetch.get(args.source_id, '?')}")
    for item in items[: args.limit]:
        print(f"- {item.title}\n  {item.url}\n  {item.excerpt[:160]}")
    return 0


def _cmd_diet(args: argparse.Namespace) -> int:
    cfg = _settings()
    sources = _sources(cfg)
    agent = {
        "id": 0,
        "name": "预览",
        "job": args.job,
        "state": {"platform_dependence": args.platform},
        "ext": {"big_five": {"o": args.openness, "c": 0, "e": 0, "a": 0, "n": 0}},
    }
    interests = [i.strip() for i in (args.interests or "").replace("，", ",").split(",") if i.strip()]
    rows = diet.build_media_diet(agent, sources, interests=interests, config=cfg.get("diet", {}))
    print(
        f"职业：{args.job}  兴趣：{'、'.join(interests) or '—'}  "
        f"开放性 z={args.openness}  平台依赖={args.platform}"
    )
    print(f"职业域：{'/'.join(diet.profession_topics(args.job)) or '（未匹配）'}\n")
    for row in rows:
        kind = KIND_LABELS_ZH.get(row["kind"], row["kind"])
        print(f"{row['weight']:.2f}  {kind:<5} {row['name']:<22} {row['reason']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m gaworld.infosources", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    list_cmd = sub.add_parser("list", help="List registered sources")
    list_cmd.add_argument("--kind", choices=("news", "social", "professional"))
    refresh_cmd = sub.add_parser("refresh", help="Fetch stale sources into the feed cache")
    refresh_cmd.add_argument("--force", action="store_true", help="Fetch even if the cache is fresh")
    refresh_cmd.add_argument("--ttl-hours", type=float, default=None)
    show_cmd = sub.add_parser("show", help="Print cached items of one source")
    show_cmd.add_argument("source_id")
    show_cmd.add_argument("--limit", type=int, default=10)
    diet_cmd = sub.add_parser("diet", help="Preview the media diet for a job / interests")
    diet_cmd.add_argument("--job", required=True)
    diet_cmd.add_argument("--interests", default="")
    diet_cmd.add_argument("--openness", type=float, default=0.0, help="Big Five openness z score")
    diet_cmd.add_argument("--platform", type=float, default=0.5, help="platform_dependence state (0-1)")
    return parser


_COMMANDS = {"list": _cmd_list, "refresh": _cmd_refresh, "show": _cmd_show, "diet": _cmd_diet}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return _COMMANDS[args.command](args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
