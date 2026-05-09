def register_comfyui_image_routes(app, ctx):
    base64 = ctx["base64"]
    request = ctx["request"]
    json_resp = ctx["json_resp"]
    require_csrf = ctx["require_csrf"]
    get_db = ctx["get_db"]
    get_client_ip = ctx["get_client_ip"]
    get_ua = ctx["get_ua"]
    audit = ctx["audit"]
    attach_existing_file = ctx["attach_existing_file"]
    datetime = ctx["datetime"]
    ComfyUIError = ctx["ComfyUIError"]
    _active_generation_snapshot = ctx["active_generation_snapshot"]
    _actor_or_401 = ctx["actor_or_401"]
    _actor_value = ctx["actor_value"]
    _assert_reasonable_image_size = ctx["assert_reasonable_image_size"]
    _client = ctx["client"]
    _client_for_url = ctx["client_for_url"]
    _comfyui_binding = ctx["comfyui_binding"]
    _compose_comfyui_share_content = ctx["compose_comfyui_share_content"]
    _configured_comfyui_base_dir = ctx["configured_comfyui_base_dir"]
    _configured_comfyui_project_dir = ctx["configured_comfyui_project_dir"]
    _existing_saved_image = ctx["existing_saved_image"]
    _find_or_create_comfyui_board = ctx["find_or_create_comfyui_board"]
    _generation_owner_id = ctx["generation_owner_id"]
    _image_ref_payload = ctx["image_ref_payload"]
    _interrupt_policy = ctx["interrupt_policy"]
    _is_root = ctx["is_root"]
    _json_error_from_comfy = ctx["json_error_from_comfy"]
    _load_comfyui_image_ref_record = ctx["load_comfyui_image_ref_record"]
    _normalize_comfyui_backend_url = ctx["normalize_comfyui_backend_url"]
    _safe_text = ctx["safe_text"]
    _save_fetched_image = ctx["save_fetched_image"]

    @app.route("/api/comfyui/image-preview", methods=["POST"])
    @require_csrf
    def comfyui_image_preview():
        actor, err = _actor_or_401()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok": False, "msg": "請求內容格式錯誤"}), 400
        image_ref = _image_ref_payload(data.get("image_ref"))
        if not image_ref:
            return json_resp({"ok": False, "msg": "圖片引用不合法"}), 400
        conn = get_db()
        try:
            ref_row = _load_comfyui_image_ref_record(conn, actor=actor, image_ref=image_ref)
        finally:
            conn.close()
        if not ref_row:
            return json_resp({"ok": False, "msg": "無權讀取這張 ComfyUI 圖片"}), 403
        active_client = _client_for_url(_comfyui_binding(actor, backend_url=(ref_row or {}).get("backend_url")).get("url"))
        try:
            image = active_client.fetch_image(image_ref)
            _assert_reasonable_image_size(image)
        except ComfyUIError as exc:
            return _json_error_from_comfy(exc, active_client)
        return json_resp({
            "ok": True,
            "image": {
                "image_ref": image_ref,
                "mime_type": image.mime_type,
                "size_bytes": len(image.data),
                "data_url": f"data:{image.mime_type};base64,{base64.b64encode(image.data).decode('ascii')}",
            },
        })

    @app.route("/api/comfyui/interrupt", methods=["POST"])
    @require_csrf
    def comfyui_interrupt():
        actor, err = _actor_or_401()
        if err:
            return err
        try:
            data = request.get_json(force=True, silent=True)
        except TypeError:
            data = None
        data = data if isinstance(data, dict) else {}
        allowed, reason, summary = _interrupt_policy(actor)
        if not allowed:
            audit(
                "COMFYUI_INTERRUPT_SKIPPED",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"reason={reason}, summary={summary}",
            )
            msg = "已中斷本頁等待；未送出 ComfyUI 全域中斷，避免影響其他使用者的產圖。"
            if reason == "no_owned_generation":
                msg = "目前沒有偵測到你的後端產圖任務；已中斷本頁等待。"
            return json_resp({
                "ok": True,
                "msg": msg,
                "interrupt": {
                    "interrupted": False,
                    "backend_interrupted": False,
                    "reason": reason,
                    **summary,
                },
            })
        active_client = _client(actor)
        if _is_root(actor):
            own_active = [
                item for item in _active_generation_snapshot()
                if int(item.get("user_id") or 0) == int(_generation_owner_id(actor) or 0)
            ]
            own_backends = {
                _normalize_comfyui_backend_url(item.get("backend_url"))
                for item in own_active
                if _normalize_comfyui_backend_url(item.get("backend_url"))
            }
            if len(own_backends) == 1:
                active_client = _client_for_url(next(iter(own_backends)))
        try:
            if not hasattr(active_client, "interrupt"):
                return json_resp({"ok": False, "msg": "ComfyUI 中斷產圖不支援"}), 501
            result = active_client.interrupt()
        except ComfyUIError as exc:
            audit("COMFYUI_INTERRUPT_ERROR", get_client_ip(), user=actor["username"], success=False, ua=get_ua(), detail=str(exc)[:180])
            return _json_error_from_comfy(exc, active_client)
        payload = result if isinstance(result, dict) else {}
        payload.setdefault("interrupted", True)
        payload["backend_interrupted"] = True
        payload["reason"] = reason
        payload.update(summary)
        audit("COMFYUI_INTERRUPT", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"interrupt requested, reason={reason}, summary={summary}")
        return json_resp({"ok": True, "msg": "已送出中斷產圖請求", "interrupt": payload})

    @app.route("/api/comfyui/save", methods=["POST"])
    @require_csrf
    def comfyui_save():
        actor, err = _actor_or_401()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "請求 JSON 格式錯誤"}), 400
        data = data if isinstance(data, dict) else {}
        image_ref = data.get("image_ref")
        if not isinstance(image_ref, dict):
            return json_resp({"ok": False, "msg": "缺少 image_ref"}), 400
        conn = get_db()
        try:
            ref_row = _load_comfyui_image_ref_record(conn, actor=actor, image_ref=image_ref)
            if not ref_row:
                audit("COMFYUI_IMAGE_REF_DENIED", get_client_ip(), user=actor["username"], success=False, ua=get_ua(), detail=f"action=save,file={image_ref.get('filename', '-')}")
                return json_resp({"ok": False, "msg": "找不到可存取的產圖預覽"}), 404
            active_client = _client_for_url(_comfyui_binding(actor, backend_url=ref_row.get("backend_url")).get("url"))
            try:
                image = active_client.fetch_image(image_ref)
                _assert_reasonable_image_size(image)
            except ComfyUIError as exc:
                return _json_error_from_comfy(exc, active_client)
            upload_result, storage_file, album, msg = _save_fetched_image(conn, actor=actor, data=data, image=image)
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400
            conn.commit()
            audit("COMFYUI_SAVE_TO_DRIVE", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"file_id={upload_result['file_id']}, storage_file_id={storage_file['id']}")
            return json_resp({"ok": True, "file": upload_result, "storage_file": storage_file, "album": album})
        finally:
            conn.close()

    @app.route("/api/comfyui/discard", methods=["POST"])
    @require_csrf
    def comfyui_discard():
        actor, err = _actor_or_401()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "請求 JSON 格式錯誤"}), 400
        data = data if isinstance(data, dict) else {}
        image_ref = data.get("image_ref")
        if not isinstance(image_ref, dict):
            return json_resp({"ok": False, "msg": "缺少 image_ref"}), 400
        conn = get_db()
        try:
            ref_row = _load_comfyui_image_ref_record(conn, actor=actor, image_ref=image_ref, prompt_id=data.get("prompt_id"))
            if not ref_row:
                audit("COMFYUI_IMAGE_REF_DENIED", get_client_ip(), user=actor["username"], success=False, ua=get_ua(), detail=f"action=discard,file={image_ref.get('filename', '-')}")
                return json_resp({"ok": False, "msg": "找不到可丟棄的產圖預覽"}), 404
            conn.commit()
        finally:
            conn.close()
        image_binding = _comfyui_binding(actor, backend_url=(ref_row or {}).get("backend_url"))
        if image_binding["connection_mode"] != "local":
            result = {
                "file_deleted": False,
                "file_missing": False,
                "file_delete_supported": False,
                "history_deleted": False,
                "remote_preview_only": True,
            }
            audit("COMFYUI_DISCARD_REMOTE_PREVIEW_ONLY", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"file={image_ref.get('filename')}")
            return json_resp({
                "ok": True,
                "msg": "已移除網頁上的預覽；遠端 ComfyUI API 不支援刪除 output 原始檔。",
                "discard": result,
                "warning": "source_file_not_deleted",
            })
        active_client = _client_for_url(image_binding["url"])
        try:
            if not hasattr(active_client, "discard_image"):
                return json_resp({"ok": False, "msg": "ComfyUI 原始檔刪除不支援"}), 501
            result = active_client.discard_image(
                image_ref,
                prompt_id=data.get("prompt_id"),
                local_base_dir=str(_configured_comfyui_project_dir() or _configured_comfyui_base_dir() or ""),
                allow_api_delete=False,
            )
        except ComfyUIError as exc:
            audit("COMFYUI_DISCARD_ERROR", get_client_ip(), user=actor["username"], success=False, ua=get_ua(), detail=str(exc)[:180])
            return _json_error_from_comfy(exc, active_client)
        if not (result.get("file_deleted") or result.get("file_missing")):
            msg = "已丟棄前端預覽；ComfyUI 未提供刪除 output 檔案端點，原始檔可能仍留在 ComfyUI output。若要同步刪原檔，請設定 COMFYUI_OUTPUT_DIR 或 COMFYUI_BASE_DIR。"
            audit("COMFYUI_DISCARD_UNSUPPORTED", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=str(result)[:180])
            return json_resp({"ok": True, "msg": msg, "discard": result, "warning": "source_file_not_deleted"})
        audit("COMFYUI_DISCARD", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"file={image_ref.get('filename')}, result={result}")
        return json_resp({"ok": True, "msg": "已丟棄預覽並刪除 ComfyUI 原始檔", "discard": result})

    @app.route("/api/comfyui/share", methods=["POST"])
    @require_csrf
    def comfyui_share():
        actor, err = _actor_or_401()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "請求 JSON 格式錯誤"}), 400
        data = data if isinstance(data, dict) else {}
        image_ref = data.get("image_ref")
        conn = get_db()
        try:
            existing = _existing_saved_image(conn, actor=actor, data=data)
            if existing:
                upload_result, storage_file, album, msg = existing
                if msg:
                    conn.rollback()
                    return json_resp({"ok": False, "msg": msg}), 400
            else:
                if not isinstance(image_ref, dict):
                    return json_resp({"ok": False, "msg": "缺少 image_ref"}), 400
                ref_row = _load_comfyui_image_ref_record(conn, actor=actor, image_ref=image_ref)
                if not ref_row:
                    audit("COMFYUI_IMAGE_REF_DENIED", get_client_ip(), user=actor["username"], success=False, ua=get_ua(), detail=f"action=share,file={image_ref.get('filename', '-')}")
                    conn.rollback()
                    return json_resp({"ok": False, "msg": "找不到可分享的產圖預覽"}), 404
                active_client = _client_for_url(_comfyui_binding(actor, backend_url=ref_row.get("backend_url")).get("url"))
                try:
                    image = active_client.fetch_image(image_ref)
                    _assert_reasonable_image_size(image)
                except ComfyUIError as exc:
                    return _json_error_from_comfy(exc, active_client)
                upload_result, storage_file, album, msg = _save_fetched_image(conn, actor=actor, data=data, image=image)
                if msg:
                    conn.rollback()
                    return json_resp({"ok": False, "msg": msg}), 400
            board = _find_or_create_comfyui_board(conn, actor)
            title = _safe_text(data.get("title"), 120) or "ComfyUI 產圖分享"
            content = _compose_comfyui_share_content(
                data,
                file_id=upload_result["file_id"],
                storage_file=storage_file or {},
            )
            if not content.strip():
                conn.rollback()
                return json_resp({"ok": False, "msg": "分享內容不可為空"}), 400
            level = _actor_value(actor, "effective_level") or _actor_value(actor, "base_level") or _actor_value(actor, "member_level") or "normal"
            role = _actor_value(actor, "role", "user")
            status = "pending" if role == "user" and level == "newbie" else "approved"
            now = datetime.now().isoformat()
            cur = conn.execute(
                """
                INSERT INTO forum_threads (
                    board_id, title, content, status, post_type, author_user_id,
                    author_username, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'normal', ?, ?, ?, ?)
                """,
                (board["id"], title, content, status, int(_actor_value(actor, "id")), _actor_value(actor, "username"), now, now),
            )
            thread_id = cur.lastrowid
            conn.execute("UPDATE forum_boards SET last_activity_at=?, updated_at=? WHERE id=?", (now, now, board["id"]))
            attached, msg = attach_existing_file(
                conn,
                actor=actor,
                file_id=upload_result["file_id"],
                context_type="forum_thread",
                context_id=thread_id,
                grant_role="user",
                can_preview=True,
            )
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400
            conn.commit()
            audit(
                "COMFYUI_SHARE_TO_COMMUNITY",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"thread_id={thread_id}, file_id={upload_result['file_id']}, board_id={board['id']}",
            )
            return json_resp({
                "ok": True,
                "msg": "已分享到 ComfyUI 專區" if status == "approved" else "已送出分享，待審核後公開",
                "thread": {"id": thread_id, "board_id": board["id"], "title": title, "status": status},
                "file": upload_result,
                "storage_file": storage_file,
                "album": album,
                "attachment": attached,
            })
        finally:
            conn.close()
