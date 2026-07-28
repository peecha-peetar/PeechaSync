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
    const tx = db.transaction(STORE_NAME, "readwrite");
    const req = tx.objectStore(STORE_NAME).add(item);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function dbGetAll() {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readonly");
    const req = tx.objectStore(STORE_NAME).getAll();
    req.onsuccess = () => resolve(req.result || []);
    req.onerror = () => reject(req.error);
  });
}

function dbDelete(id) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    const req = tx.objectStore(STORE_NAME).delete(id);
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
  });
}

function dbUpdate(item) {
  return new Promise((resolve, reject) => {
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
  if (sending) return;
  const reachable = await checkReachable();
  setStatus(reachable ? "🟢 متصل به پیچا" : "🔴 به پیچا وصل نیست — عکس‌ها تو صف می‌مونن", reachable);
  if (!reachable) return;

  sending = true;
  try {
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
  const ext = (originalName.match(/\.[a-zA-Z0-9]+$/) || [".jpg"])[0];
  return `photo_${stamp}${ext}`;
}

async function handleFile(file) {
  const suggested = suggestFilename(file.name || "photo.jpg");
  const chosen = window.prompt(
    "نام فایل رو وارد کنید (بهتره کدِ کالا توش باشه، مثلاً 0103005.jpg):",
    suggested
  );
  if (chosen === null) return; // انصراف
  const filename = chosen.trim() || suggested;

  await dbAdd({
    filename,
    blob: file,
    createdAt: Date.now(),
    status: "pending",
  });
  await renderQueue();
  flushQueue();
}

function init() {
  document.getElementById("captureInput").addEventListener("change", (ev) => {
    const file = ev.target.files && ev.target.files[0];
    if (file) handleFile(file);
    ev.target.value = "";
  });

  document.getElementById("refreshBtn").addEventListener("click", () => flushQueue());

  window.addEventListener("online", () => flushQueue());
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") flushQueue();
  });
  setInterval(flushQueue, PING_INTERVAL_MS);

  openDb().then((database) => {
    db = database;
    renderQueue();
    flushQueue();
  });

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("./sw.js").catch(() => {});
  }
}

document.addEventListener("DOMContentLoaded", init);
