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
  <title>فروشگاه میتسو</title>
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
    .tabs {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      margin-bottom: 12px;
    }
    .tab, .button {
      border: 1px solid var(--line);
      background: var(--tg-theme-secondary-bg-color, var(--panel));
      color: var(--tg-theme-text-color, var(--text));
      border-radius: 8px;
      padding: 10px;
      font: inherit;
      cursor: pointer;
    }
    .tab.active, .button.primary {
      background: var(--tg-theme-button-color, var(--blue));
      color: var(--tg-theme-button-text-color, #fff);
      border-color: transparent;
    }
    .stack { display: grid; gap: 10px; }
    .product-title {
      font-weight: 700;
      font-size: 15px;
      line-height: 1.7;
    }
    .desc {
      white-space: pre-line;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.8;
      margin-top: 6px;
    }
    input, textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      font: inherit;
      background: var(--tg-theme-secondary-bg-color, var(--panel));
      color: var(--tg-theme-text-color, var(--text));
    }
    textarea { min-height: 72px; resize: vertical; }
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
      <h1>فروشگاه میتسو</h1>
      <div class="pill" id="user-pill">Mitso</div>
    </div>
    <nav class="tabs">
      <button class="tab active" data-tab="shop">سرویس‌ها</button>
      <button class="tab" data-tab="account">حساب من</button>
      <button class="tab" data-tab="admin" id="admin-tab" hidden>مدیریت</button>
    </nav>
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

    let state = { me: null, catalog: null, tab: "shop" };

    function setTab(tab) {
      state.tab = tab;
      document.querySelectorAll(".tab").forEach(el => el.classList.toggle("active", el.dataset.tab === tab));
      render();
    }

    function renderAccount(data) {
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

    function renderShop(catalog) {
      const categories = catalog.categories.map(category => {
        const products = catalog.products.filter(product => product.category_key === category.category_key);
        if (!products.length) return "";
        return `
          <div class="card wide">
            <div class="metric">${category.title}</div>
            <div class="stack">
              ${products.map(product => `
                <div class="row">
                  <div>
                    <div class="product-title">${product.title}</div>
                    <div class="sub">${product.price_text}</div>
                    ${product.description ? `<div class="desc">${product.description}</div>` : ""}
                  </div>
                  <button class="button primary" onclick="openBotOrder('${product.product_key}')">سفارش</button>
                </div>
              `).join("")}
            </div>
          </div>
        `;
      }).join("");
      content.className = "grid";
      content.innerHTML = categories || `<div class="card wide empty">فعلاً سرویسی فعال نیست.</div>`;
    }

    function renderAdmin(catalog) {
      content.className = "grid";
      content.innerHTML = `
        <div class="card wide">
          <div class="metric">مدیریت سرویس‌ها</div>
          <div class="stack">
            ${catalog.admin_products.map(product => `
              <form class="stack" data-product="${product.product_key}" onsubmit="saveProduct(event)">
                <div class="sub">${product.product_key}</div>
                <input name="title" value="${product.title.replaceAll('"', '&quot;')}" placeholder="عنوان">
                <input name="price" value="${product.price}" inputmode="numeric" placeholder="قیمت تومان">
                <textarea name="description" placeholder="توضیحات">${product.description || ""}</textarea>
                <label class="sub"><input name="active" type="checkbox" ${product.active ? "checked" : ""}> فعال باشد</label>
                <button class="button primary" type="submit">ذخیره</button>
              </form>
            `).join("")}
          </div>
        </div>
      `;
    }

    function render() {
      if (!state.me || !state.catalog) return;
      document.getElementById("admin-tab").hidden = !state.me.is_admin;
      if (state.tab === "account") return renderAccount(state.me);
      if (state.tab === "admin" && state.me.is_admin) return renderAdmin(state.catalog);
      return renderShop(state.catalog);
    }

    function openBotOrder(productKey) {
      tg?.showAlert?.("فعلاً ثبت نهایی سفارش داخل بات انجام می‌شود. از منوی بات همین سرویس را انتخاب کنید.");
    }

    async function saveProduct(event) {
      event.preventDefault();
      const form = event.currentTarget;
      const payload = {
        product_key: form.dataset.product,
        title: form.elements.title.value,
        price: Number(form.elements.price.value || 0),
        description: form.elements.description.value,
        active: form.elements.active.checked,
      };
      const response = await fetch("api/admin/product", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Telegram-Init-Data": tg?.initData || ""
        },
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!response.ok) return tg?.showAlert?.(data.error || "خطا در ذخیره");
      state.catalog = data.catalog;
      tg?.showAlert?.("ذخیره شد.");
      render();
    }

    async function load() {
      try {
        const [meResponse, catalogResponse] = await Promise.all([
          fetch("api/me", {
            headers: { "X-Telegram-Init-Data": tg?.initData || "" }
          }),
          fetch("api/catalog", {
            headers: { "X-Telegram-Init-Data": tg?.initData || "" }
          })
        ]);
        const data = await meResponse.json();
        const catalog = await catalogResponse.json();
        if (!meResponse.ok) throw new Error(data.error || "خطا در دریافت اطلاعات");
        if (!catalogResponse.ok) throw new Error(catalog.error || "خطا در دریافت سرویس‌ها");
        state.me = data;
        state.catalog = catalog;
        render();
      } catch (error) {
        content.innerHTML = `<div class="card wide error">${error.message}</div>`;
      }
    }
    document.querySelectorAll(".tab").forEach(el => el.addEventListener("click", () => setTab(el.dataset.tab)));
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


def catalog_payload(include_admin: bool = False) -> dict:
    categories = storage.list_catalog_categories(include_inactive=include_admin)
    products = storage.list_catalog_products(include_inactive=include_admin)
    payload = {
        "categories": [
            {
                "category_key": category["category_key"],
                "title": category["title"],
                "active": bool(category["active"]),
            }
            for category in categories
        ],
        "products": [
            {
                "product_key": product["product_key"],
                "title": product["title"],
                "category_key": product["category_key"],
                "subcategory_key": product["subcategory_key"],
                "price": int(product["price"]),
                "price_text": toman(int(product["price"])),
                "active": bool(product["active"]),
                "description": product["description"] or "",
                "payment_note": product["payment_note"] or "",
            }
            for product in products
            if include_admin or product["active"]
        ],
    }
    if include_admin:
        payload["admin_products"] = payload["products"]
    return payload


def is_admin_user(user: dict) -> bool:
    try:
        return int(user["id"]) in config.ADMIN_IDS
    except (KeyError, TypeError, ValueError):
        return False


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
                dashboard = user_dashboard(user)
                dashboard["is_admin"] = is_admin_user(user)
                self.send_json(200, dashboard)
            except ValueError as exc:
                self.send_json(401, {"error": str(exc)})
            except Exception:
                logger.exception("Could not load mini app dashboard")
                self.send_json(500, {"error": "خطا در دریافت اطلاعات حساب."})
            return

        if path in {"/api/catalog", "/miniapp/api/catalog"}:
            try:
                user = validate_init_data(self.headers.get("X-Telegram-Init-Data", ""))
                self.send_json(200, catalog_payload(include_admin=is_admin_user(user)))
            except ValueError as exc:
                self.send_json(401, {"error": str(exc)})
            except Exception:
                logger.exception("Could not load mini app catalog")
                self.send_json(500, {"error": "خطا در دریافت لیست سرویس‌ها."})
            return

        self.send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path not in {"/api/admin/product", "/miniapp/api/admin/product"}:
            self.send_json(404, {"error": "Not found"})
            return

        try:
            user = validate_init_data(self.headers.get("X-Telegram-Init-Data", ""))
            if not is_admin_user(user):
                self.send_json(403, {"error": "دسترسی ادمین لازم است."})
                return

            length = int(self.headers.get("Content-Length", "0") or "0")
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            product_key = str(payload.get("product_key") or "").strip()
            title = str(payload.get("title") or "").strip()
            if not product_key or not title:
                self.send_json(400, {"error": "شناسه و عنوان محصول الزامی است."})
                return

            current_products = {product["product_key"]: product for product in storage.list_catalog_products(include_inactive=True)}
            current = current_products.get(product_key)
            category_key = current["category_key"] if current else "other"
            subcategory_key = current["subcategory_key"] if current else None
            price = max(0, int(payload.get("price") or 0))
            storage.update_catalog_product(
                product_key,
                title=title,
                category_key=category_key,
                subcategory_key=subcategory_key,
                price=price,
                description=str(payload.get("description") or "").strip(),
                payment_note=current["payment_note"] if current else None,
                active=bool(payload.get("active")),
            )
            if product_key in config.PRODUCTS and not config.PRODUCTS[product_key].get("variable_volume"):
                storage.set_price_override(product_key, price)
            self.send_json(200, {"ok": True, "catalog": catalog_payload(include_admin=True)})
        except ValueError as exc:
            self.send_json(401, {"error": str(exc)})
        except Exception:
            logger.exception("Could not update product from mini app")
            self.send_json(500, {"error": "خطا در ذخیره سرویس."})


def main() -> None:
    storage.init_db()
    storage.sync_catalog_from_config(config.CATEGORIES, config.PRODUCTS)
    server = ThreadingHTTPServer((config.MINI_APP_HOST, config.MINI_APP_PORT), MiniAppHandler)
    logger.info("Mini App server started on %s:%s", config.MINI_APP_HOST, config.MINI_APP_PORT)
    server.serve_forever()


if __name__ == "__main__":
    main()
