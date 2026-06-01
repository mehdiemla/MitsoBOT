from __future__ import annotations

import logging
import re
import json
import threading
import time
import urllib.request
from html import escape, unescape

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
    WebAppInfo,
)
from telegram.constants import KeyboardButtonStyle
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import config
import storage


(
    SELECTING_PRODUCT,
    ASK_VPN_VOLUME,
    ASK_TELEGRAM_ID,
    ASK_SPOTIFY_EMAIL,
    ASK_SPOTIFY_PASSWORD,
    ASK_APPLE_ID,
    ASK_CHATGPT_SESSION,
    ASK_CLAUDE_USER_ID,
    ASK_DISCOUNT_CODE,
    ASK_PAYMENT_METHOD,
    ASK_RECEIPT,
    ASK_WALLET_AMOUNT,
    ASK_WALLET_RECEIPT,
    ASK_FOREIGN_SITE_URL,
    ASK_FOREIGN_USD_AMOUNT,
    ASK_FOREIGN_USERNAME,
    ASK_FOREIGN_PASSWORD,
    ASK_SPOTIFY_ACCOUNT_CHOICE,
) = range(18)
logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
USDT_CACHE_SECONDS = 300
SAFE_TELEGRAM_TEXT_LIMIT = 3500
usdt_cache: dict[str, float] = {"price": 0.0, "updated_at": 0.0}
VPN_RATE_TIERS = {
    "1_5": {"label": "1 تا 5 گیگ", "default": 109_000},
    "5_plus": {"label": "بیشتر از 5 گیگ", "default": 77_000},
}
FOREIGN_PAYMENT_PRODUCT_KEY = "foreign_site_payment"
V2RAY_ONE_GB_BLOCK_MESSAGE = (
    "به دلیل حجم بالای تراکنش‌ها، هر کاربر فقط یک بار می‌تواند سفارش V2Ray 1 گیگ ثبت کند.\n"
    "شما قبلاً یک سفارش 1 گیگ V2Ray ثبت کرده‌اید.\n\n"
    "برای سفارش مجدد می‌توانید حجم بالاتر از 1 گیگ انتخاب کنید."
)


def toman(value: int) -> str:
    return "قیمت ثبت نشده" if value <= 0 else f"{value:,} تومان"


def payable_toman(value: int) -> str:
    return "0 تومان" if value == 0 else toman(value)


def plain_text_from_html(text: str) -> str:
    text = re.sub(r"</?code>", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    return unescape(text)


def split_long_text(text: str, limit: int = SAFE_TELEGRAM_TEXT_LIMIT) -> list[str]:
    parts: list[str] = []
    remaining = text.strip()
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at < limit // 2:
            split_at = limit
        parts.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        parts.append(remaining)
    return parts or [""]


async def send_long_message(
    bot,
    chat_id: int,
    text: str,
    parse_mode: str | None = None,
    reply_markup=None,
) -> None:
    if len(text) <= SAFE_TELEGRAM_TEXT_LIMIT:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
            return
        except BadRequest:
            if parse_mode is None:
                raise
            text = plain_text_from_html(text)
            parse_mode = None

    if parse_mode is not None:
        text = plain_text_from_html(text)
        parse_mode = None

    for index, part in enumerate(split_long_text(text)):
        await bot.send_message(
            chat_id=chat_id,
            text=part,
            parse_mode=parse_mode,
            reply_markup=reply_markup if index == 0 else None,
        )


def round_toman_up_to_thousand(value: float) -> int:
    return int(-(-value // 1000) * 1000)


def fetch_usdt_toman_price_from_api() -> float:
    with urllib.request.urlopen(config.BITPIN_MARKETS_URL, timeout=10) as response:
        data = json.load(response)

    markets = data.get("results", data) if isinstance(data, dict) else data
    for market in markets:
        if market.get("code") == "USDT_IRT":
            price_info = market.get("price_info") or {}
            return float(price_info.get("price") or market["price"])
    raise RuntimeError("USDT_IRT market not found in Bitpin response")


def refresh_usdt_cache() -> None:
    price = fetch_usdt_toman_price_from_api()
    usdt_cache.update({"price": price, "updated_at": time.time()})
    logger.info("USDT cache updated: %s", price)


def start_usdt_cache_updater() -> None:
    def update_loop() -> None:
        while True:
            try:
                refresh_usdt_cache()
            except Exception as exc:
                if usdt_cache["price"]:
                    logger.warning(
                        "Could not refresh USDT cache; keeping cached price %s: %s",
                        usdt_cache["price"],
                        exc,
                    )
                else:
                    logger.warning("Could not refresh USDT cache; dynamic prices will use fallback prices: %s", exc)
            time.sleep(USDT_CACHE_SECONDS)

    thread = threading.Thread(target=update_loop, name="usdt-cache-updater", daemon=True)
    thread.start()


def dynamic_usd_price_toman(product_key: str) -> int | None:
    usd_price = storage.get_usd_price_override(product_key)
    if usd_price is None:
        usd_price = config.PRODUCTS[product_key].get("usd_price")
    if usd_price is None:
        return None

    usdt_price = usdt_cache["price"]
    if not usdt_price:
        return None
    return round_toman_up_to_thousand(float(usd_price) * usdt_price)


def uses_usd_pricing(product_key: str) -> bool:
    product = config.PRODUCTS[product_key]
    return product.get("usd_price") is not None or storage.get_usd_price_override(product_key) is not None


def foreign_payment_multiplier(usd_amount: float) -> float:
    if usd_amount <= 10:
        return 1.25
    if usd_amount <= 20:
        return 1.20
    if usd_amount <= 100:
        return 1.15
    return 1.05


def foreign_payment_base_toman(usd_amount: float) -> int | None:
    usdt_price = usdt_cache["price"]
    if not usdt_price:
        return None
    return round_toman_up_to_thousand(usd_amount * usdt_price)


def foreign_payment_total_toman(usd_amount: float) -> int | None:
    usdt_price = usdt_cache["price"]
    if not usdt_price:
        return None
    multiplier = foreign_payment_multiplier(usd_amount)
    return round_toman_up_to_thousand(usd_amount * usdt_price * multiplier)


def foreign_payment_service_fee_toman(usd_amount: float) -> int | None:
    base = foreign_payment_base_toman(usd_amount)
    total = foreign_payment_total_toman(usd_amount)
    if base is None or total is None:
        return None
    return max(0, total - base)


def foreign_payment_service_fee_text(usd_amount: float) -> str | None:
    fee = foreign_payment_service_fee_toman(usd_amount)
    total = foreign_payment_total_toman(usd_amount)
    if fee is None or total is None:
        return None
    return (
        f"هزینه انجام خدمات و کارمزد: {toman(fee)}\n"
        f"هزینه سرویس: {toman(total)}"
    )


def foreign_payment_admin_pricing_text(usd_amount: float) -> str:
    base = foreign_payment_base_toman(usd_amount)
    fee = foreign_payment_service_fee_toman(usd_amount)
    total = foreign_payment_total_toman(usd_amount)
    if base is None or fee is None or total is None:
        return f"مبلغ دلاری: {usd_amount:g}$"
    multiplier = foreign_payment_multiplier(usd_amount)
    return (
        f"مبلغ دلاری: {usd_amount:g}$\n"
        f"نرخ پایه: {toman(base)}\n"
        f"کارمزد ({multiplier:.2f}x): {toman(fee)}\n"
        f"مبلغ نهایی: {toman(total)}"
    )


def is_foreign_payment_product(product_key: str) -> bool:
    return bool(config.PRODUCTS.get(product_key, {}).get("variable_foreign_payment"))


def product_price(product_key: str) -> int:
    if config.PRODUCTS[product_key].get("variable_volume"):
        return 0
    if config.PRODUCTS[product_key].get("variable_foreign_payment"):
        return 0
    if uses_usd_pricing(product_key):
        dynamic_price = dynamic_usd_price_toman(product_key)
        if dynamic_price is not None:
            return dynamic_price
        return int(config.PRODUCTS[product_key]["price"])
    override = storage.get_price_override(product_key)
    if override is not None:
        return override
    return int(config.PRODUCTS[product_key]["price"])


def product_title(product_key: str) -> str:
    catalog_product = storage.get_catalog_product(product_key)
    if catalog_product:
        return catalog_product["title"]
    return config.PRODUCTS[product_key]["title"]


def product_payment_note(product_key: str) -> str:
    catalog_product = storage.get_catalog_product(product_key)
    if catalog_product and catalog_product["payment_note"]:
        return catalog_product["payment_note"]
    return config.PRODUCTS.get(product_key, {}).get("payment_note", "")


def product_order_summary_text(product_key: str) -> str:
    summary = config.get_order_summary(product_key)
    if not summary:
        return ""
    return f"\n\n📋 {summary}"


def product_credential_note(product_key: str) -> str:
    return config.PRODUCTS.get(product_key, {}).get("credential_note", "")


def order_original_price(order) -> int:
    if "original_price" in order.keys() and order["original_price"] is not None:
        return int(order["original_price"])
    return int(order["price"])


def order_discount_summary(order) -> str:
    if "discount_code" not in order.keys() or not order["discount_code"]:
        return ""
    return (
        f"\nکد تخفیف: {order['discount_code']} ({order['discount_percent']}٪)"
        f"\nمبلغ کسرشده: {toman(order['discount_amount'] or 0)}"
        f"\nمبلغ قبل از تخفیف: {toman(order_original_price(order))}"
    )


def discount_scope_label(discount) -> str:
    if "product_key" not in discount.keys() or not discount["product_key"]:
        return "همه سرویس‌ها"
    product = config.PRODUCTS.get(discount["product_key"])
    if product:
        return product["title"]
    return discount["product_key"]


def support_contacts_text() -> str:
    return " یا ".join(config.SUPPORT_USERNAMES)


async def respond_in_place(update: Update, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
        return
    await update.effective_message.reply_text(text, reply_markup=reply_markup)


async def clear_legacy_reply_keyboard(update: Update) -> None:
    if update.callback_query or not update.effective_message:
        return
    try:
        message = await update.effective_message.reply_text(
            "در حال آماده‌سازی منو...",
            reply_markup=ReplyKeyboardRemove(),
        )
        await message.delete()
    except Exception:
        logger.debug("Could not clear legacy reply keyboard", exc_info=True)


def normalize_number_text(value: str) -> str:
    translation = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫،", "01234567890123456789..")
    normalized = value.translate(translation).strip().replace(",", ".")
    match = re.search(r"\d+(?:\.\d+)?", normalized)
    return match.group(0) if match else normalized


def normalize_int_text(value: str) -> str:
    return normalize_number_text(value).replace(".", "")


def vpn_unit_price(volume_gb: float) -> int:
    tier_key = "1_5" if 1 <= volume_gb <= 5 else "5_plus"

    override = storage.get_vpn_rate_override(tier_key)
    if override is not None:
        return override
    return int(VPN_RATE_TIERS[tier_key]["default"])


def vpn_rates_text() -> str:
    lines = []
    for tier_key, tier in VPN_RATE_TIERS.items():
        unit_price = storage.get_vpn_rate_override(tier_key)
        if unit_price is None:
            unit_price = int(tier["default"])
        lines.append(f"✅ {tier['label']}: هر گیگ {unit_price:,} تومان")
    return "\n".join(lines)


def format_volume(volume_gb: float) -> str:
    if volume_gb.is_integer():
        return str(int(volume_gb))
    return f"{volume_gb:g}"


def v2ray_one_gb_limit_blocks_user(user_id: int) -> bool:
    if not storage.is_v2ray_one_gb_limit_enabled():
        return False
    if storage.is_user_v2ray_one_gb_exempt(user_id):
        return False
    return storage.user_has_v2ray_one_gb_order(user_id)


def remember_user(update: Update) -> None:
    if update.effective_user:
        storage.upsert_user(update.effective_user)


BACK_TO_CATEGORIES_TEXT = "⬅️ بازگشت به دسته‌بندی‌ها"
BACK_TO_EDIT_SUBCATEGORIES_TEXT = "⬅️ بازگشت به Canva، CapCut و Figma"
BACK_TO_MUSIC_SUBCATEGORIES_TEXT = "⬅️ بازگشت به موسیقی و پادکست"
BACK_TO_AI_SUBCATEGORIES_TEXT = "⬅️ بازگشت به هوش مصنوعی و AI"
BACK_TO_OTHER_SUBCATEGORIES_TEXT = "⬅️ بازگشت به سرویس‌های دیگر"
BACK_TO_SOCIAL_SUBCATEGORIES_TEXT = "⬅️ بازگشت به سوشال مدیا"
WALLET_TEXT = "💳 کیف پول"
RULES_TEXT = "📜 قوانین"
SHOP_RULES = (
    "قوانین فروشگاه Mitso\n\n"
    "• تمامی سفارشات بین ۱ تا ۲۴ ساعت کاری پردازش و تکمیل می‌شوند.\n\n"
    "• زمان بررسی و تایید فیش‌های واریزی، همه‌روزه از ساعت ۱۰ صبح الی ۱۰ شب می‌باشد.\n\n"
    "• زمان تحویل سفارشات، همه‌روزه از ساعت ۱۲ ظهر الی ۱۰ شب می‌باشد.\n\n"
    "• لطفاً در ثبت سفارش خود دقت فرمایید؛ پس از ثبت، امکان لغو یا عودت وجه وجود ندارد، مگر در صورتی که مشکل از سمت Mitso باشد.\n\n"
    "• در روزهای پنج‌شنبه و جمعه، به دلیل تعطیلات، پردازش سفارشات و تایید رسیدها ممکن است با تاخیر بیشتری انجام شود."
)
RULES_ACCEPTANCE_NOTE = (
    "\n\n⚠️ برای ثبت سفارش، ابتدا باید قوانین را مطالعه کرده و تایید کنید."
)
MUSIC_CATEGORY_KEY = "spotify"
EDIT_CATEGORY_KEY = "capcut"
AI_CATEGORY_KEY = "ai"
OTHER_CATEGORY_KEY = "other"
SOCIAL_CATEGORY_KEY = "social"
EDIT_SUBCATEGORIES = {
    "capcut": "🎬 CapCut",
    "canva": "🎨 Canva",
    "figma": "🎨 Figma",
}
MUSIC_SUBCATEGORIES = {
    "spotify": "🎵 Spotify",
    "soundcloud": "🎧 SoundCloud",
    "apple_music": "🎵 Apple Music",
    "castbox": "🎙 Castbox",
}
AI_SUBCATEGORIES = {
    "chatgpt": "🤖 ChatGPT",
    "claude": "🧠 Claude",
    "gemini": "✨ Gemini",
    "grok": "⚡ Grok",
    "cursor": "💻 Cursor",
}
OTHER_SUBCATEGORIES = {
    "v2ray": "🌐 V2Ray",
    "openvpn": "🔐 OpenVPN",
    "happ": "🌍 Happ مولتی‌لوکیشن",
    "windscribe": "🌬 Windscribe",
    "expressvpn": "🚀 ExpressVPN",
}
SOCIAL_SUBCATEGORIES = {
    "telegram": "⭐ Telegram Premium",
    "linkedin": "💼 LinkedIn",
}
CATEGORY_SUBCATEGORIES = {
    MUSIC_CATEGORY_KEY: MUSIC_SUBCATEGORIES,
    EDIT_CATEGORY_KEY: EDIT_SUBCATEGORIES,
    AI_CATEGORY_KEY: AI_SUBCATEGORIES,
    OTHER_CATEGORY_KEY: OTHER_SUBCATEGORIES,
    SOCIAL_CATEGORY_KEY: SOCIAL_SUBCATEGORIES,
}
BACK_TO_SUBCATEGORIES_TEXT = {
    MUSIC_CATEGORY_KEY: BACK_TO_MUSIC_SUBCATEGORIES_TEXT,
    EDIT_CATEGORY_KEY: BACK_TO_EDIT_SUBCATEGORIES_TEXT,
    AI_CATEGORY_KEY: BACK_TO_AI_SUBCATEGORIES_TEXT,
    OTHER_CATEGORY_KEY: BACK_TO_OTHER_SUBCATEGORIES_TEXT,
    SOCIAL_CATEGORY_KEY: BACK_TO_SOCIAL_SUBCATEGORIES_TEXT,
}


def inline_button(
    text: str,
    *,
    callback_data: str | None = None,
    url: str | None = None,
    web_app_url: str | None = None,
    style: str | None = None,
) -> InlineKeyboardButton:
    web_app = WebAppInfo(web_app_url) if web_app_url else None
    return InlineKeyboardButton(text, callback_data=callback_data, url=url, web_app=web_app, style=style)


# primary = آبی | success = سبز | danger = قرمز
CATEGORY_BUTTON_STYLES = {
    "spotify": KeyboardButtonStyle.SUCCESS,   # موسیقی / Spotify
    "capcut": KeyboardButtonStyle.PRIMARY,    # ادیت و طراحی
    "ai": KeyboardButtonStyle.PRIMARY,        # AI / تکنولوژی
    "education": KeyboardButtonStyle.SUCCESS, # آموزشی / رشد
    "social": KeyboardButtonStyle.PRIMARY,      # تلگرام / شبکه اجتماعی
    "finance": KeyboardButtonStyle.SUCCESS,   # پکیج مالی
    "sim": KeyboardButtonStyle.PRIMARY,       # سیم‌کارت / اتصال
    "other": KeyboardButtonStyle.SUCCESS,       # VPN و سرویس شبکه
}

SUBCATEGORY_BUTTON_STYLES = {
    "spotify": KeyboardButtonStyle.SUCCESS,
    "soundcloud": KeyboardButtonStyle.PRIMARY,
    "apple_music": KeyboardButtonStyle.PRIMARY,
    "castbox": KeyboardButtonStyle.SUCCESS,
    "capcut": KeyboardButtonStyle.PRIMARY,
    "canva": KeyboardButtonStyle.SUCCESS,
    "figma": KeyboardButtonStyle.PRIMARY,
    "chatgpt": KeyboardButtonStyle.SUCCESS,
    "claude": KeyboardButtonStyle.PRIMARY,
    "gemini": KeyboardButtonStyle.PRIMARY,
    "grok": KeyboardButtonStyle.PRIMARY,
    "cursor": KeyboardButtonStyle.SUCCESS,
    "v2ray": KeyboardButtonStyle.SUCCESS,
    "openvpn": KeyboardButtonStyle.PRIMARY,
    "happ": KeyboardButtonStyle.PRIMARY,
    "windscribe": KeyboardButtonStyle.PRIMARY,
    "expressvpn": KeyboardButtonStyle.SUCCESS,
}

PRODUCT_BUTTON_STYLES = {
    "spotihyp_finance_package": KeyboardButtonStyle.SUCCESS,
    "telegram_premium_3": KeyboardButtonStyle.PRIMARY,
    "telegram_premium_6": KeyboardButtonStyle.PRIMARY,
    "telegram_premium_12": KeyboardButtonStyle.PRIMARY,
    "duolingo_super_12": KeyboardButtonStyle.SUCCESS,
    "duolingo_max_12": KeyboardButtonStyle.SUCCESS,
    "duolingo_team_12": KeyboardButtonStyle.SUCCESS,
}


def category_button_style(category_key: str) -> str:
    return CATEGORY_BUTTON_STYLES.get(category_key, KeyboardButtonStyle.PRIMARY)


def product_button_style(product_key: str, product: dict) -> str:
    if product_key in PRODUCT_BUTTON_STYLES:
        return PRODUCT_BUTTON_STYLES[product_key]
    subcategory = product.get("subcategory")
    if subcategory:
        return SUBCATEGORY_BUTTON_STYLES.get(subcategory, category_button_style(product["category"]))
    return category_button_style(product["category"])


def button_rows(buttons: list[InlineKeyboardButton], size: int = 2) -> list[list[InlineKeyboardButton]]:
    return [buttons[index : index + size] for index in range(0, len(buttons), size)]


def categories_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        inline_button(
            title,
            callback_data=f"category:{key}",
            style=category_button_style(key),
        )
        for key, title in config.CATEGORIES.items()
    ]
    rows = button_rows(buttons, 2)
    rows.append(
        [
            inline_button("📜 قوانین", callback_data="rules", style=KeyboardButtonStyle.DANGER),
            inline_button("💳 کیف پول", callback_data="wallet_show", style=KeyboardButtonStyle.SUCCESS),
        ]
    )
    rows.append(
        [
            inline_button("سفارش‌های من 📦", callback_data="myorders", style=KeyboardButtonStyle.PRIMARY),
        ]
    )
    if config.MINI_APP_ENABLED and config.is_valid_mini_app_url(config.MINI_APP_URL):
        rows.append(
            [
                inline_button(
                    "باز کردن فروشگاه میتسو 🛍",
                    web_app_url=config.MINI_APP_URL,
                    style=KeyboardButtonStyle.SUCCESS,
                ),
            ]
        )
    return InlineKeyboardMarkup(rows)


def products_keyboard(category_key: str) -> InlineKeyboardMarkup:
    buttons = [
        inline_button(
            product_title(key),
            callback_data=f"product:{key}",
            style=product_button_style(key, item),
        )
        for key, item in config.PRODUCTS.items()
        if item["category"] == category_key and storage.is_catalog_product_active(key)
    ]
    rows = button_rows(buttons, 2)
    rows.append([
        inline_button("⬅️ بازگشت به دسته‌بندی‌ها", callback_data="back:categories", style=KeyboardButtonStyle.PRIMARY)
    ])
    return InlineKeyboardMarkup(rows)


def subcategories_keyboard(category_key: str) -> InlineKeyboardMarkup:
    buttons = [
        inline_button(
            title,
            callback_data=f"subcategory:{category_key}:{key}",
            style=SUBCATEGORY_BUTTON_STYLES.get(key, category_button_style(category_key)),
        )
        for key, title in CATEGORY_SUBCATEGORIES[category_key].items()
    ]
    rows = button_rows(buttons, 2)
    rows.append([
        inline_button("⬅️ بازگشت به دسته‌بندی‌ها", callback_data="back:categories", style=KeyboardButtonStyle.PRIMARY)
    ])
    return InlineKeyboardMarkup(rows)


def products_by_subcategory_keyboard(category_key: str, subcategory_key: str) -> InlineKeyboardMarkup:
    buttons = [
        inline_button(
            product_title(key),
            callback_data=f"product:{key}",
            style=product_button_style(key, item),
        )
        for key, item in config.PRODUCTS.items()
        if item["category"] == category_key
        and item.get("subcategory") == subcategory_key
        and storage.is_catalog_product_active(key)
    ]
    rows = button_rows(buttons, 2)
    rows.append(
        [
            inline_button(
                BACK_TO_SUBCATEGORIES_TEXT[category_key],
                callback_data=f"back:category:{category_key}",
                style=KeyboardButtonStyle.PRIMARY,
            )
        ]
    )
    rows.append([
        inline_button("⬅️ بازگشت به دسته‌بندی‌ها", callback_data="back:categories", style=KeyboardButtonStyle.PRIMARY)
    ])
    return InlineKeyboardMarkup(rows)


def subcategory_products_text(category_key: str, subcategory_key: str) -> str:
    products = [
        (key, item)
        for key, item in config.PRODUCTS.items()
        if item["category"] == category_key
        and item.get("subcategory") == subcategory_key
        and storage.is_catalog_product_active(key)
    ]
    if not products:
        return "پلنی برای این بخش ثبت نشده است."

    lines = ["پلن‌ها و قیمت‌ها:"]
    for product_key, product in products:
        if product.get("variable_volume"):
            lines.append(f"• {product_title(product_key)}: هر گیگ 99,000 تومان، حجم دلخواه")
        else:
            lines.append(f"• {product_title(product_key)}: {toman(product_price(product_key))}")
    return "\n".join(lines)


def subcategory_context_by_title(text: str) -> tuple[str, str] | None:
    for category_key, subcategories in CATEGORY_SUBCATEGORIES.items():
        for subcategory_key, subcategory_title in subcategories.items():
            if text == subcategory_title:
                return category_key, subcategory_key
    return None


def is_navigation_text(text: str) -> bool:
    if text in config.CATEGORIES.values():
        return True
    if subcategory_context_by_title(text):
        return True
    if text in {
        BACK_TO_CATEGORIES_TEXT,
        BACK_TO_EDIT_SUBCATEGORIES_TEXT,
        BACK_TO_MUSIC_SUBCATEGORIES_TEXT,
        BACK_TO_AI_SUBCATEGORIES_TEXT,
        BACK_TO_OTHER_SUBCATEGORIES_TEXT,
        WALLET_TEXT,
        RULES_TEXT,
    }:
        return True
    return any(text == product_title(product_key) for product_key in config.PRODUCTS)


def admin_review_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                inline_button("تایید فیش", callback_data=f"approve:{order_id}", style=KeyboardButtonStyle.SUCCESS),
                inline_button("رد فیش", callback_data=f"reject:{order_id}", style=KeyboardButtonStyle.DANGER),
            ]
        ]
    )


def payment_method_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                inline_button("💳 کیف پول", callback_data=f"pay_wallet:{order_id}", style=KeyboardButtonStyle.SUCCESS),
                inline_button("🏦 کارت به کارت", callback_data=f"pay_card:{order_id}", style=KeyboardButtonStyle.PRIMARY),
            ],
        ]
    )


def discount_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                inline_button("🎁 کد تخفیف دارم", callback_data=f"discount_enter:{order_id}", style=KeyboardButtonStyle.SUCCESS),
                inline_button("➡️ بدون کد", callback_data=f"discount_skip:{order_id}", style=KeyboardButtonStyle.PRIMARY),
            ],
        ]
    )


def skip_discount_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[inline_button("➡️ ادامه بدون کد تخفیف", callback_data=f"discount_skip:{order_id}", style=KeyboardButtonStyle.PRIMARY)]]
    )


def finish_chatgpt_session_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[inline_button("✅ اتمام و ادامه پرداخت", callback_data="finish_chatgpt_session", style=KeyboardButtonStyle.SUCCESS)]]
    )


def own_username_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[inline_button("👤 ارسال نام کاربری خودم", callback_data="use_own_username", style=KeyboardButtonStyle.PRIMARY)]]
    )


def spotify_account_choice_keyboard() -> InlineKeyboardMarkup:
    fee_text = toman(config.SPOTIFY_ACCOUNT_CREATION_FEE)
    return InlineKeyboardMarkup([
        [inline_button("✅ اکانت Spotify دارم", callback_data="spotify_has_account", style=KeyboardButtonStyle.PRIMARY)],
        [inline_button(f"❌ اکانت ندارم (+{fee_text})", callback_data="spotify_no_account")],
    ])


def skip_foreign_username_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[inline_button("➡️ نام کاربری ندارم", callback_data="foreign_skip_username", style=KeyboardButtonStyle.PRIMARY)]]
    )


def skip_foreign_password_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[inline_button("➡️ رمز عبور ندارم", callback_data="foreign_skip_password", style=KeyboardButtonStyle.PRIMARY)]]
    )


def telegram_id_prompt_text() -> str:
    return (
        "حالا لطفا آیدی تلگرامت رو بفرست تا اگر مشکلی پیش اومد بتونیم باهات در ارتباط باشیم.\n\n"
        "اگر سفارش برای خودته، می‌تونی دکمه «ارسال نام کاربری خودم» رو بزنی.\n"
        "اگر برای شخص دیگه‌ای سفارش می‌دی، آیدی اون شخص رو دستی تایپ کن.\n\n"
        "نمونه ارسال:\n"
        "@spotihyp"
    )


def wallet_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [inline_button("➕ شارژ کیف پول", callback_data="wallet_charge", style=KeyboardButtonStyle.SUCCESS)]
    ])


def wallet_topup_review_keyboard(topup_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                inline_button("تایید شارژ", callback_data=f"topup_approve:{topup_id}", style=KeyboardButtonStyle.SUCCESS),
                inline_button("رد شارژ", callback_data=f"topup_reject:{topup_id}", style=KeyboardButtonStyle.DANGER),
            ]
        ]
    )


ORDER_STATUS_LABELS = {
    "all": "همه",
    "waiting_receipt": "در انتظار فیش",
    "pending_review": "در حال بررسی فیش",
    "approved": "تایید شده",
    "rejected": "رد شده",
    "delivered": "انجام شده",
}


def admin_orders_keyboard(active_status: str = "all") -> InlineKeyboardMarkup:
    rows = [
        [
            inline_button("همه", callback_data="orders:all", style=KeyboardButtonStyle.PRIMARY),
            inline_button("در انتظار فیش", callback_data="orders:waiting_receipt", style=KeyboardButtonStyle.PRIMARY),
        ],
        [
            inline_button("بررسی فیش", callback_data="orders:pending_review", style=KeyboardButtonStyle.PRIMARY),
            inline_button("تایید شده", callback_data="orders:approved", style=KeyboardButtonStyle.SUCCESS),
        ],
        [
            inline_button("انجام شده", callback_data="orders:delivered", style=KeyboardButtonStyle.SUCCESS),
            inline_button("رد شده", callback_data="orders:rejected", style=KeyboardButtonStyle.DANGER),
        ],
    ]
    return InlineKeyboardMarkup(rows)


def display_order_code(order) -> str:
    return str(order["id"])


def status_label(status: str) -> str:
    return ORDER_STATUS_LABELS.get(status, status)


PAYMENT_METHOD_LABELS = {
    "card": "کارت به کارت",
    "wallet": "کیف پول",
    "discount": "کد تخفیف کامل",
}


def payment_method_label(payment_method: str | None) -> str:
    if not payment_method:
        return "هنوز انتخاب نشده"
    return PAYMENT_METHOD_LABELS.get(payment_method, payment_method)


def join_channel_keyboard() -> InlineKeyboardMarkup:
    channel_username = config.REQUIRED_CHANNEL.lstrip("@")
    return InlineKeyboardMarkup(
        [
            [inline_button("عضویت در کانال", url=f"https://t.me/{channel_username}", style=KeyboardButtonStyle.PRIMARY)],
            [inline_button("عضو شدم", callback_data="check_join", style=KeyboardButtonStyle.SUCCESS)],
        ]
    )


async def is_joined_required_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not config.REQUIRED_CHANNEL:
        return True
    if update.effective_user.id in config.ADMIN_IDS:
        return True

    member = await context.bot.get_chat_member(config.REQUIRED_CHANNEL, update.effective_user.id)
    if member.status in {"creator", "administrator", "member"}:
        return True
    if member.status == "restricted":
        return bool(getattr(member, "is_member", False))
    return False


async def require_channel_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        if await is_joined_required_channel(update, context):
            return True
    except BadRequest as error:
        logger.exception("Could not check channel membership for user %s", update.effective_user.id)
        if "Member list is inaccessible" in str(error):
            text = (
                f"برای فعال شدن عضویت اجباری، خود بات باید در کانال {config.REQUIRED_CHANNEL} ادمین باشد.\n"
                "بعد از ادمین کردن بات، دوباره «عضو شدم» را بزنید."
            )
        else:
            text = (
                f"عضویت شما در کانال {config.REQUIRED_CHANNEL} قابل بررسی نبود.\n"
                "بعد از عضویت روی «عضو شدم» بزنید."
            )
        await send_join_required_message(update, text)
        return False
    except Exception:
        logger.exception("Could not check channel membership for user %s", update.effective_user.id)

    text = (
        f"برای استفاده از بات، ابتدا باید عضو کانال {config.REQUIRED_CHANNEL} شوید.\n"
        "بعد از عضویت روی «عضو شدم» بزنید."
    )
    await send_join_required_message(update, text)
    return False


async def send_join_required_message(update: Update, text: str) -> None:
    if update.callback_query:
        await update.callback_query.answer("ابتدا عضو کانال شوید.", show_alert=True)
        try:
            await update.callback_query.edit_message_text(text, reply_markup=join_channel_keyboard())
        except BadRequest as error:
            if "Message is not modified" not in str(error):
                raise
    else:
        await update.effective_message.reply_text(text, reply_markup=join_channel_keyboard())


def rules_acceptance_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                inline_button(
                    "✅ قوانین را خواندم و می‌پذیرم",
                    callback_data="accept_rules",
                    style=KeyboardButtonStyle.SUCCESS,
                )
            ]
        ]
    )


def rules_view_keyboard(*, accepted: bool) -> InlineKeyboardMarkup:
    if not accepted:
        return rules_acceptance_keyboard()
    return InlineKeyboardMarkup(
        [
            [
                inline_button(
                    "⬅️ بازگشت به دسته‌بندی‌ها",
                    callback_data="back:categories",
                    style=KeyboardButtonStyle.PRIMARY,
                )
            ]
        ]
    )


async def send_rules_acceptance_prompt(update: Update) -> None:
    text = f"{SHOP_RULES}{RULES_ACCEPTANCE_NOTE}"
    if update.callback_query:
        await update.callback_query.answer("ابتدا قوانین را بپذیرید.", show_alert=True)
        try:
            await update.callback_query.edit_message_text(text, reply_markup=rules_acceptance_keyboard())
        except BadRequest as error:
            if "Message is not modified" not in str(error):
                raise
    else:
        await update.effective_message.reply_text(text, reply_markup=rules_acceptance_keyboard())


async def require_rules_acceptance(update: Update) -> bool:
    user = update.effective_user
    if not user:
        return False
    if storage.has_accepted_rules(user.id):
        return True
    await send_rules_acceptance_prompt(update)
    return False


async def show_main_menu_message(update: Update) -> None:
    text = (
        "❤️ سلام به ربات میتسو خوش اومدین ❤️\n"
        "✨ امیدوارم خرید خوبی رو تجربه کنید ✨\n"
        "👇 لطفا سفارش مد نظرتونو انتخاب کنید:"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=categories_keyboard())
    else:
        await update.effective_message.reply_text(text, reply_markup=categories_keyboard())


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    context.user_data.clear()
    if not await require_channel_membership(update, context):
        return SELECTING_PRODUCT

    await clear_legacy_reply_keyboard(update)
    if not storage.has_accepted_rules(update.effective_user.id):
        await update.effective_message.reply_text(
            f"{SHOP_RULES}{RULES_ACCEPTANCE_NOTE}",
            reply_markup=rules_acceptance_keyboard(),
        )
        return SELECTING_PRODUCT

    await show_main_menu_message(update)
    return SELECTING_PRODUCT


async def show_category(update: Update, context: ContextTypes.DEFAULT_TYPE, category_key: str) -> int:
    if not await require_rules_acceptance(update):
        return SELECTING_PRODUCT
    category_title = config.CATEGORIES[category_key]
    if category_key in CATEGORY_SUBCATEGORIES:
        await update.effective_message.reply_text(
            f"بخش {category_title}\n"
            "اول سرویس مورد نظرت رو انتخاب کن:",
            reply_markup=subcategories_keyboard(category_key),
        )
        return SELECTING_PRODUCT

    await update.effective_message.reply_text(
        f"بخش {category_title}\n"
        "یکی از پلن‌های زیر رو انتخاب کن تا قیمت و مراحل سفارش رو ببینی:",
        reply_markup=products_keyboard(category_key),
    )
    return SELECTING_PRODUCT


async def choose_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    query = update.callback_query
    if not await require_channel_membership(update, context):
        return SELECTING_PRODUCT
    if not await require_rules_acceptance(update):
        return SELECTING_PRODUCT
    await query.answer()

    category_key = query.data.split(":", 1)[1]
    category_title = config.CATEGORIES[category_key]
    if category_key in CATEGORY_SUBCATEGORIES:
        await query.edit_message_text(
            f"بخش {category_title}\n"
            "اول سرویس مورد نظرت رو انتخاب کن:",
            reply_markup=subcategories_keyboard(category_key),
        )
        return SELECTING_PRODUCT

    await query.edit_message_text(
        f"بخش {category_title}\n"
        "یکی از پلن‌های زیر رو انتخاب کن تا قیمت و مراحل سفارش رو ببینی:",
        reply_markup=products_keyboard(category_key),
    )
    return SELECTING_PRODUCT


async def show_edit_subcategory(
    update: Update, context: ContextTypes.DEFAULT_TYPE, category_key: str, subcategory_key: str
) -> int:
    if not await require_rules_acceptance(update):
        return SELECTING_PRODUCT
    subcategory_title = CATEGORY_SUBCATEGORIES[category_key][subcategory_key]
    await update.effective_message.reply_text(
        f"بخش {subcategory_title}\n"
        f"{subcategory_products_text(category_key, subcategory_key)}\n\n"
        "یکی از پلن‌های زیر رو انتخاب کن تا مراحل سفارش رو ببینی:",
        reply_markup=products_by_subcategory_keyboard(category_key, subcategory_key),
    )
    return SELECTING_PRODUCT


async def choose_edit_subcategory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    query = update.callback_query
    if not await require_channel_membership(update, context):
        return SELECTING_PRODUCT
    if not await require_rules_acceptance(update):
        return SELECTING_PRODUCT
    await query.answer()

    _, category_key, subcategory_key = query.data.split(":", 2)
    subcategory_title = CATEGORY_SUBCATEGORIES[category_key][subcategory_key]
    await query.edit_message_text(
        f"بخش {subcategory_title}\n"
        f"{subcategory_products_text(category_key, subcategory_key)}\n\n"
        "یکی از پلن‌های زیر رو انتخاب کن تا مراحل سفارش رو ببینی:",
        reply_markup=products_by_subcategory_keyboard(category_key, subcategory_key),
    )
    return SELECTING_PRODUCT


async def handle_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    text = (update.message.text or "").strip()

    if not await require_channel_membership(update, context):
        return SELECTING_PRODUCT

    if text == RULES_TEXT:
        await rules_command(update, context)
        return SELECTING_PRODUCT

    for category_key, category_title in config.CATEGORIES.items():
        if text == category_title:
            return await show_category(update, context, category_key)

    if text == BACK_TO_CATEGORIES_TEXT:
        context.user_data.clear()
        await update.message.reply_text(
            "دوباره دسته‌بندی مورد نظرت رو انتخاب کن:",
            reply_markup=categories_keyboard(),
        )
        return SELECTING_PRODUCT

    if text == BACK_TO_EDIT_SUBCATEGORIES_TEXT:
        return await show_category(update, context, EDIT_CATEGORY_KEY)
    if text == BACK_TO_MUSIC_SUBCATEGORIES_TEXT:
        return await show_category(update, context, MUSIC_CATEGORY_KEY)
    if text == BACK_TO_AI_SUBCATEGORIES_TEXT:
        return await show_category(update, context, AI_CATEGORY_KEY)
    if text == BACK_TO_OTHER_SUBCATEGORIES_TEXT:
        return await show_category(update, context, OTHER_CATEGORY_KEY)

    if text == WALLET_TEXT:
        await wallet_command(update, context)
        return SELECTING_PRODUCT

    subcategory_context = subcategory_context_by_title(text)
    if subcategory_context:
        category_key, subcategory_key = subcategory_context
        return await show_edit_subcategory(update, context, category_key, subcategory_key)

    for product_key, product in config.PRODUCTS.items():
        if text == product_title(product_key) and storage.is_catalog_product_active(product_key):
            return await start_product_order(update, context, product_key)

    await update.message.reply_text(
        "لطفا یکی از دکمه‌های منو رو انتخاب کن.",
        reply_markup=categories_keyboard(),
    )
    return SELECTING_PRODUCT


async def maybe_handle_navigation_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    text = (update.message.text or "").strip()
    if not is_navigation_text(text):
        return None
    return await handle_menu_text(update, context)


async def back_to_categories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    query = update.callback_query
    context.user_data.clear()
    if not await require_channel_membership(update, context):
        return SELECTING_PRODUCT
    await query.answer()

    if not storage.has_accepted_rules(update.effective_user.id):
        await query.edit_message_text(
            f"{SHOP_RULES}{RULES_ACCEPTANCE_NOTE}",
            reply_markup=rules_acceptance_keyboard(),
        )
        return SELECTING_PRODUCT

    await query.edit_message_text(
        "دوباره دسته‌بندی مورد نظرت رو انتخاب کن:",
        reply_markup=categories_keyboard(),
    )
    return SELECTING_PRODUCT


async def back_to_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    query = update.callback_query
    if not await require_channel_membership(update, context):
        return SELECTING_PRODUCT
    await query.answer()

    category_key = query.data.rsplit(":", 1)[1]
    if category_key in CATEGORY_SUBCATEGORIES:
        category_title = config.CATEGORIES[category_key]
        await query.edit_message_text(
            f"بخش {category_title}\n"
            "اول سرویس مورد نظرت رو انتخاب کن:",
            reply_markup=subcategories_keyboard(category_key),
        )
        return SELECTING_PRODUCT

    return await back_to_categories(update, context)


async def start_product_order(update: Update, context: ContextTypes.DEFAULT_TYPE, product_key: str) -> int:
    if not await require_rules_acceptance(update):
        return SELECTING_PRODUCT
    if not storage.is_catalog_product_active(product_key):
        await respond_in_place(update, "این سرویس فعلاً فعال نیست.")
        return SELECTING_PRODUCT
    product = config.PRODUCTS[product_key]
    context.user_data.pop("order_id", None)
    context.user_data.pop("wallet_topup_id", None)
    if product.get("variable_foreign_payment"):
        payment_note = product_payment_note(product_key)
        payment_note_text = f"\n\n{payment_note}" if payment_note else ""
        context.user_data["order"] = {
            "product_key": product_key,
            "product_title": product_title(product_key),
            "price": 0,
            "needs_credentials": False,
        }
        await respond_in_place(
            update,
            "💳 پرداخت در سایت خارجی\n\n"
            "لطفا لینک سایت خارجی که می‌خواهید در آن پرداخت انجام شود را ارسال کنید.\n"
            "نمونه:\n"
            "https://example.com/checkout"
            f"{payment_note_text}"
        )
        return ASK_FOREIGN_SITE_URL
    if product.get("variable_volume"):
        payment_note = product_payment_note(product_key)
        payment_note_text = f"\n\n{payment_note}" if payment_note else ""
        context.user_data["order"] = {
            "product_key": product_key,
            "product_title": product_title(product_key),
            "price": 0,
            "needs_credentials": product["needs_credentials"],
            "needs_apple_id": product.get("needs_apple_id", False),
            "needs_chatgpt_session": product.get("needs_chatgpt_session", False),
            "needs_claude_user_id": product.get("needs_claude_user_id", False),
            "needs_delivery_email": product.get("needs_delivery_email", False),
        }
        await respond_in_place(
            update,
            "🌐 V2Ray حجم دلخواه\n\n"
            f"{vpn_rates_text()}\n\n"
            "حجم مورد نظرتون رو به گیگ وارد کنید؛ در مرحله بعد قیمت دقیق نمایش داده می‌شه و بعدش می‌تونید اقدام به پرداخت کنید.\n\n"
            "📝 مثال: 7"
            f"{payment_note_text}"
        )
        return ASK_VPN_VOLUME

    price = product_price(product_key)
    if price <= 0:
        await respond_in_place(
            update,
            "قیمت این سرویس هنوز ثبت نشده و فعلاً قابل سفارش نیست.\n"
            f"ادمین می‌تواند قیمت را با این دستور تنظیم کند:\n/setprice {product_key} amount"
        )
        return SELECTING_PRODUCT

    context.user_data["order"] = {
        "product_key": product_key,
        "product_title": product_title(product_key),
        "price": price,
        "needs_credentials": product["needs_credentials"],
        "needs_apple_id": product.get("needs_apple_id", False),
        "needs_chatgpt_session": product.get("needs_chatgpt_session", False),
        "needs_claude_user_id": product.get("needs_claude_user_id", False),
        "needs_delivery_email": product.get("needs_delivery_email", False),
    }

    catalog_product = storage.get_catalog_product(product_key)
    description = catalog_product["description"] if catalog_product and catalog_product["description"] else product.get("description")
    description_text = f"\n\n{description}" if description else ""

    if config.is_spotify_credentials_product(product_key):
        fee_text = toman(config.SPOTIFY_ACCOUNT_CREATION_FEE)
        await respond_in_place(
            update,
            f"انتخابت ثبت شد: {product_title(product_key)}\n"
            f"قیمت: {toman(price)}"
            f"{description_text}\n\n"
            "آیا اکانت Spotify داری؟\n"
            f"اگر اکانت نداری، هزینه ساخت اکانت {fee_text} به مبلغ سفارش اضافه می‌شود.",
            reply_markup=spotify_account_choice_keyboard(),
        )
        return ASK_SPOTIFY_ACCOUNT_CHOICE

    await respond_in_place(
        update,
        f"انتخابت ثبت شد: {product_title(product_key)}\n"
        f"قیمت: {toman(price)}"
        f"{description_text}\n\n"
        f"{telegram_id_prompt_text()}",
        reply_markup=own_username_keyboard(),
    )
    return ASK_TELEGRAM_ID


async def choose_product(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    query = update.callback_query
    if not await require_channel_membership(update, context):
        return SELECTING_PRODUCT
    if not await require_rules_acceptance(update):
        return SELECTING_PRODUCT
    await query.answer()

    product_key = query.data.split(":", 1)[1]
    return await start_product_order(update, context, product_key)


async def choose_spotify_account(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    query = update.callback_query
    if not await require_channel_membership(update, context):
        return ASK_SPOTIFY_ACCOUNT_CHOICE
    if not await require_rules_acceptance(update):
        return ASK_SPOTIFY_ACCOUNT_CHOICE
    await query.answer()

    order = context.user_data.get("order")
    if not order:
        await query.edit_message_text("سفارش پیدا نشد. لطفا /start را بزن.")
        return SELECTING_PRODUCT

    if query.data == "spotify_no_account":
        order["account_creation_requested"] = True
        order["price"] += config.SPOTIFY_ACCOUNT_CREATION_FEE
        order["spotify_email"] = "ساخت اکانت جدید"
        order["spotify_password"] = ""
        choice_text = (
            f"اکانت نداری — هزینه ساخت اکانت ({toman(config.SPOTIFY_ACCOUNT_CREATION_FEE)}) "
            f"به سفارش اضافه شد.\n"
            f"مبلغ نهایی: {toman(order['price'])}"
        )
    else:
        order["account_creation_requested"] = False
        choice_text = "اکانت Spotify داری — در مرحله بعد ایمیل و رمز اکانت را می‌گیریم."

    await query.edit_message_text(
        f"{choice_text}\n\n{telegram_id_prompt_text()}",
        reply_markup=own_username_keyboard(),
    )
    return ASK_TELEGRAM_ID


def is_valid_foreign_site_url(value: str) -> bool:
    text = value.strip()
    if len(text) < 4:
        return False
    if text.startswith(("http://", "https://")):
        return True
    return "." in text and " " not in text


async def ask_foreign_site_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    if not await require_channel_membership(update, context):
        return ASK_FOREIGN_SITE_URL
    navigation_state = await maybe_handle_navigation_text(update, context)
    if navigation_state is not None:
        return navigation_state

    site_url = update.message.text.strip()
    if not is_valid_foreign_site_url(site_url):
        await update.message.reply_text(
            "لینک سایت معتبر نیست. لطفا آدرس کامل سایت را ارسال کن.\n"
            "نمونه:\n"
            "https://example.com/pay"
        )
        return ASK_FOREIGN_SITE_URL

    if not site_url.startswith(("http://", "https://")):
        site_url = f"https://{site_url}"

    context.user_data["order"]["foreign_site_url"] = site_url
    await update.message.reply_text(
        "لینک سایت ثبت شد.\n\n"
        "حالا مبلغ پرداخت را به دلار وارد کن.\n"
        "مثال: 45"
    )
    return ASK_FOREIGN_USD_AMOUNT


async def ask_foreign_usd_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    if not await require_channel_membership(update, context):
        return ASK_FOREIGN_USD_AMOUNT
    navigation_state = await maybe_handle_navigation_text(update, context)
    if navigation_state is not None:
        return navigation_state

    raw_amount = normalize_number_text(update.message.text)
    try:
        usd_amount = float(raw_amount)
    except ValueError:
        await update.message.reply_text("مبلغ دلاری باید عددی باشد. مثال: 45")
        return ASK_FOREIGN_USD_AMOUNT

    if usd_amount <= 0:
        await update.message.reply_text("مبلغ دلاری باید بیشتر از صفر باشد.")
        return ASK_FOREIGN_USD_AMOUNT

    price_text = foreign_payment_service_fee_text(usd_amount)
    if price_text is None:
        await update.message.reply_text(
            "نرخ تتر هنوز دریافت نشده. لطفا چند لحظه بعد دوباره مبلغ دلاری را ارسال کن."
        )
        return ASK_FOREIGN_USD_AMOUNT

    service_fee = foreign_payment_service_fee_toman(usd_amount)
    total_price = foreign_payment_total_toman(usd_amount)
    if service_fee is None or total_price is None:
        await update.message.reply_text(
            "نرخ تتر هنوز دریافت نشده. لطفا چند لحظه بعد دوباره مبلغ دلاری را ارسال کن."
        )
        return ASK_FOREIGN_USD_AMOUNT

    context.user_data["order"]["foreign_usd_amount"] = usd_amount
    context.user_data["order"]["price"] = total_price
    context.user_data["order"]["product_title"] = (
        f"پرداخت سایت خارجی - {usd_amount:g}$"
    )

    await update.message.reply_text(
        f"{price_text}\n\n"
        "اگر برای ورود به سایت نام کاربری داری ارسال کن؛ در غیر این صورت دکمه زیر را بزن.",
        reply_markup=skip_foreign_username_keyboard(),
    )
    return ASK_FOREIGN_USERNAME


async def prompt_foreign_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_text(
        "اگر برای سایت رمز عبور داری ارسال کن؛ در غیر این صورت دکمه زیر را بزن.",
        reply_markup=skip_foreign_password_keyboard(),
    )
    return ASK_FOREIGN_PASSWORD


async def ask_foreign_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    if not await require_channel_membership(update, context):
        return ASK_FOREIGN_USERNAME
    navigation_state = await maybe_handle_navigation_text(update, context)
    if navigation_state is not None:
        return navigation_state

    context.user_data["order"]["spotify_email"] = update.message.text.strip()
    await update.message.reply_text("نام کاربری ثبت شد.")
    return await prompt_foreign_password(update, context)


async def skip_foreign_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    query = update.callback_query
    if not await require_channel_membership(update, context):
        return ASK_FOREIGN_USERNAME
    if "order" not in context.user_data:
        await query.answer()
        await query.edit_message_text("سفارش فعالی پیدا نشد. لطفا دوباره /start رو بزن.")
        return ConversationHandler.END

    await query.answer()
    await query.edit_message_text("بدون نام کاربری ادامه می‌دیم.")
    return await prompt_foreign_password(update, context)


async def ask_foreign_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    if not await require_channel_membership(update, context):
        return ASK_FOREIGN_PASSWORD
    navigation_state = await maybe_handle_navigation_text(update, context)
    if navigation_state is not None:
        return navigation_state

    context.user_data["order"]["spotify_password"] = update.message.text.strip()
    await update.message.reply_text(
        "رمز عبور ثبت شد.\n\n"
        f"{telegram_id_prompt_text()}",
        reply_markup=own_username_keyboard(),
    )
    return ASK_TELEGRAM_ID


async def skip_foreign_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    query = update.callback_query
    if not await require_channel_membership(update, context):
        return ASK_FOREIGN_PASSWORD
    if "order" not in context.user_data:
        await query.answer()
        await query.edit_message_text("سفارش فعالی پیدا نشد. لطفا دوباره /start رو بزن.")
        return ConversationHandler.END

    await query.answer()
    await query.edit_message_text(
        f"بدون رمز عبور ادامه می‌دیم.\n\n{telegram_id_prompt_text()}",
        reply_markup=own_username_keyboard(),
    )
    return ASK_TELEGRAM_ID


async def ask_vpn_volume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    if not await require_channel_membership(update, context):
        return ASK_VPN_VOLUME
    navigation_state = await maybe_handle_navigation_text(update, context)
    if navigation_state is not None:
        return navigation_state

    raw_volume = normalize_number_text(update.message.text)
    try:
        volume_gb = float(raw_volume)
    except ValueError:
        await update.message.reply_text("حجم باید عددی باشه. مثال: 7")
        return ASK_VPN_VOLUME

    if volume_gb < 1:
        await update.message.reply_text("حداقل حجم قابل سفارش 1 گیگ است. لطفا دوباره حجم رو وارد کن.")
        return ASK_VPN_VOLUME

    if format_volume(volume_gb) == "1" and update.effective_user:
        if v2ray_one_gb_limit_blocks_user(update.effective_user.id):
            await update.message.reply_text(V2RAY_ONE_GB_BLOCK_MESSAGE)
            return ASK_VPN_VOLUME

    unit_price = vpn_unit_price(volume_gb)
    total_price = int(volume_gb * unit_price)
    volume_text = format_volume(volume_gb)
    context.user_data["order"]["product_title"] = (
        f"V2Ray نامحدود کاربر و زمان - {volume_text} گیگ"
    )
    context.user_data["order"]["price"] = total_price
    context.user_data["order"]["vpn_volume_gb"] = volume_text
    context.user_data["order"]["vpn_unit_price"] = unit_price

    await update.message.reply_text(
        f"حجم انتخابی: {volume_text} گیگ\n"
        f"قیمت هر گیگ: {toman(unit_price)}\n"
        f"مبلغ نهایی: {toman(total_price)}"
        f"{product_order_summary_text('v2ray_custom')}\n\n"
        f"{telegram_id_prompt_text()}",
        reply_markup=own_username_keyboard(),
    )
    return ASK_TELEGRAM_ID


async def ask_telegram_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    if not await require_channel_membership(update, context):
        return ASK_TELEGRAM_ID
    navigation_state = await maybe_handle_navigation_text(update, context)
    if navigation_state is not None:
        return navigation_state

    context.user_data["order"]["telegram_id"] = update.message.text.strip()
    return await continue_after_telegram_id(update, context)


async def use_own_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    query = update.callback_query
    if not await require_channel_membership(update, context):
        return ASK_TELEGRAM_ID
    if "order" not in context.user_data:
        await query.answer()
        await query.edit_message_text("سفارش فعالی پیدا نشد. لطفا دوباره /start رو بزن.")
        return ConversationHandler.END

    username = update.effective_user.username
    if not username:
        await query.answer(
            "روی اکانتت username تنظیم نشده. لطفا آیدی مدنظرت رو دستی تایپ کن.",
            show_alert=True,
        )
        return ASK_TELEGRAM_ID

    telegram_id = f"@{username}"
    context.user_data["order"]["telegram_id"] = telegram_id
    await query.answer("نام کاربری خودت ثبت شد.")
    await query.edit_message_text(f"آیدی تلگرام ثبت شد: {telegram_id}")
    return await continue_after_telegram_id(update, context)


async def continue_after_telegram_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if context.user_data["order"]["needs_credentials"]:
        await update.effective_message.reply_text(
            "برای فعال‌سازی این سرویس، ایمیل یا نام کاربری اکانتت رو بفرست.\n"
            "نمونه ارسال:\n"
            "example@gmail.com"
        )
        return ASK_SPOTIFY_EMAIL
    if context.user_data["order"].get("needs_apple_id"):
        await update.effective_message.reply_text(
            "برای فعال‌سازی Apple Music، لطفا Apple ID اکانتت رو بفرست تا به فمیلی جوین بشه.\n\n"
            "حتما دقت کن ریجن Apple ID باید ترکیه باشه؛ اگر ریجن اکانتت ترکیه نباشه، جوین فمیلی انجام نمی‌شه.\n\n"
            "نمونه ارسال:\n"
            "example@icloud.com"
        )
        return ASK_APPLE_ID
    if context.user_data["order"].get("needs_chatgpt_session"):
        context.user_data["chatgpt_session_parts"] = []
        await update.effective_message.reply_text(
            "برای ثبت سفارش ChatGPT لازمه session اکانتتون رو بفرستید.\n\n"
            "1. تحت وب وارد اکانت ChatGPT خودتون بشید. حتما باید لاگین باشید و چت‌های قبلیتون رو ببینید.\n\n"
            "2. لینک زیر رو باز کنید:\n"
            "https://chatgpt.com/api/auth/session\n\n"
            "3. هر محتوایی که نمایش داده می‌شه رو کامل کپی کنید و همینجا ارسال کنید.\n\n"
            "اگر متن طولانی بود، می‌تونی چند پیام پشت سر هم بفرستی. وقتی همه بخش‌ها رو فرستادی، دکمه اتمام رو بزن.",
            reply_markup=finish_chatgpt_session_keyboard(),
        )
        return ASK_CHATGPT_SESSION
    if context.user_data["order"].get("needs_claude_user_id"):
        await update.effective_message.reply_text(
            "برای شارژ Claude نیازی به لاگین، نام کاربری یا رمز عبور نیست.\n\n"
            "لطفا فقط Claude User ID اکانتت رو بفرست.\n\n"
            "برای دریافت Claude User ID:\n"
            "1. وارد claude.ai/settings شو.\n"
            "2. در بخش Account Info مقدار User ID رو پیدا کن.\n"
            "3. همان User ID را همینجا ارسال کن."
        )
        return ASK_CLAUDE_USER_ID
    if context.user_data["order"].get("needs_delivery_email"):
        await update.effective_message.reply_text(
            "نحوه تحویل: لینک فعال‌سازی به ایمیل شما ارسال می‌شود.\n\n"
            "لطفا ایمیلت را برای دریافت لینک بفرست:\n"
            "example@gmail.com"
        )
        return ASK_SPOTIFY_EMAIL

    return await ask_receipt(update, context)


async def ask_apple_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    if not await require_channel_membership(update, context):
        return ASK_APPLE_ID
    navigation_state = await maybe_handle_navigation_text(update, context)
    if navigation_state is not None:
        return navigation_state

    context.user_data["order"]["apple_id"] = update.message.text.strip()
    return await ask_receipt(update, context)


async def ask_spotify_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    if not await require_channel_membership(update, context):
        return ASK_SPOTIFY_EMAIL
    navigation_state = await maybe_handle_navigation_text(update, context)
    if navigation_state is not None:
        return navigation_state

    context.user_data["order"]["spotify_email"] = update.message.text.strip()
    if context.user_data["order"].get("needs_delivery_email") and not context.user_data["order"]["needs_credentials"]:
        return await ask_receipt(update, context)
    credential_note = product_credential_note(context.user_data["order"]["product_key"])
    credential_note_text = f"\n\n{credential_note}" if credential_note else ""
    await update.message.reply_text(
        "پسورد اکانتت رو هم بفرست.\n"
        "نمونه ارسال:\n"
        "MyPass1234"
        f"{credential_note_text}"
    )
    return ASK_SPOTIFY_PASSWORD


async def ask_spotify_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    if not await require_channel_membership(update, context):
        return ASK_SPOTIFY_PASSWORD
    navigation_state = await maybe_handle_navigation_text(update, context)
    if navigation_state is not None:
        return navigation_state

    context.user_data["order"]["spotify_password"] = update.message.text.strip()
    return await ask_receipt(update, context)


async def ask_chatgpt_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    if not await require_channel_membership(update, context):
        return ASK_CHATGPT_SESSION
    navigation_state = await maybe_handle_navigation_text(update, context)
    if navigation_state is not None:
        return navigation_state

    session_text = update.message.text.strip()
    if not session_text:
        await update.message.reply_text("پیام خالی دریافت شد. لطفا بخش بعدی session رو بفرست.")
        return ASK_CHATGPT_SESSION

    parts = context.user_data.setdefault("chatgpt_session_parts", [])
    parts.append(session_text)
    await update.message.reply_text(
        f"بخش {len(parts)} session دریافت شد.\n"
        "اگر بخش دیگری مونده، بفرست. اگر کامل شد، دکمه اتمام رو بزن.",
        reply_markup=finish_chatgpt_session_keyboard(),
    )
    return ASK_CHATGPT_SESSION


async def ask_claude_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    if not await require_channel_membership(update, context):
        return ASK_CLAUDE_USER_ID
    navigation_state = await maybe_handle_navigation_text(update, context)
    if navigation_state is not None:
        return navigation_state

    claude_user_id = update.message.text.strip()
    if not claude_user_id:
        await update.message.reply_text("User ID خالی دریافت شد. لطفا Claude User ID رو بفرست.")
        return ASK_CLAUDE_USER_ID

    context.user_data["order"]["spotify_email"] = claude_user_id
    return await ask_receipt(update, context)


async def finish_chatgpt_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    parts = context.user_data.get("chatgpt_session_parts") or []
    if not parts:
        await query.edit_message_text(
            "هنوز هیچ بخشی از session دریافت نشده. لطفا متن session رو بفرست و بعد دکمه اتمام رو بزن."
        )
        return ASK_CHATGPT_SESSION

    context.user_data["order"]["chatgpt_session"] = "\n\n".join(parts)
    context.user_data.pop("chatgpt_session_parts", None)
    await query.edit_message_text("Session کامل دریافت شد. حالا می‌ریم مرحله پرداخت.")
    return await ask_receipt(update, context)


async def ask_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    order_data = context.user_data["order"]
    order_data["user_id"] = user.id
    order_data["username"] = user.username
    order_id = storage.create_order(order_data)
    context.user_data["order_id"] = order_id
    order = storage.get_order(order_id)
    order_code = display_order_code(order)
    order_summary_text = product_order_summary_text(order_data["product_key"])

    await update.effective_message.reply_text(
        f"شماره سفارش: {order_code}\n"
        f"محصول: {order_data['product_title']}\n"
        f"مبلغ: {toman(order_data['price'])}\n"
        f"موجودی کیف پول شما: {toman(storage.get_wallet_balance(user.id))}"
        f"{order_summary_text}\n\n"
        "اگر کد تخفیف داری وارد کن؛ در غیر این صورت بدون کد ادامه بده."
        ,
        reply_markup=discount_keyboard(order_id),
    )
    return ASK_DISCOUNT_CODE


async def show_payment_method_step(update: Update, context: ContextTypes.DEFAULT_TYPE, order) -> int:
    order_summary_text = product_order_summary_text(order["product_key"])
    await update.effective_message.reply_text(
        f"شماره سفارش: {display_order_code(order)}\n"
        f"محصول: {order['product_title']}\n"
        f"مبلغ قابل پرداخت: {payable_toman(order['price'])}"
        f"{order_discount_summary(order)}"
        f"\nموجودی کیف پول شما: {toman(storage.get_wallet_balance(order['user_id']))}"
        f"{order_summary_text}\n\n"
        "روش پرداخت رو انتخاب کن:",
        reply_markup=payment_method_keyboard(order["id"]),
    )
    return ASK_PAYMENT_METHOD


async def discount_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    query = update.callback_query
    await query.answer()

    action, raw_order_id = query.data.split(":", 1)
    order_id = int(raw_order_id)
    order = storage.get_order(order_id)
    if not order:
        await query.edit_message_text("سفارش پیدا نشد. لطفا /start را بزن.")
        return ConversationHandler.END
    if order["user_id"] != update.effective_user.id:
        await query.edit_message_text("این سفارش متعلق به شما نیست.")
        return ConversationHandler.END

    context.user_data["order_id"] = order_id
    if action == "discount_skip":
        await query.edit_message_text("بدون کد تخفیف ادامه می‌دیم.")
        return await show_payment_method_step(update, context, order)

    await query.edit_message_text(
        "کد تخفیف رو ارسال کن.\n\n"
        "اگر کد نداری، روی دکمه زیر بزن و بدون کد ادامه بده.",
        reply_markup=skip_discount_keyboard(order_id),
    )
    return ASK_DISCOUNT_CODE


async def ask_discount_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    if not await require_channel_membership(update, context):
        return ASK_DISCOUNT_CODE
    navigation_state = await maybe_handle_navigation_text(update, context)
    if navigation_state is not None:
        return navigation_state

    order_id = context.user_data.get("order_id")
    if not order_id:
        await update.message.reply_text("سفارش فعالی پیدا نشد. لطفا /start را بزن.")
        return ConversationHandler.END

    order = storage.get_order(order_id)
    if not order or order["user_id"] != update.effective_user.id:
        await update.message.reply_text("سفارش پیدا نشد. لطفا /start را بزن.")
        return ConversationHandler.END

    raw_code = update.message.text.strip()
    discount = storage.get_discount_code(raw_code, order["product_key"])
    if not discount:
        await update.message.reply_text(
            "کد تخفیف معتبر نیست، غیرفعال شده یا برای این سرویس قابل استفاده نیست.\n"
            "می‌تونی کد درست رو دوباره بفرستی یا بدون کد ادامه بدی.",
            reply_markup=skip_discount_keyboard(order_id),
        )
        return ASK_DISCOUNT_CODE

    original_price = order_original_price(order)
    percent = int(discount["percent"])
    discount_amount = min(original_price, (original_price * percent) // 100)
    final_price = max(0, original_price - discount_amount)
    storage.set_order_discount(order_id, discount["code"], percent, discount_amount, final_price)
    updated_order = storage.get_order(order_id)

    await update.message.reply_text(
        f"کد تخفیف اعمال شد: {discount['code']}\n"
        f"درصد تخفیف: {percent}٪\n"
        f"قابل استفاده برای: {discount_scope_label(discount)}\n"
        f"مبلغ کسرشده: {toman(discount_amount)}\n"
        f"مبلغ قبل از تخفیف: {toman(original_price)}\n"
        f"مبلغ نهایی: {payable_toman(final_price)}"
    )
    if final_price <= 0:
        storage.set_order_payment_method(order_id, "discount")
        storage.set_status(order_id, "approved")
        await update.message.reply_text(
            "مبلغ سفارش با کد تخفیف کامل صفر شد.\n"
            "سفارش شما تایید شد و در حال پردازش می‌باشد."
        )
        await notify_admins_wallet_order(context, order_id, "کد تخفیف کامل")
        context.user_data.clear()
        return ConversationHandler.END

    return await show_payment_method_step(update, context, updated_order)


async def choose_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    query = update.callback_query
    await query.answer()

    action, raw_order_id = query.data.split(":", 1)
    order_id = int(raw_order_id)
    order = storage.get_order(order_id)
    if not order:
        await query.edit_message_text("سفارش پیدا نشد. لطفا /start را بزن.")
        return ConversationHandler.END
    if order["user_id"] != update.effective_user.id:
        await query.edit_message_text("این سفارش متعلق به شما نیست.")
        return ConversationHandler.END

    context.user_data["order_id"] = order_id
    if order["price"] <= 0:
        storage.set_order_payment_method(order_id, "discount")
        storage.set_status(order_id, "approved")
        await query.edit_message_text(
            f"سفارش {display_order_code(order)} با کد تخفیف کامل ثبت و تایید شد.\n"
            "سفارش شما در حال پردازش می‌باشد."
        )
        await notify_admins_wallet_order(context, order_id, "کد تخفیف کامل")
        context.user_data.clear()
        return ConversationHandler.END

    if action == "pay_wallet":
        balance = storage.get_wallet_balance(order["user_id"])
        if balance < order["price"]:
            await query.edit_message_text(
                f"موجودی کیف پول کافی نیست.\n"
                f"موجودی فعلی: {toman(balance)}\n"
                f"مبلغ سفارش: {toman(order['price'])}\n\n"
                "می‌تونی کیف پول رو شارژ کنی یا کارت به کارت انجام بدی.",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            inline_button("➕ شارژ کیف پول", callback_data="wallet_charge", style=KeyboardButtonStyle.SUCCESS),
                            inline_button("🏦 کارت به کارت", callback_data=f"pay_card:{order_id}", style=KeyboardButtonStyle.PRIMARY),
                        ],
                    ]
                ),
            )
            return ASK_PAYMENT_METHOD

        if not storage.debit_wallet(order["user_id"], order["price"], order_id):
            await query.edit_message_text("پرداخت از کیف پول انجام نشد. لطفا دوباره تلاش کن.")
            return ASK_PAYMENT_METHOD

        storage.set_order_payment_method(order_id, "wallet")
        storage.set_status(order_id, "approved")
        await query.edit_message_text(
            f"پرداخت سفارش {display_order_code(order)} از کیف پول انجام شد.\n"
            "سفارش شما تایید شد و در حال پردازش می‌باشد."
        )
        await notify_admins_wallet_order(context, order_id)
        context.user_data.clear()
        return ConversationHandler.END

    storage.set_order_payment_method(order_id, "card")
    order_summary_text = product_order_summary_text(order["product_key"])
    payment_note = product_payment_note(order["product_key"])
    payment_note_text = f"\n\n{payment_note}" if payment_note else ""
    await query.edit_message_text(
        f"شماره سفارش: {display_order_code(order)}\n"
        f"محصول: {order['product_title']}\n"
        f"مبلغ: {payable_toman(order['price'])}"
        f"{order_summary_text}"
        f"{payment_note_text}\n\n"
        f"{config.PAYMENT_TEXT}"
    )
    return ASK_RECEIPT


async def receive_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    if not await require_channel_membership(update, context):
        return ASK_RECEIPT

    order_id = context.user_data.get("order_id")
    if not order_id:
        await update.message.reply_text("سفارش فعالی پیدا نشد. لطفا /start را بزنید.")
        return ConversationHandler.END

    file_id = None
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    elif update.message.document:
        file_id = update.message.document.file_id

    if not file_id:
        await update.message.reply_text("لطفا فیش رو به صورت عکس یا فایل ارسال کن.")
        return ASK_RECEIPT

    storage.set_receipt(order_id, file_id)
    await update.message.reply_text("فیشت دریافت شد. حداکثر تا 30 دقیقه دیگه بررسی می‌شه.")
    await notify_admins(update, context, order_id, file_id)
    context.user_data.clear()
    return ConversationHandler.END


async def handle_receipt_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    navigation_state = await maybe_handle_navigation_text(update, context)
    if navigation_state is not None:
        return navigation_state
    await update.message.reply_text("لطفا فیش رو به صورت عکس یا فایل ارسال کن.")
    return ASK_RECEIPT


async def notify_admins(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: int, file_id: str) -> None:
    order = storage.get_order(order_id)
    if not order:
        return

    text = format_order_for_admin(order)
    caption = text
    should_send_full_text = False
    if len(caption) > 950:
        caption = "فیش سفارش دریافت شد.\nمتن کامل سفارش و اطلاعات ChatGPT در پیام بعدی ارسال می‌شود."
        should_send_full_text = True

    for admin_id in config.ADMIN_IDS:
        try:
            await context.bot.send_photo(
                chat_id=admin_id,
                photo=file_id,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=admin_review_keyboard(order_id),
            )
            if should_send_full_text:
                await send_long_message(
                    context.bot,
                    admin_id,
                    text,
                    parse_mode=ParseMode.HTML,
                )
        except Exception:
            logger.exception("Could not notify admin %s for order %s", admin_id, order_id)


async def notify_admins_wallet_order(
    context: ContextTypes.DEFAULT_TYPE,
    order_id: int,
    payment_label: str = "کیف پول",
) -> None:
    order = storage.get_order(order_id)
    if not order:
        return

    text = format_order_for_admin(order, payment_label=payment_label)
    for admin_id in config.ADMIN_IDS:
        try:
            await send_long_message(
                context.bot,
                admin_id,
                text,
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            logger.exception("Could not notify admin %s for wallet order %s", admin_id, order_id)


def format_order_for_admin(order, payment_label: str | None = None) -> str:
    username = f"@{order['username']}" if order["username"] else "ندارد"
    payment_method = order["payment_method"] if "payment_method" in order.keys() else "-"
    payment_text = payment_label or payment_method_label(payment_method)
    lines = [
        "🧾 سفارش جدید",
        "",
        f"ID: <code>{order['id']}</code>",
        f"شماره سفارش: <code>{escape(display_order_code(order))}</code>",
        f"تاریخ و ساعت: {escape(order['created_at'])}",
        f"سفارش: {escape(order['product_title'])}",
        f"مبلغ: {escape(payable_toman(order['price']))}",
        f"نحوه پرداخت: {escape(payment_text)}",
        f"وضعیت: {escape(status_label(order['status']))}",
    ]
    if "foreign_site_url" in order.keys() and order["foreign_site_url"]:
        lines.extend(
            [
                "",
                "🌍 پرداخت سایت خارجی",
                f"لینک سایت: {escape(order['foreign_site_url'])}",
            ]
        )
        if "foreign_usd_amount" in order.keys() and order["foreign_usd_amount"]:
            usd_amount = float(order["foreign_usd_amount"])
            lines.append(foreign_payment_admin_pricing_text(usd_amount))
    if "discount_code" in order.keys() and order["discount_code"]:
        lines.extend(
            [
                "",
                "🎁 تخفیف",
                f"مبلغ قبل از تخفیف: {escape(toman(order_original_price(order)))}",
                f"کد تخفیف: <code>{escape(order['discount_code'])}</code>",
                f"درصد تخفیف: {escape(str(order['discount_percent']))}٪",
                f"مبلغ کسرشده: {escape(toman(order['discount_amount'] or 0))}",
            ]
        )
    lines.extend(
        [
            "",
            "👤 کاربر",
            f"آیدی عددی: <code>{order['user_id']}</code>",
            f"یوزرنیم: {escape(username)}",
            f"آیدی ثبت‌شده: {escape(order['telegram_id'] or '-')}",
        ]
    )
    if order["spotify_email"]:
        if "🔐 اطلاعات اکانت" not in lines:
            lines.extend(["", "🔐 اطلاعات اکانت"])
        if order["product_key"] == "claude_ai_personal_1":
            credential_label = "Claude User ID"
        elif is_foreign_payment_product(order["product_key"]):
            credential_label = "نام کاربری سایت"
        elif config.PRODUCTS.get(order["product_key"], {}).get("needs_claude_user_id"):
            credential_label = "Claude User ID"
        elif config.PRODUCTS.get(order["product_key"], {}).get("needs_delivery_email"):
            credential_label = "ایمیل تحویل لینک"
        else:
            credential_label = "ایمیل یا نام کاربری اکانت"
        lines.append(f"{credential_label}: <code>{escape(order['spotify_email'])}</code>")
    if order["spotify_password"]:
        if "🔐 اطلاعات اکانت" not in lines:
            lines.extend(["", "🔐 اطلاعات اکانت"])
        password_label = "رمز عبور سایت" if is_foreign_payment_product(order["product_key"]) else "پسورد اکانت"
        lines.append(f"{password_label}: <code>{escape(order['spotify_password'])}</code>")
    if "apple_id" in order.keys() and order["apple_id"]:
        if "🔐 اطلاعات اکانت" not in lines:
            lines.extend(["", "🔐 اطلاعات اکانت"])
        lines.append(f"Apple ID: <code>{escape(order['apple_id'])}</code>")
        lines.append("نکته Apple Music: ریجن اکانت باید ترکیه باشد.")
    if "chatgpt_session" in order.keys() and order["chatgpt_session"]:
        lines.append("")
        lines.append("Session ChatGPT:")
        lines.append(f"<code>{escape(order['chatgpt_session'])}</code>")
    return "\n".join(lines)


def format_order_detail_for_admin(order) -> str:
    lines = [
        format_order_for_admin(order),
        "",
        "جزئیات تکمیلی",
        f"فیش: {'دریافت شده' if order['receipt_file_id'] else 'ندارد'}",
        f"آخرین تغییر: {escape(order['updated_at'])}",
    ]
    if order["delivery_text"]:
        lines.extend(["", "متن تحویل:", f"<code>{escape(order['delivery_text'])}</code>"])
    return "\n".join(lines)


def admin_actor_text(user) -> str:
    username = f"@{user.username}" if user and user.username else None
    if username:
        return f"{username} ({user.id})"
    return str(user.id) if user else "ادمین"


async def notify_other_admins_about_order_decision(
    context: ContextTypes.DEFAULT_TYPE,
    actor_id: int,
    actor_text: str,
    order,
    decision_label: str,
) -> None:
    text = (
        f"وضعیت فیش سفارش توسط ادمین دیگر مشخص شد.\n\n"
        f"اقدام: {decision_label}\n"
        f"ادمین: {actor_text}\n"
        f"شماره سفارش: {display_order_code(order)}\n"
        f"شناسه داخلی: {order['id']}\n"
        f"محصول: {order['product_title']}\n"
        f"مبلغ: {toman(order['price'])}"
    )
    for admin_id in config.ADMIN_IDS:
        if admin_id == actor_id:
            continue
        try:
            await context.bot.send_message(chat_id=admin_id, text=text)
        except Exception:
            logger.exception("Could not notify admin %s about order decision %s", admin_id, order["id"])


async def notify_other_admins_about_topup_decision(
    context: ContextTypes.DEFAULT_TYPE,
    actor_id: int,
    actor_text: str,
    topup,
    decision_label: str,
) -> None:
    username = f"@{topup['username']}" if topup["username"] else "-"
    text = (
        f"وضعیت فیش شارژ کیف پول توسط ادمین دیگر مشخص شد.\n\n"
        f"اقدام: {decision_label}\n"
        f"ادمین: {actor_text}\n"
        f"شناسه شارژ: #{topup['id']}\n"
        f"کاربر: {topup['user_id']} | {username}\n"
        f"مبلغ: {toman(topup['amount'])}"
    )
    for admin_id in config.ADMIN_IDS:
        if admin_id == actor_id:
            continue
        try:
            await context.bot.send_message(chat_id=admin_id, text=text)
        except Exception:
            logger.exception("Could not notify admin %s about topup decision %s", admin_id, topup["id"])


async def admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if update.effective_user.id not in config.ADMIN_IDS:
        await query.edit_message_caption(caption="شما دسترسی ادمین ندارید.")
        return

    action, raw_order_id = query.data.split(":", 1)
    order_id = int(raw_order_id)
    order = storage.get_order(order_id)
    if not order:
        await query.edit_message_caption(caption="سفارش پیدا نشد.")
        return
    if order["status"] in {"approved", "rejected", "delivered"}:
        await query.edit_message_caption(
            caption=f"این سفارش قبلاً {status_label(order['status'])} شده است."
        )
        return

    if action == "reject":
        storage.set_status(order_id, "rejected")
        updated_order = storage.get_order(order_id) or order
        await context.bot.send_message(
            chat_id=order["user_id"],
            text=(
                f"سفارش {display_order_code(order)} لغو شد.\n"
                f"برای پیگیری لطفا به تلگرام {support_contacts_text()} پیام بدهید."
            ),
        )
        await query.edit_message_caption(caption=f"سفارش {display_order_code(order)} رد شد.")
        await notify_other_admins_about_order_decision(
            context,
            update.effective_user.id,
            admin_actor_text(update.effective_user),
            updated_order,
            "رد شد",
        )
        return

    storage.set_status(order_id, "approved")
    updated_order = storage.get_order(order_id) or order
    await context.bot.send_message(
        chat_id=order["user_id"],
        text=f"سفارش {display_order_code(order)} تایید شد و در حال پردازش می‌باشد.",
    )
    await query.edit_message_caption(
        caption=(
            f"سفارش {display_order_code(order)} تایید شد.\n"
            "برای ارسال سفارش به کاربر، پیام تحویل را اینطور بفرستید:\n"
            f"/deliver {order_id} متن یا اطلاعات سفارش\n"
            "برای ارسال فایل، فایل را داخل بات بفرستید و روی همان فایل ریپلای کنید:\n"
            f"/deliver {order_id} متن اختیاری"
        )
    )
    await notify_other_admins_about_order_decision(
        context,
        update.effective_user.id,
        admin_actor_text(update.effective_user),
        updated_order,
        "تایید شد",
    )


async def deliver(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in config.ADMIN_IDS:
        await update.message.reply_text("شما دسترسی ادمین ندارید.")
        return

    if len(context.args) < 1:
        await update.message.reply_text(
            "فرمت درست:\n"
            "/deliver شماره_سفارش متن_تحویل\n\n"
            "برای ارسال فایل، فایل را بفرست و روی همان فایل ریپلای کن:\n"
            "/deliver شماره_سفارش متن_اختیاری"
        )
        return

    try:
        order_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("شماره سفارش باید عدد باشد.")
        return

    order = storage.get_order(order_id)
    if not order:
        await update.message.reply_text("سفارش پیدا نشد.")
        return

    raw_text = update.message.text or update.message.caption or ""
    parts = raw_text.split(maxsplit=2)
    delivery_text = parts[2].strip() if len(parts) >= 3 else ""
    file_message = None
    if update.message.reply_to_message:
        replied = update.message.reply_to_message
        if replied.document or replied.photo or replied.video or replied.audio or replied.voice:
            file_message = replied
    elif update.message.document or update.message.photo or update.message.video or update.message.audio or update.message.voice:
        file_message = update.message

    if not delivery_text and not file_message:
        await update.message.reply_text(
            "متن یا فایل تحویل پیدا نشد.\n"
            "برای متن: /deliver شماره_سفارش متن_تحویل\n"
            "برای فایل: روی فایل ریپلای کن /deliver شماره_سفارش متن_اختیاری"
        )
        return

    stored_delivery_text = delivery_text or "فایل تحویل برای کاربر ارسال شد."
    if file_message:
        caption = f"سفارش {display_order_code(order)} آماده شد."
        if delivery_text:
            caption = f"{caption}\n\n{delivery_text}"
        await context.bot.copy_message(
            chat_id=order["user_id"],
            from_chat_id=file_message.chat.id,
            message_id=file_message.message_id,
            caption=caption,
        )
    else:
        await context.bot.send_message(
            chat_id=order["user_id"],
            text=f"سفارش {display_order_code(order)} آماده شد:\n\n{delivery_text}",
        )
    storage.set_delivery(order_id, stored_delivery_text)
    await update.message.reply_text(f"تحویل سفارش {display_order_code(order)} برای کاربر ارسال شد.")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    context.user_data.clear()
    await update.effective_message.reply_text("ثبت سفارش لغو شد. برای شروع دوباره /start را بزنید.")
    return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remember_user(update)
    await update.effective_message.reply_text(
        "راهنمای ربات میتسو\n\n"
        "برای ثبت سفارش:\n"
        "1. دستور /start رو بزن.\n"
        "2. دسته‌بندی مورد نظرت رو انتخاب کن.\n"
        "3. پلن دلخواهت رو بزن تا قیمت نمایش داده بشه.\n"
        "4. آیدی تلگرامت رو بفرست.\n"
        "5. اگر سفارش نیاز به اکانت داشته باشه، ایمیل و پسورد اکانتت هم گرفته می‌شه.\n"
        "6. مبلغ رو واریز کن و عکس فیش رو داخل بات بفرست.\n\n"
        "بعد از ارسال فیش، سفارش بررسی می‌شه و نتیجه داخل همین بات بهت پیام داده می‌شه.\n\n"
        "دستورهای کاربردی:\n"
        "/start شروع سفارش جدید\n"
        "/myorders سفارش‌های من\n"
        "/wallet کیف پول و شارژ حساب\n"
        "/cancel لغو سفارش فعلی\n"
        "/info اطلاعات پشتیبانی و سایت\n"
        "/rules قوانین فروشگاه"
    )


async def rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remember_user(update)
    accepted = storage.has_accepted_rules(update.effective_user.id)
    await update.effective_message.reply_text(
        SHOP_RULES if accepted else f"{SHOP_RULES}{RULES_ACCEPTANCE_NOTE}",
        reply_markup=rules_view_keyboard(accepted=accepted),
    )


async def rules_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    query = update.callback_query
    await query.answer()
    accepted = storage.has_accepted_rules(update.effective_user.id)
    await query.edit_message_text(
        SHOP_RULES if accepted else f"{SHOP_RULES}{RULES_ACCEPTANCE_NOTE}",
        reply_markup=rules_view_keyboard(accepted=accepted),
    )
    return SELECTING_PRODUCT


async def accept_rules_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    query = update.callback_query
    if not await require_channel_membership(update, context):
        return SELECTING_PRODUCT

    storage.set_rules_accepted(update.effective_user.id)
    await query.answer("قوانین پذیرفته شد.")
    await show_main_menu_message(update)
    return SELECTING_PRODUCT


def format_myorders_text(user_id: int) -> str:
    orders = storage.list_user_orders(user_id, limit=None)
    if not orders:
        return (
            "هنوز سفارشی برای شما ثبت نشده.\n\n"
            "برای ثبت سفارش جدید از منوی اصلی سرویس موردنظرت رو انتخاب کن."
        )

    counts = storage.count_user_orders_by_status(user_id)
    lines = [
        "سفارش‌های من 📦",
        "",
        f"تعداد کل سفارش‌ها: {len(orders)}",
        f"در انتظار فیش: {counts.get('waiting_receipt', 0)}",
        f"در حال بررسی فیش: {counts.get('pending_review', 0)}",
        f"تایید شده: {counts.get('approved', 0)}",
        f"انجام شده: {counts.get('delivered', 0)}",
        f"رد شده: {counts.get('rejected', 0)}",
        "",
        "لیست کامل سفارش‌ها:",
    ]
    for order in orders:
        receipt_status = "ارسال شده" if order["receipt_file_id"] else "ارسال نشده"
        lines.extend(
            [
                "",
                "----------------",
                f"شماره سفارش: {display_order_code(order)}",
                f"محصول: {order['product_title']}",
                f"مبلغ: {payable_toman(order['price'])}",
                f"وضعیت: {status_label(order['status'])}",
                f"روش پرداخت: {payment_method_label(order['payment_method'] if 'payment_method' in order.keys() else None)}",
                f"فیش پرداخت: {receipt_status}",
                f"زمان ثبت: {order['created_at']}",
                f"آخرین تغییر: {order['updated_at']}",
            ]
        )
        if order["telegram_id"]:
            lines.append(f"آیدی ثبت‌شده: {order['telegram_id']}")
        if order["spotify_email"]:
            credential_label = "ایمیل/نام کاربری"
            if order["product_key"] == "claude_ai_personal_1":
                credential_label = "User ID"
            elif config.PRODUCTS.get(order["product_key"], {}).get("needs_delivery_email"):
                credential_label = "ایمیل تحویل"
            lines.append(f"{credential_label}: {order['spotify_email']}")
        if "apple_id" in order.keys() and order["apple_id"]:
            lines.append(f"Apple ID: {order['apple_id']}")
        if "vpn_volume_gb" in order.keys() and order["vpn_volume_gb"]:
            lines.append(f"حجم V2Ray: {order['vpn_volume_gb']} گیگ")
        if "discount_code" in order.keys() and order["discount_code"]:
            lines.append(f"کد تخفیف: {order['discount_code']} ({order['discount_percent']}٪)")
        if order["delivery_text"]:
            lines.append(f"تحویل: {order['delivery_text']}")

    lines.extend(["", "برای پیگیری، شماره سفارش را برای پشتیبانی ارسال کنید."])
    return "\n".join(lines)


async def myorders_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remember_user(update)
    await send_long_message(context.bot, update.effective_chat.id, format_myorders_text(update.effective_user.id))


async def myorders_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    query = update.callback_query
    await query.answer()
    await send_long_message(context.bot, update.effective_chat.id, format_myorders_text(update.effective_user.id))
    return SELECTING_PRODUCT


async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remember_user(update)
    await update.effective_message.reply_text(
        "اطلاعات میتسو\n\n"
        f"پشتیبانی: {support_contacts_text()}\n"
        f"کانال: {config.REQUIRED_CHANNEL}\n"
        f"سایت: {config.SUPPORT_SITE}\n\n"
        "برای پیگیری سفارش، شماره سفارش یا اسکرین‌شات پیام سفارش رو برای پشتیبانی بفرست."
    )


async def wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remember_user(update)
    balance = storage.get_wallet_balance(update.effective_user.id)
    await update.effective_message.reply_text(
        f"کیف پول شما\n\n"
        f"موجودی فعلی: {toman(balance)}\n\n"
        "برای شارژ کیف پول، روی دکمه زیر بزن و مبلغ شارژ رو وارد کن.",
        reply_markup=wallet_keyboard(),
    )


async def wallet_show(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    query = update.callback_query
    await query.answer()
    balance = storage.get_wallet_balance(update.effective_user.id)
    await query.edit_message_text(
        f"کیف پول شما\n\n"
        f"موجودی فعلی: {toman(balance)}\n\n"
        "برای شارژ کیف پول، روی دکمه زیر بزن و مبلغ شارژ رو وارد کن.",
        reply_markup=wallet_keyboard(),
    )
    return SELECTING_PRODUCT


async def userwallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in config.ADMIN_IDS:
        await update.effective_message.reply_text("شما دسترسی ادمین ندارید.")
        return

    if len(context.args) != 1:
        await update.effective_message.reply_text(
            "فرمت درست:\n"
            "/userwallet user_id_or_username\n\n"
            "مثال:\n"
            "/userwallet 5447072835\n"
            "/userwallet @spotihyp"
        )
        return

    user = storage.find_user(context.args[0])
    if not user:
        await update.effective_message.reply_text("کاربر پیدا نشد. باید قبلاً با بات کار کرده باشد.")
        return

    username = f"@{user['username']}" if user["username"] else "-"
    balance = storage.get_wallet_balance(user["user_id"])
    await update.effective_message.reply_text(
        "کیف پول کاربر\n\n"
        f"آیدی عددی: {user['user_id']}\n"
        f"یوزرنیم: {username}\n"
        f"نام: {user['first_name'] or '-'} {user['last_name'] or ''}\n"
        f"موجودی: {toman(balance)}"
    )


async def adjust_userwallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str) -> None:
    if update.effective_user.id not in config.ADMIN_IDS:
        await update.effective_message.reply_text("شما دسترسی ادمین ندارید.")
        return

    command = "/addwallet" if mode == "add" else "/removewallet"
    if len(context.args) < 2:
        await update.effective_message.reply_text(
            "فرمت درست:\n"
            f"{command} user_id_or_username amount پیام_اختیاری\n\n"
            "مثال:\n"
            f"{command} @username 500000 به عنوان جایزه برای شما شارژ شد"
        )
        return

    user = storage.find_user(context.args[0])
    if not user:
        await update.effective_message.reply_text("کاربر پیدا نشد. باید قبلاً با بات کار کرده باشد.")
        return

    normalized_amount = normalize_int_text(context.args[1])
    if not normalized_amount.isdigit():
        await update.effective_message.reply_text("مبلغ باید عددی باشد. مثال: 500000")
        return

    amount = int(normalized_amount)
    if amount <= 0:
        await update.effective_message.reply_text("مبلغ باید بیشتر از صفر باشد.")
        return

    signed_amount = amount if mode == "add" else -amount
    reason = "admin_add" if mode == "add" else "admin_remove"
    if not storage.adjust_wallet_balance(user["user_id"], signed_amount, reason):
        await update.effective_message.reply_text("کسر موجودی انجام نشد؛ موجودی کیف پول کاربر کافی نیست.")
        return

    balance = storage.get_wallet_balance(user["user_id"])
    admin_message = " ".join(context.args[2:]).strip()
    username = f"@{user['username']}" if user["username"] else "-"
    action_text = "افزایش" if mode == "add" else "کاهش"
    await update.effective_message.reply_text(
        f"موجودی کیف پول کاربر {action_text} پیدا کرد.\n\n"
        f"آیدی عددی: {user['user_id']}\n"
        f"یوزرنیم: {username}\n"
        f"مبلغ: {toman(amount)}\n"
        f"موجودی جدید: {toman(balance)}"
    )

    if mode == "add":
        user_text = (
            "کیف پول شما شارژ شد.\n\n"
            f"مبلغ شارژ: {toman(amount)}\n"
            f"موجودی جدید: {toman(balance)}"
        )
    else:
        user_text = (
            "از موجودی کیف پول شما کسر شد.\n\n"
            f"مبلغ کسرشده: {toman(amount)}\n"
            f"موجودی جدید: {toman(balance)}"
        )
    if admin_message:
        user_text += f"\n\nپیام میتسو:\n{admin_message}"

    try:
        await context.bot.send_message(chat_id=user["user_id"], text=user_text)
    except Exception:
        logger.exception("Could not notify user %s about admin wallet adjustment", user["user_id"])
        await update.effective_message.reply_text("تغییر موجودی انجام شد، ولی ارسال پیام به کاربر ناموفق بود.")


async def addwallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await adjust_userwallet_command(update, context, "add")


async def removewallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await adjust_userwallet_command(update, context, "remove")


async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in config.ADMIN_IDS:
        await update.effective_message.reply_text("شما دسترسی ادمین ندارید.")
        return

    user_count = storage.count_users()
    await update.effective_message.reply_text(
        "آمار کاربران بات\n\n"
        f"تعداد کاربرهای ثبت‌شده: {user_count:,}"
    )


def v2ray_one_gb_limit_status_text() -> str:
    enabled = storage.is_v2ray_one_gb_limit_enabled()
    exempt_users = storage.list_v2ray_one_gb_exempt_user_ids()
    lines = [
        "وضعیت محدودیت V2Ray 1 گیگ",
        "",
        f"وضعیت کلی: {'فعال ✅' if enabled else 'غیرفعال ⛔️'}",
        "قانون: هر کاربر فقط یک بار می‌تواند سفارش 1 گیگ V2Ray ثبت کند.",
        "",
        "کاربران معاف از محدودیت:",
    ]
    if exempt_users:
        lines.extend(f"- <code>{user_id}</code>" for user_id in exempt_users[:20])
        if len(exempt_users) > 20:
            lines.append(f"... و {len(exempt_users) - 20} کاربر دیگر")
    else:
        lines.append("- موردی ثبت نشده")
    lines.extend(
        [
            "",
            "دستورها:",
            "/v2ray1glimit on فعال‌سازی برای همه",
            "/v2ray1glimit off غیرفعال‌سازی برای همه",
            "/v2ray1glimit user USER_ID off معاف کردن یک کاربر",
            "/v2ray1glimit user USER_ID on اعمال مجدد محدودیت برای یک کاربر",
        ]
    )
    return "\n".join(lines)


async def v2ray1glimit_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in config.ADMIN_IDS:
        await update.effective_message.reply_text("شما دسترسی ادمین ندارید.")
        return

    if not context.args:
        await update.effective_message.reply_text(
            v2ray_one_gb_limit_status_text(),
            parse_mode=ParseMode.HTML,
        )
        return

    action = context.args[0].strip().lower()
    if action in {"on", "enable", "active", "فعال"}:
        storage.set_v2ray_one_gb_limit_enabled(True)
        await update.effective_message.reply_text("محدودیت V2Ray 1 گیگ برای همه کاربران فعال شد.")
        return

    if action in {"off", "disable", "deactive", "غیرفعال"}:
        storage.set_v2ray_one_gb_limit_enabled(False)
        await update.effective_message.reply_text("محدودیت V2Ray 1 گیگ برای همه کاربران غیرفعال شد.")
        return

    if action == "user":
        if len(context.args) != 3:
            await update.effective_message.reply_text(
                "فرمت درست:\n"
                "/v2ray1glimit user USER_ID off\n"
                "/v2ray1glimit user USER_ID on"
            )
            return

        raw_user_id, user_action = context.args[1], context.args[2].strip().lower()
        if not raw_user_id.isdigit():
            await update.effective_message.reply_text("USER_ID باید عددی باشد.")
            return

        user_id = int(raw_user_id)
        if user_action in {"off", "exempt", "disable", "معاف"}:
            storage.set_user_v2ray_one_gb_exempt(user_id, True)
            await update.effective_message.reply_text(
                f"کاربر <code>{user_id}</code> از محدودیت V2Ray 1 گیگ معاف شد.",
                parse_mode=ParseMode.HTML,
            )
            return

        if user_action in {"on", "apply", "enable", "فعال"}:
            storage.set_user_v2ray_one_gb_exempt(user_id, False)
            has_order = storage.user_has_v2ray_one_gb_order(user_id)
            extra = " این کاربر قبلاً 1 گیگ سفارش داده و دوباره نمی‌تواند بخرد." if has_order else ""
            await update.effective_message.reply_text(
                f"محدودیت V2Ray 1 گیگ برای کاربر <code>{user_id}</code> دوباره فعال شد.{extra}",
                parse_mode=ParseMode.HTML,
            )
            return

        await update.effective_message.reply_text("عملیات کاربر نامعتبر است. از on یا off استفاده کن.")
        return

    await update.effective_message.reply_text(
        "دستور نامعتبر است.\n\n" + v2ray_one_gb_limit_status_text(),
        parse_mode=ParseMode.HTML,
    )


async def wallet_charge_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "مبلغ شارژ کیف پول رو به تومان وارد کن.\n\n"
            "مثال: 500000"
        )
    else:
        await update.effective_message.reply_text(
            "مبلغ شارژ کیف پول رو به تومان وارد کن.\n\n"
            "مثال: 500000"
        )
    return ASK_WALLET_AMOUNT


async def ask_wallet_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    navigation_state = await maybe_handle_navigation_text(update, context)
    if navigation_state is not None:
        return navigation_state

    normalized_amount = normalize_int_text(update.message.text)
    if not normalized_amount.isdigit():
        await update.message.reply_text("مبلغ باید عددی باشد. مثال: 500000")
        return ASK_WALLET_AMOUNT

    amount = int(normalized_amount)
    if amount <= 0:
        await update.message.reply_text("مبلغ شارژ باید بیشتر از صفر باشد.")
        return ASK_WALLET_AMOUNT

    user = update.effective_user
    topup_id = storage.create_wallet_topup(
        {"user_id": user.id, "username": user.username, "amount": amount}
    )
    context.user_data["wallet_topup_id"] = topup_id
    await update.message.reply_text(
        f"درخواست شارژ #{topup_id}\n"
        f"مبلغ: {toman(amount)}\n\n"
        f"{config.PAYMENT_TEXT}"
    )
    return ASK_WALLET_RECEIPT


async def receive_wallet_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    topup_id = context.user_data.get("wallet_topup_id")
    if not topup_id:
        await update.message.reply_text("درخواست شارژ فعالی پیدا نشد. لطفا /wallet را بزن.")
        return ConversationHandler.END

    file_id = None
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    elif update.message.document:
        file_id = update.message.document.file_id

    if not file_id:
        await update.message.reply_text("لطفا فیش شارژ کیف پول رو به صورت عکس یا فایل ارسال کن.")
        return ASK_WALLET_RECEIPT

    storage.set_wallet_topup_receipt(topup_id, file_id)
    await update.message.reply_text("فیش شارژ کیف پول دریافت شد و برای ادمین ارسال شد.")
    await notify_admins_wallet_topup(update, context, topup_id, file_id)
    context.user_data.clear()
    return ConversationHandler.END


async def handle_wallet_receipt_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    navigation_state = await maybe_handle_navigation_text(update, context)
    if navigation_state is not None:
        return navigation_state
    await update.message.reply_text("لطفا فیش شارژ کیف پول رو به صورت عکس یا فایل ارسال کن.")
    return ASK_WALLET_RECEIPT


async def notify_admins_wallet_topup(
    update: Update, context: ContextTypes.DEFAULT_TYPE, topup_id: int, file_id: str
) -> None:
    topup = storage.get_wallet_topup(topup_id)
    if not topup:
        return

    username = f"@{topup['username']}" if topup["username"] else "ندارد"
    text = (
        "درخواست شارژ کیف پول\n"
        f"شناسه شارژ: <code>{topup['id']}</code>\n"
        f"کاربر: <code>{topup['user_id']}</code>\n"
        f"یوزرنیم: {escape(username)}\n"
        f"مبلغ: {escape(toman(topup['amount']))}"
    )
    for admin_id in config.ADMIN_IDS:
        try:
            await context.bot.send_photo(
                chat_id=admin_id,
                photo=file_id,
                caption=text,
                parse_mode=ParseMode.HTML,
                reply_markup=wallet_topup_review_keyboard(topup_id),
            )
        except Exception:
            logger.exception("Could not notify admin %s for wallet topup %s", admin_id, topup_id)


async def wallet_topup_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if update.effective_user.id not in config.ADMIN_IDS:
        await query.edit_message_caption(caption="شما دسترسی ادمین ندارید.")
        return

    action, raw_topup_id = query.data.split(":", 1)
    topup_id = int(raw_topup_id)
    topup = storage.get_wallet_topup(topup_id)
    if not topup:
        await query.edit_message_caption(caption="درخواست شارژ پیدا نشد.")
        return
    if topup["status"] in {"approved", "rejected"}:
        topup_status_label = "تایید شده" if topup["status"] == "approved" else "رد شده"
        await query.edit_message_caption(caption=f"این درخواست شارژ قبلاً {topup_status_label} است.")
        return

    if action == "topup_reject":
        storage.set_wallet_topup_status(topup_id, "rejected")
        updated_topup = storage.get_wallet_topup(topup_id) or topup
        await context.bot.send_message(
            chat_id=topup["user_id"],
            text=f"درخواست شارژ کیف پول #{topup_id} رد شد. برای پیگیری به {support_contacts_text()} پیام بدهید.",
        )
        await query.edit_message_caption(caption=f"درخواست شارژ #{topup_id} رد شد.")
        await notify_other_admins_about_topup_decision(
            context,
            update.effective_user.id,
            admin_actor_text(update.effective_user),
            updated_topup,
            "رد شد",
        )
        return

    topup = storage.approve_wallet_topup(topup_id)
    if not topup or topup["status"] != "approved":
        await query.edit_message_caption(caption=f"درخواست شارژ #{topup_id} قابل تایید نیست.")
        return
    balance = storage.get_wallet_balance(topup["user_id"])
    await context.bot.send_message(
        chat_id=topup["user_id"],
        text=(
            f"شارژ کیف پول #{topup_id} تایید شد.\n"
            f"مبلغ شارژ: {toman(topup['amount'])}\n"
            f"موجودی جدید: {toman(balance)}"
        ),
    )
    await query.edit_message_caption(caption=f"درخواست شارژ #{topup_id} تایید شد.")
    await notify_other_admins_about_topup_decision(
        context,
        update.effective_user.id,
        admin_actor_text(update.effective_user),
        topup,
        "تایید شد",
    )


async def prices_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in config.ADMIN_IDS:
        await update.effective_message.reply_text("شما دسترسی ادمین ندارید.")
        return

    lines = ["لیست قیمت‌ها برای ویرایش:", ""]
    for product_key, product in config.PRODUCTS.items():
        lines.append(f"{product_key}")
        lines.append(f"{product['title']}")
        if product.get("variable_volume"):
            lines.append("قیمت: فرمولی بر اساس حجم. برای تغییر نرخ‌ها: /vpnrates")
        elif uses_usd_pricing(product_key):
            lines.append(f"قیمت لحظه‌ای با تتر: {toman(product_price(product_key))}")
            usd_price = storage.get_usd_price_override(product_key)
            if usd_price is None:
                usd_price = product["usd_price"]
            lines.append(f"قیمت دلاری فعلی: {usd_price:g}$")
        else:
            lines.append(f"{toman(product_price(product_key))}")
        lines.append("")
    lines.append("برای تغییر قیمت:")
    lines.append("/setprice product_key amount")
    lines.append("مثال:")
    lines.append("/setprice spotify_1 2.7")
    lines.append("/setprice gemini_18 8")
    lines.append("برای تغییر نرخ VPN:")
    lines.append("/vpnrates")
    await send_long_message(context.bot, update.effective_chat.id, "\n".join(lines))


def format_product_keys_panel() -> str:
    lines = ["Product keyهای سرویس‌ها", ""]
    for category_key, category_title in config.CATEGORIES.items():
        lines.append(category_title)
        category_products = [
            (product_key, product)
            for product_key, product in config.PRODUCTS.items()
            if product.get("category") == category_key
        ]
        if not category_products:
            lines.append("موردی ثبت نشده.")
            lines.append("")
            continue

        if category_key in CATEGORY_SUBCATEGORIES:
            for subcategory_key, subcategory_title in CATEGORY_SUBCATEGORIES[category_key].items():
                subcategory_products = [
                    (product_key, product)
                    for product_key, product in category_products
                    if product.get("subcategory") == subcategory_key
                ]
                if not subcategory_products:
                    continue
                lines.append(f"  {subcategory_title}")
                for product_key, product in subcategory_products:
                    lines.append(f"  `{product_key}` - {product['title']}")
            uncategorized_products = [
                (product_key, product)
                for product_key, product in category_products
                if not product.get("subcategory")
            ]
            if uncategorized_products:
                lines.append("  بدون زیرشاخه")
                for product_key, product in uncategorized_products:
                    lines.append(f"  `{product_key}` - {product['title']}")
        else:
            for product_key, product in category_products:
                lines.append(f"`{product_key}` - {product['title']}")
        lines.append("")

    lines.append("برای قیمت فعلی یک سرویس:")
    lines.append("/get product_key")
    lines.append("برای تخفیف مخصوص یک سرویس:")
    lines.append("/setdiscount CODE percent product_key")
    return "\n".join(lines).strip()


async def productkeys_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in config.ADMIN_IDS:
        await update.effective_message.reply_text("شما دسترسی ادمین ندارید.")
        return

    await send_long_message(
        context.bot,
        update.effective_chat.id,
        format_product_keys_panel(),
        parse_mode=ParseMode.MARKDOWN,
    )


def usdt_cache_status_text() -> str:
    if not usdt_cache["price"]:
        return "نرخ تتر: هنوز از API دریافت نشده و قیمت fallback نمایش داده می‌شود."

    age_seconds = max(0, int(time.time() - usdt_cache["updated_at"]))
    age_minutes = age_seconds // 60
    if age_minutes:
        age_text = f"{age_minutes} دقیقه قبل"
    else:
        age_text = f"{age_seconds} ثانیه قبل"
    return f"نرخ تتر کش‌شده: {toman(int(usdt_cache['price']))} | آپدیت: {age_text}"


def product_search_values(product_key: str, product: dict) -> list[str]:
    values = [
        product_key,
        product["title"],
        product.get("category", ""),
        config.CATEGORIES.get(product.get("category", ""), ""),
        product.get("subcategory", ""),
    ]
    category_key = product.get("category")
    subcategory_key = product.get("subcategory")
    if category_key in CATEGORY_SUBCATEGORIES and subcategory_key:
        values.append(CATEGORY_SUBCATEGORIES[category_key].get(subcategory_key, ""))
    return [value.casefold() for value in values if value]


def find_products_for_get(query: str) -> list[tuple[str, dict]]:
    normalized_query = query.strip().casefold()
    if normalized_query in config.PRODUCTS:
        return [(normalized_query, config.PRODUCTS[normalized_query])]

    for category_key, subcategories in CATEGORY_SUBCATEGORIES.items():
        for subcategory_key, subcategory_title in subcategories.items():
            if normalized_query in {subcategory_key.casefold(), subcategory_title.casefold()}:
                return [
                    (product_key, product)
                    for product_key, product in config.PRODUCTS.items()
                    if product.get("category") == category_key and product.get("subcategory") == subcategory_key
                ]

    return [
        (product_key, product)
        for product_key, product in config.PRODUCTS.items()
        if any(normalized_query in value for value in product_search_values(product_key, product))
    ]


def format_product_price_for_admin(product_key: str, product: dict) -> str:
    lines = [
        f"{product_key}",
        product["title"],
    ]
    if product.get("variable_volume"):
        lines.append("قیمت: فرمولی بر اساس حجم V2Ray")
        lines.append("برای نرخ هر بازه: /vpnrates")
        return "\n".join(lines)

    price = product_price(product_key)
    if uses_usd_pricing(product_key):
        usd_price = storage.get_usd_price_override(product_key)
        if usd_price is None:
            usd_price = product["usd_price"]
        lines.append(f"قیمت دلاری فعلی: {usd_price:g}$")
        lines.append(f"قیمت تومانی لحظه‌ای: {toman(price)}")
        lines.append(usdt_cache_status_text())
        return "\n".join(lines)

    override = storage.get_price_override(product_key)
    lines.append(f"قیمت تومانی: {toman(price)}")
    if override is not None:
        lines.append("منبع قیمت: override ادمین")
    else:
        lines.append("منبع قیمت: config")
    return "\n".join(lines)


async def get_price_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in config.ADMIN_IDS:
        await update.effective_message.reply_text("شما دسترسی ادمین ندارید.")
        return

    if not context.args:
        await update.effective_message.reply_text(
            "فرمت درست:\n"
            "/get product_key_or_name\n\n"
            "مثال:\n"
            "/get spotify\n"
            "/get spotify_1\n"
            "/get chatgpt"
        )
        return

    query = " ".join(context.args)
    matches = find_products_for_get(query)
    if not matches:
        await update.effective_message.reply_text(
            "محصولی پیدا نشد.\n"
            "برای دیدن product_keyها دستور /prices رو بزن."
        )
        return

    lines = [f"نتیجه قیمت برای: {query}", ""]
    for product_key, product in matches[:20]:
        lines.append(format_product_price_for_admin(product_key, product))
        lines.append("")
    if len(matches) > 20:
        lines.append(f"{len(matches) - 20} نتیجه دیگر نمایش داده نشد. جستجو را دقیق‌تر کن.")

    await send_long_message(context.bot, update.effective_chat.id, "\n".join(lines).strip())


async def setprice_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in config.ADMIN_IDS:
        await update.effective_message.reply_text("شما دسترسی ادمین ندارید.")
        return

    if len(context.args) != 2:
        await update.effective_message.reply_text(
            "فرمت درست:\n/setprice product_key amount\n\n"
            "مثال:\n/setprice spotify_1 499000\n\n"
            "برای دیدن product_keyها دستور /prices رو بزن."
        )
        return

    product_key, raw_price = context.args
    if product_key not in config.PRODUCTS:
        await update.effective_message.reply_text("این product_key پیدا نشد. برای لیست کامل /prices رو بزن.")
        return
    if config.PRODUCTS[product_key].get("variable_volume"):
        await update.effective_message.reply_text("این محصول قیمت فرمولی دارد و با /setprice تغییر نمی‌کند.")
        return

    product_title = config.PRODUCTS[product_key]["title"]
    if uses_usd_pricing(product_key):
        normalized_usd = normalize_number_text(raw_price)
        try:
            usd_price = float(normalized_usd)
        except ValueError:
            await update.effective_message.reply_text("قیمت دلاری باید عددی باشد. مثال: 2.7")
            return
        if usd_price <= 0:
            await update.effective_message.reply_text("قیمت دلاری باید بیشتر از صفر باشد.")
            return
        storage.clear_price_override(product_key)
        storage.set_usd_price_override(product_key, usd_price)
        await update.effective_message.reply_text(
            f"قیمت دلاری آپدیت شد.\n"
            f"محصول: {product_title}\n"
            f"قیمت دلاری جدید: {usd_price:g}$\n"
            f"قیمت تومانی لحظه‌ای: {toman(product_price(product_key))}"
        )
        return

    normalized_price = normalize_int_text(raw_price)
    if not normalized_price.isdigit():
        await update.effective_message.reply_text("قیمت تومانی باید عددی باشد. مثال: 650000")
        return

    price = int(normalized_price)
    storage.clear_usd_price_override(product_key)
    storage.set_price_override(product_key, price)
    await update.effective_message.reply_text(
        f"قیمت تومانی آپدیت شد.\n"
        f"محصول: {product_title}\n"
        f"قیمت جدید: {toman(price)}"
    )


async def setdiscount_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in config.ADMIN_IDS:
        await update.effective_message.reply_text("شما دسترسی ادمین ندارید.")
        return

    if len(context.args) != 3:
        await update.effective_message.reply_text(
            "فرمت درست:\n"
            "/setdiscount CODE percent all\n"
            "/setdiscount CODE percent product_key\n\n"
            "مثال:\n"
            "/setdiscount OFF20 20 all\n"
            "/setdiscount GPT10 10 chatgpt_no_login_1"
        )
        return

    raw_code, raw_percent, raw_scope = context.args
    code = storage.normalize_discount_code(raw_code)
    if not code or any(char.isspace() for char in code):
        await update.effective_message.reply_text("کد تخفیف نباید خالی باشد یا فاصله داشته باشد.")
        return

    normalized_percent = normalize_int_text(raw_percent)
    if not normalized_percent.isdigit():
        await update.effective_message.reply_text("درصد تخفیف باید عددی بین 1 تا 100 باشد.")
        return

    percent = int(normalized_percent)
    if percent < 1 or percent > 100:
        await update.effective_message.reply_text("درصد تخفیف باید بین 1 تا 100 باشد.")
        return

    product_key = storage.normalize_discount_product_key(raw_scope)
    if product_key is not None and product_key not in config.PRODUCTS:
        await update.effective_message.reply_text(
            "این product_key پیدا نشد.\n"
            "برای دیدن product_keyها دستور /prices رو بزن.\n"
            "اگر کد برای همه سرویس‌هاست از all استفاده کن."
        )
        return

    storage.set_discount_code(code, percent, product_key)
    scope_text = "همه سرویس‌ها" if product_key is None else config.PRODUCTS[product_key]["title"]
    await update.effective_message.reply_text(
        f"کد تخفیف ذخیره شد.\n"
        f"کد: {code}\n"
        f"درصد: {percent}٪\n"
        f"اعمال روی: {scope_text}"
    )


async def discounts_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in config.ADMIN_IDS:
        await update.effective_message.reply_text("شما دسترسی ادمین ندارید.")
        return

    discounts = storage.list_discount_codes()
    if not discounts:
        await update.effective_message.reply_text("فعلا کد تخفیف فعالی ثبت نشده.")
        return

    lines = ["کدهای تخفیف فعال:", ""]
    for discount in discounts:
        lines.append(f"{discount['code']} - {discount['percent']}٪ - {discount_scope_label(discount)}")
    lines.extend(["", "حذف کد:", "/deldiscount CODE"])
    await update.effective_message.reply_text("\n".join(lines))


async def deldiscount_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in config.ADMIN_IDS:
        await update.effective_message.reply_text("شما دسترسی ادمین ندارید.")
        return

    if len(context.args) != 1:
        await update.effective_message.reply_text(
            "فرمت درست:\n"
            "/deldiscount CODE\n\n"
            "مثال:\n"
            "/deldiscount OFF20"
        )
        return

    code = storage.normalize_discount_code(context.args[0])
    if storage.delete_discount_code(code):
        await update.effective_message.reply_text(f"کد تخفیف {code} غیرفعال شد.")
    else:
        await update.effective_message.reply_text("این کد تخفیف فعال پیدا نشد.")


async def vpnrates_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in config.ADMIN_IDS:
        await update.effective_message.reply_text("شما دسترسی ادمین ندارید.")
        return

    lines = ["نرخ‌های فعلی V2Ray:", ""]
    for tier_key, tier in VPN_RATE_TIERS.items():
        unit_price = storage.get_vpn_rate_override(tier_key)
        if unit_price is None:
            unit_price = int(tier["default"])
        lines.append(f"{tier_key}")
        lines.append(f"{tier['label']}: {unit_price:,} تومان برای هر گیگ")
        lines.append("")
    lines.append("برای تغییر نرخ هر بازه:")
    lines.append("/setvpnrate tier_key amount")
    lines.append("مثال:")
    lines.append("/setvpnrate 1_5 190")
    lines.append("اگر عدد را کوتاه بزنی، خودکار هزار تومان در نظر گرفته می‌شود؛ مثلا 190 یعنی 190,000 تومان.")
    await update.effective_message.reply_text("\n".join(lines))


async def setvpnrate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in config.ADMIN_IDS:
        await update.effective_message.reply_text("شما دسترسی ادمین ندارید.")
        return

    if len(context.args) != 2:
        await update.effective_message.reply_text(
            "فرمت درست:\n/setvpnrate tier_key amount\n\n"
            "مثال:\n/setvpnrate 1_5 190\n"
            "نکته: 190 یعنی 190,000 تومان برای هر گیگ.\n\n"
            "برای دیدن tier_keyها دستور /vpnrates رو بزن."
        )
        return

    tier_key, raw_price = context.args
    if tier_key not in VPN_RATE_TIERS:
        await update.effective_message.reply_text("این tier_key پیدا نشد. برای لیست کامل /vpnrates رو بزن.")
        return

    normalized_price = normalize_int_text(raw_price)
    if not normalized_price.isdigit():
        await update.effective_message.reply_text("نرخ باید عددی باشد. مثال: 259000")
        return

    unit_price = storage.normalize_vpn_unit_price(int(normalized_price))
    storage.set_vpn_rate_override(tier_key, unit_price)
    await update.effective_message.reply_text(
        f"نرخ V2Ray آپدیت شد.\n"
        f"بازه: {VPN_RATE_TIERS[tier_key]['label']}\n"
        f"نرخ جدید: {unit_price:,} تومان برای هر گیگ"
    )


def format_orders_panel(status: str = "all") -> str:
    selected_status = None if status == "all" else status
    orders = storage.list_orders(selected_status, limit=10)
    counts = storage.count_orders_by_status()
    total = sum(counts.values())

    lines = [
        "پنل سفارش‌ها",
        "",
        f"همه: {total}",
        f"در انتظار فیش: {counts.get('waiting_receipt', 0)}",
        f"در حال بررسی فیش: {counts.get('pending_review', 0)}",
        f"تایید شده: {counts.get('approved', 0)}",
        f"انجام شده: {counts.get('delivered', 0)}",
        f"رد شده: {counts.get('rejected', 0)}",
        "",
        f"نمایش: {status_label(status)}",
    ]

    if not orders:
        lines.append("سفارشی برای این بخش پیدا نشد.")
        return "\n".join(lines)

    lines.append("آخرین 10 سفارش:")
    lines.append("")
    for order in orders:
        username = f"@{order['username']}" if order["username"] else "-"
        payment_method = order["payment_method"] if "payment_method" in order.keys() else None
        lines.extend(
            [
                f"ID: #{order['id']}",
                f"شماره سفارش: {display_order_code(order)}",
                f"تاریخ و ساعت: {order['created_at']}",
                f"سفارش: {order['product_title']}",
                f"مبلغ: {payable_toman(order['price'])}",
                f"نحوه پرداخت: {payment_method_label(payment_method)}",
                f"وضعیت: {status_label(order['status'])}",
                f"کاربر: {username} | {order['telegram_id'] or '-'}",
                "",
            ]
        )
    lines.append("برای تحویل سفارش: /deliver شناسه_داخلی متن_تحویل")
    return "\n".join(lines)


async def orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in config.ADMIN_IDS:
        await update.effective_message.reply_text("شما دسترسی ادمین ندارید.")
        return

    status = context.args[0] if context.args else "all"
    if status not in ORDER_STATUS_LABELS:
        await update.effective_message.reply_text("فیلتر درست نیست. از /orders استفاده کن.")
        return

    await update.effective_message.reply_text(
        format_orders_panel(status),
        reply_markup=admin_orders_keyboard(status),
    )


async def undelivered_orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in config.ADMIN_IDS:
        await update.effective_message.reply_text("شما دسترسی ادمین ندارید.")
        return

    await update.effective_message.reply_text(
        "سفارش‌های تایید شده ولی تحویل نشده\n\n" + format_orders_panel("approved"),
        reply_markup=admin_orders_keyboard("approved"),
    )


async def order_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in config.ADMIN_IDS:
        await update.effective_message.reply_text("شما دسترسی ادمین ندارید.")
        return

    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.effective_message.reply_text(
            "فرمت درست:\n"
            "/order order_id\n\n"
            "مثال:\n"
            "/order 29"
        )
        return

    order_id = int(context.args[0])
    order = storage.get_order(order_id)
    if not order:
        await update.effective_message.reply_text("سفارش پیدا نشد.")
        return

    await send_long_message(
        context.bot,
        update.effective_chat.id,
        format_order_detail_for_admin(order),
        parse_mode=ParseMode.HTML,
    )


async def helpadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in config.ADMIN_IDS:
        await update.effective_message.reply_text("شما دسترسی ادمین ندارید.")
        return

    await update.effective_message.reply_text(
        "راهنمای ادمین میتسو\n\n"
        "/orders لیست و فیلتر سفارش‌ها\n"
        "/undelivered سفارش‌های تایید شده ولی تحویل نشده\n"
        "/order order_id جزئیات کامل یک سفارش\n"
        "/deliver order_id متن_تحویل ارسال تحویل سفارش\n"
        "/deliver order_id متن_اختیاری در ریپلای روی فایل، ارسال فایل تحویل\n"
        "/prices لیست قیمت‌ها و product_keyها\n"
        "/productkeys لیست مرتب product_keyها بر اساس دسته‌بندی\n"
        "/get product_key_or_name دیدن قیمت فعلی یک سرویس\n"
        "/setprice product_key amount تغییر قیمت دلاری یا تومانی\n"
        "/setdiscount CODE percent all ساخت کد برای همه سرویس‌ها\n"
        "/setdiscount CODE percent product_key ساخت کد برای یک سرویس خاص\n"
        "/discounts لیست کدهای تخفیف فعال\n"
        "/deldiscount CODE غیرفعال کردن کد تخفیف\n"
        "/vpnrates نرخ‌های V2Ray\n"
        "/setvpnrate tier_key amount تغییر نرخ V2Ray\n"
        "/v2ray1glimit وضعیت محدودیت V2Ray 1 گیگ\n"
        "/v2ray1glimit on|off فعال/غیرفعال برای همه\n"
        "/v2ray1glimit user USER_ID on|off اعمال/معاف کردن یک کاربر\n"
        "/userwallet user_id_or_username دیدن موجودی کیف پول کاربر\n"
        "/addwallet user amount پیام_اختیاری افزایش موجودی کیف پول و پیام به کاربر\n"
        "/removewallet user amount پیام_اختیاری کاهش موجودی کیف پول و پیام به کاربر\n"
        "/users تعداد کاربران بات\n"
        "/broadcast متن ارسال پیام همگانی\n"
        "/refreshmenu ارسال منوی بروزرسانی‌شده برای همه کاربران\n"
        "/refreshmenu متن_اختیاری ارسال منوی جدید همراه متن دلخواه"
    )


async def orders_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if update.effective_user.id not in config.ADMIN_IDS:
        await query.edit_message_text("شما دسترسی ادمین ندارید.")
        return

    status = query.data.split(":", 1)[1]
    if status not in ORDER_STATUS_LABELS:
        await query.edit_message_text("فیلتر سفارش نامعتبر است.")
        return

    await query.edit_message_text(
        format_orders_panel(status),
        reply_markup=admin_orders_keyboard(status),
    )


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in config.ADMIN_IDS:
        await update.effective_message.reply_text("شما دسترسی ادمین ندارید.")
        return

    raw_text = update.effective_message.text or ""
    parts = raw_text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await update.effective_message.reply_text(
            "فرمت درست:\n"
            "/broadcast متن پیام\n\n"
            "مثال:\n"
            "/broadcast سلام، تخفیف‌های جدید میتسو فعال شد."
        )
        return

    message = parts[1].strip()
    user_ids = storage.list_user_ids()
    if not user_ids:
        await update.effective_message.reply_text("هنوز کاربری برای ارسال همگانی ذخیره نشده است.")
        return

    await update.effective_message.reply_text(f"ارسال پیام همگانی شروع شد. تعداد کاربران: {len(user_ids)}")
    sent = 0
    failed = 0
    for user_id in user_ids:
        try:
            await context.bot.send_message(chat_id=user_id, text=message)
            sent += 1
        except Exception:
            failed += 1
            logger.exception("Could not broadcast to user %s", user_id)

    await update.effective_message.reply_text(
        f"ارسال همگانی تمام شد.\n"
        f"موفق: {sent}\n"
        f"ناموفق: {failed}"
    )


async def refreshmenu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in config.ADMIN_IDS:
        await update.effective_message.reply_text("شما دسترسی ادمین ندارید.")
        return

    raw_text = update.effective_message.text or ""
    parts = raw_text.split(maxsplit=1)
    message = (
        parts[1].strip()
        if len(parts) > 1 and parts[1].strip()
        else (
            "❤️ سلام به ربات میتسو خوش اومدین ❤️\n"
            "✨ امیدوارم خرید خوبی رو تجربه کنید ✨\n"
            "👇 لطفا سفارش مد نظرتونو انتخاب کنید:"
        )
    )

    user_ids = storage.list_user_ids()
    if not user_ids:
        await update.effective_message.reply_text("هنوز کاربری برای ارسال منوی جدید ذخیره نشده است.")
        return

    await update.effective_message.reply_text(f"ارسال منوی جدید شروع شد. تعداد کاربران: {len(user_ids)}")
    sent = 0
    failed = 0
    for user_id in user_ids:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=message,
                reply_markup=categories_keyboard(),
            )
            sent += 1
        except Exception:
            failed += 1
            logger.exception("Could not send refreshed menu to user %s", user_id)

    await update.effective_message.reply_text(
        f"ارسال منوی جدید تمام شد.\n"
        f"موفق: {sent}\n"
        f"ناموفق: {failed}"
    )


async def check_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    remember_user(update)
    query = update.callback_query

    if not await require_channel_membership(update, context):
        return SELECTING_PRODUCT
    await query.answer("عضویت تایید شد.")

    context.user_data.clear()
    if not storage.has_accepted_rules(update.effective_user.id):
        await query.edit_message_text(
            f"عضویتت تایید شد.\n\n{SHOP_RULES}{RULES_ACCEPTANCE_NOTE}",
            reply_markup=rules_acceptance_keyboard(),
        )
        return SELECTING_PRODUCT

    await query.edit_message_text(
        "عضویتت تایید شد. حالا دسته‌بندی مورد نظرت رو انتخاب کن:",
        reply_markup=categories_keyboard(),
    )
    return SELECTING_PRODUCT


def main() -> None:
    if not config.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN تنظیم نشده است.")
    if not config.ADMIN_IDS:
        raise RuntimeError("ADMIN_IDS تنظیم نشده است.")

    storage.init_db()
    storage.sync_catalog_from_config(config.CATEGORIES, config.PRODUCTS)
    storage.backfill_users_from_orders()
    start_usdt_cache_updater()
    app = Application.builder().token(config.BOT_TOKEN).build()
    conversation = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SELECTING_PRODUCT: [
                CallbackQueryHandler(check_join, pattern=r"^check_join$"),
                CallbackQueryHandler(rules_callback, pattern=r"^rules$"),
                CallbackQueryHandler(accept_rules_callback, pattern=r"^accept_rules$"),
                CallbackQueryHandler(myorders_callback, pattern=r"^myorders$"),
                CallbackQueryHandler(wallet_show, pattern=r"^wallet_show$"),
                CallbackQueryHandler(wallet_charge_start, pattern=r"^wallet_charge$"),
                CallbackQueryHandler(choose_category, pattern=r"^category:"),
                CallbackQueryHandler(choose_edit_subcategory, pattern=r"^subcategory:"),
                CallbackQueryHandler(back_to_category, pattern=r"^back:category:"),
                CallbackQueryHandler(back_to_categories, pattern=r"^back:categories$"),
                CallbackQueryHandler(choose_product, pattern=r"^product:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_text),
            ],
            ASK_VPN_VOLUME: [
                CallbackQueryHandler(check_join, pattern=r"^check_join$"),
                CallbackQueryHandler(myorders_callback, pattern=r"^myorders$"),
                CallbackQueryHandler(wallet_show, pattern=r"^wallet_show$"),
                CallbackQueryHandler(choose_category, pattern=r"^category:"),
                CallbackQueryHandler(choose_edit_subcategory, pattern=r"^subcategory:"),
                CallbackQueryHandler(back_to_category, pattern=r"^back:category:"),
                CallbackQueryHandler(back_to_categories, pattern=r"^back:categories$"),
                CallbackQueryHandler(choose_product, pattern=r"^product:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_vpn_volume),
            ],
            ASK_FOREIGN_SITE_URL: [
                CallbackQueryHandler(check_join, pattern=r"^check_join$"),
                CallbackQueryHandler(myorders_callback, pattern=r"^myorders$"),
                CallbackQueryHandler(wallet_show, pattern=r"^wallet_show$"),
                CallbackQueryHandler(choose_category, pattern=r"^category:"),
                CallbackQueryHandler(choose_edit_subcategory, pattern=r"^subcategory:"),
                CallbackQueryHandler(back_to_category, pattern=r"^back:category:"),
                CallbackQueryHandler(back_to_categories, pattern=r"^back:categories$"),
                CallbackQueryHandler(choose_product, pattern=r"^product:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_foreign_site_url),
            ],
            ASK_FOREIGN_USD_AMOUNT: [
                CallbackQueryHandler(check_join, pattern=r"^check_join$"),
                CallbackQueryHandler(myorders_callback, pattern=r"^myorders$"),
                CallbackQueryHandler(wallet_show, pattern=r"^wallet_show$"),
                CallbackQueryHandler(choose_category, pattern=r"^category:"),
                CallbackQueryHandler(choose_edit_subcategory, pattern=r"^subcategory:"),
                CallbackQueryHandler(back_to_category, pattern=r"^back:category:"),
                CallbackQueryHandler(back_to_categories, pattern=r"^back:categories$"),
                CallbackQueryHandler(choose_product, pattern=r"^product:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_foreign_usd_amount),
            ],
            ASK_FOREIGN_USERNAME: [
                CallbackQueryHandler(check_join, pattern=r"^check_join$"),
                CallbackQueryHandler(skip_foreign_username, pattern=r"^foreign_skip_username$"),
                CallbackQueryHandler(myorders_callback, pattern=r"^myorders$"),
                CallbackQueryHandler(wallet_show, pattern=r"^wallet_show$"),
                CallbackQueryHandler(choose_category, pattern=r"^category:"),
                CallbackQueryHandler(choose_edit_subcategory, pattern=r"^subcategory:"),
                CallbackQueryHandler(back_to_category, pattern=r"^back:category:"),
                CallbackQueryHandler(back_to_categories, pattern=r"^back:categories$"),
                CallbackQueryHandler(choose_product, pattern=r"^product:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_foreign_username),
            ],
            ASK_FOREIGN_PASSWORD: [
                CallbackQueryHandler(check_join, pattern=r"^check_join$"),
                CallbackQueryHandler(skip_foreign_password, pattern=r"^foreign_skip_password$"),
                CallbackQueryHandler(myorders_callback, pattern=r"^myorders$"),
                CallbackQueryHandler(wallet_show, pattern=r"^wallet_show$"),
                CallbackQueryHandler(choose_category, pattern=r"^category:"),
                CallbackQueryHandler(choose_edit_subcategory, pattern=r"^subcategory:"),
                CallbackQueryHandler(back_to_category, pattern=r"^back:category:"),
                CallbackQueryHandler(back_to_categories, pattern=r"^back:categories$"),
                CallbackQueryHandler(choose_product, pattern=r"^product:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_foreign_password),
            ],
            ASK_SPOTIFY_ACCOUNT_CHOICE: [
                CallbackQueryHandler(check_join, pattern=r"^check_join$"),
                CallbackQueryHandler(myorders_callback, pattern=r"^myorders$"),
                CallbackQueryHandler(wallet_show, pattern=r"^wallet_show$"),
                CallbackQueryHandler(choose_spotify_account, pattern=r"^spotify_(has|no)_account$"),
                CallbackQueryHandler(choose_category, pattern=r"^category:"),
                CallbackQueryHandler(choose_edit_subcategory, pattern=r"^subcategory:"),
                CallbackQueryHandler(back_to_category, pattern=r"^back:category:"),
                CallbackQueryHandler(back_to_categories, pattern=r"^back:categories$"),
                CallbackQueryHandler(choose_product, pattern=r"^product:"),
            ],
            ASK_TELEGRAM_ID: [
                CallbackQueryHandler(check_join, pattern=r"^check_join$"),
                CallbackQueryHandler(myorders_callback, pattern=r"^myorders$"),
                CallbackQueryHandler(wallet_show, pattern=r"^wallet_show$"),
                CallbackQueryHandler(use_own_username, pattern=r"^use_own_username$"),
                CallbackQueryHandler(choose_category, pattern=r"^category:"),
                CallbackQueryHandler(choose_edit_subcategory, pattern=r"^subcategory:"),
                CallbackQueryHandler(back_to_category, pattern=r"^back:category:"),
                CallbackQueryHandler(back_to_categories, pattern=r"^back:categories$"),
                CallbackQueryHandler(choose_product, pattern=r"^product:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_telegram_id),
            ],
            ASK_SPOTIFY_EMAIL: [
                CallbackQueryHandler(check_join, pattern=r"^check_join$"),
                CallbackQueryHandler(myorders_callback, pattern=r"^myorders$"),
                CallbackQueryHandler(wallet_show, pattern=r"^wallet_show$"),
                CallbackQueryHandler(choose_category, pattern=r"^category:"),
                CallbackQueryHandler(choose_edit_subcategory, pattern=r"^subcategory:"),
                CallbackQueryHandler(back_to_category, pattern=r"^back:category:"),
                CallbackQueryHandler(back_to_categories, pattern=r"^back:categories$"),
                CallbackQueryHandler(choose_product, pattern=r"^product:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_spotify_email),
            ],
            ASK_SPOTIFY_PASSWORD: [
                CallbackQueryHandler(check_join, pattern=r"^check_join$"),
                CallbackQueryHandler(myorders_callback, pattern=r"^myorders$"),
                CallbackQueryHandler(wallet_show, pattern=r"^wallet_show$"),
                CallbackQueryHandler(choose_category, pattern=r"^category:"),
                CallbackQueryHandler(choose_edit_subcategory, pattern=r"^subcategory:"),
                CallbackQueryHandler(back_to_category, pattern=r"^back:category:"),
                CallbackQueryHandler(back_to_categories, pattern=r"^back:categories$"),
                CallbackQueryHandler(choose_product, pattern=r"^product:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_spotify_password),
            ],
            ASK_APPLE_ID: [
                CallbackQueryHandler(check_join, pattern=r"^check_join$"),
                CallbackQueryHandler(myorders_callback, pattern=r"^myorders$"),
                CallbackQueryHandler(wallet_show, pattern=r"^wallet_show$"),
                CallbackQueryHandler(choose_category, pattern=r"^category:"),
                CallbackQueryHandler(choose_edit_subcategory, pattern=r"^subcategory:"),
                CallbackQueryHandler(back_to_category, pattern=r"^back:category:"),
                CallbackQueryHandler(back_to_categories, pattern=r"^back:categories$"),
                CallbackQueryHandler(choose_product, pattern=r"^product:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_apple_id),
            ],
            ASK_CHATGPT_SESSION: [
                CallbackQueryHandler(check_join, pattern=r"^check_join$"),
                CallbackQueryHandler(finish_chatgpt_session, pattern=r"^finish_chatgpt_session$"),
                CallbackQueryHandler(myorders_callback, pattern=r"^myorders$"),
                CallbackQueryHandler(wallet_show, pattern=r"^wallet_show$"),
                CallbackQueryHandler(choose_category, pattern=r"^category:"),
                CallbackQueryHandler(choose_edit_subcategory, pattern=r"^subcategory:"),
                CallbackQueryHandler(back_to_category, pattern=r"^back:category:"),
                CallbackQueryHandler(back_to_categories, pattern=r"^back:categories$"),
                CallbackQueryHandler(choose_product, pattern=r"^product:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_chatgpt_session),
            ],
            ASK_CLAUDE_USER_ID: [
                CallbackQueryHandler(check_join, pattern=r"^check_join$"),
                CallbackQueryHandler(myorders_callback, pattern=r"^myorders$"),
                CallbackQueryHandler(wallet_show, pattern=r"^wallet_show$"),
                CallbackQueryHandler(choose_category, pattern=r"^category:"),
                CallbackQueryHandler(choose_edit_subcategory, pattern=r"^subcategory:"),
                CallbackQueryHandler(back_to_category, pattern=r"^back:category:"),
                CallbackQueryHandler(back_to_categories, pattern=r"^back:categories$"),
                CallbackQueryHandler(choose_product, pattern=r"^product:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_claude_user_id),
            ],
            ASK_DISCOUNT_CODE: [
                CallbackQueryHandler(check_join, pattern=r"^check_join$"),
                CallbackQueryHandler(myorders_callback, pattern=r"^myorders$"),
                CallbackQueryHandler(wallet_show, pattern=r"^wallet_show$"),
                CallbackQueryHandler(discount_decision, pattern=r"^discount_(enter|skip):"),
                CallbackQueryHandler(choose_category, pattern=r"^category:"),
                CallbackQueryHandler(choose_edit_subcategory, pattern=r"^subcategory:"),
                CallbackQueryHandler(back_to_category, pattern=r"^back:category:"),
                CallbackQueryHandler(back_to_categories, pattern=r"^back:categories$"),
                CallbackQueryHandler(choose_product, pattern=r"^product:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_discount_code),
            ],
            ASK_RECEIPT: [
                CallbackQueryHandler(check_join, pattern=r"^check_join$"),
                CallbackQueryHandler(myorders_callback, pattern=r"^myorders$"),
                CallbackQueryHandler(wallet_show, pattern=r"^wallet_show$"),
                CallbackQueryHandler(choose_category, pattern=r"^category:"),
                CallbackQueryHandler(choose_edit_subcategory, pattern=r"^subcategory:"),
                CallbackQueryHandler(back_to_category, pattern=r"^back:category:"),
                CallbackQueryHandler(back_to_categories, pattern=r"^back:categories$"),
                CallbackQueryHandler(choose_product, pattern=r"^product:"),
                MessageHandler(filters.PHOTO | filters.Document.ALL, receive_receipt),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_receipt_text),
            ],
            ASK_PAYMENT_METHOD: [
                CallbackQueryHandler(check_join, pattern=r"^check_join$"),
                CallbackQueryHandler(wallet_charge_start, pattern=r"^wallet_charge$"),
                CallbackQueryHandler(myorders_callback, pattern=r"^myorders$"),
                CallbackQueryHandler(wallet_show, pattern=r"^wallet_show$"),
                CallbackQueryHandler(choose_category, pattern=r"^category:"),
                CallbackQueryHandler(choose_edit_subcategory, pattern=r"^subcategory:"),
                CallbackQueryHandler(back_to_category, pattern=r"^back:category:"),
                CallbackQueryHandler(back_to_categories, pattern=r"^back:categories$"),
                CallbackQueryHandler(choose_product, pattern=r"^product:"),
                CallbackQueryHandler(choose_payment_method, pattern=r"^pay_(wallet|card):"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_text),
            ],
            ASK_WALLET_AMOUNT: [
                CallbackQueryHandler(check_join, pattern=r"^check_join$"),
                CallbackQueryHandler(myorders_callback, pattern=r"^myorders$"),
                CallbackQueryHandler(choose_category, pattern=r"^category:"),
                CallbackQueryHandler(choose_edit_subcategory, pattern=r"^subcategory:"),
                CallbackQueryHandler(back_to_category, pattern=r"^back:category:"),
                CallbackQueryHandler(back_to_categories, pattern=r"^back:categories$"),
                CallbackQueryHandler(choose_product, pattern=r"^product:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_wallet_amount),
            ],
            ASK_WALLET_RECEIPT: [
                CallbackQueryHandler(check_join, pattern=r"^check_join$"),
                CallbackQueryHandler(myorders_callback, pattern=r"^myorders$"),
                CallbackQueryHandler(choose_category, pattern=r"^category:"),
                CallbackQueryHandler(choose_edit_subcategory, pattern=r"^subcategory:"),
                CallbackQueryHandler(back_to_category, pattern=r"^back:category:"),
                CallbackQueryHandler(back_to_categories, pattern=r"^back:categories$"),
                CallbackQueryHandler(choose_product, pattern=r"^product:"),
                MessageHandler(filters.PHOTO | filters.Document.ALL, receive_wallet_receipt),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_wallet_receipt_text),
            ],
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("help", help_command),
            CommandHandler("info", info_command),
            CommandHandler("rules", rules_command),
            CommandHandler("myorders", myorders_command),
            CommandHandler("wallet", wallet_command),
            CommandHandler("charge", wallet_charge_start),
            CommandHandler("userwallet", userwallet_command),
            CommandHandler("addwallet", addwallet_command),
            CommandHandler("removewallet", removewallet_command),
            CommandHandler("users", users_command),
            CommandHandler("prices", prices_command),
            CommandHandler("productkeys", productkeys_command),
            CommandHandler("get", get_price_command),
            CommandHandler("setprice", setprice_command),
            CommandHandler("setdiscount", setdiscount_command),
            CommandHandler("discounts", discounts_command),
            CommandHandler("deldiscount", deldiscount_command),
            CommandHandler("vpnrates", vpnrates_command),
            CommandHandler("setvpnrate", setvpnrate_command),
            CommandHandler("v2ray1glimit", v2ray1glimit_command),
            CommandHandler("orders", orders_command),
            CommandHandler("undelivered", undelivered_orders_command),
            CommandHandler("pendingdeliver", undelivered_orders_command),
            CommandHandler("order", order_command),
            CommandHandler("helpadmin", helpadmin_command),
            CommandHandler("broadcast", broadcast_command),
            CommandHandler("refreshmenu", refreshmenu_command),
            CommandHandler("cancel", cancel),
        ],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("info", info_command))
    app.add_handler(CommandHandler("rules", rules_command))
    app.add_handler(CommandHandler("myorders", myorders_command))
    app.add_handler(CommandHandler("wallet", wallet_command))
    app.add_handler(CommandHandler("charge", wallet_charge_start))
    app.add_handler(CommandHandler("userwallet", userwallet_command))
    app.add_handler(CommandHandler("addwallet", addwallet_command))
    app.add_handler(CommandHandler("removewallet", removewallet_command))
    app.add_handler(CommandHandler("users", users_command))
    app.add_handler(CommandHandler("prices", prices_command))
    app.add_handler(CommandHandler("productkeys", productkeys_command))
    app.add_handler(CommandHandler("get", get_price_command))
    app.add_handler(CommandHandler("setprice", setprice_command))
    app.add_handler(CommandHandler("setdiscount", setdiscount_command))
    app.add_handler(CommandHandler("discounts", discounts_command))
    app.add_handler(CommandHandler("deldiscount", deldiscount_command))
    app.add_handler(CommandHandler("vpnrates", vpnrates_command))
    app.add_handler(CommandHandler("setvpnrate", setvpnrate_command))
    app.add_handler(CommandHandler("v2ray1glimit", v2ray1glimit_command))
    app.add_handler(CommandHandler("orders", orders_command))
    app.add_handler(CommandHandler("undelivered", undelivered_orders_command))
    app.add_handler(CommandHandler("pendingdeliver", undelivered_orders_command))
    app.add_handler(CommandHandler("order", order_command))
    app.add_handler(CommandHandler("helpadmin", helpadmin_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("refreshmenu", refreshmenu_command))
    app.add_handler(conversation)
    app.add_handler(CallbackQueryHandler(rules_callback, pattern=r"^rules$"))
    app.add_handler(CallbackQueryHandler(accept_rules_callback, pattern=r"^accept_rules$"))
    app.add_handler(CallbackQueryHandler(myorders_callback, pattern=r"^myorders$"))
    app.add_handler(CallbackQueryHandler(wallet_show, pattern=r"^wallet_show$"))
    app.add_handler(CallbackQueryHandler(wallet_charge_start, pattern=r"^wallet_charge$"))
    app.add_handler(CallbackQueryHandler(wallet_topup_decision, pattern=r"^topup_(approve|reject):"))
    app.add_handler(CallbackQueryHandler(orders_filter, pattern=r"^orders:"))
    app.add_handler(CallbackQueryHandler(admin_decision, pattern=r"^(approve|reject):"))
    app.add_handler(CommandHandler("deliver", deliver))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, start))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
