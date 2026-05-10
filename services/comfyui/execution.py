"""Prompt queue, progress, and image generation orchestration helpers."""

import json
import inspect
import time
import urllib.parse
import uuid


QUEUE_TIMEOUT_EXTENSION_SECONDS = 1800
QUEUE_MAX_TIMEOUT_SECONDS = 21600


def queue_prompt_with_client_id(client, workflow, *, client_id=None, extra_data=None, error_cls):
    client_id = str(client_id or uuid.uuid4().hex)
    payload = {"prompt": workflow, "client_id": client_id}
    if isinstance(extra_data, dict) and extra_data:
        payload["extra_data"] = dict(extra_data)
    data = client._json_request("/prompt", method="POST", payload=payload)
    prompt_id = data.get("prompt_id") if isinstance(data, dict) else None
    if not prompt_id:
        raise error_cls("ComfyUI 未回傳 prompt_id")
    return {"prompt_id": str(prompt_id), "client_id": client_id}


def queue_prompt(client, workflow, *, extra_data=None, error_cls):
    return queue_prompt_with_client_id(client, workflow, client_id=None, extra_data=extra_data, error_cls=error_cls)["prompt_id"]


def interrupt(client):
    return client._json_request("/interrupt", method="POST", payload={}, allow_non_json=True)


def emit_progress(progress_callback, snapshot):
    if not progress_callback:
        return
    progress_callback(dict(snapshot))


def _queued_deadline(now, *, start_time, deadline, extension_seconds=None, max_seconds=None):
    extension_seconds = QUEUE_TIMEOUT_EXTENSION_SECONDS if extension_seconds is None else extension_seconds
    max_seconds = QUEUE_MAX_TIMEOUT_SECONDS if max_seconds is None else max_seconds
    extension_seconds = max(int(extension_seconds or 0), 0)
    refresh_window = max(5, min(60, extension_seconds // 10 if extension_seconds else 5))
    if deadline - now > refresh_window:
        return deadline, False
    max_deadline = start_time + max(int(max_seconds or 0), 0)
    if max_deadline <= start_time:
        return deadline, False
    extended = min(max_deadline, now + extension_seconds)
    new_deadline = max(deadline, extended)
    return new_deadline, new_deadline > deadline


def apply_ws_message_to_progress(snapshot, message, prompt_id):
    if not isinstance(message, dict):
        return False
    msg_type = str(message.get("type") or "")
    data = message.get("data") if isinstance(message.get("data"), dict) else {}
    if data.get("prompt_id") and str(data.get("prompt_id")) != str(prompt_id):
        return False
    updated = False
    snapshot["last_event"] = msg_type
    snapshot["updated_at"] = time.time()
    if msg_type == "status":
        exec_info = data.get("status") if isinstance(data.get("status"), dict) else data.get("exec_info")
        if isinstance(exec_info, dict):
            queue_remaining = exec_info.get("queue_remaining")
            if queue_remaining is not None:
                snapshot["queue_remaining"] = int(queue_remaining)
                updated = True
    elif msg_type == "executing":
        snapshot["phase"] = "running"
        snapshot["current_node"] = data.get("node")
        updated = True
    elif msg_type == "execution_cached":
        snapshot["phase"] = "running"
        nodes = data.get("nodes") if isinstance(data.get("nodes"), list) else []
        snapshot["detail"] = f"使用快取節點 {len(nodes)} 個"
        updated = True
    elif msg_type == "progress":
        value = data.get("value")
        maximum = data.get("max")
        if isinstance(value, (int, float)) and isinstance(maximum, (int, float)) and maximum:
            snapshot["phase"] = "running"
            snapshot["current"] = float(value)
            snapshot["max"] = float(maximum)
            snapshot["percent"] = max(0, min(99, round((float(value) / float(maximum)) * 100)))
            node_id = data.get("node") or data.get("display_node_id")
            snapshot["current_node"] = node_id
            snapshot["detail"] = f"節點 {node_id or '-'}：{int(value)}/{int(maximum)}"
            updated = True
    elif msg_type == "progress_state":
        nodes = data.get("nodes") if isinstance(data.get("nodes"), dict) else {}
        total_value = 0.0
        total_max = 0.0
        active_node = None
        for node_id, node in nodes.items():
            if not isinstance(node, dict):
                continue
            if node.get("prompt_id") and str(node.get("prompt_id")) != str(prompt_id):
                continue
            node_max = node.get("max")
            node_value = node.get("value")
            if isinstance(node_max, (int, float)) and float(node_max) > 0:
                total_max += float(node_max)
                total_value += min(float(node_value or 0), float(node_max))
                if active_node is None and float(node_value or 0) < float(node_max):
                    active_node = node
                    active_node["node_id"] = node.get("display_node_id") or node.get("node_id") or node_id
        if total_max > 0:
            snapshot["phase"] = "running"
            snapshot["current"] = total_value
            snapshot["max"] = total_max
            snapshot["percent"] = max(0, min(99, round((total_value / total_max) * 100)))
            if active_node:
                node_label = active_node.get("node_id") or "-"
                snapshot["current_node"] = node_label
                snapshot["detail"] = f"節點 {node_label}：{int(active_node.get('value') or 0)}/{int(active_node.get('max') or 0)}"
            updated = True
    return updated


def wait_for_images(
    client,
    prompt_id,
    *,
    timeout_seconds=1800,
    poll_interval=1.0,
    expected_count=1,
    websocket_conn=None,
    progress_callback=None,
    error_cls,
    websocket_module=None,
):
    start_time = time.time()
    deadline = start_time + int(timeout_seconds)
    last_status = None
    expected = max(1, int(expected_count or 1))
    running_started = False
    snapshot = {
        "prompt_id": str(prompt_id),
        "phase": "queued",
        "percent": 0,
        "current": 0,
        "max": 0,
        "current_node": None,
        "queue_remaining": None,
        "detail": "已送出至 ComfyUI 佇列",
        "completed": False,
        "timeout_seconds": int(timeout_seconds),
        "timeout_extended": False,
        "updated_at": time.time(),
    }
    next_history_poll = 0.0
    while True:
        now = time.time()
        if snapshot.get("phase") == "running" and not running_started:
            running_started = True
            deadline = max(deadline, now + int(timeout_seconds))
            snapshot["timeout_seconds"] = max(int(snapshot.get("timeout_seconds") or 0), int(deadline - start_time))
            emit_progress(progress_callback, snapshot)
        if not running_started and snapshot.get("phase") == "queued":
            deadline, extended = _queued_deadline(now, start_time=start_time, deadline=deadline)
            if extended:
                snapshot["timeout_extended"] = True
                snapshot["timeout_seconds"] = max(int(snapshot.get("timeout_seconds") or 0), int(deadline - start_time))
                snapshot["detail"] = "仍在 ComfyUI 佇列中，已自動延長等待時間"
                emit_progress(progress_callback, snapshot)
        if now >= deadline:
            break
        if websocket_conn is not None and websocket_module is not None:
            for _ in range(20):
                try:
                    raw = websocket_conn.recv()
                except websocket_module.WebSocketTimeoutException:
                    break
                except websocket_module.WebSocketConnectionClosedException:
                    websocket_conn = None
                    break
                except Exception:
                    websocket_conn = None
                    break
                if not isinstance(raw, str):
                    continue
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if apply_ws_message_to_progress(snapshot, message, prompt_id):
                    emit_progress(progress_callback, snapshot)
        now = time.time()
        if now >= next_history_poll:
            history = client._json_request(f"/history/{urllib.parse.quote(str(prompt_id))}", timeout=client.timeout)
            record = history.get(prompt_id) if isinstance(history, dict) else None
            if record:
                status = record.get("status") or {}
                last_status = status
                if status.get("status_str") == "error" or status.get("completed") is False and status.get("status_str") == "error":
                    raise error_cls("ComfyUI 產圖失敗")
                found = []
                outputs = record.get("outputs") or {}
                for output in outputs.values():
                    images = output.get("images") if isinstance(output, dict) else None
                    if images:
                        found.extend(images)
                if len(found) >= expected:
                    snapshot["phase"] = "completed"
                    snapshot["percent"] = 100
                    snapshot["completed"] = True
                    snapshot["detail"] = f"已完成，共 {len(found[:expected])} 張"
                    emit_progress(progress_callback, snapshot)
                    return found[:expected]
                if found and status.get("completed") is True:
                    snapshot["phase"] = "completed"
                    snapshot["percent"] = 100
                    snapshot["completed"] = True
                    snapshot["detail"] = f"已完成，共 {len(found)} 張"
                    emit_progress(progress_callback, snapshot)
                    return found
            next_history_poll = now + float(poll_interval)
        time.sleep(0.15)
    detail = f"；最後狀態：{last_status}" if last_status else ""
    raise error_cls(f"ComfyUI 產圖逾時{detail}")


def wait_for_first_image(client, prompt_id, *, timeout_seconds=1800, poll_interval=1.0, error_cls, websocket_module=None):
    return wait_for_images(
        client,
        prompt_id,
        timeout_seconds=timeout_seconds,
        poll_interval=poll_interval,
        expected_count=1,
        error_cls=error_cls,
        websocket_module=websocket_module,
    )[0]


def generate_from_workflow(
    client,
    workflow,
    *,
    timeout_seconds=1800,
    expected_count=1,
    progress_callback=None,
    extra_data=None,
    error_cls,
    websocket_module=None,
    image_fetcher,
):
    websocket_conn = None
    client_id = uuid.uuid4().hex
    try:
        if progress_callback:
            try:
                websocket_conn = client._open_progress_socket(client_id, timeout=min(5, client.timeout))
            except error_cls:
                websocket_conn = None
        queued = queue_prompt_with_client_id(
            client,
            workflow,
            client_id=client_id,
            extra_data=extra_data,
            error_cls=error_cls,
        )
        prompt_id = queued["prompt_id"]
        emit_progress(progress_callback, {
            "prompt_id": prompt_id,
            "phase": "queued",
            "percent": 0,
            "current": 0,
            "max": 0,
            "current_node": None,
            "queue_remaining": None,
            "detail": "已送出至 ComfyUI 佇列",
            "completed": False,
            "updated_at": time.time(),
        })
        image_refs = wait_for_images(
            client,
            prompt_id,
            timeout_seconds=timeout_seconds,
            expected_count=expected_count,
            websocket_conn=websocket_conn,
            progress_callback=progress_callback,
            error_cls=error_cls,
            websocket_module=websocket_module,
        )
    finally:
        try:
            if websocket_conn is not None:
                websocket_conn.close()
        except Exception:
            pass
    images = [image_fetcher(image_ref) for image_ref in image_refs]
    image = images[0]
    serialized_images = [{
        "image_ref": {
            "filename": item.filename,
            "subfolder": item.subfolder,
            "type": item.type,
        },
        "mime_type": item.mime_type,
        "data": item.data,
    } for item in images]
    return {
        "prompt_id": prompt_id,
        "image_ref": {
            "filename": image.filename,
            "subfolder": image.subfolder,
            "type": image.type,
        },
        "mime_type": image.mime_type,
        "data": image.data,
        "images": serialized_images,
    }


def generate_image(
    client,
    params,
    *,
    timeout_seconds=1800,
    progress_callback=None,
    extra_data=None,
    build_generation_workflow_func,
    generate_from_workflow_func=None,
    error_cls,
    websocket_module=None,
    image_fetcher=None,
):
    workflow = build_generation_workflow_func(params)
    expected_count = int(params.get("batch_size") or 1)
    if generate_from_workflow_func is not None:
        kwargs = {
            "timeout_seconds": timeout_seconds,
            "expected_count": expected_count,
            "progress_callback": progress_callback,
        }
        if extra_data:
            try:
                signature = inspect.signature(generate_from_workflow_func)
                accepts_extra_data = (
                    "extra_data" in signature.parameters
                    or any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values())
                )
            except (TypeError, ValueError):
                accepts_extra_data = True
            if accepts_extra_data:
                kwargs["extra_data"] = extra_data
        return generate_from_workflow_func(workflow, **kwargs)
    if image_fetcher is None:
        raise TypeError("generate_image() requires image_fetcher when generate_from_workflow_func is not provided")
    return generate_from_workflow(
        client,
        workflow,
        timeout_seconds=timeout_seconds,
        expected_count=expected_count,
        progress_callback=progress_callback,
        extra_data=extra_data,
        error_cls=error_cls,
        websocket_module=websocket_module,
        image_fetcher=image_fetcher,
    )
