"""Root and mounted deployments share code/data, never cookies or route prefixes."""

import http.client
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

from gaworld.apps import dashboard_server
from gaworld.apps.subpath import MountedHTML, configured_prefix, cookie_name
from tests import test_accounts as support


@pytest.fixture
def host(monkeypatch, request):
    monkeypatch.setenv("GAWORLD_URL_PREFIX", "/GAWorld")
    server = support.HttpTest()
    server.setUp()
    request.addfinalizer(server.tearDown)
    server.store = support._store(server.tmp.name)
    server.store.create_user("alice", support.PASSWORD, role="admin")
    server.store.create_user("bob", support.PASSWORD)
    return server


def login(host, nickname, prefix="", headers=None):
    response, data = host._req(
        "POST",
        prefix + "/api/auth/login",
        {"nickname": nickname, "password": support.PASSWORD},
        headers=headers,
    )
    assert response.status == 200, data
    return response.getheader("Set-Cookie")


def html_request(host, path, method="GET"):
    connection = http.client.HTTPConnection("127.0.0.1", host.port, timeout=10)
    connection.request(method, path)
    response = connection.getresponse()
    body = response.read()
    connection.close()
    return response, body


def test_health_private_routes_and_redirects_use_mount(host):
    for prefix in ("", "/GAWorld"):
        response, health = host._req("GET", prefix + "/api/health")
        assert response.status == 200 and health["accounts"]
        assert host._req("GET", prefix + "/api/config")[0].status == 401
    response, _ = host._req("GET", "/GAWorld?next=research")
    assert response.status == 308
    assert response.getheader("Location") == "/GAWorld/?next=research"
    response, _ = host._req("GET", "/GAWorld/console?tab=research")
    assert response.status == 303
    target = urlsplit(response.getheader("Location"))
    assert target.path == "/GAWorld/login"
    assert parse_qs(target.query)["next"] == ["/console?tab=research"]
    assert host._req("GET", "/gaworld/api/health")[0].status != 200


def test_sessions_are_scoped_and_root_login_is_not_changed(host):
    root = login(host, "alice")
    mounted = login(host, "bob", "/GAWorld", {"X-Forwarded-Proto": "https"})
    key = cookie_name("gaworld_session", "/GAWorld")
    cookie = SimpleCookie(mounted)[key]
    assert cookie["path"] == "/GAWorld/"
    assert cookie["httponly"] and cookie["secure"] and cookie["samesite"] == "Strict"
    assert "gaworld_session=" in root and "Path=/;" in root
    root_pair, mount_pair = root.split(";", 1)[0], mounted.split(";", 1)[0]
    mixed = root_pair + "; " + mount_pair
    assert host._req("GET", "/api/auth/me", cookie=mixed)[1]["user"]["nickname"] == "alice"
    assert host._req("GET", "/GAWorld/api/auth/me", cookie=mixed)[1]["user"]["nickname"] == "bob"
    assert host._req("GET", "/GAWorld/api/auth/me", cookie=root_pair)[1]["user"] is None
    assert host._req("GET", "/api/auth/me", cookie=mount_pair)[1]["user"] is None
    response, _ = host._req("POST", "/GAWorld/api/auth/logout", {}, cookie=mixed)
    cleared = SimpleCookie(response.getheader("Set-Cookie"))[key]
    assert cleared["max-age"] == "0" and cleared["path"] == "/GAWorld/"
    assert host._req("GET", "/api/auth/me", cookie=root_pair)[1]["user"]["nickname"] == "alice"


def test_html_bootstrap_and_assets_are_prefixed_but_root_is_unchanged(host):
    response, body = html_request(host, "/GAWorld/login")
    assert response.status == 200
    text = body.decode()
    assert '<script src="/GAWorld/site/url.js"></script>' in text
    assert 'src="/GAWorld/site/auth/auth.js"' in text
    assert text.index("/GAWorld/site/url.js") < text.index("/GAWorld/site/auth/auth.js")
    head, empty = html_request(host, "/GAWorld/login", "HEAD")
    assert head.status == 200 and not empty
    assert int(head.getheader("Content-Length")) == len(body)
    assert "/GAWorld/" not in html_request(host, "/login")[1].decode()
    assert host._req("GET", "/GAWorld/site/url.js")[0].status == 200
    assert host._req("GET", "/site/url.js")[0].status == 200


def test_mount_does_not_bypass_security_guards(host):
    cookie = login(host, "bob", "/GAWorld").split(";", 1)[0]
    for path in (
        "/.git/config",
        "/dashboard_config.json",
        "/site/auth/../../dashboard_config.json",
        "/output/worlds/wffffffff/config.json",
    ):
        assert host._req("GET", "/GAWorld" + path, cookie=cookie)[0].status in (401, 403, 404)
    assert host._req("GET", "/GAWorld/api/auth/users", cookie=cookie)[0].status == 403
    assert (
        host._req(
            "POST",
            "/GAWorld/api/community/posts",
            {},
            cookie=cookie,
            headers={"Origin": "https://foreign.test"},
        )[0].status
        == 403
    )
    assert (
        host._req(
            "POST",
            "/GAWorld/api/research/analyze",
            {},
            cookie=cookie,
            headers={"X-GAWorld-World": "wffffffff"},
        )[0].status
        == 409
    )
    response, _ = host._req("GET", "/console", headers={"X-Forwarded-Prefix": "/untrusted"})
    assert response.getheader("Location").startswith("/login?")


def test_board_form_fallback_redirects_to_mounted_board(host, monkeypatch):
    monkeypatch.setattr(dashboard_server, "TODO_BOARD_PATH", host.tmp.name + "/todos.json")
    cookie = login(host, "bob", "/GAWorld").split(";", 1)[0]
    connection = http.client.HTTPConnection("127.0.0.1", host.port, timeout=10)
    connection.request(
        "POST",
        "/GAWorld/api/todos/create-form",
        body=urlencode({"title": "Mounted form", "proposer": "bob", "details": "Test only"}),
        headers={"Cookie": cookie, "Content-Type": "application/x-www-form-urlencoded"},
    )
    response = connection.getresponse()
    response.read()
    connection.close()
    assert response.status == 303
    assert response.getheader("Location") == "/GAWorld/board"
    assert host._req("GET", "/GAWorld/api/todos", cookie=cookie)[1]["items"][0]["title"] == "Mounted form"


def test_world_selection_cookies_do_not_cross_mounts(host):
    root = login(host, "alice").split(";", 1)[0]
    mounted = login(host, "bob", "/GAWorld").split(";", 1)[0]
    alice = host._req("GET", "/api/auth/me", cookie=root)[1]["user"]
    bob = host._req("GET", "/GAWorld/api/auth/me", cookie=mounted)[1]["user"]
    root_world = host.store.create_world(alice["id"], "Root world")
    mount_world = host.store.create_world(bob["id"], "Mounted world")
    response, _ = host._req("POST", "/api/worlds/select", {"id": root_world["id"]}, cookie=root)
    assert response.status == 200
    root_selection = response.getheader("Set-Cookie").split(";", 1)[0]
    response, _ = host._req("POST", "/GAWorld/api/worlds/select", {"id": mount_world["id"]}, cookie=mounted)
    assert response.status == 200
    selected = SimpleCookie(response.getheader("Set-Cookie"))[cookie_name("gaworld_world", "/GAWorld")]
    assert selected["path"] == "/GAWorld/"
    mixed = "; ".join([root, mounted, root_selection, selected.OutputString().split(";", 1)[0]])
    assert host._req("GET", "/api/worlds", cookie=mixed)[1]["current"]["id"] == root_world["id"]
    assert host._req("GET", "/GAWorld/api/worlds", cookie=mixed)[1]["current"]["id"] == mount_world["id"]
    assert (
        host._req("POST", "/GAWorld/api/worlds/select", {"id": root_world["id"]}, cookie=mixed)[0].status
        == 404
    )


@pytest.mark.parametrize("value", ["GAWorld", "//host", "/GAWorld/../outside", "/x?y", "/x\\y", "/x\ny"])
def test_invalid_prefixes_fail_closed(monkeypatch, value):
    monkeypatch.setenv("GAWORLD_URL_PREFIX", value)
    with pytest.raises(ValueError):
        configured_prefix()


def test_html_only_changes_url_attributes_not_data_or_scripts():
    parser = MountedHTML("/GAWorld")
    parser.feed(
        '<html><head></head><body><a href="/login?x=1&amp;y=2">/api/config</a><script>fetch("/api/config")</script></body></html>'
    )
    result = "".join(parser.parts)
    assert 'href="/GAWorld/login?x=1&amp;y=2"' in result
    assert ">/api/config</a>" in result
    assert 'fetch("/api/config")' in result
