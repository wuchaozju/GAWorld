"""``python -m gaworld.cluster join <hub> --token <token>``: run part of a distributed world here."""

from __future__ import annotations

import argparse
import os
import sys

from gaworld.cluster.node import NodeRunner


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m gaworld.cluster", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    join = sub.add_parser("join", help="作为节点加入一个分布式世界，运行分给本机的居民")
    join.add_argument("hub", help="枢纽地址，例如 https://gaworld.example.edu 或 http://192.168.1.10:8766")
    join.add_argument(
        "--token",
        default=os.environ.get("GAWORLD_NODE_TOKEN", ""),
        help="世界属主在「管理世界 → 分布式节点」里拿到的令牌（也可用环境变量 GAWORLD_NODE_TOKEN）",
    )
    args = parser.parse_args(argv)
    if args.token.count(".") < 2:
        parser.error("需要 --token（形如 w1a2b3c4d.n1.xxxx）")
    return NodeRunner(args.hub, args.token).run()


if __name__ == "__main__":
    sys.exit(main())
