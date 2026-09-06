import json
import os
import shutil
import sys
from datetime import datetime
from cryptography.fernet import Fernet, InvalidToken


def _safe_log(log, level, message):
    if log is None:
        return
    fn = getattr(log, level, None)
    if callable(fn):
        fn(message)


def _base_paths():
    paths = []

    # پروفایل فعال — اولویت اول
    try:
        from sync_app.core.user_profile import get_current_profile_id, profile_dir

        pid = get_current_profile_id()
        if pid:
            paths.append(profile_dir(pid))
    except Exception:
        pass

    # اول PEECHA_CONFIG_DIR
    env_path = os.getenv("PEECHA_CONFIG_DIR", "").strip()
    if env_path:
        paths.append(env_path)

    # کنار exe
    if getattr(sys, 'frozen', False):
        paths.append(os.path.dirname(sys.executable))

    # کنار لودر
    paths.append(os.path.dirname(os.path.abspath(__file__)))

    # cwd
    paths.append(os.getcwd())

    # dedupe
    unique = []
    seen = set()
    for p in paths:
        np = os.path.normpath(p)
        if np not in seen:
            seen.add(np)
            unique.append(np)
    return unique


def _candidate_pairs():
    # اگه پروفایل فعالی داریم، پوشه‌ش رو از قبل می‌سازیم (برای save بعدی)،
    # ولی دیگه اینجا return زودهنگام نمی‌کنیم — چون قبلاً وقتی پروفایل فعال
    # بود ولی هنوز فایل کانفیگش ساخته نشده بود (مثلاً کانفیگِ قدیمی هنوز
    # کنارِ فایل‌هایِ نصب مونده بود)، هیچ‌وقت به مسیرهایِ قدیمی/legacy سر
    # نمی‌زدیم و load_secure_config بی‌صدا {} برمی‌گردوند — یعنی تنظیماتی
    # که واقعاً وجود داشتن، «گم‌شده» به نظر می‌رسیدن (و با نصبِ نسخه‌ی جدید
    # که پوشه‌ی نصب رو بازنویسی می‌کنه، واقعاً از بین می‌رفتن).
    try:
        from sync_app.core.user_profile import get_current_profile_id, ensure_profile_dir

        pid = get_current_profile_id()
        if pid:
            ensure_profile_dir(pid)
    except Exception:
        pass

    pairs = []
    for base in _base_paths():
        pairs.append((
            os.path.join(base, 'sync_key.key'),
            os.path.join(base, 'secure_config.bin')
        ))
    return pairs


def _migrate_to_profile_if_needed(key_file: str, config_file: str, log=None):
    """اگه کانفیگ از یه مسیرِ قدیمی/legacy (مثلاً کنارِ فایل‌هایِ نصب) خونده
    شده ولی الان یه پروفایلِ فعال داریم، فایل‌ها رو به پوشه‌ی پروفایل (که
    بیرون از پوشه‌ی نصب و امن در برابرِ آپدیت/نصبِ مجدده) کپی می‌کنه و
    مسیرِ جدید رو برمی‌گردونه — تا ذخیره‌هایِ بعدی دیگه هیچ‌وقت به پوشه‌ی
    نصب برنگردن."""
    try:
        from sync_app.core.user_profile import get_current_profile_id, profile_dir
    except Exception:
        return key_file, config_file

    pid = get_current_profile_id()
    if not pid:
        return key_file, config_file

    base = profile_dir(pid)
    target_key = os.path.join(base, "sync_key.key")
    target_config = os.path.join(base, "secure_config.bin")

    if os.path.normpath(config_file) == os.path.normpath(target_config):
        return key_file, config_file
    if os.path.exists(target_config):
        # پروفایل از قبل کانفیگِ خودش رو داره — نباید جایگزینش کنیم
        return key_file, config_file

    try:
        os.makedirs(base, exist_ok=True)
        if os.path.exists(key_file):
            shutil.copy2(key_file, target_key)
        shutil.copy2(config_file, target_config)
        _safe_log(
            log, "info",
            f"📁 تنظیمات از مسیرِ قدیمیِ «{config_file}» به پوشه‌ی پروفایل منتقل شد "
            "(برای اینکه با نصبِ نسخه‌ی جدید از بین نره).",
        )
        return target_key, target_config
    except Exception as e:
        _safe_log(log, "warning", f"⚠️ انتقالِ تنظیمات به پوشه‌ی پروفایل ناموفق بود: {e}")
        return key_file, config_file


def _read_key(path):
    with open(path, "rb") as key_file:
        return key_file.read()


def _write_key(path, key):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as key_file:
        key_file.write(key)


def _get_encryption_key(preferred_key_path):
    if os.path.exists(preferred_key_path):
        return _read_key(preferred_key_path)

    key = Fernet.generate_key()
    _write_key(preferred_key_path, key)
    return key


def load_secure_config(log):
    for key_file, config_file in _candidate_pairs():
        if not os.path.exists(config_file):
            continue

        try:
            if os.path.exists(key_file):
                key = _read_key(key_file)
            else:
                # config هست key نیست
                _safe_log(log, "warning", f"⚠️ کلید رمزنگاری در مسیر {key_file} یافت نشد.")
                continue

            f = Fernet(key)
            with open(config_file, "rb") as file:
                encrypted_data = file.read()
            decrypted_data = f.decrypt(encrypted_data)
            config = json.loads(decrypted_data.decode('utf-8'))

            key_file, config_file = _migrate_to_profile_if_needed(key_file, config_file, log)

            # مسیر برای save هم
            config["_CONFIG_PATH"] = config_file
            config["_KEY_PATH"] = key_file
            try:
                from sync_app.core.wc_site_profiles import ensure_wc_sites

                config = ensure_wc_sites(config)
            except Exception:
                pass
            return config
        except InvalidToken:
            _safe_log(log, "warning", f"⚠️ کلید/فایل تنظیمات در مسیر {config_file} معتبر نیست.")
        except Exception as e:
            _safe_log(log, "error", f"❌ خطای بارگذاری تنظیمات از {config_file}: {e}")

    _safe_log(log, "warning", "⚠️ فایل تنظیمات امن یافت نشد.")
    return {}


def save_secure_config(config_dict):
    data = dict(config_dict or {})

    preferred_config = data.pop("_CONFIG_PATH", None)
    preferred_key = data.pop("_KEY_PATH", None)

    if preferred_config and preferred_key:
        key_file = preferred_key
        config_file = preferred_config
    else:
        key_file, config_file = _candidate_pairs()[0]

    # --- محافظ حیاتی (بعد از یک حادثه‌ی واقعی) ---
    # load_secure_config در هر نوع خطای موقت (فایل قفل، خواندن ناموفق و...)
    # بی‌صدا {} برمی‌گردونه، نه خطا. خیلی جاها (از جمله کد خودمون) الگوی
    # `cfg = load_secure_config(None) or {}` رو دارن — یعنی اگه یه خواندن
    # موقتاً شکست بخوره، کالر فکر می‌کنه کانفیگ واقعاً خالیه، چندتا کلید
    # بهش اضافه می‌کنه و ذخیره می‌کنه؛ نتیجه: کل تنظیمات کاربر (اتصال SQL،
    # ووکامرس، لایسنس و...) با یه فایل تقریباً خالی جایگزین می‌شه.
    # برای همین: قبل از نوشتن، اگه فایل فعلی دیتای قابل‌توجهی داره ولی چیزی
    # که می‌خوایم جایگزینش کنیم به‌طرز مشکوکی خیلی کوچیک‌تره، ذخیره متوقف
    # می‌شه — بهتره یه عملیات ناموفق بشه تا کل تنظیمات پاک بشه.
    try:
        if os.path.exists(config_file):
            existing = load_secure_config(None)
            existing_count = len(existing) if isinstance(existing, dict) else 0
            new_count = len(data)
            if existing_count >= 6 and new_count < max(3, existing_count // 2):
                raise RuntimeError(
                    "ذخیره‌ی تنظیمات به‌خاطر محافظت از داده متوقف شد: کانفیگ فعلی "
                    f"{existing_count} کلید دارد ولی مقدار جدید فقط {new_count} کلید "
                    "دارد. این معمولاً نشانه‌ی یک خطای موقتِ خواندن است، نه خواستِ "
                    "واقعیِ کاربر برای پاک کردن تنظیمات. دوباره تلاش کنید."
                )
    except RuntimeError:
        raise
    except Exception:
        pass  # اگه خودِ همین چک خطا داد، نذار جلوی ذخیره‌ی معمولی رو بگیره

    # --- پشتیبان‌گیری خودکار (بعد از حادثه‌ی قبلی، برای اطمینان بیشتر) ---
    # قبل از رونویسی فایل فعلی، یه کپی از حالت الان (قبل از تغییر) با
    # تاریخ/ساعت تو یه پوشه‌ی جدا نگه می‌داریم. فقط ۱۵ تای آخر نگه داشته
    # می‌شه (قدیمی‌ترها خودکار پاک می‌شن). اگه خودِ این کار خطا بده، نباید
    # جلوی ذخیره‌ی اصلی رو بگیره — پشتیبان‌گیری «best effort»ه.
    try:
        _backup_config_file(config_file)
    except Exception:
        pass

    json_string = json.dumps(data, indent=4, ensure_ascii=False)
    key = _get_encryption_key(key_file)
    f = Fernet(key)
    encrypted_data = f.encrypt(json_string.encode('utf-8'))

    os.makedirs(os.path.dirname(config_file), exist_ok=True)
    with open(config_file, "wb") as file:
        file.write(encrypted_data)


CONFIG_BACKUP_KEEP = 15


def _backup_config_file(config_file: str) -> None:
    """قبل از رونویسی، یه کپی از فایل تنظیمات فعلی نگه می‌داره (اگه از قبل وجود داشته باشه)."""
    if not os.path.exists(config_file):
        return  # اولین ذخیره — چیزی برای پشتیبان‌گیری نیست

    backup_dir = os.path.join(os.path.dirname(config_file), "config_backups")
    os.makedirs(backup_dir, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = os.path.basename(config_file)
    backup_path = os.path.join(backup_dir, f"{base_name}.{stamp}.bak")

    # اگه دقیقاً همین ثانیه یه پشتیبان دیگه هم ساخته شده (بعید ولی ممکنه)،
    # یه پسوند عددی اضافه کن تا رونویسی نشه.
    counter = 1
    while os.path.exists(backup_path):
        backup_path = os.path.join(backup_dir, f"{base_name}.{stamp}_{counter}.bak")
        counter += 1

    shutil.copy2(config_file, backup_path)
    _prune_old_backups(backup_dir, base_name)


def _prune_old_backups(backup_dir: str, base_name: str) -> None:
    """فقط آخرین CONFIG_BACKUP_KEEP نسخه رو نگه می‌داره، بقیه رو پاک می‌کنه."""
    try:
        entries = [
            os.path.join(backup_dir, name)
            for name in os.listdir(backup_dir)
            if name.startswith(base_name + ".") and name.endswith(".bak")
        ]
    except FileNotFoundError:
        return
    entries.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    for old_path in entries[CONFIG_BACKUP_KEEP:]:
        try:
            os.remove(old_path)
        except OSError:
            pass


def list_config_backups(config_file: str) -> list[dict]:
    """لیست پشتیبان‌های موجود برای این فایل تنظیمات (جدیدترین اول)."""
    backup_dir = os.path.join(os.path.dirname(config_file), "config_backups")
    base_name = os.path.basename(config_file)
    if not os.path.isdir(backup_dir):
        return []
    entries = []
    for name in os.listdir(backup_dir):
        if name.startswith(base_name + ".") and name.endswith(".bak"):
            full = os.path.join(backup_dir, name)
            entries.append({
                "path": full,
                "name": name,
                "modified": datetime.fromtimestamp(os.path.getmtime(full)),
                "size": os.path.getsize(full),
            })
    entries.sort(key=lambda e: e["modified"], reverse=True)
    return entries


def restore_config_backup(backup_path: str, config_file: str) -> None:
    """یه نسخه‌ی پشتیبان رو به‌عنوان فایل تنظیمات فعلی برمی‌گردونه.

    قبل از این کار، حالت فعلی (که داره جایگزین می‌شه) هم خودش پشتیبان
    گرفته می‌شه — یعنی restore هم برگشت‌پذیره.

    نکته‌ی مهم: محتوای فایل مقصد رو اول تو حافظه می‌خونیم، بعد پشتیبان
    از وضعیت فعلی می‌گیریم — چون اون پشتیبان‌گیری ممکنه باعث چرخش
    (حذف قدیمی‌ترین‌ها) بشه، و اگه ترتیب برعکس بود، ممکن بود همون
    فایلی که می‌خوایم ازش بازیابی کنیم، در همون لحظه پاک بشه.
    """
    if not os.path.isfile(backup_path):
        raise FileNotFoundError(f"فایل پشتیبان یافت نشد: {backup_path}")

    with open(backup_path, "rb") as f:
        backup_content = f.read()

    try:
        _backup_config_file(config_file)
    except Exception:
        pass

    os.makedirs(os.path.dirname(config_file), exist_ok=True)
    with open(config_file, "wb") as f:
        f.write(backup_content)
