#!/usr/bin/env python3
import argparse
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

SMOKE_ROOT_PASSWORD = "Root@1234!Smoke"
SMOKE_ADMIN_PASSWORD = "Admin@1234!Smoke"
SMOKE_USER_PASSWORD = "Test@1234!Smoke"


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

    def multipart_request(self, method, path, *, fields=None, files=None, headers=None):
        boundary = "----hackmeWebSmokeBoundary"
        chunks = []
        for key, value in (fields or {}).items():
            chunks.append(f"--{boundary}\r\n".encode("utf-8"))
            chunks.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
            chunks.append(str(value).encode("utf-8"))
            chunks.append(b"\r\n")
        for field, filename, content, mime in (files or []):
            chunks.append(f"--{boundary}\r\n".encode("utf-8"))
            chunks.append(
                f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
                f"Content-Type: {mime or 'application/octet-stream'}\r\n\r\n"
                .encode("utf-8")
            )
            chunks.append(content if isinstance(content, bytes) else bytes(content))
            chunks.append(b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
        req_headers = dict(headers or {})
        req_headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        req = urllib.request.Request(self.base_url + path, data=b"".join(chunks), headers=req_headers, method=method)
        try:
            with self.opener.open(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return {"status": resp.status, "headers": dict(resp.headers.items()), "text": raw, "json": _safe_json(raw)}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            return {"status": exc.code, "headers": dict(exc.headers.items()), "text": raw, "json": _safe_json(raw)}

    def fetch_csrf(self):
        res = self.request("GET", "/api/csrf-token")
        if res["status"] != 200 or not res["json"].get("csrf_token"):
            raise SmokeFailure(f"failed to fetch csrf token: {res['status']} {res['text'][:200]}")
        return res["json"]["csrf_token"]

    def login(self, username, password, *, rotate_to=None):
        csrf = self.fetch_csrf()
        res = self.request(
            "POST",
            "/api/login",
            body={"username": username, "password": password},
            headers={"X-CSRF-Token": csrf},
        )
        if res["status"] != 200 or not res["json"].get("ok"):
            raise SmokeFailure(f"login failed for {username}: {res['status']} {res['text'][:200]}")
        if res["json"].get("must_change_password"):
            if not rotate_to:
                raise SmokeFailure(f"{username} requires password change but no rotate_to password was provided")
            me = self.me()
            assert_status(f"{username} /api/me before password rotation", me, 200)
            csrf = self.fetch_csrf()
            changed = self.request(
                "PUT",
                f"/api/admin/users/{me['json']['id']}",
                body={"current_password": password, "password": rotate_to, "password_confirm": rotate_to},
                headers={"X-CSRF-Token": csrf},
            )
            assert_status(f"{username} forced password change", changed, 200)
            assert_json_ok(f"{username} forced password change", changed)
            self.jar.clear()
            return self.login(username, rotate_to)
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


def login_default_or_rotated(client, username, default_password, rotated_password):
    try:
        return client.login(username, rotated_password, rotate_to=rotated_password)
    except SmokeFailure:
        client.jar.clear()
        return client.login(username, default_password, rotate_to=rotated_password)


def enable_smoke_features(root_client):
    feature_updates = {
        "feature_chat_enabled": True,
        "feature_community_enabled": True,
        "feature_appeals_enabled": True,
        "feature_privacy_uploads_enabled": True,
        "feature_attachments_enabled": True,
        "feature_storage_albums_enabled": True,
        "feature_games_enabled": True,
    }
    csrf = root_client.fetch_csrf()
    res = root_client.request(
        "PUT",
        "/api/admin/features",
        body=feature_updates,
        headers={"X-CSRF-Token": csrf},
    )
    assert_status("root enable smoke feature flags", res, 200)
    assert_json_ok("root enable smoke feature flags", res)


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

    login_default_or_rotated(root, "root", "root", SMOKE_ROOT_PASSWORD)
    login_default_or_rotated(admin, "admin", "admin", SMOKE_ADMIN_PASSWORD)
    login_default_or_rotated(user, "test", "test", SMOKE_USER_PASSWORD)

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

    enable_smoke_features(root)

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
    upload = user.multipart_request(
        "POST",
        "/api/cloud-drive/upload",
        fields={"privacy_mode": "standard_plain"},
        files=[("file", "chat-smoke.txt", b"chat attachment smoke", "text/plain")],
        headers={"X-CSRF-Token": csrf},
    )
    assert_status("test upload chat attachment candidate", upload, 200)
    assert_json_ok("test upload chat attachment candidate", upload)
    chat_file_id = upload["json"]["file"]["file_id"]

    csrf = user.fetch_csrf()
    res = user.request(
        "POST",
        f"/api/chat/rooms/{room_id}/messages",
        body={"content": "smoke attachment message", "attachment_file_ids": [chat_file_id]},
        headers={"X-CSRF-Token": csrf},
    )
    assert_status("test send chat message with attachment", res, 200)
    assert_json_ok("test send chat message with attachment", res)
    attachment_message_id = res["json"]["message_id"]

    csrf = user.fetch_csrf()
    res = user.request("GET", f"/api/chat/rooms/{room_id}/messages", headers={"X-CSRF-Token": csrf})
    assert_status("test read chat messages before recall", res, 200)
    assert_json_ok("test read chat messages before recall", res)
    sent_messages = [m for m in res["json"].get("messages", []) if m.get("sender") == "test" and m.get("content") == "smoke secret message"]
    if not sent_messages:
        raise SmokeFailure("new chat message was not returned before recall")
    message_id = sent_messages[-1]["id"]
    attachment_messages = [m for m in res["json"].get("messages", []) if m.get("id") == attachment_message_id]
    if not attachment_messages or not attachment_messages[0].get("attachments"):
        raise SmokeFailure("chat attachment message did not return attachment metadata")

    csrf = user.fetch_csrf()
    res = user.request("DELETE", f"/api/chat/messages/{message_id}", headers={"X-CSRF-Token": csrf})
    assert_status("test recall chat message", res, 200)
    assert_json_ok("test recall chat message", res)

    csrf = user.fetch_csrf()
    res = user.request(
        "POST",
        f"/api/chat/rooms/{room_id}/messages",
        body={"message_type": "sticker", "sticker_key": "smile"},
        headers={"X-CSRF-Token": csrf},
    )
    assert_status("test send chat sticker", res, 200)
    assert_json_ok("test send chat sticker", res)

    csrf = user.fetch_csrf()
    res = user.request(
        "POST",
        "/api/chat/friends/requests",
        body={"username": "admin"},
        headers={"X-CSRF-Token": csrf},
    )
    assert_status("test send friend request", res, 200)
    assert_json_ok("test send friend request", res)

    csrf = admin.fetch_csrf()
    res = admin.request("GET", "/api/chat/friends", headers={"X-CSRF-Token": csrf})
    assert_status("admin read friend requests", res, 200)
    assert_json_ok("admin read friend requests", res)
    incoming = res["json"].get("incoming", [])
    if incoming:
        request_id = incoming[0]["id"]
        csrf = admin.fetch_csrf()
        res = admin.request("POST", f"/api/chat/friends/requests/{request_id}/accept", headers={"X-CSRF-Token": csrf})
        assert_status("admin accept friend request", res, 200)
        assert_json_ok("admin accept friend request", res)

    csrf = user.fetch_csrf()
    res = user.request("GET", "/api/games/catalog", headers={"X-CSRF-Token": csrf})
    assert_status("test /api/games/catalog", res, 200)
    assert_json_ok("test /api/games/catalog", res)

    csrf = user.fetch_csrf()
    res = user.request("POST", "/api/games/chess/practice", body={}, headers={"X-CSRF-Token": csrf})
    assert_status("test create chess practice", res, 200)
    assert_json_ok("test create chess practice", res)
    chess_match_id = res["json"]["match_id"]

    csrf = user.fetch_csrf()
    res = user.request(
        "POST",
        f"/api/games/chess/matches/{chess_match_id}/move",
        body={"from": "e2", "to": "e4"},
        headers={"X-CSRF-Token": csrf},
    )
    assert_status("test chess legal move", res, 200)
    assert_json_ok("test chess legal move", res)
    if res["json"].get("match", {}).get("board", {}).get("e4") != "P":
        raise SmokeFailure("chess practice move did not update the board")

    csrf = user.fetch_csrf()
    res = user.request("GET", "/api/games/chess/leaderboard", headers={"X-CSRF-Token": csrf})
    assert_status("test chess leaderboard", res, 200)
    assert_json_ok("test chess leaderboard", res)

    csrf = admin.fetch_csrf()
    res = admin.request("GET", "/api/community/boards", headers={"X-CSRF-Token": csrf})
    assert_status("admin read community boards", res, 200)
    assert_json_ok("admin read community boards", res)
    boards = res["json"].get("boards", [])
    if boards:
        board_id = boards[0]["id"]
        csrf = admin.fetch_csrf()
        res = admin.request(
            "POST",
            f"/api/community/boards/{board_id}/threads",
            body={"title": "smoke pinned topic", "content": "smoke topic body"},
            headers={"X-CSRF-Token": csrf},
        )
        assert_status("admin create smoke community thread", res, 200)
        assert_json_ok("admin create smoke community thread", res)
        csrf = admin.fetch_csrf()
        res = admin.request(
            "GET",
            f"/api/community/boards/{board_id}/threads?q=smoke%20pinned%20topic",
            headers={"X-CSRF-Token": csrf},
        )
        assert_status("admin find smoke community thread", res, 200)
        assert_json_ok("admin find smoke community thread", res)
        threads = res["json"].get("threads", [])
        if not threads:
            raise SmokeFailure("created community smoke thread was not listed")
        thread_id = threads[0]["id"]
        csrf = admin.fetch_csrf()
        res = admin.request(
            "POST",
            f"/api/community/threads/{thread_id}/sticky",
            body={"sticky": True},
            headers={"X-CSRF-Token": csrf},
        )
        assert_status("admin sticky smoke community thread", res, 200)
        assert_json_ok("admin sticky smoke community thread", res)
        csrf = admin.fetch_csrf()
        res = admin.request("GET", f"/api/community/threads/{thread_id}", headers={"X-CSRF-Token": csrf})
        assert_status("admin read sticky smoke community thread", res, 200)
        assert_json_ok("admin read sticky smoke community thread", res)
        if not res["json"].get("thread", {}).get("is_sticky"):
            raise SmokeFailure("community thread sticky flag was not persisted")

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
    login_default_or_rotated(admin, "admin", "admin", SMOKE_ADMIN_PASSWORD)
    login_default_or_rotated(user, "test", "test", SMOKE_USER_PASSWORD)

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

    user.login("test", SMOKE_USER_PASSWORD)
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
