"""An optional URL mount, while keeping the existing root deployment working."""

from __future__ import annotations

import html
import io
import os
import re
from hashlib import sha256
from html.parser import HTMLParser
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from urllib.parse import urlsplit

COOKIES = ("gaworld_session", "gaworld_world", "gaworld_token")


def cookie_name(name: str, prefix: str) -> str:
    return f"gaworld_{sha256(prefix.encode()).hexdigest()[:12]}_{name.removeprefix('gaworld_')}"


def configured_prefix() -> str:
    value = os.environ.get("GAWORLD_URL_PREFIX", "").rstrip("/")
    if value and not re.fullmatch(r"(?:/[A-Za-z0-9_-]+)+", value):
        raise ValueError("GAWORLD_URL_PREFIX must contain only slash-separated URL path segments")
    return value


def mounted_url(value: str, prefix: str) -> str:
    if not prefix or not value.startswith("/") or value.startswith("//"):
        return value
    path = urlsplit(value).path
    if path == prefix or path.startswith(prefix + "/"):
        return value
    return prefix + value


class MountedHTML(HTMLParser):
    """Transform URL attributes only, never script text or user-visible content."""

    URL_ATTRIBUTES = frozenset({"href", "src", "action", "formaction", "poster", "data", "xlink:href"})

    def __init__(self, prefix: str):
        super().__init__(convert_charrefs=False)
        self.prefix = prefix
        self.parts: list[str] = []
        self.bootstrapped = False

    def tag(self, tag, attrs, suffix):
        mapped = []
        for key, value in attrs:
            if value and key in self.URL_ATTRIBUTES:
                value = mounted_url(value, self.prefix)
            if tag == "meta" and key == "content" and dict(attrs).get("http-equiv", "").lower() == "refresh":
                delay, separator, destination = (value or "").partition(";")
                if separator and destination.strip().lower().startswith("url="):
                    target = destination.strip()[4:].strip()
                    value = delay + ";url=" + mounted_url(target, self.prefix)
            mapped.append((key, value))
        if mapped == attrs:
            self.parts.append(self.get_starttag_text())
        else:
            attributes = "".join(
                " " + key if value is None else f' {key}="{html.escape(value, quote=True)}"'
                for key, value in mapped
            )
            self.parts.append("<" + tag + attributes + suffix)

    def handle_starttag(self, tag, attrs):
        self.tag(tag, attrs, ">")
        if tag == "head" and not self.bootstrapped:
            self.parts.append(f'<script src="{self.prefix}/site/url.js"></script>')
            self.bootstrapped = True

    def handle_startendtag(self, tag, attrs):
        self.tag(tag, attrs, "/>")

    def handle_endtag(self, tag):
        self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        self.parts.append(data)

    def handle_entityref(self, name):
        self.parts.append(f"&{name};")

    def handle_charref(self, name):
        self.parts.append(f"&#{name};")

    def handle_comment(self, data):
        self.parts.append(f"<!--{data}-->")

    def handle_decl(self, decl):
        self.parts.append(f"<!{decl}>")

    def handle_pi(self, data):
        self.parts.append(f"<?{data}>")


class SubpathMixin:
    """Normalize a configured mount before the existing auth and path guards."""

    url_prefix = ""

    def parse_request(self):
        self.url_prefix = ""
        if not super().parse_request():
            return False
        try:
            prefix = configured_prefix()
        except ValueError:
            self.send_error(503, "Invalid URL mount configuration")
            return False
        path, separator, query = self.path.partition("?")
        if prefix and path == prefix:
            self.send_response(308)
            self.send_header("Location", prefix + "/" + (separator + query if separator else ""))
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False
        if prefix and path.startswith(prefix + "/"):
            self.url_prefix = prefix
            self.path = self.path[len(prefix) :]
            # Do not let root-deployment or Mo cookies select an identity/world here.
            try:
                supplied = SimpleCookie(self.headers.get("Cookie", ""))
            except CookieError:
                supplied = SimpleCookie()
            canonical = SimpleCookie()
            for name in COOKIES:
                scoped = supplied.get(cookie_name(name, prefix))
                if scoped is not None:
                    canonical[name] = scoped.value
            if "Cookie" in self.headers:
                del self.headers["Cookie"]
            if canonical:
                self.headers["Cookie"] = canonical.output(header="", sep=";").strip()
        return True

    def send_header(self, keyword, value):
        if self.url_prefix and keyword.lower() == "location":
            value = mounted_url(value, self.url_prefix)
        elif self.url_prefix and keyword.lower() == "set-cookie":
            cookies = SimpleCookie(value)
            for name, cookie in cookies.items():
                output = SimpleCookie()
                key = cookie_name(name, self.url_prefix) if name in COOKIES else name
                output[key] = cookie.value
                for attribute, setting in cookie.items():
                    if setting:
                        output[key][attribute] = setting
                output[key]["path"] = mounted_url(cookie["path"] or "/", self.url_prefix)
                if self.headers.get("X-Forwarded-Proto", "").lower() == "https":
                    output[key]["secure"] = True
                super().send_header(keyword, output.output(header="").strip())
            if cookies:
                return None
        return super().send_header(keyword, value)

    def send_head(self):
        if self.url_prefix:
            target = Path(self.translate_path(self.path))
            if target.is_dir() and urlsplit(self.path).path.endswith("/"):
                target = next(
                    (target / name for name in ("index.html", "index.htm") if (target / name).is_file()),
                    target,
                )
            if target.is_file() and target.suffix.lower() in {".html", ".htm"}:
                parser = MountedHTML(self.url_prefix)
                parser.feed(target.read_text(encoding="utf-8-sig"))
                parser.close()
                data = "".join(parser.parts).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                return io.BytesIO(data)
        return super().send_head()
