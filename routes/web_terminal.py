import threading

from flask import request

from services.web_terminal import WebTerminalManager, ensure_web_terminal_schema


def register_web_terminal_routes(app, deps):
    get_current_user_ctx = deps["get_current_user_ctx"]
    get_db = deps["get_db"]
    json_resp = deps["json_resp"]
    require_csrf_safe = deps["require_csrf_safe"]
    verify_csrf_token = deps.get("verify_csrf_token")
    is_feature_enabled = deps.get("is_feature_enabled", lambda _key: True)
    manager = deps.get("web_terminal_manager") or WebTerminalManager(
        get_db=get_db,
        storage_root=deps["STORAGE_DIR"],
        audit=deps["audit"],
    )

    def normalize_actor(actor):
        if actor is None:
            return None
        if isinstance(actor, dict):
            return actor
        try:
            return dict(actor)
        except Exception:
            return actor

    def root_actor_or_error():
        actor = normalize_actor(get_current_user_ctx())
        if not actor:
            return None, (json_resp({"ok": False, "msg": "請先登入"}), 401)
        if actor.get("username") != "root":
            return None, (json_resp({"ok": False, "msg": "只有 root 可使用 Web Terminal"}), 403)
        return actor, None

    @app.route("/api/root/web-terminal/status", methods=["GET"])
    @require_csrf_safe
    def web_terminal_status():
        actor, err = root_actor_or_error()
        if err:
            return err
        conn = get_db()
        try:
            ensure_web_terminal_schema(conn)
            recent = conn.execute(
                """
                SELECT id, status, container_name, image, mount_path, created_at, closed_at, close_reason
                FROM web_terminal_sessions
                WHERE user_id=?
                ORDER BY created_at DESC
                LIMIT 10
                """,
                (int(actor["id"]),),
            ).fetchall()
            payload = manager.status_payload(actor, feature_enabled=is_feature_enabled("web_terminal"))
            payload["recent_sessions"] = [dict(row) for row in recent]
            return json_resp({"ok": True, "terminal": payload})
        finally:
            conn.close()

    try:
        from flask_sock import Sock
    except Exception:
        Sock = None

    if not Sock:
        return

    sock = Sock(app)

    @sock.route("/api/root/web-terminal/session")
    def web_terminal_session(ws):
        actor = normalize_actor(get_current_user_ctx())
        if not actor or actor.get("username") != "root":
            ws.send("Web Terminal requires root.\r\n")
            return
        if not is_feature_enabled("web_terminal"):
            ws.send("Web Terminal is disabled by root settings.\r\n")
            return
        token = request.args.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
        if verify_csrf_token and not verify_csrf_token(token):
            ws.send("CSRF token invalid.\r\n")
            return
        session = None
        stop_event = threading.Event()
        try:
            session = manager.create_session(actor)
            ws.send(f"Web Terminal session {session.session_id} started. Cloud Drive is mounted at /home/root.\r\n")

            def pump_output():
                while not stop_event.is_set():
                    if session.idle_expired():
                        try:
                            ws.send("\r\nSession idle timeout.\r\n")
                        except Exception:
                            pass
                        stop_event.set()
                        break
                    try:
                        data = session.read_available(timeout=0.2)
                    except OSError:
                        stop_event.set()
                        break
                    if data:
                        try:
                            ws.send(data.decode("utf-8", "ignore"))
                        except Exception:
                            stop_event.set()
                            break

            thread = threading.Thread(target=pump_output, name=f"web-terminal-output-{session.session_id}", daemon=True)
            thread.start()
            while not stop_event.is_set():
                data = ws.receive(timeout=1)
                if data is None:
                    continue
                if data == "":
                    break
                session.write(data)
            stop_event.set()
        except Exception as exc:
            try:
                ws.send(f"Web Terminal failed: {exc}\r\n")
            except Exception:
                pass
        finally:
            stop_event.set()
            if session:
                session.close("websocket_closed")
