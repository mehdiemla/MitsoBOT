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
MINI_APP_HOST = os.getenv("MINI_APP_HOST", "127.0.0.1")
MINI_APP_PORT = int(os.getenv("MINI_APP_PORT", "8090"))
BITPIN_MARKETS_URL = os.getenv("BITPIN_MARKETS_URL", "https://api.bitpin.ir/v1/mkt/markets/")


def is_valid_mini_app_url(url: str) -> bool:
    normalized = url.strip().rstrip("/")
    if not normalized.startswith("https://"):
        return False
    return normalized not in {"https://t.me", "https://telegram.me"}


MINI_APP_ENABLED = os.getenv("MINI_APP_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
_default_mini_app_url = f"{SUPPORT_SITE.rstrip('/')}/"
MINI_APP_URL = os.getenv("MINI_APP_URL", _default_mini_app_url if MINI_APP_ENABLED else "")
if not MINI_APP_ENABLED or not is_valid_mini_app_url(MINI_APP_URL):
    MINI_APP_URL = ""

SPOTIFY_ACCOUNT_CREATION_FEE = 111000

CATEGORIES = {'spotify': '🎵 موسیقی و پادکست',
 'capcut': '🎬 ادیت فیلم و عکس',
 'ai': '🤖 هوش مصنوعی و AI',
 'education': '📚 آموزشی',
 'social': '📱 سوشال مدیا',
 'finance': '💎 پکیج مالی',
 'sim': '📶 سیم\u200cکارت و eSIM',
 'other': '🛠 سرویس\u200cهای اتصال',
 'foreign_payment': '💳 پرداخت در سایت\u200cهای خارجی'}

PRODUCTS = {'spotify_1': {'title': '🎵 اسپاتیفای 1 ماهه - ریجن نیجریه',
               'category': 'spotify',
               'subcategory': 'spotify',
               'price': 549000,
               'usd_price': 2.75,
               'needs_credentials': True},
 'spotify_3': {'title': '🎵 اسپاتیفای 3 ماهه - ریجن مصر',
               'category': 'spotify',
               'subcategory': 'spotify',
               'price': 1649000,
               'usd_price': 9.35,
               'needs_credentials': True},
 'spotify_6': {'title': '🎵 اسپاتیفای 6 ماهه - ریجن مصر',
               'category': 'spotify',
               'subcategory': 'spotify',
               'price': 2859000,
               'usd_price': 15.4,
               'needs_credentials': True},
 'spotify_12': {'title': '🎵 اسپاتیفای 1 ساله - ریجن مصر',
                'category': 'spotify',
                'subcategory': 'spotify',
                'price': 5169000,
                'usd_price': 26.4,
                'needs_credentials': True},
 'soundcloud_go_1': {'title': '🎧 SoundCloud Go یک ماهه',
                     'category': 'spotify',
                     'subcategory': 'soundcloud',
                     'price': 278000,
                     'usd_price': 1.54,
                     'needs_credentials': True},
 'apple_music_1': {'title': '🎵 Apple Music یک ماهه',
                   'category': 'spotify',
                   'subcategory': 'apple_music',
                   'price': 575000,
                   'usd_price': 3.19,
                   'needs_credentials': False,
                   'needs_apple_id': True},
 'apple_music_3': {'title': '🎵 Apple Music سه ماهه',
                   'category': 'spotify',
                   'subcategory': 'apple_music',
                   'price': 693000,
                   'usd_price': 3.85,
                   'needs_credentials': False,
                   'needs_apple_id': True},
 'apple_music_6': {'title': '🎵 Apple Music شش ماهه',
                   'category': 'spotify',
                   'subcategory': 'apple_music',
                   'price': 1169000,
                   'usd_price': 6.49,
                   'needs_credentials': False,
                   'needs_apple_id': True},
 'apple_music_12': {'title': '🎵 Apple Music یک ساله',
                    'category': 'spotify',
                    'subcategory': 'apple_music',
                    'price': 1941000,
                    'usd_price': 10.78,
                    'needs_credentials': False,
                    'needs_apple_id': True},
 'castbox_premium_1': {'title': '🎙 Castbox Premium یک ماهه - روی اکانت شخصی',
                       'category': 'spotify',
                       'subcategory': 'castbox',
                       'price': 219000,
                       'usd_price': 1.21,
                       'needs_credentials': True},
 'castbox_premium_3': {'title': '🎙 Castbox Premium سه ماهه - روی اکانت شخصی',
                       'category': 'spotify',
                       'subcategory': 'castbox',
                       'price': 457000,
                       'usd_price': 2.53,
                       'needs_credentials': True},
 'castbox_premium_12': {'title': '🎙 Castbox Premium یک ساله - روی اکانت شخصی',
                        'category': 'spotify',
                        'subcategory': 'castbox',
                        'price': 795000,
                        'usd_price': 4.4,
                        'needs_credentials': True},
 'castbox_pro_1': {'title': '🎙 Castbox Pro یک ماهه - روی اکانت شخصی',
                   'category': 'spotify',
                   'subcategory': 'castbox',
                   'price': 437000,
                   'usd_price': 2.42,
                   'needs_credentials': True},
 'castbox_pro_3': {'title': '🎙 Castbox Pro سه ماهه - روی اکانت شخصی',
                   'category': 'spotify',
                   'subcategory': 'castbox',
                   'price': 735000,
                   'usd_price': 4.07,
                   'needs_credentials': True},
 'castbox_pro_12': {'title': '🎙 Castbox Pro یک ساله - روی اکانت شخصی',
                    'category': 'spotify',
                    'subcategory': 'castbox',
                    'price': 1787000,
                    'usd_price': 9.9,
                    'needs_credentials': True},
 'claude_pro_1': {'title': '🧠 Claude Pro',
                  'category': 'ai',
                  'subcategory': 'claude',
                  'price': 3527000,
                  'usd_price': 20.35,
                  'needs_credentials': False,
                  'needs_claude_user_id': True,
                  'description': 'پلن Pro روی اکانت شخصی شما فعال می\u200cشود.\n'
                                 'نیازی به لاگین، نام کاربری یا رمز عبور نیست.\n'
                                 'فقط Claude User ID شما از مسیر رسمی لازم است.\n'
                                 'برای دریافت Claude User ID وارد claude.ai/settings شوید و User ID را در بخش Account '
                                 'Info پیدا کنید.'},
 'chatgpt_no_login_1': {'title': '🤖 ChatGPT روی اکانت شما',
                        'category': 'ai',
                        'subcategory': 'chatgpt',
                        'price': 4179000,
                        'usd_price': 20.9,
                        'needs_credentials': False,
                        'needs_chatgpt_session': True,
                        'description': 'روی اکانت ChatGPT خودتان فعال می\u200cشود.\n'
                                       'نیازی نیست رمز عبور اکانت را برای ما بفرستید؛ فقط session اکانت طبق راهنمای '
                                       'مرحله بعد لازم است.\n'
                                       'مناسب زمانی که می\u200cخواهید اشتراک روی همان اکانت و چت\u200cهای قبلی خودتان '
                                       'باشد.'},
 'chatgpt_go_1': {'title': '🤖 ChatGPT Go یک ماهه',
                  'category': 'ai',
                  'subcategory': 'chatgpt',
                  'price': 2772000,
                  'usd_price': 15.4,
                  'needs_credentials': False,
                  'description': 'پلن اقتصادی ChatGPT Go یک ماهه است.\n'
                                 'بعد از تایید پرداخت، اطلاعات فعال\u200cسازی یا تحویل توسط پشتیبانی ارسال '
                                 'می\u200cشود.'},
 'chatgpt_ready_personal_1': {'title': '🤖 GPT آماده شخصی',
                              'category': 'ai',
                              'subcategory': 'chatgpt',
                              'price': 1783000,
                              'usd_price': 9.9,
                              'needs_credentials': False,
                              'description': 'اکانت آماده شخصی ChatGPT یک ماهه تحویل می\u200cگیرید.\n'
                                             'نیازی به ارسال session یا لاگین اکانت خودتان نیست.\n'
                                             'مناسب کاربرهایی که می\u200cخواهند سریع با یک اکانت آماده شروع کنند.'},
 'chatgpt_shared_1': {'title': '🤖 ChatGPT اشتراکی یک ماهه',
                      'category': 'ai',
                      'subcategory': 'chatgpt',
                      'price': 991000,
                      'usd_price': 5.5,
                      'needs_credentials': False,
                      'description': 'اشتراک اشتراکی ChatGPT یک ماهه.\n'
                                     'بعد از تایید پرداخت، اطلاعات ورود توسط پشتیبانی ارسال می\u200cشود.'},
 'gemini_3': {'title': '🤖 Gemini سه ماهه',
              'category': 'ai',
              'subcategory': 'gemini',
              'price': 2080000,
              'usd_price': 11.55,
              'needs_credentials': False,
              'needs_delivery_email': True},
 'gemini_18': {'title': '🤖 Gemini هجده ماهه - با 24 ساعت گارانتی',
               'category': 'ai',
               'subcategory': 'gemini',
               'price': 2200000,
               'usd_price': 12.1,
               'needs_credentials': False,
               'needs_delivery_email': True},
 'super_grok_1': {'title': '⚡ Super Grok',
                  'category': 'ai',
                  'subcategory': 'grok',
                  'price': 1979000,
                  'usd_price': 11.0,
                  'needs_credentials': False,
                  'description': 'اشتراک Super Grok یک ماهه برای استفاده از قابلیت\u200cهای هوش مصنوعی Grok.\n'
                                 'بعد از تایید پرداخت، جزئیات فعال\u200cسازی یا تحویل توسط پشتیبانی ارسال '
                                 'می\u200cشود.'},
 'super_grok_ready_1': {'title': '⚡ Grok آماده',
                        'category': 'ai',
                        'subcategory': 'grok',
                        'price': 1882000,
                        'usd_price': 10.45,
                        'needs_credentials': False,
                        'description': 'اکانت آماده Super Grok یک ماهه تحویل می\u200cگیرید.\n'
                                       'نیازی به ارسال اطلاعات اکانت شخصی خودتان نیست.\n'
                                       'مناسب سفارش سریع و آماده تحویل.'},
 'cursor_pro_1': {'title': '💻 Cursor Pro',
                  'category': 'ai',
                  'subcategory': 'cursor',
                  'price': 3763000,
                  'usd_price': 20.9,
                  'needs_credentials': False,
                  'needs_delivery_email': True,
                  'description': 'Cursor Pro یک ماهه با تحویل لینک فعال\u200cسازی به ایمیل شما.\n'
                                 'برای توسعه\u200cدهنده\u200cهایی که می\u200cخواهند روی ایمیل خودشان دسترسی Pro داشته '
                                 'باشند.'},
 'cursor_ready_1': {'title': '💻 Cursor آماده',
                    'category': 'ai',
                    'subcategory': 'cursor',
                    'price': 3862000,
                    'usd_price': 21.45,
                    'needs_credentials': False,
                    'description': 'اکانت آماده Cursor یک ماهه تحویل می\u200cگیرید.\n'
                                   'نیازی به ارسال ایمیل برای لینک فعال\u200cسازی نیست.\n'
                                   'مناسب کاربرهایی که اکانت آماده و سریع می\u200cخواهند.'},
 'cursor_pro_plus_1': {'title': '💻 Cursor Pro Plus',
                       'category': 'ai',
                       'subcategory': 'cursor',
                       'price': 8712000,
                       'usd_price': 48.4,
                       'needs_credentials': False,
                       'needs_delivery_email': True,
                       'description': 'Cursor Pro Plus یک ماهه با تحویل لینک فعال\u200cسازی به ایمیل شما.\n'
                                      'پلن قوی\u200cتر برای استفاده سنگین\u200cتر از امکانات Cursor.'},
 'cursor_pro_education': {'title': '🤖 Cursor Pro Education - با 5 ساعت گارانتی',
                          'category': 'ai',
                          'subcategory': 'cursor',
                          'price': 6931000,
                          'usd_price': 38.5,
                          'needs_credentials': False,
                          'needs_delivery_email': True},
 'capcut_personal_4': {'title': '🎬 CapCut چهار ماهه شخصی',
                       'category': 'capcut',
                       'subcategory': 'capcut',
                       'price': 3299000,
                       'usd_price': 19.8,
                       'needs_credentials': False},
 'capcut_pro_team_30': {'title': '🎬 CapCut Pro تیم - 30 روزه',
                        'category': 'capcut',
                        'subcategory': 'capcut',
                        'price': 793000,
                        'usd_price': 4.4,
                        'needs_credentials': False},
 'capcut_team_6': {'title': '🎬 CapCut شش ماهه تیم',
                   'category': 'capcut',
                   'subcategory': 'capcut',
                   'price': 2178000,
                   'usd_price': 12.1,
                   'needs_credentials': False},
 'capcut_personal_12': {'title': '🎬 CapCut یک ساله شخصی',
                        'category': 'capcut',
                        'subcategory': 'capcut',
                        'price': 9702000,
                        'usd_price': 53.9,
                        'needs_credentials': False},
 'capcut_shared_premade_1': {'title': '🎬 CapCut Pro اشتراکی پیش\u200cساخته - یک ماهه',
                             'category': 'capcut',
                             'subcategory': 'capcut',
                             'price': 594000,
                             'usd_price': 3.3,
                             'needs_credentials': False},
 'canva_family_personal_1': {'title': '🎨 Canva اکانت شخصی عضو فمیلی - یک ماهه',
                             'category': 'capcut',
                             'subcategory': 'canva',
                             'price': 297000,
                             'usd_price': 1.65,
                             'needs_credentials': False},
 'figma_education_12': {'title': '🎨 Figma Education یک ساله',
                        'category': 'capcut',
                        'subcategory': 'figma',
                        'price': 1981000,
                        'usd_price': 11.0,
                        'needs_credentials': False},
 'duolingo_super_12': {'title': '📚 Duolingo Super یک ساله',
                       'category': 'education',
                       'price': 3169000,
                       'usd_price': 17.6,
                       'needs_credentials': False},
 'duolingo_max_12': {'title': '📚 Duolingo Max یک ساله',
                     'category': 'education',
                     'price': 5742000,
                     'usd_price': 31.9,
                     'needs_credentials': False},
 'duolingo_team_12': {'title': '📚 Duolingo تیم کامل یک ساله - افزودن 5 نفر',
                      'category': 'education',
                      'price': 7723000,
                      'usd_price': 42.9,
                      'needs_credentials': False},
 'telegram_premium_3': {'title': '⭐ Telegram Premium سه ماهه',
                        'category': 'social',
                        'subcategory': 'telegram',
                        'price': 2772000,
                        'usd_price': 15.4,
                        'needs_credentials': False},
 'telegram_premium_6': {'title': '⭐ Telegram Premium شش ماهه',
                        'category': 'social',
                        'subcategory': 'telegram',
                        'price': 3763000,
                        'usd_price': 20.9,
                        'needs_credentials': False},
 'telegram_premium_12': {'title': '⭐ Telegram Premium یک ساله',
                         'category': 'social',
                         'subcategory': 'telegram',
                         'price': 6535000,
                         'usd_price': 36.3,
                         'needs_credentials': False},
 'linkedin_first_1': {'title': '💼 LinkedIn Premium یک ماهه — فعال\u200cسازی اولین اشتراک',
                      'category': 'social',
                      'subcategory': 'linkedin',
                      'price': 281000,
                      'usd_price': 1.65,
                      'hide_usd_in_miniapp': True,
                      'needs_credentials': True,
                      'description': '⚠️ قوانین اولین اشتراک\n'
                                     '\n'
                                     'در صورتی که قبلاً حتی یک بار اشتراک فعال داشته باشید، این گزینه مناسب شما نیست. '
                                     'اگر این گزینه را پرداخت کنید، هزینه شما با کسر ۱۰ درصد مالیات عودت داده خواهد '
                                     'شد.',
                      'payment_note': 'تحویل سفارش: ۱ تا ۷۲ ساعت کاری.'},
 'linkedin_renew_1': {'title': '💼 LinkedIn Premium یک ماهه — تمدید',
                      'category': 'social',
                      'subcategory': 'linkedin',
                      'price': 903000,
                      'usd_price': 5.28,
                      'hide_usd_in_miniapp': True,
                      'needs_credentials': True,
                      'payment_note': 'تحویل سفارش: ۱ تا ۷۲ ساعت کاری.'},
 'linkedin_renew_12': {'title': '💼 LinkedIn Premium یک ساله — تمدید',
                       'category': 'social',
                       'subcategory': 'linkedin',
                       'price': 5610000,
                       'usd_price': 32.89,
                       'hide_usd_in_miniapp': True,
                       'needs_credentials': True,
                       'payment_note': 'تحویل سفارش: ۱ تا ۷۲ ساعت کاری.'},
 'spotihyp_finance_package': {'title': '💎 پکیج مالی SPOTIHYP',
                              'category': 'finance',
                              'price': 75350000,
                              'usd_price': 418.0,
                              'needs_credentials': False,
                              'description': '💎 پکیج مالی SPOTIHYP\n'
                                             '\n'
                                             'شامل حساب\u200cهای:\n'
                                             '✅ Revolut\n'
                                             '✅ Paypal\n'
                                             '✅ Wise\n'
                                             '✅ Payoneer\n'
                                             '✅ Kucoin\n'
                                             '✅ Binance\n'
                                             '\n'
                                             '🎁 به همراه یک سیمکارت رایگان EETY اتریش.\n'
                                             '\n'
                                             '🔥 همچنین خیلی از سایت\u200cهای دیگر را هم می\u200cتوانید با مدرکی که '
                                             'برایتان ارسال می\u200cشود وریفای کنید؛ مثل Contra، Gumroad، '
                                             'Freelancer.com و ...\n'
                                             '\n'
                                             '📝 با نام و مشخصات دلخواه شما.\n'
                                             '✅ مدرک ارسالی آیدی کارت از کشور Estony هستش.\n'
                                             '⏳ زمان تحویل: ۲ تا ۷ روز کاری',
                              'payment_note': 'اطلاعات مورد نیاز از جانب شما:\n'
                                              'فایل عکس پرسونلی با کیفیت بالا + اسم و فامیل دلخواه + تاریخ تولد به '
                                              'میلادی\n'
                                              '\n'
                                              'پس از ثبت سفارش، اطلاعات را داخل پی\u200cوی برای ما ارسال نمایید:\n'
                                              't.me/spotihyp'},
 'sim_armenia_team_physical': {'title': '📶 سیم\u200cکارت فیزیکی ارمنستان - Team',
                               'category': 'sim',
                               'price': 10307000,
                               'usd_price': 57.2,
                               'needs_credentials': False,
                               'payment_note': 'تحویل سفارش: ۲ الی ۴ روز کاری.'},
 'sim_austria_eety_physical': {'title': '📶 سیم\u200cکارت فیزیکی اتریش - EETY',
                               'category': 'sim',
                               'price': 10703000,
                               'usd_price': 59.4,
                               'needs_credentials': False,
                               'payment_note': 'تحویل سفارش: ۲ الی ۴ روز کاری.'},
 'esim_turkey_uae_oman_saudi': {'title': '📱 eSIM مخصوص ترکیه، امارات، عمان و عربستان',
                                'category': 'sim',
                                'price': 3180000,
                                'usd_price': 17.6,
                                'needs_credentials': False,
                                'payment_note': 'تحویل سفارش: ۲ الی ۴ روز کاری.'},
 'v2ray_custom': {'title': '🌐 V2Ray سرویس پر سرعت نامحدود کاربر و زمان - حجم دلخواه',
                  'category': 'other',
                  'subcategory': 'v2ray',
                  'price': 0,
                  'needs_credentials': False,
                  'variable_volume': True,
                  'payment_note': 'تحویل سفارش: ۱ تا ۲۴ ساعت کاری.'},
 'foreign_site_payment': {'title': '💳 پرداخت در سایت خارجی',
                          'category': 'foreign_payment',
                          'price': 0,
                          'needs_credentials': False,
                          'variable_foreign_payment': True,
                          'payment_note': 'تحویل سفارش: ۱ تا ۷۲ ساعت کاری.'},
 'openvpn_unlimited_1user_1': {'title': '🔐 OpenVPN نامحدود تک\u200cکاربره 1 ماهه',
                               'category': 'other',
                               'subcategory': 'openvpn',
                               'price': 605000,
                               'needs_credentials': False,
                               'description': 'OpenVPN نامحدود یک\u200cماهه و تک\u200cکاربره است.\n'
                                              'این سرویس تضمین سرعت ندارد.\n'
                                              'جهت کندی سرعت، اختلال اینترنت یا مشکل اتصال روی شبکه شما هیچ\u200cگونه '
                                              'پشتیبانی انجام نمی\u200cشود.\n'
                                              'بعد از تایید سفارش، فایل اتصال توسط پشتیبانی داخل همین بات ارسال '
                                              'می\u200cشود.',
                               'payment_note': 'این سرویس نامحدود است اما تضمین سرعت ندارد.\n'
                                               'جهت کندی سرعت، اختلال اینترنت یا مشکل اتصال روی شبکه شما هیچ\u200cگونه '
                                               'پشتیبانی انجام نمی\u200cشود.\n'
                                               'فایل OpenVPN بعد از آماده شدن سفارش داخل همین بات ارسال می\u200cشود.'},
 'expressvpn_1user_1': {'title': '🚀 ExpressVPN تک\u200cکاربره 1 ماهه',
                        'category': 'other',
                        'subcategory': 'expressvpn',
                        'price': 238000,
                        'usd_price': 1.32,
                        'needs_credentials': False,
                        'description': 'اکانت آماده ExpressVPN تحویل داده می\u200cشود و روی اکانت شخصی شما فعال '
                                       'نمی\u200cشود.\n'
                                       'گارانتی فقط برای مشکل خود اکانت آماده است؛ یعنی اگر برای اکانت تحویلی مشکلی '
                                       'پیش بیاید، گارانتی می\u200cشود.\n'
                                       'مشکل اتصال روی اینترنت شما، اختلال اینترنت، فیلترینگ یا وصل نشدن روی بعضی '
                                       'شبکه\u200cها شامل گارانتی نیست.',
                        'payment_note': 'اکانت آماده ExpressVPN برای شما ارسال می\u200cشود.\n'
                                        'گارانتی فقط برای مشکل خود اکانت آماده است.\n'
                                        'اختلال اینترنت، مشکل اتصال روی شبکه شما یا وصل نشدن به دلیل شرایط اینترنت '
                                        'شامل گارانتی نیست.'},
 'expressvpn_1user_3': {'title': '🚀 ExpressVPN تک\u200cکاربره 3 ماهه',
                        'category': 'other',
                        'subcategory': 'expressvpn',
                        'price': 416000,
                        'usd_price': 2.31,
                        'needs_credentials': False,
                        'description': 'اکانت آماده ExpressVPN تحویل داده می\u200cشود و روی اکانت شخصی شما فعال '
                                       'نمی\u200cشود.\n'
                                       'گارانتی فقط برای مشکل خود اکانت آماده است؛ یعنی اگر برای اکانت تحویلی مشکلی '
                                       'پیش بیاید، گارانتی می\u200cشود.\n'
                                       'مشکل اتصال روی اینترنت شما، اختلال اینترنت، فیلترینگ یا وصل نشدن روی بعضی '
                                       'شبکه\u200cها شامل گارانتی نیست.',
                        'payment_note': 'اکانت آماده ExpressVPN برای شما ارسال می\u200cشود.\n'
                                        'گارانتی فقط برای مشکل خود اکانت آماده است.\n'
                                        'اختلال اینترنت، مشکل اتصال روی شبکه شما یا وصل نشدن به دلیل شرایط اینترنت '
                                        'شامل گارانتی نیست.'},
 'expressvpn_1user_6': {'title': '🚀 ExpressVPN تک\u200cکاربره 6 ماهه',
                        'category': 'other',
                        'subcategory': 'expressvpn',
                        'price': 594000,
                        'usd_price': 3.3,
                        'needs_credentials': False,
                        'description': 'اکانت آماده ExpressVPN تحویل داده می\u200cشود و روی اکانت شخصی شما فعال '
                                       'نمی\u200cشود.\n'
                                       'گارانتی فقط برای مشکل خود اکانت آماده است؛ یعنی اگر برای اکانت تحویلی مشکلی '
                                       'پیش بیاید، گارانتی می\u200cشود.\n'
                                       'مشکل اتصال روی اینترنت شما، اختلال اینترنت، فیلترینگ یا وصل نشدن روی بعضی '
                                       'شبکه\u200cها شامل گارانتی نیست.',
                        'payment_note': 'اکانت آماده ExpressVPN برای شما ارسال می\u200cشود.\n'
                                        'گارانتی فقط برای مشکل خود اکانت آماده است.\n'
                                        'اختلال اینترنت، مشکل اتصال روی شبکه شما یا وصل نشدن به دلیل شرایط اینترنت '
                                        'شامل گارانتی نیست.'},
 'windscribe_1user_1': {'title': '🌬 Windscribe تک\u200cکاربره 1 ماهه',
                        'category': 'other',
                        'subcategory': 'windscribe',
                        'price': 297000,
                        'usd_price': 1.65,
                        'needs_credentials': False,
                        'description': 'اکانت آماده Windscribe تحویل داده می\u200cشود و روی اکانت شخصی شما فعال '
                                       'نمی\u200cشود.\n'
                                       'گارانتی فقط برای مشکل خود اکانت آماده است؛ یعنی اگر برای اکانت تحویلی مشکلی '
                                       'پیش بیاید، گارانتی می\u200cشود.\n'
                                       'مشکل اتصال روی اینترنت شما، اختلال اینترنت، فیلترینگ یا وصل نشدن روی بعضی '
                                       'شبکه\u200cها شامل گارانتی نیست.',
                        'payment_note': 'اکانت آماده Windscribe برای شما ارسال می\u200cشود.\n'
                                        'گارانتی فقط برای مشکل خود اکانت آماده است.\n'
                                        'اختلال اینترنت، مشکل اتصال روی شبکه شما یا وصل نشدن به دلیل شرایط اینترنت '
                                        'شامل گارانتی نیست.'},
 'windscribe_2user_1': {'title': '🌬 Windscribe دوکاربره 1 ماهه',
                        'category': 'other',
                        'subcategory': 'windscribe',
                        'price': 555000,
                        'usd_price': 3.08,
                        'needs_credentials': False,
                        'description': 'اکانت آماده Windscribe دوکاربره تحویل داده می\u200cشود و روی اکانت شخصی شما '
                                       'فعال نمی\u200cشود.\n'
                                       'گارانتی فقط برای مشکل خود اکانت آماده است؛ یعنی اگر برای اکانت تحویلی مشکلی '
                                       'پیش بیاید، گارانتی می\u200cشود.\n'
                                       'مشکل اتصال روی اینترنت شما، اختلال اینترنت، فیلترینگ یا وصل نشدن روی بعضی '
                                       'شبکه\u200cها شامل گارانتی نیست.',
                        'payment_note': 'اکانت آماده Windscribe برای شما ارسال می\u200cشود.\n'
                                        'گارانتی فقط برای مشکل خود اکانت آماده است.\n'
                                        'اختلال اینترنت، مشکل اتصال روی شبکه شما یا وصل نشدن به دلیل شرایط اینترنت '
                                        'شامل گارانتی نیست.'},
 'windscribe_1user_12': {'title': '🌬 Windscribe یک\u200cساله',
                         'category': 'other',
                         'subcategory': 'windscribe',
                         'price': 991000,
                         'usd_price': 5.5,
                         'needs_credentials': False,
                         'description': 'اکانت آماده Windscribe یک\u200cساله تحویل داده می\u200cشود و روی اکانت شخصی '
                                        'شما فعال نمی\u200cشود.\n'
                                        'گارانتی فقط برای مشکل خود اکانت آماده است؛ یعنی اگر برای اکانت تحویلی مشکلی '
                                        'پیش بیاید، گارانتی می\u200cشود.\n'
                                        'مشکل اتصال روی اینترنت شما، اختلال اینترنت، فیلترینگ یا وصل نشدن روی بعضی '
                                        'شبکه\u200cها شامل گارانتی نیست.',
                         'payment_note': 'اکانت آماده Windscribe برای شما ارسال می\u200cشود.\n'
                                         'گارانتی فقط برای مشکل خود اکانت آماده است.\n'
                                         'اختلال اینترنت، مشکل اتصال روی شبکه شما یا وصل نشدن به دلیل شرایط اینترنت '
                                         'شامل گارانتی نیست.'},
 'happ_multilocation_170': {'title': '🌍 Happ مولتی\u200cلوکیشن 170 گیگ - معادل 2.61GB - 30 روزه',
                            'category': 'other',
                            'subcategory': 'happ',
                            'price': 826000,
                            'needs_credentials': False,
                            'description': 'سرویس مولتی\u200cلوکیشن اسپاتی\u200cهایپ برای همه دستگاه\u200cها.\n'
                                           'حجم بسته: 170 گیگ با ضریب مصرف، تقریباً معادل 2.61 گیگابایت مصرف واقعی.\n'
                                           'صرفاً روی برنامه Happ قابل استفاده است.\n'
                                           'بسته قابل استفاده همزمان روی تعداد نامحدود گوشی و لپتاپ است.',
                            'payment_note': 'قوانین سرویس حجمی:\n'
                                            '• این سرویس 30 روزه است و پس از تمدید، زمان سرویس دوباره روی 30 روز ریست '
                                            'می\u200cشود.\n'
                                            '• در صورت تمام شدن حجم یا زمان، سرویس غیرفعال می\u200cشود و باید سرویس '
                                            'جدید تهیه کنید.\n'
                                            '• نهایتاً تا 10 گیگابایت ترافیک باقی\u200cمانده به دوره بعد منتقل '
                                            'می\u200cشود.\n'
                                            '• سرویس\u200cهای عادی برای اتصال به اینترنت بین\u200cالمللی نیاز دارند و '
                                            'در شرایط نت ملی کار نمی\u200cکنند؛ در حال حاضر فقط سرورهای نت ملی متصل '
                                            'می\u200cشوند.'},
 'happ_multilocation_250': {'title': '🌍 Happ مولتی\u200cلوکیشن 250 گیگ - معادل 3.84GB - 30 روزه',
                            'category': 'other',
                            'subcategory': 'happ',
                            'price': 1046000,
                            'needs_credentials': False,
                            'description': 'سرویس مولتی\u200cلوکیشن اسپاتی\u200cهایپ برای همه دستگاه\u200cها.\n'
                                           'حجم بسته: 250 گیگ با ضریب مصرف، تقریباً معادل 3.84 گیگابایت مصرف واقعی.\n'
                                           'صرفاً روی برنامه Happ قابل استفاده است.\n'
                                           'بسته قابل استفاده همزمان روی تعداد نامحدود گوشی و لپتاپ است.',
                            'payment_note': 'قوانین سرویس حجمی:\n'
                                            '• این سرویس 30 روزه است و پس از تمدید، زمان سرویس دوباره روی 30 روز ریست '
                                            'می\u200cشود.\n'
                                            '• در صورت تمام شدن حجم یا زمان، سرویس غیرفعال می\u200cشود و باید سرویس '
                                            'جدید تهیه کنید.\n'
                                            '• نهایتاً تا 10 گیگابایت ترافیک باقی\u200cمانده به دوره بعد منتقل '
                                            'می\u200cشود.\n'
                                            '• سرویس\u200cهای عادی برای اتصال به اینترنت بین\u200cالمللی نیاز دارند و '
                                            'در شرایط نت ملی کار نمی\u200cکنند؛ در حال حاضر فقط سرورهای نت ملی متصل '
                                            'می\u200cشوند.'},
 'happ_multilocation_500': {'title': '🌍 Happ مولتی\u200cلوکیشن 500 گیگ - معادل 7.69GB - 30 روزه',
                            'category': 'other',
                            'subcategory': 'happ',
                            'price': 2080000,
                            'needs_credentials': False,
                            'description': 'سرویس مولتی\u200cلوکیشن اسپاتی\u200cهایپ برای همه دستگاه\u200cها.\n'
                                           'حجم بسته: 500 گیگ با ضریب مصرف، تقریباً معادل 7.69 گیگابایت مصرف واقعی.\n'
                                           'صرفاً روی برنامه Happ قابل استفاده است.\n'
                                           'بسته قابل استفاده همزمان روی تعداد نامحدود گوشی و لپتاپ است.',
                            'payment_note': 'قوانین سرویس حجمی:\n'
                                            '• این سرویس 30 روزه است و پس از تمدید، زمان سرویس دوباره روی 30 روز ریست '
                                            'می\u200cشود.\n'
                                            '• در صورت تمام شدن حجم یا زمان، سرویس غیرفعال می\u200cشود و باید سرویس '
                                            'جدید تهیه کنید.\n'
                                            '• نهایتاً تا 10 گیگابایت ترافیک باقی\u200cمانده به دوره بعد منتقل '
                                            'می\u200cشود.\n'
                                            '• سرویس\u200cهای عادی برای اتصال به اینترنت بین\u200cالمللی نیاز دارند و '
                                            'در شرایط نت ملی کار نمی\u200cکنند؛ در حال حاضر فقط سرورهای نت ملی متصل '
                                            'می\u200cشوند.'},
 'happ_multilocation_1000': {'title': '🌍 Happ مولتی\u200cلوکیشن 1000 گیگ - معادل 15.38GB - 30 روزه',
                             'category': 'other',
                             'subcategory': 'happ',
                             'price': 3180000,
                             'needs_credentials': False,
                             'description': 'سرویس مولتی\u200cلوکیشن اسپاتی\u200cهایپ برای همه دستگاه\u200cها.\n'
                                            'حجم بسته: 1000 گیگ با ضریب مصرف، تقریباً معادل 15.38 گیگابایت مصرف '
                                            'واقعی.\n'
                                            'صرفاً روی برنامه Happ قابل استفاده است.\n'
                                            'بسته قابل استفاده همزمان روی تعداد نامحدود گوشی و لپتاپ است.',
                             'payment_note': 'قوانین سرویس حجمی:\n'
                                             '• این سرویس 30 روزه است و پس از تمدید، زمان سرویس دوباره روی 30 روز ریست '
                                             'می\u200cشود.\n'
                                             '• در صورت تمام شدن حجم یا زمان، سرویس غیرفعال می\u200cشود و باید سرویس '
                                             'جدید تهیه کنید.\n'
                                             '• نهایتاً تا 10 گیگابایت ترافیک باقی\u200cمانده به دوره بعد منتقل '
                                             'می\u200cشود.\n'
                                             '• سرویس\u200cهای عادی برای اتصال به اینترنت بین\u200cالمللی نیاز دارند و '
                                             'در شرایط نت ملی کار نمی\u200cکنند؛ در حال حاضر فقط سرورهای نت ملی متصل '
                                             'می\u200cشوند.'},
 'happ_multilocation_2000': {'title': '🌍 Happ مولتی\u200cلوکیشن 2000 گیگ - معادل 30.76GB - 30 روزه',
                             'category': 'other',
                             'subcategory': 'happ',
                             'price': 5720000,
                             'needs_credentials': False,
                             'description': 'سرویس مولتی\u200cلوکیشن اسپاتی\u200cهایپ برای همه دستگاه\u200cها.\n'
                                            'حجم بسته: 2000 گیگ با ضریب مصرف، تقریباً معادل 30.76 گیگابایت مصرف '
                                            'واقعی.\n'
                                            'صرفاً روی برنامه Happ قابل استفاده است.\n'
                                            'بسته قابل استفاده همزمان روی تعداد نامحدود گوشی و لپتاپ است.',
                             'payment_note': 'قوانین سرویس حجمی:\n'
                                             '• این سرویس 30 روزه است و پس از تمدید، زمان سرویس دوباره روی 30 روز ریست '
                                             'می\u200cشود.\n'
                                             '• در صورت تمام شدن حجم یا زمان، سرویس غیرفعال می\u200cشود و باید سرویس '
                                             'جدید تهیه کنید.\n'
                                             '• نهایتاً تا 10 گیگابایت ترافیک باقی\u200cمانده به دوره بعد منتقل '
                                             'می\u200cشود.\n'
                                             '• سرویس\u200cهای عادی برای اتصال به اینترنت بین\u200cالمللی نیاز دارند و '
                                             'در شرایط نت ملی کار نمی\u200cکنند؛ در حال حاضر فقط سرورهای نت ملی متصل '
                                             'می\u200cشوند.'}}

CATEGORY_ORDER_SUMMARIES = {'spotify': 'فعال\u200cسازی روی اکانت شما | ⏳ تحویل: ۱ تا ۷۲ ساعت کاری',
 'capcut': 'فعال\u200cسازی روی اکانت شما | ⏳ تحویل: ۱ تا ۷۲ ساعت کاری',
 'ai': 'فعال\u200cسازی سرویس AI | ⏳ تحویل: ۱ تا ۷۲ ساعت کاری',
 'education': 'فعال\u200cسازی روی اکانت شما | ⏳ تحویل: ۱ تا ۷۲ ساعت کاری',
 'social': 'Telegram Premium، LinkedIn و سرویس\u200cهای سوشال | ⏳ تحویل: ۱ تا ۷۲ ساعت کاری',
 'finance': 'پکیج مالی اختصاصی | ⏳ تحویل: ۲ تا ۷ روز کاری',
 'sim': 'ارسال سیم\u200cکارت/eSIM | ⏳ تحویل: ۲ تا ۴ روز کاری',
 'other': 'فعال\u200cسازی سرویس | ⏳ تحویل: ۱ تا ۲۴ ساعت کاری',
 'foreign_payment': 'پرداخت سایت خارجی | ⏳ ۱ تا ۷۲ ساعت'}

SUBCATEGORY_ORDER_SUMMARIES = {'spotify': 'Premium اسپاتیفای روی اکانت شما | بدون اکانت: ساخت اکانت ۱۰۰,۰۰۰ ت | ⏳ ۱ تا ۷۲ ساعت',
 'soundcloud': 'SoundCloud Go روی اکانت شما | نیاز به نام کاربری و رمز | ⏳ ۱ تا ۷۲ ساعت',
 'apple_music': 'Apple Music فمیلی | Apple ID باید ریجن ترکیه باشد | ⏳ ۱ تا ۷۲ ساعت',
 'castbox': 'Castbox روی اکانت شخصی شما | ⏳ ۱ تا ۷۲ ساعت',
 'capcut': 'CapCut Pro/Team روی اکانت شما | ⏳ ۱ تا ۷۲ ساعت',
 'canva': 'Canva فمیلی روی اکانت شخصی | ⏳ ۱ تا ۷۲ ساعت',
 'figma': 'Figma Education یک\u200cساله | ⏳ ۱ تا ۷۲ ساعت',
 'chatgpt': 'ChatGPT روی اکانت شما | ⏳ ۱ تا ۷۲ ساعت',
 'claude': 'Claude AI روی اکانت شما | ⏳ ۱ تا ۷۲ ساعت',
 'gemini': 'Gemini | ⏱ گارانتی: ۲۴ ساعت | 📧 تحویل: لینک به ایمیل | ⏳ ۱ تا ۷۲ ساعت',
 'grok': 'Super Grok یک\u200cماهه | ⏳ ۱ تا ۷۲ ساعت',
 'cursor': 'Cursor | 📧 تحویل: لینک به ایمیل | ⏳ ۱ تا ۷۲ ساعت',
 'v2ray': 'V2Ray پرسرعت | کاربر و زمان نامحدود | ⏳ ۱ تا ۲۴ ساعت',
 'openvpn': 'OpenVPN نامحدود تک\u200cکاربره | بدون تضمین سرعت | ارسال فایل داخل بات',
 'happ': 'Happ مولتی\u200cلوکیشن ۳۰ روزه | ⏳ ۱ تا ۲۴ ساعت',
 'expressvpn': 'ExpressVPN اکانت آماده | گارانتی فقط مشکل اکانت تحویلی | ⏳ ۱ تا ۷۲ ساعت',
 'windscribe': 'Windscribe اکانت آماده | گارانتی فقط مشکل اکانت تحویلی | ⏳ ۱ تا ۷۲ ساعت',
 'telegram': 'Telegram Premium | ⏳ تحویل: ۱ تا ۷۲ ساعت کاری',
 'linkedin': 'LinkedIn Premium | نیاز به ایمیل و رمز اکانت | ⏳ ۱ تا ۷۲ ساعت'}

PRODUCT_ORDER_SUMMARIES = {'spotify_1': 'Premium اسپاتیفای ۱ ماهه | ریجن نیجریه | با اکانت یا ساخت اکانت (+۱۰۰,۰۰۰ ت) | ⏳ ۱ تا ۷۲ ساعت',
 'spotify_3': 'Premium اسپاتیفای ۳ ماهه | ریجن مصر | با اکانت یا ساخت اکانت (+۱۰۰,۰۰۰ ت) | ⏳ ۱ تا ۷۲ ساعت',
 'spotify_6': 'Premium اسپاتیفای ۶ ماهه | ریجن مصر | با اکانت یا ساخت اکانت (+۱۰۰,۰۰۰ ت) | ⏳ ۱ تا ۷۲ ساعت',
 'spotify_12': 'Premium اسپاتیفای ۱ ساله | ریجن مصر | با اکانت یا ساخت اکانت (+۱۰۰,۰۰۰ ت) | ⏳ ۱ تا ۷۲ ساعت',
 'claude_pro_1': 'Claude Pro روی اکانت شما | فقط User ID لازم است | ⏳ ۱ تا ۷۲ ساعت',
 'chatgpt_no_login_1': 'ChatGPT روی اکانت شما | ارسال session لازم است | ⏳ ۱ تا ۷۲ ساعت',
 'chatgpt_go_1': 'ChatGPT Go یک\u200cماهه | تحویل توسط پشتیبانی | ⏳ ۱ تا ۷۲ ساعت',
 'chatgpt_ready_personal_1': 'ChatGPT اکانت آماده شخصی | بدون نیاز به session | ⏳ ۱ تا ۷۲ ساعت',
 'chatgpt_shared_1': 'ChatGPT اشتراکی یک\u200cماهه | تحویل توسط پشتیبانی | ⏳ ۱ تا ۷۲ ساعت',
 'gemini_3': 'Gemini سه\u200cماهه | 📧 تحویل: لینک به ایمیل | ⏳ ۱ تا ۷۲ ساعت',
 'gemini_18': 'Gemini هجده\u200cماهه | ⏱ گارانتی: ۲۴ ساعت | 📧 تحویل: لینک به ایمیل | ⏳ ۱ تا ۷۲ ساعت',
 'super_grok_1': 'Super Grok یک\u200cماهه | تحویل توسط پشتیبانی | ⏳ ۱ تا ۷۲ ساعت',
 'super_grok_ready_1': 'Super Grok اکانت آماده یک\u200cماهه | بدون نیاز به اکانت شخصی | ⏳ ۱ تا ۷۲ ساعت',
 'cursor_pro_1': 'Cursor Pro روی ایمیل شما | 📧 تحویل: لینک به ایمیل | ⏳ ۱ تا ۷۲ ساعت',
 'cursor_ready_1': 'Cursor اکانت آماده یک\u200cماهه | بدون نیاز به ایمیل تحویل | ⏳ ۱ تا ۷۲ ساعت',
 'cursor_pro_plus_1': 'Cursor Pro Plus روی ایمیل شما | 📧 تحویل: لینک به ایمیل | ⏳ ۱ تا ۷۲ ساعت',
 'cursor_pro_education': 'Cursor Pro Education | ⏱ گارانتی: ۵ ساعت | 📧 تحویل: لینک به ایمیل | ⏳ ۱ تا ۷۲ ساعت',
 'linkedin_first_1': 'LinkedIn Premium ۱ ماهه — اولین اشتراک | نیاز به ایمیل و رمز LinkedIn | ⏳ ۱ تا ۷۲ ساعت',
 'linkedin_renew_1': 'LinkedIn Premium ۱ ماهه — تمدید | نیاز به ایمیل و رمز LinkedIn | ⏳ ۱ تا ۷۲ ساعت',
 'linkedin_renew_12': 'LinkedIn Premium ۱ ساله — تمدید | نیاز به ایمیل و رمز LinkedIn | ⏳ ۱ تا ۷۲ ساعت',
 'spotihyp_finance_package': 'پکیج مالی Revolut/PayPal/Wise و ... | همراه سیم\u200cکارت EETY | ⏳ ۲ تا ۷ روز',
 'v2ray_custom': 'V2Ray پرسرعت | کاربر و زمان نامحدود | حجم دلخواه | ⏳ ۱ تا ۲۴ ساعت',
 'foreign_site_payment': 'پرداخت سایت خارجی | ⏳ ۱ تا ۷۲ ساعت',
 'openvpn_unlimited_1user_1': 'OpenVPN نامحدود تک\u200cکاربره ۱ ماهه | بدون تضمین سرعت | تحویل فایل داخل بات | ۵۵۰ '
                              'هزار تومان',
 'expressvpn_1user_1': 'ExpressVPN اکانت آماده تک\u200cکاربره ۱ ماهه | گارانتی فقط مشکل اکانت تحویلی | ⏳ ۱ تا ۷۲ ساعت',
 'expressvpn_1user_3': 'ExpressVPN اکانت آماده تک\u200cکاربره ۳ ماهه | گارانتی فقط مشکل اکانت تحویلی | ⏳ ۱ تا ۷۲ ساعت',
 'expressvpn_1user_6': 'ExpressVPN اکانت آماده تک\u200cکاربره ۶ ماهه | گارانتی فقط مشکل اکانت تحویلی | ⏳ ۱ تا ۷۲ ساعت',
 'windscribe_1user_1': 'Windscribe اکانت آماده تک\u200cکاربره ۱ ماهه | گارانتی فقط مشکل اکانت تحویلی | ⏳ ۱ تا ۷۲ ساعت',
 'windscribe_2user_1': 'Windscribe اکانت آماده دوکاربره ۱ ماهه | گارانتی فقط مشکل اکانت تحویلی | ⏳ ۱ تا ۷۲ ساعت',
 'windscribe_1user_12': 'Windscribe اکانت آماده یک\u200cساله | گارانتی فقط مشکل اکانت تحویلی | ⏳ ۱ تا ۷۲ ساعت',
 'happ_multilocation_170': 'Happ 170 گیگ (≈2.61GB واقعی) | ۳۰ روز | فقط اپ Happ | ⏳ ۱ تا ۲۴ ساعت',
 'happ_multilocation_250': 'Happ 250 گیگ (≈3.84GB واقعی) | ۳۰ روز | فقط اپ Happ | ⏳ ۱ تا ۲۴ ساعت',
 'happ_multilocation_500': 'Happ 500 گیگ (≈7.69GB واقعی) | ۳۰ روز | فقط اپ Happ | ⏳ ۱ تا ۲۴ ساعت',
 'happ_multilocation_1000': 'Happ 1000 گیگ (≈15.38GB واقعی) | ۳۰ روز | فقط اپ Happ | ⏳ ۱ تا ۲۴ ساعت',
 'happ_multilocation_2000': 'Happ 2000 گیگ (≈30.76GB واقعی) | ۳۰ روز | فقط اپ Happ | ⏳ ۱ تا ۲۴ ساعت'}



def is_spotify_credentials_product(product_key: str) -> bool:
    product = PRODUCTS.get(product_key)
    if not product:
        return False
    return product.get("subcategory") == "spotify" and bool(product.get("needs_credentials"))


def get_order_summary(product_key: str) -> str:
    if product_key in PRODUCT_ORDER_SUMMARIES:
        return PRODUCT_ORDER_SUMMARIES[product_key]
    product = PRODUCTS.get(product_key)
    if not product:
        return "⏳ زمان تحویل: ۱ تا ۷۲ ساعت کاری"
    subcategory = product.get("subcategory")
    if subcategory and subcategory in SUBCATEGORY_ORDER_SUMMARIES:
        return SUBCATEGORY_ORDER_SUMMARIES[subcategory]
    category = product.get("category")
    if category and category in CATEGORY_ORDER_SUMMARIES:
        return CATEGORY_ORDER_SUMMARIES[category]
    return "⏳ زمان تحویل: ۱ تا ۷۲ ساعت کاری"

