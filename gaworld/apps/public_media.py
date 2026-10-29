"""Byte-range delivery for the public homepage film, after normal access checks."""

from __future__ import annotations

import io
import os
import re
from urllib.parse import unquote, urlsplit

INTRO_VIDEO = "/site/home/media/gaworld-intro-zh-music.mp4"


class _RangeFile(io.FileIO):
    remaining: int

    def read(self, size: int = -1) -> bytes:
        size = self.remaining if size < 0 else min(size, self.remaining)
        data = super().read(size)
        self.remaining -= len(data)
        return data


class PublicMediaMixin:
    """Keep inherited GET/HEAD behavior while bounding video response bodies."""

    def send_head(self):
        if unquote(urlsplit(self.path).path) != INTRO_VIDEO:
            return super().send_head()
        try:
            stream = _RangeFile(self.translate_path(self.path), "r")
        except OSError:
            self.send_error(404, "Video not found")
            return None
        stat = os.fstat(stream.fileno())
        total = stat.st_size
        start, end = 0, total - 1
        requested = self.headers.get("Range") if self.command == "GET" else None
        if requested:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested.strip())
            try:
                if not match or not any(match.groups()):
                    raise ValueError("Invalid range")
                first, last = match.groups()
                if first:
                    start = int(first)
                    end = min(int(last), total - 1) if last else total - 1
                else:
                    length = int(last)
                    if length <= 0:
                        raise ValueError("Empty suffix")
                    start = max(0, total - length)
                if start > end or start >= total:
                    raise ValueError("Unsatisfiable range")
            except ValueError:
                stream.close()
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{total}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
        stream.seek(start)
        stream.remaining = max(0, end - start + 1)
        self.send_response(206 if requested else 200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(stream.remaining))
        self.send_header("Last-Modified", self.date_time_string(stat.st_mtime))
        if requested:
            self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
        self.end_headers()
        return stream
