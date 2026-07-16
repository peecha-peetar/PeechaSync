# Peecha License Manager

افزونه لایسنس و بروزرسانی برای نرم‌افزار PeechaSync روی ویندوز.

## نصب

پوشه `peecha-license-manager` را ببر داخل `wp-content/plugins/` و از ادمین وردپرس فعالش کن.
اگر `wp-admin/plugins.php` timeout می‌دهد، از `tools\Run_Install_WP_LicensePlugin.bat` استفاده کن.
فقط ZIP را در wp-admin آپلود کن (Add New -> Upload Plugin)؛ cPanel لازم نیست.
بعد لینک `web-install.php` را یک بار در مرورگر باز کن.

## بروزرسانی (بدون خطای «افزونه پاک نمی‌شود»)

**روش ۱ — از داخل wp-admin (ساده‌ترین)**

1. `tools\Run_Install_WP_LicensePlugin.bat` را بزن (update.zip ساخته می‌شود).
2. wp-admin -> **لایسنس‌های پیچا** -> بخش **بروزرسانی افزونه**.
3. `update.zip` را آپلود کن -> **اعمال بروزرسانی**.

نیازی به حذف افزونه یا آپلود از منوی Plugins نیست.

**روش ۲ — web-update**

1. `update.zip` و `web-update.php` را در File Manager ببر داخل `wp-content/plugins/peecha-license-manager/`.
2. لینk `INSTALL-URL.txt` را باز کن (یا وقتی در wp-admin لاگین هستی همان web-update.php).
3. بعد از OK فایل‌های موقت را حذف کن.

**روش ۳ — FTP**

یک بار `tools\wp-license-deploy.local.json` را پر کن، بعد `tools\Run_Deploy_WP_LicensePlugin.bat`.

**مهم:** پوشه روی سرور باید دقیقاً `peecha-license-manager` باشد — نه `peecha-license-manager-wp`. اگر پوشه اشتباه ساخته شد از File Manager حذفش کن.

## API `https://peecha.ir/wp-json/peecha/v1/` (روی سایت خودت عوض می‌شود)

اگر توی تنظیمات افزونه API key گذاشتی، کلاینت باید هدر `X-Peecha-Api-Key` بفرستد.

**فعال‌سازی** — `POST /license/activate`

```json
{
  "license_key": "...",
  "hwid": "...",
  "app_version": "1.0.22"
}
```

**اعتبارسنجی** — `POST /license/validate` (همان body بالا)

کلاینت‌هایی که قبل از این افزونه کلید v2 امضا‌شده گرفته‌اند، با اولین اتصال آنلاین (validate/activate) خودکار در جدول لایسنس‌ها ثبت می‌شوند و `last_seen_at` به‌روز می‌شود.

**چک بروزرسانی** — `GET /updates/check?license_key=...&hwid=...&version=1.0.22`

**دانلود آینه** — `GET /updates/download?license_key=...&hwid=...`

## تنظیم کلاینت

توی `secure_config.bin`:

- `LICENSE_SERVER_URL` مثلا `https://peecha.ir`
- `LICENSE_API_KEY` همان کلیدی که توی افزونه ست کردی (اگر خالی باشد سرور چک نمی‌کند)

## کار روزمره

لایسنس جدید بساز، تاریخ انقضا و updates until را بزن.
HWID را خالی بگذار تا مشتری اولین بار از برنامه فعال کند و خودش bind شود؛ یا HWID را از قبل بزن و کلید signed بده.
برای قطع دسترسی status را revoked کن؛ برای تمدید تاریخ‌ها را از صفحه edit عوض کن.

## آینه بروزرسانی کلاینت (DirectAdmin / peecha.ir)

مشتری **هرگز** مستقیم از GitHub دانلود نمی‌کند. همیشه از `peecha.ir/wp-json/peecha/v1/updates/download` می‌گیرد.
سرور به ترتیب این منابع را امتحان می‌کند:

1. مسیر ZIP روی دیسک (تنظیمات یا File Manager)
2. ZIP آپلودشده در wp-admin (بخش **آینه بروزرسانی PeechaSync**)
3. شناسه مدیا (قدیمی)
4. GitHub (فقط روی سرور)

**روش پیشنهادی برای تحویل به مشتری**

1. افزونه را به 1.0.17+ بروز کن.
2. wp-admin -> **لایسنس‌های پیچا** -> **آینه بروزرسانی PeechaSync** -> ZIP کلاینت را آپلود کن (مثلا `PeechaSync-1.0.31.zip`).
3. فیلد **آخرین نسخه برنامه** را همان نسخه بزن و changelog را پر کن.
4. کلید API لایسنس را در تنظیمات PeechaSync مشتری بگذار.

**روش DirectAdmin (بدون wp-admin)**

1. در File Manager پوشه بساز: `public_html/peecha-sync-updates/`
2. ZIP را بگذار: `latest.zip` یا `PeechaSync-1.0.31.zip`
3. در تنظیمات افزونه **مسیر ZIP روی سرور** را بزن: `peecha-sync-updates/latest.zip`
4. **آخرین نسخه برنامه** را مطابق ZIP ست کن.

اگر ZIP روی سرور باشد، نسخه از GitHub خوانده نمی‌شود — مشتری حتی با قطع GitHub هم آپدیت می‌گیرد.

**سریع بودن:** اگر **آخرین نسخه برنامه** را در تنظیمات زده باشید یا ZIP روی سرور باشد، چک بروزرسانی دیگر منتظر GitHub نمی‌ماند (حداکثر ۶ ثانیه فقط وقتی هیچ‌کدام ست نشده باشد). دانلود هم اول از دیسک سرور است، بعد GitHub.

## استقرار خودکار ZIP کلاینت (از لپ‌تاپ)

ZIP کلاینت داخل `wp-content/plugins/` نیست.
مسیر روی سرور:

`wp-content/uploads/peecha-sync-updates/PeechaSync-X.Y.Z.zip`

**اتوماتیک با تغییر نسخه (GitHub + FTP با هم):**

1. `app_version.py` را عوض کن
2. بزن: `tools\Run_Publish_Release.bat`

این کار: `git push` به GitHub + آپلود افزونه و ZIP کلاینت روی peecha.ir

فقط FTP بدون git: `tools\Run_Deploy_ClientUpdate.bat`  
فقط git: `tools\Run_Publish_Release.bat -GitOnly`

---

**اتوماتیک با تغییر نسخه (فقط FTP):**

1. یک بار `tools\Setup_WP_LicenseDeploy.bat` و FTP را در `wp-license-deploy.local.json` پر کن.
2. نسخه را در `sync_app/core/app_version.py` عوض کن.
3. بزن: `tools\Run_Deploy_ClientUpdate.bat`

این کار ZIP را از روی `APP_VERSION` می‌سازد و با FTP می‌فرستد به `uploads/peecha-sync-updates/` (همراه `latest.zip`).

یا همراه deploy افزونه:

`tools\Run_Deploy_WP_LicensePlugin.bat` با `-AlsoDeployClient` (در PowerShell).

بعد در wp-admin **آخرین نسخه برنامه** را همان نسخه بزن (یا از نام فایل ZIP خوانده می‌شود).
