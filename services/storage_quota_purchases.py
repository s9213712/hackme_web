import uuid
import json
from datetime import datetime, timedelta, timezone


STORAGE_UPGRADE_PRODUCTS = {
    "cloud_storage_1gb_30d": {
        "storage_bytes": 1024 ** 3,
        "duration_days": 30,
        "label": "雲端容量 1GB / 30 天",
    },
    "cloud_storage_10gb_30d": {
        "storage_bytes": 10 * 1024 ** 3,
        "duration_days": 30,
        "label": "雲端容量 10GB / 30 天",
    },
}

STORAGE_UPGRADE_PRICE_DEFAULTS = {
    "cloud_storage_1gb_30d": {
        "item_name": "雲端容量 1GB / 30 天",
        "category": "cloud_drive",
        "currency_type": "soft",
        "base_price": 100,
        "dynamic_pricing": 0,
        "min_price": 50,
        "max_price": 500,
        "enabled": 1,
        "metadata_json": "{}",
    },
    "cloud_storage_10gb_30d": {
        "item_name": "雲端容量 10GB / 30 天",
        "category": "cloud_drive",
        "currency_type": "soft",
        "base_price": 30,
        "dynamic_pricing": 0,
        "min_price": 10,
        "max_price": 100,
        "enabled": 1,
        "metadata_json": "{}",
    },
}


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(value):
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def ensure_storage_quota_purchase_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS storage_quota_purchases (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            item_key TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            purchased_bytes INTEGER NOT NULL,
            points_spent INTEGER NOT NULL,
            ledger_uuid TEXT,
            starts_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_storage_quota_purchases_user ON storage_quota_purchases(user_id, status, expires_at)"
    )


def storage_upgrade_product(item_key):
    return STORAGE_UPGRADE_PRODUCTS.get(str(item_key or "").strip())


def _metadata_from_item(item):
    if not item:
        return {}
    if isinstance(item.get("metadata"), dict):
        return item["metadata"]
    try:
        return json.loads(item.get("metadata_json") or "{}")
    except Exception:
        return {}


def storage_upgrade_product_from_catalog_item(item):
    if not item:
        return None
    static = storage_upgrade_product(item.get("item_key")) or {}
    metadata = _metadata_from_item(item)
    try:
        storage_bytes = int(metadata.get("storage_bytes") or static.get("storage_bytes") or 0)
        duration_days = int(metadata.get("duration_days") or static.get("duration_days") or 0)
    except Exception:
        return None
    if storage_bytes < 1 or duration_days < 1:
        return None
    return {
        "storage_bytes": storage_bytes,
        "duration_days": duration_days,
        "label": str(metadata.get("label") or item.get("item_name") or static.get("label") or item.get("item_key") or "雲端容量方案"),
    }


def storage_upgrade_product_from_catalog(conn, item_key):
    try:
        row = conn.execute(
            "SELECT * FROM economy_price_catalog WHERE item_key=? AND category='cloud_drive' AND enabled=1",
            (str(item_key or "").strip(),),
        ).fetchone()
    except Exception:
        row = None
    return storage_upgrade_product_from_catalog_item(dict(row)) if row else storage_upgrade_product(item_key)


def enrich_storage_upgrade_catalog(items):
    catalog = []
    for item in items or []:
        product = storage_upgrade_product_from_catalog_item(item)
        if not product:
            continue
        catalog.append({
            **dict(item),
            "storage_bytes": int(product["storage_bytes"]),
            "duration_days": int(product["duration_days"]),
            "label": product["label"],
        })
    return catalog


def default_storage_upgrade_catalog():
    rows = []
    for item_key, item in STORAGE_UPGRADE_PRICE_DEFAULTS.items():
        rows.append({
            "item_key": item_key,
            **item,
            "metadata": {},
        })
    return enrich_storage_upgrade_catalog(rows)


def list_storage_upgrade_price_catalog(conn):
    rows = conn.execute(
        """
        SELECT *
        FROM economy_price_catalog
        WHERE category='cloud_drive' AND enabled=1
        ORDER BY base_price, item_key
        """
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        try:
            item["metadata"] = json.loads(item.get("metadata_json") or "{}")
        except Exception:
            item["metadata"] = {}
        items.append(item)
    return enrich_storage_upgrade_catalog(items)


def ensure_storage_upgrade_price_catalog(conn):
    now = _iso(_now())
    for item_key, item in STORAGE_UPGRADE_PRICE_DEFAULTS.items():
        conn.execute(
            """
            INSERT OR IGNORE INTO economy_price_catalog (
                item_key, item_name, category, currency_type, base_price,
                dynamic_pricing, min_price, max_price, enabled, metadata_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_key,
                item["item_name"],
                item["category"],
                item["currency_type"],
                item["base_price"],
                item["dynamic_pricing"],
                item["min_price"],
                item["max_price"],
                item["enabled"],
                item["metadata_json"],
                now,
                now,
            ),
        )


def record_storage_quota_purchase(conn, *, user_id, item_key, quantity, points_spent, ledger_uuid=None):
    ensure_storage_quota_purchase_schema(conn)
    product = storage_upgrade_product_from_catalog(conn, item_key)
    if not product:
        raise ValueError("不支援的雲端容量商品")
    quantity = max(1, int(quantity or 1))
    starts_at = _now()
    expires_at = starts_at + timedelta(days=int(product["duration_days"]))
    purchased_bytes = int(product["storage_bytes"]) * quantity
    purchase_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO storage_quota_purchases (
            id, user_id, item_key, quantity, purchased_bytes, points_spent,
            ledger_uuid, starts_at, expires_at, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
        """,
        (
            purchase_id,
            int(user_id),
            str(item_key),
            quantity,
            purchased_bytes,
            int(points_spent or 0),
            str(ledger_uuid or "") or None,
            _iso(starts_at),
            _iso(expires_at),
            _iso(starts_at),
        ),
    )
    return get_storage_quota_purchase(conn, purchase_id)


def get_storage_quota_purchase(conn, purchase_id):
    ensure_storage_quota_purchase_schema(conn)
    row = conn.execute("SELECT * FROM storage_quota_purchases WHERE id=?", (str(purchase_id),)).fetchone()
    return dict(row) if row else None


def active_storage_quota_purchases(conn, user_id, *, now=None):
    ensure_storage_quota_purchase_schema(conn)
    now_iso = _iso(now or _now())
    rows = conn.execute(
        """
        SELECT * FROM storage_quota_purchases
        WHERE user_id=? AND status='active' AND expires_at>?
        ORDER BY expires_at ASC, created_at ASC
        """,
        (int(user_id), now_iso),
    ).fetchall()
    return [dict(row) for row in rows]


def purchased_storage_summary(conn, user_id, *, now=None):
    purchases = active_storage_quota_purchases(conn, user_id, now=now)
    total = sum(int(row.get("purchased_bytes") or 0) for row in purchases)
    latest_expiry = max((row.get("expires_at") for row in purchases), default=None)
    return {
        "purchased_extra_bytes": int(total),
        "active_purchases": purchases,
        "active_purchase_count": len(purchases),
        "latest_expires_at": latest_expiry,
    }


def get_user_purchased_storage_bytes(conn, user_id):
    return int(purchased_storage_summary(conn, user_id).get("purchased_extra_bytes") or 0)
