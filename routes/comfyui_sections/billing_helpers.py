"""ComfyUI billing and wallet helper factory."""

import secrets


def _int_range(value, default, minimum, maximum, *, multiple_of=None):
    try:
        number = int(value)
    except Exception:
        number = default
    number = max(minimum, min(maximum, number))
    if multiple_of:
        number = max(minimum, (number // multiple_of) * multiple_of)
    return number


def build_comfyui_billing_helpers(ctx):
    actor_value = ctx["actor_value"]
    basic_price_item_key = ctx["COMFYUI_BASIC_PRICE_ITEM_KEY"]
    lora_extra_price_points = ctx["COMFYUI_LORA_EXTRA_PRICE_POINTS"]
    points_service = ctx["points_service"]

    def _is_root(actor):
        return actor_value(actor, "username") == "root"

    def _comfyui_charge_required(actor):
        return not _is_root(actor)

    def _comfyui_wallet_payload(actor):
        if not points_service:
            return None
        try:
            wallet = points_service.get_wallet(actor_value(actor, "id"))
        except Exception:
            return None
        if not isinstance(wallet, dict):
            return None
        return {
            "points_balance": int(wallet.get("points_balance") or 0),
            "charged": _comfyui_charge_required(actor),
        }

    def _comfyui_lora_count(params):
        loras = (params or {}).get("loras") or []
        return len(loras) if isinstance(loras, list) else 0

    def _comfyui_price_quote(quantity, *, lora_count=0):
        if not points_service:
            return None, "積分服務未啟用，無法使用 ComfyUI 產圖"
        catalog = points_service.list_catalog()
        item = next((row for row in catalog if row.get("item_key") == basic_price_item_key), None)
        if not item:
            return None, "ComfyUI 產圖收費項目未啟用"
        quantity = max(1, int(quantity or 1))
        lora_count = max(0, int(lora_count or 0))
        unit_price = int(item.get("base_price") or 0)
        lora_extra_price = lora_extra_price_points * lora_count * quantity
        return {
            "item_key": basic_price_item_key,
            "item_name": item.get("item_name") or "ComfyUI 基礎生圖一次",
            "unit_price": unit_price,
            "lora_extra_unit_price": lora_extra_price_points,
            "lora_count": lora_count,
            "lora_extra_price": lora_extra_price,
            "quantity": quantity,
            "base_price_total": unit_price * quantity,
            "total_price": unit_price * quantity + lora_extra_price,
            "currency_type": "points",
        }, None

    def _comfyui_total_quantity(data, params):
        batch_size = max(1, int((params or {}).get("batch_size") or 1))
        run_count = _int_range((data or {}).get("run_count"), 1, 1, 10)
        return batch_size * run_count, run_count

    def _ensure_comfyui_balance(actor, quote):
        if not quote or not points_service:
            return None
        wallet = points_service.get_wallet(actor_value(actor, "id"))
        balance = int((wallet or {}).get("points_balance") or 0)
        if balance < int(quote.get("total_price") or 0):
            return f"積分不足：本次產圖需要 {quote['total_price']} 點，目前餘額 {balance} 點"
        return None

    def _charge_comfyui_generation(actor, quote, *, prompt_id):
        if not quote or not points_service:
            return None
        result = points_service.rc1_facade().spend_service_fee(
            user_id=actor_value(actor, "id"),
            item_key=quote["item_key"],
            quantity=quote["quantity"],
            override_amount=quote["total_price"],
            reference_type="comfyui_generation",
            reference_id=str(prompt_id or ""),
            idempotency_key=f"comfyui_generation:{actor_value(actor, 'id')}:{prompt_id or secrets.token_hex(8)}",
            metadata={
                "charged_after_success": True,
                "unit_price": quote["unit_price"],
                "quantity": quote["quantity"],
                "lora_count": quote.get("lora_count", 0),
                "lora_extra_unit_price": quote.get("lora_extra_unit_price", 0),
                "lora_extra_price": quote.get("lora_extra_price", 0),
                "total_price": quote["total_price"],
            },
            actor=actor,
        )
        return {
            "charged": True,
            "item_key": quote["item_key"],
            "unit_price": quote["unit_price"],
            "quantity": quote["quantity"],
            "lora_count": quote.get("lora_count", 0),
            "lora_extra_unit_price": quote.get("lora_extra_unit_price", 0),
            "lora_extra_price": quote.get("lora_extra_price", 0),
            "total_price": quote["total_price"],
            "ledger_uuid": (result.get("ledger") or {}).get("ledger_uuid"),
            "wallet": result.get("wallet"),
        }

    return {
        "_is_root": _is_root,
        "_comfyui_charge_required": _comfyui_charge_required,
        "_comfyui_wallet_payload": _comfyui_wallet_payload,
        "_comfyui_lora_count": _comfyui_lora_count,
        "_comfyui_price_quote": _comfyui_price_quote,
        "_comfyui_total_quantity": _comfyui_total_quantity,
        "_ensure_comfyui_balance": _ensure_comfyui_balance,
        "_charge_comfyui_generation": _charge_comfyui_generation,
    }
