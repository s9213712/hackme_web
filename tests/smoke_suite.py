#!/usr/bin/env python3
import argparse
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar


class SmokeFailure(RuntimeError):
    pass


class Client:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")
        self.jar = CookieJar()
        self.ctx = ssl._create_unverified_context()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=self.ctx),
            urllib.request.HTTPCookieProcessor(self.jar),
        )

    def request(self, method, path, *, body=None, headers=None):
        url = self.base_url + path
        req_headers = dict(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
        try:
            with self.opener.open(req, timeout=10) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return {
                    "status": resp.status,
                    "headers": dict(resp.headers.items()),
                    "text": raw,
                    "json": _safe_json(raw),
                }
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            return {
                "status": exc.code,
                "headers": dict(exc.headers.items()),
                "text": raw,
                "json": _safe_json(raw),
            }

    def fetch_csrf(self):
        res = self.request("GET", "/api/csrf-token")
        if res["status"] != 200 or not res["json"].get("csrf_token"):
            raise SmokeFailure(f"failed to fetch csrf token: {res['status']} {res['text'][:200]}")
        return res["json"]["csrf_token"]

    def login(self, username, password):
        csrf = self.fetch_csrf()
        res = self.request(
            "POST",
            "/api/login",
            body={"username": username, "password": password},
            headers={"X-CSRF-Token": csrf},
        )
        if res["status"] != 200 or not res["json"].get("ok"):
            raise SmokeFailure(f"login failed for {username}: {res['status']} {res['text'][:200]}")
        return res

    def me(self):
        return self.request("GET", "/api/me")


def _safe_json(text):
    try:
        return json.loads(text)
    except Exception:
        return {}


def assert_status(label, response, expected):
    if response["status"] != expected:
        raise SmokeFailure(f"{label}: expected HTTP {expected}, got {response['status']} body={response['text'][:240]}")


def assert_json_ok(label, response):
    if not response["json"].get("ok"):
        raise SmokeFailure(f"{label}: expected ok=true body={response['text'][:240]}")


def run_functional_suite(base_url):
    probe = Client(base_url)
    root = Client(base_url)
    admin = Client(base_url)
    user = Client(base_url)

    csrf = probe.fetch_csrf()
    register = probe.request(
        "POST",
        "/api/register",
        body={
            "username": "smokeprobe",
            "password": "Smoke@123",
            "password_confirm": "Smoke@123",
            "nickname": "smoke-nick",
            "real_name": "Smoke Probe",
            "id_number": "A123456789",
            "birthdate": "2000-01-02",
            "phone": "+886912345678",
            "csrf_token": csrf,
        },
    )
    assert_status("register smokeprobe", register, 200)
    assert_json_ok("register smokeprobe", register)

    root.login("root", "root")
    admin.login("admin", "admin")
    user.login("test", "test")

    root_me = root.me()
    assert_status("root /api/me", root_me, 200)
    if root_me["json"].get("role") != "super_admin":
        raise SmokeFailure(f"root role mismatch: {root_me['json']}")

    admin_me = admin.me()
    assert_status("admin /api/me", admin_me, 200)
    if admin_me["json"].get("role") != "manager":
        raise SmokeFailure(f"admin role mismatch: {admin_me['json']}")

    user_me = user.me()
    assert_status("test /api/me", user_me, 200)
    if user_me["json"].get("role") != "user":
        raise SmokeFailure(f"test role mismatch: {user_me['json']}")

    csrf = user.fetch_csrf()
    res = user.request("GET", "/api/admin/users", headers={"X-CSRF-Token": csrf})
    assert_status("test forbidden /api/admin/users", res, 403)

    csrf = admin.fetch_csrf()
    res = admin.request("GET", "/api/admin/users", headers={"X-CSRF-Token": csrf})
    assert_status("admin /api/admin/users", res, 200)
    assert_json_ok("admin /api/admin/users", res)
    usernames = {item.get("username") for item in res["json"].get("users", [])}
    for expected in ("root", "admin", "test"):
        if expected not in usernames:
            raise SmokeFailure(f"missing seeded account {expected} in admin users list")

    csrf = user.fetch_csrf()
    res = user.request("GET", "/api/chat/rooms", headers={"X-CSRF-Token": csrf})
    assert_status("test /api/chat/rooms", res, 200)
    assert_json_ok("test /api/chat/rooms", res)

    csrf = user.fetch_csrf()
    res = user.request(
        "POST",
        "/api/chat/rooms",
        body={"name": "smoke-room", "target_user": "admin"},
        headers={"X-CSRF-Token": csrf},
    )
    assert_status("test create chat room", res, 200)
    assert_json_ok("test create chat room", res)
    room_id = res["json"]["room"]["id"]

    csrf = user.fetch_csrf()
    res = user.request(
        "POST",
        f"/api/chat/rooms/{room_id}/messages",
        body={"content": "smoke secret message"},
        headers={"X-CSRF-Token": csrf},
    )
    assert_status("test send chat message", res, 200)
    assert_json_ok("test send chat message", res)

    csrf = user.fetch_csrf()
    res = user.request("GET", "/api/appeals", headers={"X-CSRF-Token": csrf})
    assert_status("test /api/appeals", res, 200)
    assert_json_ok("test /api/appeals", res)

    print("[functional] all checks passed")


def run_security_suite(base_url):
    anon = Client(base_url)
    no_csrf = anon.request("POST", "/api/login", body={"username": "root", "password": "root"})
    assert_status("login without csrf", no_csrf, 403)

    invalid_public = anon.request(
        "POST",
        "/api/login",
        body={"username": "root", "password": "root"},
        headers={"X-CSRF-Token": "invalid-token"},
    )
    assert_status("login invalid csrf", invalid_public, 403)

    admin = Client(base_url)
    user = Client(base_url)
    admin.login("admin", "admin")
    user.login("test", "test")

    invalid_auth = user.request("POST", "/api/logout", headers={"X-CSRF-Token": "invalid-token"})
    assert_status("logout invalid csrf", invalid_auth, 403)

    admin_csrf = admin.fetch_csrf()
    cross = user.request("POST", "/api/logout", headers={"X-CSRF-Token": admin_csrf})
    assert_status("logout cross-session csrf", cross, 403)

    still_logged_in = user.me()
    assert_status("user still logged in after cross-session csrf", still_logged_in, 200)

    valid_user_csrf = user.fetch_csrf()
    good_logout = user.request("POST", "/api/logout", headers={"X-CSRF-Token": valid_user_csrf})
    assert_status("valid logout", good_logout, 200)
    assert_json_ok("valid logout", good_logout)

    post_logout = user.me()
    assert_status("/api/me after logout", post_logout, 401)

    user.login("test", "test")
    no_csrf_chat = user.request("POST", "/api/chat/rooms", body={"name": "deny-room"})
    assert_status("chat create without csrf", no_csrf_chat, 403)

    print("[security] all checks passed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--suite", choices=["all", "functional", "security"], default="all")
    args = parser.parse_args()

    try:
        if args.suite in {"all", "functional"}:
            run_functional_suite(args.base_url)
        if args.suite in {"all", "security"}:
            run_security_suite(args.base_url)
    except SmokeFailure as exc:
        print(f"SMOKE FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)

    print("smoke suite passed")


if __name__ == "__main__":
    main()
