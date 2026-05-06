"""Trading notification helper wrappers and payload builders."""


def create_trading_user_notification(
    conn,
    *,
    user_id,
    notification_type,
    title,
    body,
    link="/trading",
    create_notification,
):
    create_notification(
        conn,
        user_id=user_id,
        type=notification_type,
        title=title,
        body=body,
        link=link,
    )


def create_trading_root_notification(
    conn,
    *,
    notification_type,
    title,
    body,
    link="/trading",
    once=False,
    create_root_notification,
):
    create_root_notification(
        conn,
        type=notification_type,
        title=title,
        body=body,
        link=link,
        once=once,
    )


def trade_fill_notification_payload(fill, *, units_to_quantity, decimal_text):
    side_label = "買入" if fill["side"] == "buy" else "賣出"
    quantity = units_to_quantity(fill["quantity_units"])
    return {
        "notification_type": "trading_order_filled",
        "title": "交易已成交",
        "body": (
            f"{fill['market_symbol']} {side_label} {quantity} 已成交，"
            f"成交價 {decimal_text(fill['price_points'])}，成交額 {int(fill['notional_points'])}，"
            f"手續費 {int(fill['fee_points'] or 0)}。"
        ),
    }


def insufficient_balance_notification_payload(*, market_symbol, side, order_type, quantity, error):
    return {
        "notification_type": "trading_balance_insufficient",
        "title": "交易未成立：餘額不足",
        "body": (
            f"{market_symbol or '交易市場'} {side or '-'} {order_type or '-'} "
            f"數量 {quantity} 未成立：{str(error)[:180]}"
        ),
    }


def margin_liquidated_notification_payload(*, position, risk, decimal_text):
    return {
        "notification_type": "trading_margin_liquidated",
        "title": "進階交易倉位已被強制平倉",
        "body": (
            f"{position['market_symbol']} {position['position_type']} 已低於維持保證金並自動清算；"
            f"結算價 {decimal_text(risk.get('price_points') or 0)}，"
            f"損益 {int(risk.get('delta_points') or 0)} 點。"
        ),
    }


def margin_near_liquidation_notification_payload(
    *,
    market_symbol,
    position_label,
    price,
    liquidation_price,
    ratio,
    position_uuid,
):
    return {
        "notification_type": "trading_margin_near_liquidation",
        "title": "進階交易接近強平",
        "body": (
            f"{market_symbol} {position_label} 倉位接近強平，"
            f"目前價 {price}，強平價 {liquidation_price or '-'}，"
            f"整戶維持率 {ratio}%。倉位 {position_uuid}"
        ),
    }


def margin_price_jump_notification_payload(
    *,
    market_symbol,
    position_label,
    direction,
    move_percent,
    entry_price,
    price,
    position_uuid,
):
    return {
        "notification_type": "trading_margin_price_jump",
        "title": "進階交易價格大幅波動",
        "body": (
            f"{market_symbol} {position_label} 參考價較開倉價{direction} {move_percent:.2f}%，"
            f"開倉價 {entry_price}，目前價 {price}。倉位 {position_uuid}"
        ),
    }


def bot_audit_notification_payload(*, row, status, label, display_symbol):
    name = str(row.get("name") or row.get("market_symbol") or "bot")
    body = f"{name}（{display_symbol}）稽核結果 {label}。"
    return {
        "root_notification_type": f"trading_bot_audit_{status}",
        "root_title": "交易機器人稽核警示",
        "user_notification_type": "trading_bot_audit_warning",
        "user_title": "交易機器人需要檢查",
        "body": body,
    }
