"""Server startup and background worker orchestration helpers.

The legacy ``server.py`` module remains the Flask entrypoint. This module
owns recurring worker loops plus the ``__main__`` startup sequence so the
entrypoint can converge toward a thinner façade.
"""

import json
import os
import threading
import time


def _int_env(name, default, *, minimum=None, maximum=None):
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        value = int(default)
    if minimum is not None:
        value = max(int(minimum), value)
    if maximum is not None:
        value = min(int(maximum), value)
    return value


def start_daily_snapshot_worker(*, snapshot_service, get_system_settings, save_settings, audit):
    interval = _int_env("HTML_LEARNING_SNAPSHOT_CHECK_INTERVAL_SECONDS", 3600, minimum=60)

    def loop():
        while True:
            try:
                result = snapshot_service.create_daily_snapshot_if_due(
                    actor={"id": 0, "username": "system"},
                    settings=get_system_settings(),
                    save_settings=save_settings,
                )
                if result.get("created"):
                    audit(
                        "DAILY_SNAPSHOT_CREATED",
                        "0.0.0.0",
                        user="system",
                        success=True,
                        detail=f"snapshot_id={result.get('snapshot_id')}",
                    )
            except Exception as exc:
                audit("DAILY_SNAPSHOT_FAILED", "0.0.0.0", user="system", success=False, detail=str(exc))
            time.sleep(interval)

    worker = threading.Thread(target=loop, name="daily-snapshot-worker", daemon=True)
    worker.start()
    return worker


def start_storage_maintenance_worker(*, get_db, run_storage_maintenance_if_due, get_system_settings, save_settings, audit):
    interval = _int_env("HTML_LEARNING_STORAGE_MAINTENANCE_CHECK_INTERVAL_SECONDS", 3600, minimum=60)

    def loop():
        while True:
            conn = None
            try:
                conn = get_db()
                result = run_storage_maintenance_if_due(
                    conn,
                    settings=get_system_settings(),
                    save_settings=save_settings,
                    actor_user_id=0,
                )
                if result.get("ran"):
                    conn.commit()
                    audit(
                        "STORAGE_MAINTENANCE_AUTO_RUN",
                        "0.0.0.0",
                        user="system",
                        success=True,
                        detail=str(result.get("result") or {}),
                    )
                else:
                    conn.rollback()
            except Exception as exc:
                if conn:
                    conn.rollback()
                audit("STORAGE_MAINTENANCE_FAILED", "0.0.0.0", user="system", success=False, detail=str(exc))
            finally:
                if conn:
                    conn.close()
            time.sleep(interval)

    worker = threading.Thread(target=loop, name="storage-maintenance-worker", daemon=True)
    worker.start()
    return worker


def start_points_chain_block_worker(
    *,
    points_service,
    audit,
    default_block_ledger_threshold,
    default_block_max_interval_seconds,
):
    check_interval = _int_env("HTML_LEARNING_POINTS_BLOCK_CHECK_INTERVAL_SECONDS", 15, minimum=5)
    ledger_threshold = _int_env(
        "HTML_LEARNING_POINTS_BLOCK_LEDGER_THRESHOLD",
        default_block_ledger_threshold,
        minimum=1,
    )
    max_interval_seconds = _int_env(
        "HTML_LEARNING_POINTS_BLOCK_MAX_INTERVAL_SECONDS",
        default_block_max_interval_seconds,
        minimum=60,
    )

    def loop():
        actor = {"username": "system", "role": "system"}
        while True:
            try:
                backup_result = points_service.create_scheduled_backup_if_due()
                if backup_result.get("created"):
                    audit(
                        "POINTS_SCHEDULED_BACKUP_CREATED",
                        "0.0.0.0",
                        user="system",
                        success=bool(backup_result.get("ok")),
                        detail=backup_result.get("backup_id"),
                    )
                result = points_service.seal_due_block(
                    actor=actor,
                    ledger_threshold=ledger_threshold,
                    max_interval_seconds=max_interval_seconds,
                    limit=500,
                )
                if result.get("sealed"):
                    block = result.get("block") or {}
                    audit(
                        "POINTS_AUTO_BLOCK_SEALED",
                        "0.0.0.0",
                        user="system",
                        success=True,
                        detail=f"block_number={block.get('block_number')},ledger_count={block.get('ledger_count')}",
                    )
                elif result.get("ok") is False:
                    audit(
                        "POINTS_AUTO_BLOCK_SKIPPED",
                        "0.0.0.0",
                        user="system",
                        success=False,
                        detail=str(result.get("msg") or "verification failed"),
                    )
            except Exception as exc:
                audit("POINTS_AUTO_BLOCK_FAILED", "0.0.0.0", user="system", success=False, detail=str(exc))
            time.sleep(check_interval)

    worker = threading.Thread(target=loop, name="points-chain-block-worker", daemon=True)
    worker.start()
    return worker


def start_trading_liquidation_worker(*, trading_service, audit):
    check_interval = _int_env("HTML_LEARNING_TRADING_LIQUIDATION_CHECK_INTERVAL_SECONDS", 30, minimum=10)

    def loop():
        actor = {"username": "system", "role": "system"}
        while True:
            try:
                match_result = trading_service.match_open_limit_orders(actor=actor, limit=200)
                matched = match_result.get("matched") or []
                match_errors = match_result.get("errors") or []
                if matched:
                    audit(
                        "TRADING_AUTO_LIMIT_MATCH_RUN",
                        "0.0.0.0",
                        user="system",
                        success=True,
                        detail=f"scanned={match_result.get('scanned')}, matched={len(matched)}",
                    )
                if match_errors:
                    audit(
                        "TRADING_AUTO_LIMIT_MATCH_ERRORS",
                        "0.0.0.0",
                        user="system",
                        success=False,
                        detail=json.dumps(match_errors[:5], ensure_ascii=False),
                    )
                result = trading_service.scan_margin_liquidations(actor=actor, limit=100)
                liquidated = result.get("liquidated") or []
                errors = result.get("errors") or []
                if liquidated:
                    audit(
                        "TRADING_AUTO_LIQUIDATION_RUN",
                        "0.0.0.0",
                        user="system",
                        success=True,
                        detail=f"scanned={result.get('scanned')}, liquidated={len(liquidated)}",
                    )
                if errors:
                    audit(
                        "TRADING_AUTO_LIQUIDATION_ERRORS",
                        "0.0.0.0",
                        user="system",
                        success=False,
                        detail=json.dumps(errors[:5], ensure_ascii=False),
                    )
            except Exception as exc:
                audit("TRADING_AUTO_LIQUIDATION_FAILED", "0.0.0.0", user="system", success=False, detail=str(exc))
            time.sleep(check_interval)

    worker = threading.Thread(target=loop, name="trading-liquidation-worker", daemon=True)
    worker.start()
    return worker


def start_trading_bot_worker(*, trading_service, audit):
    fallback_interval = _int_env("HTML_LEARNING_TRADING_BOT_SCAN_INTERVAL_SECONDS", 30, minimum=10, maximum=3600)

    def loop():
        actor = {"username": "system", "role": "system"}
        last_audit_started_at = 0.0
        while True:
            interval = fallback_interval
            try:
                settings = (trading_service.get_root_settings().get("settings") or {})
                interval = max(10, min(int(settings.get("bot_auto_scan_interval_seconds") or fallback_interval), 3600))
                if not settings.get("enabled", True) or not settings.get("bot_auto_scan_enabled", True):
                    time.sleep(interval)
                    continue
                limit = max(1, min(int(settings.get("bot_auto_scan_limit") or 50), 200))
                result = trading_service.run_due_trading_bots(actor=actor, limit=limit)
                triggered = result.get("triggered") or []
                failed = result.get("failed") or []
                if triggered:
                    audit(
                        "TRADING_BOT_AUTO_SCAN_RUN",
                        "0.0.0.0",
                        user="system",
                        success=True,
                        detail=f"scanned={result.get('scanned')}, triggered={len(triggered)}",
                    )
                if failed:
                    audit(
                        "TRADING_BOT_AUTO_SCAN_ERRORS",
                        "0.0.0.0",
                        user="system",
                        success=False,
                        detail=json.dumps(failed[:5], ensure_ascii=False),
                    )
                audit_enabled = settings.get("bot_audit_enabled", True)
                audit_interval = max(60, min(int(settings.get("bot_audit_interval_seconds") or 300), 86400))
                audit_limit = max(1, min(int(settings.get("bot_audit_limit") or 50), 200))
                now_mono = time.monotonic()
                if audit_enabled and now_mono - last_audit_started_at >= audit_interval:
                    audit_result = trading_service.run_due_bot_audits(actor=actor, limit=audit_limit, force=False)
                    last_audit_started_at = now_mono
                    audited_rows = audit_result.get("audited") or []
                    if audited_rows:
                        audit(
                            "TRADING_BOT_AUDIT_AUTO_RUN",
                            "0.0.0.0",
                            user="system",
                            success=True,
                            detail=f"audited={len(audited_rows)}, skipped={len(audit_result.get('skipped') or [])}",
                        )
            except Exception as exc:
                audit("TRADING_BOT_AUTO_SCAN_FAILED", "0.0.0.0", user="system", success=False, detail=str(exc))
            time.sleep(interval)

    worker = threading.Thread(target=loop, name="trading-bot-worker", daemon=True)
    worker.start()
    return worker


def run_server_main(
    *,
    server_log_path,
    install_runtime_output_capture,
    init_db,
    init_db_kwargs,
    get_db,
    ensure_trading_schema,
    reseal_audit_chain_if_required_on_startup,
    audit,
    server_mode_service,
    points_service,
    get_system_settings,
    integrity_guard,
    start_daily_snapshot_worker,
    start_storage_maintenance_worker,
    start_points_chain_block_worker,
    start_trading_liquidation_worker,
    start_trading_bot_worker,
    ensure_local_tls_files,
    cert_file,
    key_file,
    effective_server_ssl,
    effective_server_bind,
    server_bind_state,
    app,
):
    install_runtime_output_capture(server_log_path)
    init_db(**init_db_kwargs)
    conn = get_db()
    try:
        ensure_trading_schema(conn)
        conn.commit()
    finally:
        conn.close()
    try:
        reseal_audit_chain_if_required_on_startup()
    except Exception as exc:
        audit("AUDIT_CHAIN_STARTUP_RESEAL_FAILED", "0.0.0.0", user="system", success=False, detail=str(exc))
    try:
        recovery = server_mode_service.recover_superweak_on_startup(
            actor={"id": 0, "username": "system-startup", "role": "system"}
        )
        if recovery.get("recovered"):
            audit(
                "SERVER_MODE_SUPERWEAK_STARTUP_RECOVERED",
                "0.0.0.0",
                user="system",
                success=True,
                detail=json.dumps(recovery, ensure_ascii=False, sort_keys=True, default=str),
            )
        elif not recovery.get("ok"):
            audit(
                "SERVER_MODE_SUPERWEAK_STARTUP_RECOVERY_FAILED",
                "0.0.0.0",
                user="system",
                success=False,
                detail=json.dumps(recovery, ensure_ascii=False, sort_keys=True, default=str),
            )
    except Exception as exc:
        audit("SERVER_MODE_SUPERWEAK_STARTUP_RECOVERY_ERROR", "0.0.0.0", user="system", success=False, detail=str(exc))
    if os.environ.get("HTML_LEARNING_BOOTSTRAP_POINTS_CHAIN", "").strip().lower() in {"1", "true", "yes", "on"}:
        try:
            system_actor = {"username": "system", "role": "system"}
            genesis = points_service.bootstrap_admin_initial_grants(actor=system_actor, seal_genesis=True)
            salary = points_service.award_admin_weekly_salaries(actor=system_actor)
            if genesis.get("created_count") or salary.get("created_count"):
                audit(
                    "POINTS_BOOTSTRAP_GRANTS",
                    "0.0.0.0",
                    success=True,
                    detail=f"genesis={genesis.get('created_count')}, weekly={salary.get('created_count')}, week={salary.get('salary_week')}",
                )
        except Exception as exc:
            audit("POINTS_BOOTSTRAP_GRANTS_FAILED", "0.0.0.0", success=False, detail=str(exc))
    if get_system_settings().get("integrity_guard_enabled", True):
        integrity_status = integrity_guard.scan(actor="system-startup", create_initial_manifest=True)
        if get_system_settings().get("integrity_guard_strict_mode", False):
            high_risk = (integrity_status.get("summary") or {}).get("high_risk_pending", 0)
            if high_risk:
                warning = (
                    f"Integrity Guard strict mode detected {high_risk} high risk finding(s) at startup; "
                    "startup continues, but production entry must stay blocked until root reviews them."
                )
                print(f"[integrity-guard] {warning}")
                try:
                    audit(
                        "INTEGRITY_GUARD_STARTUP_WARNING",
                        "0.0.0.0",
                        user="system-startup",
                        success=False,
                        detail=warning,
                    )
                except Exception:
                    pass
    start_daily_snapshot_worker()
    start_storage_maintenance_worker()
    start_points_chain_block_worker()
    start_trading_liquidation_worker()
    start_trading_bot_worker()
    ensure_local_tls_files(cert_file, key_file)
    has_ssl_files = os.path.exists(cert_file) and os.path.exists(key_file)
    ssl_state = effective_server_ssl(get_system_settings(), cert_exists=has_ssl_files)
    has_ssl = ssl_state["enabled"]
    scheme = ssl_state["scheme"]
    bind = effective_server_bind(get_system_settings())
    host = bind["host"]
    port = bind["port"]
    server_bind_state.update({"host": host, "port": port, "ssl_enabled": has_ssl})
    print(f"\n🌐  hackme_web server running at {scheme}://{host}:{port}")
    if has_ssl:
        ssl_label = "enabled"
    elif ssl_state["enabled_by_setting"] and not has_ssl_files:
        ssl_label = "disabled (runtime/cert.pem + runtime/key.pem missing)"
    else:
        ssl_label = "disabled by root setting"
    print(f"    SSL: {ssl_label}")
    print("    Audit log: database (secure_audit table + hash-chain)")
    print("    Security: Argon2id + timing-noise + account-enum-protection + CSRF + strict-headers\n")
    kwargs = {"host": host, "port": port, "debug": False}
    if has_ssl:
        kwargs["ssl_context"] = (cert_file, key_file)
    app.run(**kwargs)
