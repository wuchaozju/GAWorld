"""CLI: ``python -m gaworld.enterprise``.

Examples::

    # preview the column mapping without writing anything
    python -m gaworld.enterprise users.xlsx --dry-run

    # pack, placing residents in an existing city's districts
    python -m gaworld.enterprise users.csv -o out/agents.zip --city 绍兴柯桥

    # fix a column the mapper guessed wrong, drop another, strip free text
    python -m gaworld.enterprise users.csv --map 会员备注=personality --map 城市= --drop-free-text
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gaworld.enterprise.pack import DROPPED_FIELDS, build_package, prepare


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m gaworld.enterprise",
        description="把企业用户数据（CSV / xlsx / JSONL）匿名化并转成 GAWorld 智能体包（zip）。",
    )
    parser.add_argument("source", type=Path, help="用户数据文件")
    parser.add_argument("-o", "--output", type=Path, help="输出 zip 路径（默认 <文件名>_agents.zip）")
    parser.add_argument("--city", help="按该城市的区划分配居住地（城市 slug 或名称）")
    parser.add_argument(
        "--map",
        action="append",
        default=[],
        metavar="列名=字段",
        help="覆盖列映射；字段留空表示丢弃该列。可重复",
    )
    parser.add_argument("--salt", help="化名盐值；给定后同一文件化名可复现（默认每次随机）")
    parser.add_argument("--seed", type=int, default=0, help="补全字段所用随机种子")
    parser.add_argument("--drop-free-text", action="store_true", help="丢弃性格/日常/价值观等自由文本")
    parser.add_argument("--dry-run", action="store_true", help="只显示列映射，不生成文件")
    return parser


def _parse_overrides(items: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for item in items:
        header, sep, field = item.partition("=")
        if not sep:
            raise ValueError(f"--map 需要「列名=字段」格式：{item}")
        overrides[header.strip()] = field.strip()
    return overrides


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if not args.source.is_file():
        print(f"找不到文件：{args.source}", file=sys.stderr)
        return 2
    try:
        overrides = _parse_overrides(args.map)
        if args.dry_run:
            headers, mapping, rows = prepare(args.source, overrides)
            print(f"{len(rows)} 行，{len(headers)} 列")
            for header in headers:
                field = mapping[header]
                verdict = "丢弃" if not field or field in DROPPED_FIELDS else f"→ {field}"
                print(f"  {header:<20} {verdict}")
            return 0

        districts = None
        if args.city:
            from gaworld.city.agents import city_districts
            from gaworld.city.bundle import resolve_city

            districts = city_districts(resolve_city(args.city))
        output = args.output or args.source.with_name(f"{args.source.stem}_agents.zip")
        report = build_package(
            args.source,
            output,
            overrides=overrides,
            districts=districts,
            salt=args.salt,
            seed=args.seed,
            drop_free_text=args.drop_free_text,
            title=args.city or "企业用户",
        )
    except (ValueError, LookupError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n已生成 {report['agents']} 个智能体 → {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
