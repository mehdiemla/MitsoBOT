from __future__ import annotations

import os
from pathlib import Path


def _parse_admin_ids(value: str) -> set[int]:
    admin_ids: set[int] = set()
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        admin_ids.add(int(item))
    return admin_ids


def _parse_usernames(value: str) -> list[str]:
    usernames: list[str] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        if not item.startswith("@"):
            item = f"@{item}"
        usernames.append(item)
    return usernames


def _load_dotenv() -> None:
    env_path = Path(__file__).with_name(".env")
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'").replace("\\n", "\n"))


_load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "@admin")
SUPPORT_USERNAMES = _parse_usernames(os.getenv("SUPPORT_USERNAMES", ADMIN_USERNAME))
PAYMENT_TEXT = os.getenv(
    "PAYMENT_TEXT",
    "💳 لطفاً مبلغ سفارش را به کارت زیر واریز کنید:\n\n"
    "شماره کارت:\n"
    "6219861922971105\n"
    "به نام: لشگری\n\n"
    "بعد از پرداخت، تصویر فیش یا رسید را همینجا ارسال کنید تا سفارش سریع‌تر بررسی و پردازش شود.",
)
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "")
SUPPORT_SITE = os.getenv("SUPPORT_SITE", "https://t.me")
MINI_APP_URL = os.getenv("MINI_APP_URL", f"{SUPPORT_SITE.rstrip('/')}/")
MINI_APP_HOST = os.getenv("MINI_APP_HOST", "127.0.0.1")
MINI_APP_PORT = int(os.getenv("MINI_APP_PORT", "8090"))
BITPIN_MARKETS_URL = os.getenv("BITPIN_MARKETS_URL", "https://api.bitpin.ir/v1/mkt/markets/")

CATEGORIES = {
    "other": "سرویس‌های Mitso 🛠",
}

PRODUCTS = {
    "v2ray_custom": {
        "title": "🌐 V2Ray حجم دلخواه",
        "category": "other",
        "subcategory": "v2ray",
        "price": 0,
        "needs_credentials": False,
        "variable_volume": True,
        "payment_note": "تعرفه V2Ray به ازای هر گیگ ۱۱۰ هزار تومان است. تحویل سفارش: ۱ تا ۲۴ ساعت کاری.",
        "description": (
            "سرویس V2Ray با حجم دلخواه ثبت می‌شود.\n"
            "قیمت هر گیگ: ۱۱۰ هزار تومان.\n"
            "بعد از تایید پرداخت، اطلاعات اتصال داخل همین بات ارسال می‌شود."
        ),
    },
    "openvpn_unlimited_1user_1": {
        "title": "🔐 OpenVPN نامحدود تک‌کاربره 1 ماهه",
        "category": "other",
        "subcategory": "openvpn",
        "price": 550_000,
        "needs_credentials": False,
        "description": (
            "OpenVPN نامحدود یک‌ماهه و تک‌کاربره است.\n"
            "قیمت: ۵۵۰ هزار تومان.\n"
            "بعد از تایید سفارش، فایل اتصال داخل همین بات ارسال می‌شود."
        ),
        "payment_note": (
            "OpenVPN نامحدود یک‌ماهه و تک‌کاربره است.\n"
            "قیمت: ۵۵۰ هزار تومان.\n"
            "فایل OpenVPN بعد از آماده شدن سفارش داخل همین بات ارسال می‌شود."
        ),
    },
}

CATEGORY_ORDER_SUMMARIES = {
    "other": "سرویس VPN | تحویل: ۱ تا ۲۴ ساعت کاری",
}

SUBCATEGORY_ORDER_SUMMARIES = {
    "v2ray": "V2Ray حجم دلخواه | هر گیگ ۱۱۰ هزار تومان | تحویل: ۱ تا ۲۴ ساعت کاری",
    "openvpn": "OpenVPN نامحدود تک‌کاربره | قیمت ۵۵۰ هزار تومان | تحویل فایل داخل بات",
}

PRODUCT_ORDER_SUMMARIES = {
    "v2ray_custom": "V2Ray حجم دلخواه | هر گیگ ۱۱۰ هزار تومان | تحویل: ۱ تا ۲۴ ساعت کاری",
    "openvpn_unlimited_1user_1": "OpenVPN نامحدود تک‌کاربره ۱ ماهه | قیمت ۵۵۰ هزار تومان | تحویل فایل داخل بات",
}


def get_order_summary(product_key: str) -> str:
    if product_key in PRODUCT_ORDER_SUMMARIES:
        return PRODUCT_ORDER_SUMMARIES[product_key]
    product = PRODUCTS.get(product_key)
    if not product:
        return "تحویل: ۱ تا ۲۴ ساعت کاری"
    subcategory = product.get("subcategory")
    if subcategory and subcategory in SUBCATEGORY_ORDER_SUMMARIES:
        return SUBCATEGORY_ORDER_SUMMARIES[subcategory]
    category = product.get("category")
    if category and category in CATEGORY_ORDER_SUMMARIES:
        return CATEGORY_ORDER_SUMMARIES[category]
    return "تحویل: ۱ تا ۲۴ ساعت کاری"
