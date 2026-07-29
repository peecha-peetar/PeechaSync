// سرویس‌ورکر: فقط پوسته‌ی اپ (HTML/CSS/JS/آیکون) رو کش می‌کنه تا اپ حتی
// بدونِ دسترسی به سرورِ پیچا هم باز بشه (گرفتنِ عکس و صف‌کردن باید همیشه
// کار کنه، صرف‌نظر از وصل بودن به کامپیوتر). درخواست‌هایِ /ping، /upload
// و /config عمداً کش نمی‌شن — چون همیشه باید تازه باشن.

const CACHE_NAME = "peecha-camera-shell-v6";
const SHELL_FILES = [
  "./",
  "./index.html",
  "./style.css",
  "./app.js",
  "./manifest.json",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_FILES))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  const dynamic = ["/ping", "/upload", "/config"].some((p) => url.pathname.endsWith(p));
  if (dynamic) return; // این‌ها همیشه مستقیم از شبکه — بدونِ دخالتِ کش

  // فایل‌هایِ حجیمِ حذفِ پس‌زمینه (WASM + مدل) عمداً تویِ SHELL_FILES نیستن —
  // فقط با اولین استفاده‌ی واقعی دانلود می‌شن، ولی بعدِ اولین بار کش می‌شن
  // تا دفعاتِ بعد آفلاین/بدونِ دانلودِ دوباره کار کنن.
  const runtimeCache = url.pathname.includes("/vendor/") || url.pathname.includes("/models/");

  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;
      return fetch(event.request)
        .then((resp) => {
          if (runtimeCache && resp && resp.ok) {
            const clone = resp.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          }
          return resp;
        })
        .catch(() => cached);
    })
  );
});
