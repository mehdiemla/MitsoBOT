from __future__ import annotations

import sqlite3
import json
from pathlib import Path
from typing import Any


DB_PATH = Path(__file__).with_name("orders.sqlite3")


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_code TEXT,
                user_id INTEGER NOT NULL,
                username TEXT,
                product_key TEXT NOT NULL,
                product_title TEXT NOT NULL,
                price INTEGER NOT NULL,
                telegram_id TEXT,
                spotify_email TEXT,
                spotify_password TEXT,
                apple_id TEXT,
                chatgpt_session TEXT,
                receipt_file_id TEXT,
                status TEXT NOT NULL DEFAULT 'waiting_receipt',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                delivery_text TEXT
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS price_overrides (
                product_key TEXT PRIMARY KEY,
                price INTEGER NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS discount_codes (
                code TEXT PRIMARY KEY,
                percent INTEGER NOT NULL,
                product_key TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS usd_price_overrides (
                product_key TEXT PRIMARY KEY,
                usd_price REAL NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS vpn_rate_overrides (
                tier_key TEXT PRIMARY KEY,
                unit_price INTEGER NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        user_columns = {row["name"] for row in db.execute("PRAGMA table_info(users)").fetchall()}
        if "rules_accepted_at" not in user_columns:
            db.execute("ALTER TABLE users ADD COLUMN rules_accepted_at TEXT")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS wallets (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS wallet_topups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                amount INTEGER NOT NULL,
                receipt_file_id TEXT,
                status TEXT NOT NULL DEFAULT 'waiting_receipt',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS wallet_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                reason TEXT NOT NULL,
                order_id INTEGER,
                topup_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        columns = {row["name"] for row in db.execute("PRAGMA table_info(orders)").fetchall()}
        if "order_code" not in columns:
            db.execute("ALTER TABLE orders ADD COLUMN order_code TEXT")
        if "payment_method" not in columns:
            db.execute("ALTER TABLE orders ADD COLUMN payment_method TEXT")
        if "chatgpt_session" not in columns:
            db.execute("ALTER TABLE orders ADD COLUMN chatgpt_session TEXT")
        if "apple_id" not in columns:
            db.execute("ALTER TABLE orders ADD COLUMN apple_id TEXT")
        if "original_price" not in columns:
            db.execute("ALTER TABLE orders ADD COLUMN original_price INTEGER")
            db.execute("UPDATE orders SET original_price = price WHERE original_price IS NULL")
        if "discount_code" not in columns:
            db.execute("ALTER TABLE orders ADD COLUMN discount_code TEXT")
        if "discount_percent" not in columns:
            db.execute("ALTER TABLE orders ADD COLUMN discount_percent INTEGER")
        if "discount_amount" not in columns:
            db.execute("ALTER TABLE orders ADD COLUMN discount_amount INTEGER")
        if "vpn_volume_gb" not in columns:
            db.execute("ALTER TABLE orders ADD COLUMN vpn_volume_gb TEXT")
        if "foreign_site_url" not in columns:
            db.execute("ALTER TABLE orders ADD COLUMN foreign_site_url TEXT")
        if "foreign_usd_amount" not in columns:
            db.execute("ALTER TABLE orders ADD COLUMN foreign_usd_amount REAL")
        db.execute("UPDATE orders SET order_code = CAST(id AS TEXT) WHERE order_code IS NULL OR order_code != CAST(id AS TEXT)")
        db.execute(
            """
            UPDATE orders
            SET vpn_volume_gb = '1'
            WHERE product_key = 'v2ray_custom'
              AND (vpn_volume_gb IS NULL OR vpn_volume_gb = '')
              AND product_title LIKE '%- 1 گیگ'
            """
        )
        discount_columns = {row["name"] for row in db.execute("PRAGMA table_info(discount_codes)").fetchall()}
        if "product_key" not in discount_columns:
            db.execute("ALTER TABLE discount_codes ADD COLUMN product_key TEXT")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS product_categories (
                category_key TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS product_catalog (
                product_key TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                category_key TEXT NOT NULL,
                subcategory_key TEXT,
                price INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                description TEXT,
                payment_note TEXT,
                settings_json TEXT NOT NULL DEFAULT '{}',
                sort_order INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS v2ray_one_gb_limit_exemptions (
                user_id INTEGER PRIMARY KEY,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            """
            INSERT OR IGNORE INTO bot_settings (key, value)
            VALUES ('v2ray_one_gb_limit_enabled', '0')
            """
        )
        for row in db.execute("SELECT tier_key, unit_price FROM vpn_rate_overrides").fetchall():
            current_price = int(row["unit_price"])
            normalized_price = normalize_vpn_unit_price(current_price)
            if normalized_price != current_price:
                db.execute(
                    "UPDATE vpn_rate_overrides SET unit_price = ?, updated_at = CURRENT_TIMESTAMP WHERE tier_key = ?",
                    (normalized_price, row["tier_key"]),
                )


V2RAY_ONE_GB_LIMIT_SETTING = "v2ray_one_gb_limit_enabled"


def get_bool_setting(key: str, default: bool = False) -> bool:
    with connect() as db:
        row = db.execute("SELECT value FROM bot_settings WHERE key = ?", (key,)).fetchone()
    if not row:
        return default
    return str(row["value"]).strip().lower() in {"1", "true", "yes", "on"}


def set_bool_setting(key: str, value: bool) -> None:
    with connect() as db:
        db.execute(
            """
            INSERT INTO bot_settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (key, "1" if value else "0"),
        )


def is_v2ray_one_gb_limit_enabled() -> bool:
    return get_bool_setting(V2RAY_ONE_GB_LIMIT_SETTING, True)


def set_v2ray_one_gb_limit_enabled(enabled: bool) -> None:
    set_bool_setting(V2RAY_ONE_GB_LIMIT_SETTING, enabled)


def is_user_v2ray_one_gb_exempt(user_id: int) -> bool:
    with connect() as db:
        row = db.execute(
            "SELECT user_id FROM v2ray_one_gb_limit_exemptions WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return row is not None


def set_user_v2ray_one_gb_exempt(user_id: int, exempt: bool) -> None:
    with connect() as db:
        if exempt:
            db.execute(
                """
                INSERT OR IGNORE INTO v2ray_one_gb_limit_exemptions (user_id)
                VALUES (?)
                """,
                (user_id,),
            )
        else:
            db.execute(
                "DELETE FROM v2ray_one_gb_limit_exemptions WHERE user_id = ?",
                (user_id,),
            )


def list_v2ray_one_gb_exempt_user_ids() -> list[int]:
    with connect() as db:
        rows = db.execute(
            "SELECT user_id FROM v2ray_one_gb_limit_exemptions ORDER BY created_at DESC"
        ).fetchall()
    return [int(row["user_id"]) for row in rows]


def user_has_v2ray_one_gb_order(user_id: int) -> bool:
    with connect() as db:
        row = db.execute(
            """
            SELECT COUNT(*) AS count
            FROM orders
            WHERE user_id = ?
              AND product_key = 'v2ray_custom'
              AND status != 'rejected'
              AND (
                    vpn_volume_gb = '1'
                    OR product_title LIKE '%- 1 گیگ'
                  )
            """,
            (user_id,),
        ).fetchone()
    return int(row["count"]) > 0


def has_accepted_rules(user_id: int) -> bool:
    with connect() as db:
        row = db.execute(
            "SELECT rules_accepted_at FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return bool(row and row["rules_accepted_at"])


def set_rules_accepted(user_id: int) -> None:
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        db.execute(
            """
            UPDATE users
            SET rules_accepted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
            """,
            (user_id,),
        )


def upsert_user(user: Any) -> None:
    with connect() as db:
        db.execute(
            """
            INSERT INTO users (user_id, username, first_name, last_name, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                user.id,
                user.username,
                getattr(user, "first_name", None),
                getattr(user, "last_name", None),
            ),
        )


def list_user_ids() -> list[int]:
    with connect() as db:
        rows = db.execute("SELECT user_id FROM users ORDER BY updated_at DESC").fetchall()
    return [int(row["user_id"]) for row in rows]


def count_users() -> int:
    with connect() as db:
        row = db.execute("SELECT COUNT(*) AS count FROM users").fetchone()
    return int(row["count"])


def normalize_discount_code(code: str) -> str:
    return code.strip().upper()


def normalize_discount_product_key(product_key: str | None) -> str | None:
    if product_key is None:
        return None
    normalized = product_key.strip()
    if not normalized or normalized.casefold() == "all":
        return None
    return normalized


def set_discount_code(code: str, percent: int, product_key: str | None = None) -> None:
    normalized_code = normalize_discount_code(code)
    normalized_product_key = normalize_discount_product_key(product_key)
    with connect() as db:
        db.execute(
            """
            INSERT INTO discount_codes (code, percent, product_key, active, updated_at)
            VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(code) DO UPDATE SET
                percent = excluded.percent,
                product_key = excluded.product_key,
                active = 1,
                updated_at = CURRENT_TIMESTAMP
            """,
            (normalized_code, percent, normalized_product_key),
        )


def get_discount_code(code: str, product_key: str | None = None) -> sqlite3.Row | None:
    normalized_code = normalize_discount_code(code)
    normalized_product_key = normalize_discount_product_key(product_key)
    with connect() as db:
        return db.execute(
            """
            SELECT *
            FROM discount_codes
            WHERE code = ? AND active = 1 AND (product_key IS NULL OR product_key = ?)
            """,
            (normalized_code, normalized_product_key),
        ).fetchone()


def delete_discount_code(code: str) -> bool:
    normalized_code = normalize_discount_code(code)
    with connect() as db:
        cursor = db.execute(
            """
            UPDATE discount_codes
            SET active = 0, updated_at = CURRENT_TIMESTAMP
            WHERE code = ? AND active = 1
            """,
            (normalized_code,),
        )
        return cursor.rowcount > 0


def list_discount_codes() -> list[sqlite3.Row]:
    with connect() as db:
        return db.execute(
            """
            SELECT *
            FROM discount_codes
            WHERE active = 1
            ORDER BY updated_at DESC
            """
        ).fetchall()


def get_user(user_id: int) -> sqlite3.Row | None:
    with connect() as db:
        return db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()


def find_user(identifier: str) -> sqlite3.Row | None:
    value = identifier.strip()
    if value.startswith("@"):
        value = value[1:]
    with connect() as db:
        if value.isdigit():
            row = db.execute("SELECT * FROM users WHERE user_id = ?", (int(value),)).fetchone()
            if row:
                return row
        return db.execute("SELECT * FROM users WHERE lower(username) = lower(?)", (value,)).fetchone()


def backfill_users_from_orders() -> None:
    with connect() as db:
        db.execute(
            """
            INSERT OR IGNORE INTO users (user_id, username)
            SELECT user_id, username
            FROM orders
            GROUP BY user_id
            """
        )


def create_order(data: dict[str, Any]) -> int:
    with connect() as db:
        cursor = db.execute(
            """
            INSERT INTO orders (
                order_code, user_id, username, product_key, product_title, original_price, price,
                telegram_id, spotify_email, spotify_password, apple_id, chatgpt_session,
                vpn_volume_gb, foreign_site_url, foreign_usd_amount, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "",
                data["user_id"],
                data.get("username"),
                data["product_key"],
                data["product_title"],
                data["price"],
                data["price"],
                data["telegram_id"],
                data.get("spotify_email"),
                data.get("spotify_password"),
                data.get("apple_id"),
                data.get("chatgpt_session"),
                data.get("vpn_volume_gb"),
                data.get("foreign_site_url"),
                data.get("foreign_usd_amount"),
                "waiting_receipt",
            ),
        )
        order_id = int(cursor.lastrowid)
        db.execute("UPDATE orders SET order_code = ? WHERE id = ?", (str(order_id), order_id))
        return order_id


def set_order_discount(
    order_id: int,
    code: str | None,
    percent: int | None,
    discount_amount: int,
    final_price: int,
) -> None:
    with connect() as db:
        db.execute(
            """
            UPDATE orders
            SET discount_code = ?, discount_percent = ?, discount_amount = ?, price = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (code, percent, discount_amount, final_price, order_id),
        )


def set_order_payment_method(order_id: int, payment_method: str) -> None:
    with connect() as db:
        db.execute(
            """
            UPDATE orders
            SET payment_method = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (payment_method, order_id),
        )


def set_receipt(order_id: int, receipt_file_id: str) -> None:
    with connect() as db:
        db.execute(
            """
            UPDATE orders
            SET receipt_file_id = ?, status = 'pending_review', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (receipt_file_id, order_id),
        )


def set_status(order_id: int, status: str) -> None:
    with connect() as db:
        db.execute(
            "UPDATE orders SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, order_id),
        )


def get_wallet_balance(user_id: int) -> int:
    with connect() as db:
        row = db.execute("SELECT balance FROM wallets WHERE user_id = ?", (user_id,)).fetchone()
    return int(row["balance"]) if row else 0


def add_wallet_balance(user_id: int, amount: int, reason: str, order_id: int | None = None, topup_id: int | None = None) -> None:
    with connect() as db:
        db.execute(
            """
            INSERT INTO wallets (user_id, balance, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                balance = balance + excluded.balance,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, amount),
        )
        db.execute(
            """
            INSERT INTO wallet_transactions (user_id, amount, reason, order_id, topup_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, amount, reason, order_id, topup_id),
        )


def adjust_wallet_balance(user_id: int, amount: int, reason: str) -> bool:
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO wallets (user_id, balance) VALUES (?, 0)", (user_id,))
        if amount < 0:
            cursor = db.execute(
                """
                UPDATE wallets
                SET balance = balance + ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND balance >= ?
                """,
                (amount, user_id, abs(amount)),
            )
        else:
            cursor = db.execute(
                """
                UPDATE wallets
                SET balance = balance + ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
                """,
                (amount, user_id),
            )
        if cursor.rowcount != 1:
            return False
        db.execute(
            """
            INSERT INTO wallet_transactions (user_id, amount, reason)
            VALUES (?, ?, ?)
            """,
            (user_id, amount, reason),
        )
        return True


def debit_wallet(user_id: int, amount: int, order_id: int) -> bool:
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO wallets (user_id, balance) VALUES (?, 0)", (user_id,))
        cursor = db.execute(
            """
            UPDATE wallets
            SET balance = balance - ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND balance >= ?
            """,
            (amount, user_id, amount),
        )
        if cursor.rowcount != 1:
            return False
        db.execute(
            """
            INSERT INTO wallet_transactions (user_id, amount, reason, order_id)
            VALUES (?, ?, 'order_payment', ?)
            """,
            (user_id, -amount, order_id),
        )
        return True


def create_wallet_topup(data: dict[str, Any]) -> int:
    with connect() as db:
        cursor = db.execute(
            """
            INSERT INTO wallet_topups (user_id, username, amount, status)
            VALUES (?, ?, ?, 'waiting_receipt')
            """,
            (data["user_id"], data.get("username"), data["amount"]),
        )
        return int(cursor.lastrowid)


def set_wallet_topup_receipt(topup_id: int, receipt_file_id: str) -> None:
    with connect() as db:
        db.execute(
            """
            UPDATE wallet_topups
            SET receipt_file_id = ?, status = 'pending_review', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (receipt_file_id, topup_id),
        )


def get_wallet_topup(topup_id: int) -> sqlite3.Row | None:
    with connect() as db:
        return db.execute("SELECT * FROM wallet_topups WHERE id = ?", (topup_id,)).fetchone()


def set_wallet_topup_status(topup_id: int, status: str) -> None:
    with connect() as db:
        db.execute(
            "UPDATE wallet_topups SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, topup_id),
        )


def approve_wallet_topup(topup_id: int) -> sqlite3.Row | None:
    with connect() as db:
        topup = db.execute("SELECT * FROM wallet_topups WHERE id = ?", (topup_id,)).fetchone()
        if not topup or topup["status"] == "approved":
            return topup
        if topup["status"] not in {"pending_review", "waiting_receipt"}:
            return topup
        db.execute(
            "UPDATE wallet_topups SET status = 'approved', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (topup_id,),
        )
        db.execute(
            """
            INSERT INTO wallets (user_id, balance, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                balance = balance + excluded.balance,
                updated_at = CURRENT_TIMESTAMP
            """,
            (topup["user_id"], topup["amount"]),
        )
        db.execute(
            """
            INSERT INTO wallet_transactions (user_id, amount, reason, topup_id)
            VALUES (?, ?, 'topup', ?)
            """,
            (topup["user_id"], topup["amount"], topup_id),
        )
        return db.execute("SELECT * FROM wallet_topups WHERE id = ?", (topup_id,)).fetchone()


def set_delivery(order_id: int, delivery_text: str) -> None:
    with connect() as db:
        db.execute(
            """
            UPDATE orders
            SET delivery_text = ?, status = 'delivered', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (delivery_text, order_id),
        )


def get_order(order_id: int) -> sqlite3.Row | None:
    with connect() as db:
        return db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()


def list_orders(status: str | None = None, limit: int = 10) -> list[sqlite3.Row]:
    query = "SELECT * FROM orders"
    params: list[Any] = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with connect() as db:
        return db.execute(query, params).fetchall()


def list_user_orders(user_id: int, limit: int | None = 10) -> list[sqlite3.Row]:
    limit_clause = "" if limit is None else "LIMIT ?"
    params: list[Any] = [user_id]
    if limit is not None:
        params.append(limit)
    with connect() as db:
        return db.execute(
            f"""
            SELECT *
            FROM orders
            WHERE user_id = ?
            ORDER BY id DESC
            {limit_clause}
            """,
            params,
        ).fetchall()


def count_user_orders_by_status(user_id: int) -> dict[str, int]:
    with connect() as db:
        rows = db.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM orders
            WHERE user_id = ?
            GROUP BY status
            """,
            (user_id,),
        ).fetchall()
    return {row["status"]: int(row["count"]) for row in rows}


def sync_catalog_from_config(categories: dict[str, str], products: dict[str, dict[str, Any]]) -> None:
    with connect() as db:
        for sort_order, (category_key, title) in enumerate(categories.items()):
            db.execute(
                """
                INSERT INTO product_categories (category_key, title, sort_order)
                VALUES (?, ?, ?)
                ON CONFLICT(category_key) DO NOTHING
                """,
                (category_key, title, sort_order),
            )

        for sort_order, (product_key, product) in enumerate(products.items()):
            settings = {
                key: value
                for key, value in product.items()
                if key
                not in {
                    "title",
                    "category",
                    "subcategory",
                    "price",
                    "description",
                    "payment_note",
                }
            }
            db.execute(
                """
                INSERT INTO product_catalog (
                    product_key, title, category_key, subcategory_key, price,
                    description, payment_note, settings_json, sort_order
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(product_key) DO NOTHING
                """,
                (
                    product_key,
                    product["title"],
                    product["category"],
                    product.get("subcategory"),
                    int(product.get("price") or 0),
                    product.get("description"),
                    product.get("payment_note"),
                    json.dumps(settings, ensure_ascii=False),
                    sort_order,
                ),
            )


def list_catalog_categories(include_inactive: bool = False) -> list[sqlite3.Row]:
    query = "SELECT * FROM product_categories"
    if not include_inactive:
        query += " WHERE active = 1"
    query += " ORDER BY sort_order, title"
    with connect() as db:
        return db.execute(query).fetchall()


def list_catalog_products(include_inactive: bool = False) -> list[sqlite3.Row]:
    query = "SELECT * FROM product_catalog"
    if not include_inactive:
        query += " WHERE active = 1"
    query += " ORDER BY sort_order, title"
    with connect() as db:
        return db.execute(query).fetchall()


def get_catalog_product(product_key: str) -> sqlite3.Row | None:
    with connect() as db:
        return db.execute("SELECT * FROM product_catalog WHERE product_key = ?", (product_key,)).fetchone()


def is_catalog_product_active(product_key: str) -> bool:
    row = get_catalog_product(product_key)
    return bool(row["active"]) if row else True


def set_catalog_product_active(product_key: str, active: bool) -> bool:
    with connect() as db:
        cursor = db.execute(
            """
            UPDATE product_catalog
            SET active = ?, updated_at = CURRENT_TIMESTAMP
            WHERE product_key = ?
            """,
            (1 if active else 0, product_key),
        )
        return cursor.rowcount > 0


def update_catalog_product(
    product_key: str,
    *,
    title: str,
    category_key: str,
    subcategory_key: str | None,
    price: int,
    description: str | None,
    payment_note: str | None,
    active: bool,
) -> None:
    with connect() as db:
        db.execute(
            """
            INSERT INTO product_catalog (
                product_key, title, category_key, subcategory_key, price,
                description, payment_note, active, settings_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}')
            ON CONFLICT(product_key) DO UPDATE SET
                title = excluded.title,
                category_key = excluded.category_key,
                subcategory_key = excluded.subcategory_key,
                price = excluded.price,
                description = excluded.description,
                payment_note = excluded.payment_note,
                active = excluded.active,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                product_key,
                title,
                category_key,
                subcategory_key,
                price,
                description,
                payment_note,
                1 if active else 0,
            ),
        )


def count_orders_by_status() -> dict[str, int]:
    with connect() as db:
        rows = db.execute("SELECT status, COUNT(*) AS count FROM orders GROUP BY status").fetchall()
    return {row["status"]: int(row["count"]) for row in rows}


def get_price_override(product_key: str) -> int | None:
    with connect() as db:
        row = db.execute(
            "SELECT price FROM price_overrides WHERE product_key = ?",
            (product_key,),
        ).fetchone()
    return int(row["price"]) if row else None


def set_price_override(product_key: str, price: int) -> None:
    with connect() as db:
        db.execute(
            """
            INSERT INTO price_overrides (product_key, price, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(product_key) DO UPDATE SET
                price = excluded.price,
                updated_at = CURRENT_TIMESTAMP
            """,
            (product_key, price),
        )


def clear_price_override(product_key: str) -> None:
    with connect() as db:
        db.execute("DELETE FROM price_overrides WHERE product_key = ?", (product_key,))


def list_price_overrides() -> dict[str, int]:
    with connect() as db:
        rows = db.execute("SELECT product_key, price FROM price_overrides").fetchall()
    return {row["product_key"]: int(row["price"]) for row in rows}


def get_usd_price_override(product_key: str) -> float | None:
    with connect() as db:
        row = db.execute(
            "SELECT usd_price FROM usd_price_overrides WHERE product_key = ?",
            (product_key,),
        ).fetchone()
    return float(row["usd_price"]) if row else None


def set_usd_price_override(product_key: str, usd_price: float) -> None:
    with connect() as db:
        db.execute(
            """
            INSERT INTO usd_price_overrides (product_key, usd_price, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(product_key) DO UPDATE SET
                usd_price = excluded.usd_price,
                updated_at = CURRENT_TIMESTAMP
            """,
            (product_key, usd_price),
        )


def clear_usd_price_override(product_key: str) -> None:
    with connect() as db:
        db.execute("DELETE FROM usd_price_overrides WHERE product_key = ?", (product_key,))


def list_usd_price_overrides() -> dict[str, float]:
    with connect() as db:
        rows = db.execute("SELECT product_key, usd_price FROM usd_price_overrides").fetchall()
    return {row["product_key"]: float(row["usd_price"]) for row in rows}


def normalize_vpn_unit_price(value: int) -> int:
    if value <= 0:
        return value
    if value < 10_000:
        return value * 1000
    return value


def get_vpn_rate_override(tier_key: str) -> int | None:
    with connect() as db:
        row = db.execute(
            "SELECT unit_price FROM vpn_rate_overrides WHERE tier_key = ?",
            (tier_key,),
        ).fetchone()
    if not row:
        return None
    return normalize_vpn_unit_price(int(row["unit_price"]))


def set_vpn_rate_override(tier_key: str, unit_price: int) -> None:
    unit_price = normalize_vpn_unit_price(unit_price)
    with connect() as db:
        db.execute(
            """
            INSERT INTO vpn_rate_overrides (tier_key, unit_price, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(tier_key) DO UPDATE SET
                unit_price = excluded.unit_price,
                updated_at = CURRENT_TIMESTAMP
            """,
            (tier_key, unit_price),
        )


def list_vpn_rate_overrides() -> dict[str, int]:
    with connect() as db:
        rows = db.execute("SELECT tier_key, unit_price FROM vpn_rate_overrides").fetchall()
    return {row["tier_key"]: int(row["unit_price"]) for row in rows}
