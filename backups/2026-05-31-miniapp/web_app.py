from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlparse

import config
import storage


logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


STATUS_LABELS = {
    "waiting_receipt": "در انتظار فیش",
    "pending_review": "در حال بررسی",
    "approved": "تایید شده",
    "delivered": "انجام شده",
    "rejected": "رد شده",
}


INDEX_HTML = """<!doctype html>
<html lang="fa" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>حساب من | SpotiHyp</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    :root {
      color-scheme: light dark;
      --bg: #f5f7fb;
      --panel: #ffffff;
      --text: #172033;
      --muted: #667085;
      --line: #e4e7ec;
      --green: #12b76a;
      --blue: #2e90fa;
      --orange: #f79009;
      --red: #f04438;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Tahoma, Arial, sans-serif;
      background: var(--tg-theme-bg-color, var(--bg));
      color: var(--tg-theme-text-color, var(--text));
    }
    main {
      width: min(100%, 680px);
      margin: 0 auto;
      padding: 16px;
    }
    .top {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 14px;
    }
    h1 {
      margin: 0;
      font-size: 22px;
      line-height: 1.5;
    }
    .pill {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 6px 10px;
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .card {
      background: var(--tg-theme-secondary-bg-color, var(--panel));
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
    }
    .metric {
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 8px;
    }
    .value {
      font-size: 22px;
      font-weight: 700;
      line-height: 1.4;
    }
    .wide { grid-column: 1 / -1; }
    .row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 10px 0;
      border-bottom: 1px solid var(--line);
    }
    .row:last-child { border-bottom: 0; }
    .title {
      font-size: 14px;
      line-height: 1.6;
    }
    .sub {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.6;
    }
    .status {
      border-radius: 999px;
      padding: 4px 8px;
      font-size: 12px;
      white-space: nowrap;
      background: rgba(46, 144, 250, 0.12);
      color: var(--blue);
    }
    .empty, .error {
      color: var(--muted);
      line-height: 1.8;
      padding: 18px 0;
      text-align: center;
    }
    .error { color: var(--red); }
    @media (max-width: 420px) {
      main { padding: 12px; }
      .grid { grid-template-columns: 1fr; }
      .wide { grid-column: auto; }
      h1 { font-size: 20px; }
    }
  </style>
</head>
<body>
  <main>
    <div class="top">
      <h1>حساب من</h1>
      <div class="pill" id="user-pill">SpotiHyp</div>
    </div>
    <section class="grid" id="content">
      <div class="card wide empty">در حال دریافت اطلاعات...</div>
    </section>
  </main>
  <script>
    const tg = window.Telegram?.WebApp;
    tg?.ready();
    tg?.expand();

    const toman = (value) => value <= 0 ? "۰ تومان" : new Intl.NumberFormat("fa-IR").format(value) + " تومان";
    const number = (value) => new Intl.NumberFormat("fa-IR").format(value);
    const content = document.getElementById("content");
    const userPill = document.getElementById("user-pill");

    function render(data) {
      userPill.textContent = data.user.username ? "@" + data.user.username : "کاربر " + data.user.id;
      const recent = data.recent_orders.length
        ? data.recent_orders.map(order => `
          <div class="row">
            <div>
              <div class="title">${order.product_title}</div>
              <div class="sub">${order.order_code} | ${order.price_text}</div>
            </div>
            <div class="status">${order.status_label}</div>
          </div>
        `).join("")
        : `<div class="empty">هنوز سفارشی ثبت نشده.</div>`;

      content.innerHTML = `
        <div class="card">
          <div class="metric">موجودی کیف پول</div>
          <div class="value">${toman(data.wallet_balance)}</div>
        </div>
        <div class="card">
          <div class="metric">کل سفارش‌ها</div>
          <div class="value">${number(data.orders.total)}</div>
        </div>
        <div class="card">
          <div class="metric">در حال بررسی</div>
          <div class="value">${number(data.orders.pending_review)}</div>
        </div>
        <div class="card">
          <div class="metric">انجام شده</div>
          <div class="value">${number(data.orders.delivered)}</div>
        </div>
        <div class="card wide">
          <div class="metric">آخرین سفارش‌ها</div>
          ${recent}
        </div>
      `;
    }

    async function load() {
      try {
        const response = await fetch("api/me", {
          headers: { "X-Telegram-Init-Data": tg?.initData || "" }
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "خطا در دریافت اطلاعات");
        render(data);
      } catch (error) {
        content.innerHTML = `<div class="card wide error">${error.message}</div>`;
      }
    }
    load();
  </script>
</body>
</html>
"""


def toman(value: int) -> str:
    return "0 تومان" if value <= 0 else f"{value:,} تومان"


def display_order_code(order) -> str:
    return order["order_code"] or f"#{order['id']}"


def validate_init_data(init_data: str) -> dict:
    if not init_data:
        raise ValueError("Mini App فقط از داخل تلگرام باز می‌شود.")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", "")
    if not received_hash:
        raise ValueError("داده ورود تلگرام معتبر نیست.")

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        raise ValueError("امضای تلگرام معتبر نیست.")

    auth_date = int(pairs.get("auth_date", "0") or "0")
    if time.time() - auth_date > 86400:
        raise ValueError("ورود تلگرام منقضی شده. دوباره Mini App را باز کنید.")

    user = json.loads(pairs.get("user", "{}"))
    if not user.get("id"):
        raise ValueError("اطلاعات کاربر دریافت نشد.")
    return user


def user_dashboard(user: dict) -> dict:
    user_id = int(user["id"])
    balance = storage.get_wallet_balance(user_id)
    counts = storage.count_user_orders_by_status(user_id)
    recent_orders = storage.list_user_orders(user_id, limit=5)

    total = sum(counts.values())
    return {
        "user": {
            "id": user_id,
            "username": user.get("username"),
            "first_name": user.get("first_name"),
        },
        "wallet_balance": balance,
        "orders": {
            "total": total,
            "waiting_receipt": counts.get("waiting_receipt", 0),
            "pending_review": counts.get("pending_review", 0),
            "approved": counts.get("approved", 0),
            "delivered": counts.get("delivered", 0),
            "rejected": counts.get("rejected", 0),
        },
        "recent_orders": [
            {
                "id": order["id"],
                "order_code": display_order_code(order),
                "product_title": order["product_title"],
                "price": order["price"],
                "price_text": toman(order["price"]),
                "status": order["status"],
                "status_label": STATUS_LABELS.get(order["status"], order["status"]),
                "created_at": order["created_at"],
            }
            for order in recent_orders
        ],
    }


class MiniAppHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        logger.info("%s - %s", self.address_string(), format % args)

    def send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status: int, payload: dict) -> None:
        self.send_bytes(status, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path in {"/", "/miniapp"}:
            self.send_bytes(200, INDEX_HTML.encode(), "text/html; charset=utf-8")
            return

        if path in {"/api/me", "/miniapp/api/me"}:
            try:
                user = validate_init_data(self.headers.get("X-Telegram-Init-Data", ""))
                storage.upsert_user(
                    SimpleNamespace(
                        id=user["id"],
                        username=user.get("username"),
                        first_name=user.get("first_name"),
                        last_name=user.get("last_name"),
                    )
                )
                self.send_json(200, user_dashboard(user))
            except ValueError as exc:
                self.send_json(401, {"error": str(exc)})
            except Exception:
                logger.exception("Could not load mini app dashboard")
                self.send_json(500, {"error": "خطا در دریافت اطلاعات حساب."})
            return

        self.send_json(404, {"error": "Not found"})


def main() -> None:
    storage.init_db()
    server = ThreadingHTTPServer((config.MINI_APP_HOST, config.MINI_APP_PORT), MiniAppHandler)
    logger.info("Mini App server started on %s:%s", config.MINI_APP_HOST, config.MINI_APP_PORT)
    server.serve_forever()


if __name__ == "__main__":
    main()
