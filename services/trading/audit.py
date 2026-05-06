"""Trading audit helper wrappers."""


def emit_trading_audit_event(
    conn,
    *,
    event_type,
    message,
    actor_id,
    target_user_id=None,
    order_id=None,
    market_symbol=None,
    severity="info",
    metadata=None,
    json_dumps,
    now_text,
    uuid_factory,
):
    conn.execute(
        """
        INSERT INTO trading_audit_events (
            event_uuid, event_type, severity, actor_user_id, target_user_id,
            order_id, market_symbol, message, metadata_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid_factory()),
            event_type,
            severity,
            actor_id,
            int(target_user_id) if target_user_id is not None else None,
            int(order_id) if order_id is not None else None,
            market_symbol,
            message,
            json_dumps(metadata or {}),
            now_text(),
        ),
    )
