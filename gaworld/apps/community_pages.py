"""Canonical page aliases shared by GET, HEAD and the static path guard."""

import re


def page_target(path):
    path = path.rstrip("/") or "/"
    if path in {"/register", "/verify", "/recover"}:
        return "/site/auth/index.html"
    if path == "/workspace":
        return "/site/community/workspace.html"
    if path in {"/explore", "/plaza"} or re.fullmatch(r"/(publications|people|posts)/[A-Za-z0-9_-]+", path):
        return "/site/community/index.html"
    return None
