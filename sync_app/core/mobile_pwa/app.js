// اپِ همراهِ «دوربینِ پیچا» — عکس می‌گیره، تویِ صفِ محلی (IndexedDB) نگه
// می‌داره، و هر وقت به سرورِ پیچا (روی وای‌فایِ محلی) دسترسی پیدا کرد،
// خودکار می‌فرسته. تا وقتی تأییدِ ارسال نگرفته، هیچ عکسی از صف پاک نمی‌شه.

const DB_NAME = "peecha-photo-queue";
const DB_VERSION = 1;
const STORE_NAME = "queue";
const PING_INTERVAL_MS = 6000;

let db = null;
let cachedToken = null;
let sending = false;

function openDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const database = req.result;
      if (!database.objectStoreNames.contains(STORE_NAME)) {
        const store = database.createObjectStore(STORE_NAME, { keyPath: "id", autoIncrement: true });
        store.createIndex("status", "status", { unique: false });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function dbAdd(item) {
  return new Promise((resolve, reject) => {
    if (!db) { reject(new Error("پایگاه‌دادهِ محلی آماده نیست")); return; }
    const tx = db.transaction(STORE_NAME, "readwrite");
    const req = tx.objectStore(STORE_NAME).add(item);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function dbGetAll() {
  return new Promise((resolve, reject) => {
    if (!db) { resolve([]); return; }
    const tx = db.transaction(STORE_NAME, "readonly");
    const req = tx.objectStore(STORE_NAME).getAll();
    req.onsuccess = () => resolve(req.result || []);
    req.onerror = () => reject(req.error);
  });
}

function dbDelete(id) {
  return new Promise((resolve, reject) => {
    if (!db) { reject(new Error("پایگاه‌دادهِ محلی آماده نیست")); return; }
    const tx = db.transaction(STORE_NAME, "readwrite");
    const req = tx.objectStore(STORE_NAME).delete(id);
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
  });
}

function dbUpdate(item) {
  return new Promise((resolve, reject) => {
    if (!db) { reject(new Error("پایگاه‌دادهِ محلی آماده نیست")); return; }
    const tx = db.transaction(STORE_NAME, "readwrite");
    const req = tx.objectStore(STORE_NAME).put(item);
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
  });
}

async function getToken() {
  if (cachedToken) return cachedToken;
  try {
    const resp = await fetch("./config", { cache: "no-store" });
    if (!resp.ok) return null;
    const data = await resp.json();
    cachedToken = data.token || null;
    return cachedToken;
  } catch (e) {
    return null;
  }
}

async function checkReachable() {
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 2500);
    const resp = await fetch("./ping", { cache: "no-store", signal: ctrl.signal });
    clearTimeout(timer);
    return resp.ok;
  } catch (e) {
    return false;
  }
}

function setStatus(text, ok) {
  const el = document.getElementById("connStatus");
  el.textContent = text;
  el.className = ok ? "status ok" : "status bad";
}

async function sendOne(item) {
  const token = await getToken();
  if (!token) return false;
  const form = new FormData();
  form.append("photo", item.blob, item.filename);
  try {
    const resp = await fetch("./upload", {
      method: "POST",
      headers: { Authorization: "Bearer " + token },
      body: form,
    });
    return resp.ok;
  } catch (e) {
    return false;
  }
}

async function flushQueue() {
  // این چک‌وست باید همین‌جا، قبلِ اولین await، به‌صورتِ اتمیک انجام بشه —
  // وگرنه وقتی دو تا فراخوانیِ هم‌زمانِ flushQueue (مثلاً تایمرِ دوره‌ای +
  // فراخوانیِ مستقیم بعدِ اضافه‌شدنِ عکس) هر دو قبل از رسیدن به «sending =
  // true» به await checkReachable() می‌رسن، هر دو از این چک رد می‌شن و
  // یک عکس دوبار ارسال می‌شه.
  if (sending) return;
  sending = true;
  try {
    const reachable = await checkReachable();
    setStatus(reachable ? "🟢 متصل به پیچا" : "🔴 به پیچا وصل نیست — عکس‌ها تو صف می‌مونن", reachable);
    if (!reachable) return;

    const items = (await dbGetAll()).filter((it) => it.status === "pending");
    for (const item of items) {
      const ok = await sendOne(item);
      if (ok) {
        // فقط بعدِ تأییدِ واقعیِ سرور (200) از صف پاک می‌شه — نه زودتر
        await dbDelete(item.id);
      } else {
        // یکی که نرسید یعنی وصل بودن موقتی بوده؛ بقیه رو هم دیگه امتحان نمی‌کنیم این دور
        break;
      }
    }
  } finally {
    sending = false;
    await renderQueue();
  }
}

function formatSize(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

async function renderQueue() {
  const items = (await dbGetAll()).sort((a, b) => b.createdAt - a.createdAt);
  const list = document.getElementById("queueList");
  const countEl = document.getElementById("queueCount");
  countEl.textContent = items.length ? `${items.length} عکس در صف` : "صف خالیه";
  list.innerHTML = "";
  for (const item of items) {
    const row = document.createElement("div");
    row.className = "queue-item";

    const thumb = document.createElement("img");
    thumb.className = "thumb";
    thumb.src = URL.createObjectURL(item.blob);
    row.appendChild(thumb);

    const info = document.createElement("div");
    info.className = "info";
    const nameEl = document.createElement("div");
    nameEl.className = "fname";
    nameEl.textContent = item.filename;
    const metaEl = document.createElement("div");
    metaEl.className = "meta";
    metaEl.textContent = `${formatSize(item.blob.size)} — ${item.status === "pending" ? "در انتظارِ ارسال" : item.status}`;
    info.appendChild(nameEl);
    info.appendChild(metaEl);
    row.appendChild(info);

    const delBtn = document.createElement("button");
    delBtn.className = "del-btn";
    delBtn.textContent = "✕";
    delBtn.title = "حذف از صف (ارسال نمی‌شه)";
    delBtn.onclick = async () => {
      await dbDelete(item.id);
      renderQueue();
    };
    row.appendChild(delBtn);

    list.appendChild(row);
  }
}

function suggestFilename(originalName) {
  const now = new Date();
  const stamp = now.toISOString().replace(/[-:T]/g, "").slice(0, 14);
  return `photo_${stamp}.jpg`;
}

// --- ویرایشِ عکس: کراپِ مربع (کشیدن/زوم) + پیش‌تنظیمِ فیلتر -----------------
const EDIT_CANVAS_SIZE = 1000;
const FILTER_PRESETS = [
  { key: "normal", label: "🔹 عادی", css: "", sharpen: false },
  { key: "bright", label: "☀️ روشن و واضح", css: "brightness(1.12) contrast(1.08) saturate(1.05)", sharpen: true },
  { key: "studio", label: "🏭 صنعتی/محصول", css: "brightness(1.05) contrast(1.22) saturate(0.92)", sharpen: true },
  { key: "warm", label: "🌟 گرم", css: "brightness(1.05) contrast(1.05) saturate(1.15) sepia(0.08)", sharpen: false },
];

function applySharpen(ctx, w, h) {
  const imgData = ctx.getImageData(0, 0, w, h);
  const src = imgData.data;
  const out = new Uint8ClampedArray(src.length);
  const kernel = [0, -1, 0, -1, 5, -1, 0, -1, 0];
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const idx = (y * w + x) * 4;
      if (x === 0 || y === 0 || x === w - 1 || y === h - 1) {
        out[idx] = src[idx];
        out[idx + 1] = src[idx + 1];
        out[idx + 2] = src[idx + 2];
        out[idx + 3] = src[idx + 3];
        continue;
      }
      let r = 0, g = 0, b = 0, k = 0;
      for (let ky = -1; ky <= 1; ky++) {
        for (let kx = -1; kx <= 1; kx++) {
          const nIdx = ((y + ky) * w + (x + kx)) * 4;
          const weight = kernel[k++];
          r += src[nIdx] * weight;
          g += src[nIdx + 1] * weight;
          b += src[nIdx + 2] * weight;
        }
      }
      out[idx] = r;
      out[idx + 1] = g;
      out[idx + 2] = b;
      out[idx + 3] = src[idx + 3];
    }
  }
  imgData.data.set(out);
  ctx.putImageData(imgData, 0, 0);
}

// --- حذفِ پس‌زمینه: کاملاً رویِ خودِ گوشی (آفلاین) با ONNX Runtime Web +
// مدلِ سبکِ U2-Netp. سشن فقط با اولین استفاده لود می‌شه (نه موقعِ بازکردنِ
// اپ) — تا اجرایِ اپ رو کند نکنه. -----------------------------------------
const BG_MODEL_PATH = "./models/u2netp.onnx";
const BG_INPUT_SIZE = 320;
const BG_SESSION_TIMEOUT_MS = 45000;
const BG_INFERENCE_TIMEOUT_MS = 30000;
let bgSessionPromise = null;

// یه Promise رو با یه سقفِ زمانی می‌پیچه — اگه promise اصلی هیچ‌وقت resolve/reject
// نشه (مثلاً fetchِ فایلِ مدل رویِ وای‌فایِ ضعیف گیر کنه و نه خطا بده نه تموم بشه)،
// بازم بعدِ ms میلی‌ثانیه با خطا reject می‌شه — تا UI برایِ همیشه رویِ «در حال
// حذفِ پس‌زمینه...» گیر نکنه.
function withTimeout(promise, ms, message) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(message)), ms);
    promise.then(
      (v) => {
        clearTimeout(timer);
        resolve(v);
      },
      (e) => {
        clearTimeout(timer);
        reject(e);
      }
    );
  });
}

async function getBgSession() {
  if (!bgSessionPromise) {
    // ort-wasm-simd-threaded برای لود شدن (حتی با numThreads=1) به
    // SharedArrayBuffer نیاز داره که فقط تویِ صفحه‌یِ crossOriginIsolated
    // در دسترسه. اگه این شرط برقرار نباشه، ort با یه خطایِ داخلیِ نامفهوم
    // شکست می‌خوره — این‌جا زودتر با یه پیامِ روشن رد می‌کنیم تا کاربر
    // بدونه مشکل از کش/مرورگره، نه از خودِ عکس یا اتصال.
    if (typeof SharedArrayBuffer === "undefined" || !window.crossOriginIsolated) {
      bgSessionPromise = Promise.reject(
        new Error(
          (typeof SharedArrayBuffer === "undefined"
            ? "SharedArrayBuffer در دسترس نیست"
            : "crossOriginIsolated فعال نشده") +
            " — این معمولاً یعنی نسخه‌ی کش‌شده‌ی قدیمیِ اپ هنوز رو گوشیه. اپ رو از صفحه‌ی اصلیِ گوشی کامل حذف کن، Safari رو ببند و دوباره از QR کد/آدرس باز کن."
        )
      );
    } else {
      ort.env.wasm.numThreads = 1;
      ort.env.wasm.proxy = false;
      bgSessionPromise = ort.InferenceSession.create(BG_MODEL_PATH, {
        executionProviders: ["wasm"],
      });
    }
  }
  try {
    return await withTimeout(
      bgSessionPromise,
      BG_SESSION_TIMEOUT_MS,
      "آماده‌سازیِ مدلِ حذفِ پس‌زمینه بیش از حد طول کشید (شاید وای‌فای ضعیفه)."
    );
  } catch (e) {
    // promiseِ ناموفق/گیرکرده رو کش نگه نمی‌داریم — تا دفعه‌ی بعد از نو امتحان بشه
    bgSessionPromise = null;
    throw e;
  }
}

const BG_MEAN = [0.485, 0.456, 0.406];
const BG_STD = [0.229, 0.224, 0.225];

// عکسِ رویِ canvas رو می‌گیره، پس‌زمینه رو تشخیص می‌ده و با سفید جایگزین
// می‌کنه — مستقیم رویِ همون ctx می‌نویسه.
async function removeBackground(ctx, size) {
  const session = await getBgSession();

  const small = document.createElement("canvas");
  small.width = BG_INPUT_SIZE;
  small.height = BG_INPUT_SIZE;
  const sctx = small.getContext("2d");
  sctx.drawImage(ctx.canvas, 0, 0, size, size, 0, 0, BG_INPUT_SIZE, BG_INPUT_SIZE);
  const srcData = sctx.getImageData(0, 0, BG_INPUT_SIZE, BG_INPUT_SIZE).data;

  const plane = BG_INPUT_SIZE * BG_INPUT_SIZE;
  const chw = new Float32Array(3 * plane);
  for (let i = 0; i < plane; i++) {
    chw[i] = (srcData[i * 4] / 255 - BG_MEAN[0]) / BG_STD[0];
    chw[plane + i] = (srcData[i * 4 + 1] / 255 - BG_MEAN[1]) / BG_STD[1];
    chw[plane * 2 + i] = (srcData[i * 4 + 2] / 255 - BG_MEAN[2]) / BG_STD[2];
  }

  const tensor = new ort.Tensor("float32", chw, [1, 3, BG_INPUT_SIZE, BG_INPUT_SIZE]);
  const feeds = {};
  feeds[session.inputNames[0]] = tensor;
  const results = await withTimeout(
    session.run(feeds),
    BG_INFERENCE_TIMEOUT_MS,
    "پردازشِ حذفِ پس‌زمینه بیش از حد طول کشید."
  );
  const outData = results[session.outputNames[0]].data;

  let mn = Infinity;
  let mx = -Infinity;
  for (let i = 0; i < outData.length; i++) {
    if (outData[i] < mn) mn = outData[i];
    if (outData[i] > mx) mx = outData[i];
  }
  const range = mx - mn || 1;

  const maskSmall = document.createElement("canvas");
  maskSmall.width = BG_INPUT_SIZE;
  maskSmall.height = BG_INPUT_SIZE;
  const mctx = maskSmall.getContext("2d");
  const maskImgData = mctx.createImageData(BG_INPUT_SIZE, BG_INPUT_SIZE);
  for (let i = 0; i < outData.length; i++) {
    const v = Math.round(((outData[i] - mn) / range) * 255);
    maskImgData.data[i * 4] = v;
    maskImgData.data[i * 4 + 1] = v;
    maskImgData.data[i * 4 + 2] = v;
    maskImgData.data[i * 4 + 3] = 255;
  }
  mctx.putImageData(maskImgData, 0, 0);

  // آپ‌اسکیلِ ماسک به اندازه‌ی تصویرِ اصلی (bilinear خودِ canvas)
  const maskBig = document.createElement("canvas");
  maskBig.width = size;
  maskBig.height = size;
  const mbctx = maskBig.getContext("2d");
  mbctx.drawImage(maskSmall, 0, 0, size, size);
  const maskData = mbctx.getImageData(0, 0, size, size).data;

  const orig = ctx.getImageData(0, 0, size, size);
  const out = orig.data;
  for (let i = 0; i < out.length; i += 4) {
    const alpha = maskData[i] / 255;
    out[i] = out[i] * alpha + 255 * (1 - alpha);
    out[i + 1] = out[i + 1] * alpha + 255 * (1 - alpha);
    out[i + 2] = out[i + 2] * alpha + 255 * (1 - alpha);
  }
  ctx.putImageData(orig, 0, 0);
}

async function loadImageSource(file) {
  try {
    return await createImageBitmap(file);
  } catch (e) {
    const url = URL.createObjectURL(file);
    return await new Promise((resolve, reject) => {
      const el = new Image();
      el.onload = () => resolve(el);
      el.onerror = reject;
      el.src = url;
    });
  }
}

// عکسِ گرفته‌شده رو تویِ یه صفحه‌ی مربع نشون می‌ده — با کشیدن جابه‌جا و با
// اسلایدر زوم می‌شه، بعد یه پیش‌تنظیمِ فیلتر (نور/کنتراست/شارپ) انتخاب
// می‌شه. خروجی یه Blob مربعِ نهایی‌ست، یا null اگه کاربر لغو کرده باشه.
function openEditor(file) {
  return new Promise(async (resolve) => {
    const overlay = document.getElementById("editScreen");
    const canvas = document.getElementById("editCanvas");
    const ctx = canvas.getContext("2d");
    canvas.width = EDIT_CANVAS_SIZE;
    canvas.height = EDIT_CANVAS_SIZE;

    const cancelBtn = document.getElementById("editCancelBtn");
    const confirmBtn = document.getElementById("editConfirmBtn");
    const bgCheckbox = document.getElementById("editBgRemove");
    const hintEl = document.getElementById("editHint");
    const CONFIRM_TEXT_DEFAULT = "✅ ادامه";
    const CONFIRM_TEXT_PREVIEW = "✅ تایید همین نتیجه و ادامه";
    const HINT_TEXT_DEFAULT = "عکس رو بکشید تا جابه‌جا بشه — با اسلایدر بزرگ‌نمایی کنید";
    const HINT_TEXT_PREVIEW = "نتیجه‌ی حذفِ پس‌زمینه رو بررسی کنید — اگه خوبه، دوباره «ادامه» بزنید.";
    bgCheckbox.checked = false;
    bgCheckbox.disabled = false;
    confirmBtn.textContent = CONFIRM_TEXT_DEFAULT;
    if (hintEl) hintEl.textContent = HINT_TEXT_DEFAULT;

    let img;
    try {
      img = await loadImageSource(file);
    } catch (e) {
      resolve(null);
      return;
    }
    const natW = img.width || img.naturalWidth;
    const natH = img.height || img.naturalHeight;
    if (!natW || !natH) {
      resolve(null);
      return;
    }

    const coverScale = Math.max(EDIT_CANVAS_SIZE / natW, EDIT_CANVAS_SIZE / natH);
    const state = {
      minScale: coverScale,
      scale: coverScale,
      offsetX: (EDIT_CANVAS_SIZE - natW * coverScale) / 2,
      offsetY: (EDIT_CANVAS_SIZE - natH * coverScale) / 2,
      filterKey: "normal",
      bgApplied: false,
    };

    function clampOffsets() {
      const w = natW * state.scale;
      const h = natH * state.scale;
      state.offsetX = w <= EDIT_CANVAS_SIZE
        ? (EDIT_CANVAS_SIZE - w) / 2
        : Math.min(0, Math.max(EDIT_CANVAS_SIZE - w, state.offsetX));
      state.offsetY = h <= EDIT_CANVAS_SIZE
        ? (EDIT_CANVAS_SIZE - h) / 2
        : Math.min(0, Math.max(EDIT_CANVAS_SIZE - h, state.offsetY));
    }

    function currentPreset() {
      return FILTER_PRESETS.find((p) => p.key === state.filterKey) || FILTER_PRESETS[0];
    }

    function draw() {
      // هر بازرسمِ خام (کشیدن/زوم/تغییرِ فیلتر) یعنی هر نتیجه‌ی حذفِ
      // پس‌زمینه‌یِ قبلی دیگه معتبر نیست — باید دوباره اجرا بشه.
      if (state.bgApplied) {
        state.bgApplied = false;
        bgCheckbox.disabled = false;
        confirmBtn.textContent = CONFIRM_TEXT_DEFAULT;
        if (hintEl) hintEl.textContent = HINT_TEXT_DEFAULT;
      }
      ctx.save();
      ctx.clearRect(0, 0, EDIT_CANVAS_SIZE, EDIT_CANVAS_SIZE);
      ctx.filter = currentPreset().css || "none";
      ctx.drawImage(img, state.offsetX, state.offsetY, natW * state.scale, natH * state.scale);
      ctx.restore();
    }

    draw();

    const zoomEl = document.getElementById("editZoom");
    zoomEl.min = "1";
    zoomEl.max = "3";
    zoomEl.step = "0.01";
    zoomEl.value = "1";
    const onZoom = () => {
      const factor = parseFloat(zoomEl.value) || 1;
      const newScale = state.minScale * factor;
      const cx = EDIT_CANVAS_SIZE / 2;
      const cy = EDIT_CANVAS_SIZE / 2;
      const imgCx = (cx - state.offsetX) / state.scale;
      const imgCy = (cy - state.offsetY) / state.scale;
      state.scale = newScale;
      state.offsetX = cx - imgCx * state.scale;
      state.offsetY = cy - imgCy * state.scale;
      clampOffsets();
      draw();
    };
    zoomEl.oninput = onZoom;

    let dragging = false;
    let lastX = 0;
    let lastY = 0;
    function toCanvasPoint(ev) {
      const rect = canvas.getBoundingClientRect();
      const scaleX = EDIT_CANVAS_SIZE / rect.width;
      const scaleY = EDIT_CANVAS_SIZE / rect.height;
      return { x: (ev.clientX - rect.left) * scaleX, y: (ev.clientY - rect.top) * scaleY };
    }
    function onDown(ev) {
      dragging = true;
      const p = toCanvasPoint(ev);
      lastX = p.x;
      lastY = p.y;
    }
    function onMove(ev) {
      if (!dragging) return;
      ev.preventDefault();
      const p = toCanvasPoint(ev);
      state.offsetX += p.x - lastX;
      state.offsetY += p.y - lastY;
      lastX = p.x;
      lastY = p.y;
      clampOffsets();
      draw();
    }
    function onUp() {
      dragging = false;
    }
    canvas.addEventListener("pointerdown", onDown);
    canvas.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);

    const presetsRow = document.getElementById("editPresets");
    presetsRow.innerHTML = "";
    FILTER_PRESETS.forEach((preset) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "preset-btn" + (preset.key === state.filterKey ? " active" : "");
      btn.textContent = preset.label;
      btn.onclick = () => {
        state.filterKey = preset.key;
        [...presetsRow.children].forEach((c) => c.classList.remove("active"));
        btn.classList.add("active");
        draw();
      };
      presetsRow.appendChild(btn);
    });

    function cleanup() {
      canvas.removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      zoomEl.oninput = null;
      overlay.classList.remove("open");
    }

    cancelBtn.onclick = () => {
      cleanup();
      resolve(null);
    };

    // با تیک‌بودنِ «حذفِ پس‌زمینه»، اولین کلیکِ «ادامه» فقط نتیجه رو رویِ
    // همون کانواس نشون می‌ده (بدونِ پرسیدنِ نامِ فایل) — کاربر نتیجه رو
    // می‌بینه و با کلیکِ دومِ «ادامه» واقعاً وارد مرحله‌ی تأییدِ نام می‌شه.
    confirmBtn.onclick = async () => {
      const wantsBgRemove = bgCheckbox.checked;

      if (wantsBgRemove && !state.bgApplied) {
        draw();
        cancelBtn.disabled = true;
        confirmBtn.disabled = true;
        confirmBtn.textContent = "⏳ در حال حذفِ پس‌زمینه...";
        try {
          await removeBackground(ctx, EDIT_CANVAS_SIZE);
          if (currentPreset().sharpen) {
            applySharpen(ctx, EDIT_CANVAS_SIZE, EDIT_CANVAS_SIZE);
          }
          state.bgApplied = true;
          bgCheckbox.disabled = true;
          confirmBtn.textContent = CONFIRM_TEXT_PREVIEW;
          if (hintEl) hintEl.textContent = HINT_TEXT_PREVIEW;
        } catch (e) {
          confirmBtn.textContent = CONFIRM_TEXT_DEFAULT;
          console.error("removeBackground failed:", e);
          const detail = (e && e.message) ? e.message : String(e);
          window.alert(
            "حذفِ پس‌زمینه ناموفق بود:\n" + detail +
              "\n\nدوباره امتحان کنید یا تیکش رو بردارید."
          );
        } finally {
          cancelBtn.disabled = false;
          confirmBtn.disabled = false;
        }
        return;
      }

      if (!wantsBgRemove) {
        draw();
        if (currentPreset().sharpen) {
          applySharpen(ctx, EDIT_CANVAS_SIZE, EDIT_CANVAS_SIZE);
        }
      }

      canvas.toBlob(
        (blob) => {
          cleanup();
          resolve(blob);
        },
        "image/jpeg",
        0.92
      );
    };

    overlay.classList.add("open");
  });
}

async function handleFile(file) {
  try {
    const edited = await openEditor(file);
    if (!edited) return; // کاربر ویرایش رو لغو کرد

    const suggested = suggestFilename(file.name || "photo.jpg");
    const chosen = window.prompt(
      "نام فایل رو وارد کنید (بهتره کدِ کالا توش باشه، مثلاً 0103005.jpg):",
      suggested
    );
    if (chosen === null) return; // انصراف
    const rawName = chosen.trim() || suggested;
    const filename = /\.[a-zA-Z0-9]+$/.test(rawName) ? rawName : `${rawName}.jpg`;

    await dbAdd({
      filename,
      blob: edited,
      createdAt: Date.now(),
      status: "pending",
    });
    await renderQueue();
    flushQueue();
  } catch (e) {
    // بدونِ این catch، هر خطایی (مثلاً پایگاه‌دادهِ محلی در دسترس نبودن)
    // بی‌صدا تویِ کنسول گم می‌شد و عکس بدونِ هیچ پیامی از دست می‌رفت.
    window.alert("مشکلی پیش اومد و عکس ذخیره نشد:\n" + e);
  }
}

// رویِ آیفون، بدونِ «Add to Home Screen»، سرویس‌ورکر/آفلاین کاملاً قابلِ
// اتکا نیست (Safari محدودیت‌هایِ ذخیره‌سازیِ سخت‌گیرانه‌تری برایِ تبِ سادهِ
// مرورگر داره، نه اپِ نصب‌شده رویِ صفحه‌یِ اصلی). این فقط یه راهنماییه —
// بدونِ نصب هم بقیه‌یِ اپ (گرفتن/ارسالِ عکس وقتی آنلاینه) کار می‌کنه.
function initA2hsBanner() {
  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
  const isStandalone =
    window.navigator.standalone === true ||
    (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches);
  const banner = document.getElementById("a2hsBanner");
  if (!banner) return;
  if (isIOS && !isStandalone) {
    banner.style.display = "block";
  }
  const closeBtn = document.getElementById("a2hsCloseBtn");
  if (closeBtn) {
    closeBtn.addEventListener("click", () => {
      banner.style.display = "none";
    });
  }
}

function init() {
  const onPick = (ev) => {
    const file = ev.target.files && ev.target.files[0];
    if (file) handleFile(file);
    ev.target.value = "";
  };
  document.getElementById("captureInput").addEventListener("change", onPick);
  document.getElementById("galleryInput").addEventListener("change", onPick);

  document.getElementById("refreshBtn").addEventListener("click", () => flushQueue());
  initA2hsBanner();

  window.addEventListener("online", () => flushQueue());
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") flushQueue();
  });
  setInterval(flushQueue, PING_INTERVAL_MS);

  openDb()
    .then((database) => {
      db = database;
      renderQueue();
      flushQueue();
    })
    .catch((err) => {
      // بدونِ این catch، اگه IndexedDB باز نشه (مثلاً حالتِ خصوصی/Private
      // مرورگر)، db برایِ همیشه null می‌مونه و عکس‌ها بی‌صدا ذخیره
      // نمی‌شن — کاربر هم هیچ پیامی نمی‌بینه.
      setStatus("❌ ذخیره‌سازیِ محلی در دسترس نیست — عکس‌ها ذخیره نمی‌شن", false);
      window.alert(
        "ذخیره‌سازیِ محلیِ این مرورگر در دسترس نیست، پس عکس‌ها نمی‌تونن ذخیره بشن.\n" +
        "اگه تویِ حالتِ خصوصی/Private هستید، از حالتِ عادیِ مرورگر امتحان کنید.\n(" + err + ")"
      );
    });

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("./sw.js").catch(() => {});
  }
}

document.addEventListener("DOMContentLoaded", init);
