"""The public introduction remains seekable through the dashboard server."""

import functools
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from gaworld.apps.public_media import INTRO_VIDEO, PublicMediaMixin


@pytest.fixture
def media_server(tmp_path):
    video = tmp_path / INTRO_VIDEO.lstrip("/")
    video.parent.mkdir(parents=True)
    video.write_bytes(b"0123456789")

    class Handler(PublicMediaMixin, SimpleHTTPRequestHandler):
        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=tmp_path))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}{INTRO_VIDEO}"
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.mark.parametrize(
    ("range_header", "expected", "content_range"),
    [
        ("bytes=2-5", b"2345", "bytes 2-5/10"),
        ("bytes=7-", b"789", "bytes 7-9/10"),
        ("bytes=-3", b"789", "bytes 7-9/10"),
    ],
)
def test_video_byte_ranges(media_server, range_header, expected, content_range):
    with urlopen(Request(media_server, headers={"Range": range_header})) as response:
        assert response.status == 206
        assert response.headers["Content-Range"] == content_range
        assert response.read() == expected


def test_video_metadata_and_full_download(media_server):
    with urlopen(Request(media_server, method="HEAD")) as response:
        assert response.headers["Accept-Ranges"] == "bytes"
        assert response.headers["Content-Length"] == "10"
        assert response.headers["Content-Type"] == "video/mp4"
        assert response.read() == b""
    with urlopen(media_server) as response:
        assert response.status == 200
        assert response.read() == b"0123456789"


def test_video_unsatisfiable_range(media_server):
    with pytest.raises(HTTPError) as error:
        urlopen(Request(media_server, headers={"Range": "bytes=10-"}))
    assert error.value.code == 416
    assert error.value.headers["Content-Range"] == "bytes */10"
