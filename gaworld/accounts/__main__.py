"""Account administration from the shell.

python -m gaworld.accounts init --admin 老师              # creates the database: accounts on
python -m gaworld.accounts invite --count 30 --label 周三班 [--can-create-city]
python -m gaworld.accounts users
python -m gaworld.accounts reset --nickname 小王          # prints a one-time reset code
python -m gaworld.accounts city-permission --nickname 小王 --allow|--deny
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
import time
from pathlib import Path

from . import AccountError, AccountStore, db_path
from .store import check_nickname, check_password

REPO_ROOT = str(Path(__file__).resolve().parents[2])


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\n")
    first = getpass.getpass("密码：")
    if getpass.getpass("再输一次：") != first:
        raise AccountError("两次输入不一致")
    return first


def _find(store: AccountStore, nickname: str) -> dict:
    for user in store.list_users():
        if user["nickname"].casefold() == nickname.strip().casefold():
            return user
    raise AccountError(f"没有昵称为「{nickname}」的用户")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m gaworld.accounts", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    init = sub.add_parser("init", help="create the account database and the first admin")
    init.add_argument("--admin", required=True, help="nickname of the first admin")
    init.add_argument("--password-stdin", action="store_true", help="read the password from stdin")
    invite = sub.add_parser("invite", help="print one-time invite codes")
    invite.add_argument("--count", type=int, default=1)
    invite.add_argument("--label", default="")
    invite.add_argument("--expires-days", type=float, default=14)
    invite.add_argument("--can-create-city", action="store_true")
    sub.add_parser("users", help="list users")
    reset = sub.add_parser("reset", help="print a one-time password reset code")
    reset.add_argument("--nickname", required=True)
    perm = sub.add_parser("city-permission", help="grant or revoke the right to create cities")
    perm.add_argument("--nickname", required=True)
    group = perm.add_mutually_exclusive_group(required=True)
    group.add_argument("--allow", action="store_true")
    group.add_argument("--deny", action="store_true")
    args = parser.parse_args(argv)

    path = db_path(REPO_ROOT)
    store = AccountStore(path)
    try:
        if args.cmd == "init":
            if os.path.exists(path) and store.list_users():
                raise AccountError(f"账号库已存在：{path}")
            nickname = check_nickname(args.admin)
            password = check_password(_read_password(args.password_stdin))
            store.init_schema()
            user = store.create_user(nickname, password, role="admin", can_create_city=True)
            store.audit(user, "init")
            print(f"已创建账号库 {path}，管理员「{user['nickname']}」。从现在起控制台需要登录。")
            return 0
        if not os.path.exists(path):
            raise AccountError("账号库不存在；先运行 python -m gaworld.accounts init --admin <昵称>")
        if args.cmd == "invite":
            codes = store.create_invites(
                args.count,
                label=args.label,
                expires_days=args.expires_days,
                can_create_city=args.can_create_city,
            )
            store.audit(None, "invite", f"cli count={len(codes)} label={args.label}")
            print("\n".join(codes))
        elif args.cmd == "users":
            for user in store.list_users():
                created = time.strftime("%Y-%m-%d", time.localtime(user["created_at"]))
                city = "可建城" if user["can_create_city"] else ""
                print(
                    f"{user['id']:>4}  {user['role']:<6}  {user['nickname']}  {user['label']}  {city}  {created}"
                )
        elif args.cmd == "reset":
            user = _find(store, args.nickname)
            store.audit(None, "reset_issue", f"cli user={user['nickname']}")
            print(store.issue_reset(user["id"]))
        elif args.cmd == "city-permission":
            user = store.set_can_create_city(_find(store, args.nickname)["id"], args.allow)
            store.audit(None, "city_permission", f"cli user={user['nickname']} allow={args.allow}")
            print(f"「{user['nickname']}」{'可以' if user['can_create_city'] else '不能'}建立城市")
    except AccountError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
