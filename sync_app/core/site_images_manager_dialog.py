"""دیالوگِ مدیریتِ عکس‌هایِ فعلیِ محصول رویِ سایت — دیدنِ گالریِ فعلیِ هر
محصولِ تیک‌خورده و حذفِ تک‌تکِ عکس‌ها از سایت، بدونِ نیاز به آپلودِ دوباره‌ی
بقیه‌ی عکس‌ها."""

from __future__ import annotations

import logging

import requests
from PyQt5.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

log = logging.getLogger("SyncApp")

_THUMB_SIZE = 96


def _fetch_wc_images(cfg, sku):
    from sync_app.core.wc_sync_helper import wc_rest_request

    timeout = int(cfg.get("WC_TIMEOUT", 60) or 60)
    resp = wc_rest_request(cfg, "GET", "products", params={"sku": sku}, timeout=timeout)
    try:
        data = resp.json()
    except Exception:
        return 0, [], "پاسخ نامعتبر از فروشگاه"
    if not isinstance(data, list) or not data:
        return 0, [], "محصول در فروشگاه پیدا نشد"
    pid = int(data[0].get("id") or 0)
    images = data[0].get("images") or []
    out = [
        {"id": img.get("id"), "src": img.get("src") or ""}
        for img in images
        if img.get("id")
    ]
    return pid, out, ""


def _fetch_ps_images(cfg, pid):
    from sync_app.core.ps_sync_helper import ps_get_product_image_ids

    try:
        ids = ps_get_product_image_ids(cfg, pid)
    except Exception as exc:
        return [], str(exc)
    return [{"id": iid, "src": ""} for iid in ids], ""


class _LoadWorker(QThread):
    row_ready = pyqtSignal(str, int, list, str)  # sku, pid, images, error
    finished_all = pyqtSignal()

    def __init__(self, cfg, is_ps, skus, product_map):
        super().__init__()
        self.cfg = cfg
        self.is_ps = is_ps
        self.skus = list(skus)
        self.product_map = product_map

    def run(self):
        for sku in self.skus:
            if self.isInterruptionRequested():
                break
            try:
                if self.is_ps:
                    pid = int(self.product_map.get(sku) or 0)
                    if not pid:
                        self.row_ready.emit(sku, 0, [], "محصول در پرستاشاپ لینک نشده")
                        continue
                    images, err = _fetch_ps_images(self.cfg, pid)
                    self.row_ready.emit(sku, pid, images, err)
                else:
                    pid, images, err = _fetch_wc_images(self.cfg, sku)
                    self.row_ready.emit(sku, pid, images, err)
            except Exception as exc:
                self.row_ready.emit(sku, 0, [], str(exc))
        self.finished_all.emit()


class _ThumbLabel(QLabel):
    def __init__(self, src_url: str):
        super().__init__()
        self.setFixedSize(_THUMB_SIZE, _THUMB_SIZE)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            "background:#f1f5f9; border:1px solid #cbd5e1; border-radius:6px; color:#64748b; font-size:11px;"
        )
        self.setText("در حال بارگذاری…")
        if src_url:
            self._load_async(src_url)
        else:
            self.setText("بدونِ پیش‌نمایش")

    def _load_async(self, src_url: str):
        # دانلودِ عکس تویِ یه ترد جدا — تا باز کردنِ دیالوگ برایِ چندین عکس،
        # رابط رو فریز نکنه.
        thread = QThread(self)
        worker = _ThumbFetcher(src_url)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_loaded)
        worker.done.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _on_loaded(self, data: bytes):
        if not data:
            self.setText("خطا در بارگذاری")
            return
        pix = QPixmap()
        if pix.loadFromData(data):
            self.setPixmap(
                pix.scaled(_THUMB_SIZE - 8, _THUMB_SIZE - 8, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            self.setText("")
        else:
            self.setText("خطا در بارگذاری")


class _ThumbFetcher(QObject):
    done = pyqtSignal(bytes)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            resp = requests.get(self.url, timeout=15)
            self.done.emit(resp.content if resp.ok else b"")
        except Exception:
            self.done.emit(b"")


class SiteImagesManagerDialog(QDialog):
    """برایِ لیستِ SKUهایِ تیک‌خورده، گالریِ فعلیِ سایت رو نشون می‌ده و اجازه‌ی
    حذفِ تک‌تکِ عکس‌ها رو (بدونِ آپلودِ دوباره‌ی بقیه) می‌ده."""

    def __init__(self, parent, cfg: dict, skus: list[str]):
        super().__init__(parent)
        self.setWindowTitle("مدیریتِ عکس‌هایِ سایت")
        self.resize(720, 560)
        self.cfg = cfg
        self.skus = list(skus)

        from sync_app.core.integrations.commerce_provider import is_prestashop
        from sync_app.core.product_woo_map_helper import load_product_woo_map

        self.is_ps = is_prestashop(cfg)
        self.product_map = load_product_woo_map()
        self._pid_by_sku: dict[str, int] = {}
        self._row_boxes: dict[str, tuple] = {}

        root = QVBoxLayout(self)
        hint = QLabel(
            "برایِ هر محصول، عکس‌هایِ فعلیِ روی سایت نشون داده می‌شه — با زدنِ ✕ "
            "همون عکس فوراً از سایت حذف می‌شه (نیازی به ارسالِ دوباره‌ی بقیه‌ی عکس‌ها نیست)."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#475569; font-size:12px;")
        root.addWidget(hint)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.container)
        root.addWidget(self.scroll)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("بستن")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        root.addLayout(close_row)

        for sku in self.skus:
            self._build_row_placeholder(sku)

        self._worker = _LoadWorker(self.cfg, self.is_ps, self.skus, self.product_map)
        self._worker.row_ready.connect(self._on_row_ready)
        self._worker.start()

    def closeEvent(self, event):
        if self._worker.isRunning():
            self._worker.requestInterruption()
            self._worker.wait(2000)
        super().closeEvent(event)

    def _build_row_placeholder(self, sku):
        box = QFrame()
        box.setFrameShape(QFrame.StyledPanel)
        box.setStyleSheet("QFrame { border:1px solid #e2e8f0; border-radius:8px; padding:6px; }")
        v = QVBoxLayout(box)
        title = QLabel(f"📦 {sku} — در حال دریافتِ عکس‌ها…")
        title.setStyleSheet("font-weight:700;")
        v.addWidget(title)
        grid_holder = QHBoxLayout()
        v.addLayout(grid_holder)
        self.container_layout.addWidget(box)
        self._row_boxes[sku] = (box, title, grid_holder)

    def _on_row_ready(self, sku, pid, images, error):
        self._pid_by_sku[sku] = pid
        box, title, grid_holder = self._row_boxes.get(sku, (None, None, None))
        if title is None:
            return
        if error:
            title.setText(f"📦 {sku} — ⚠️ {error}")
            return
        if not images:
            title.setText(f"📦 {sku} — بدونِ عکس روی سایت")
            return
        title.setText(f"📦 {sku} — {len(images)} عکس")
        for img in images:
            self._add_image_widget(grid_holder, sku, pid, img)

    def _add_image_widget(self, grid_holder, sku, pid, img):
        cell = QVBoxLayout()
        thumb = _ThumbLabel(img.get("src") or "")
        cell.addWidget(thumb)
        del_btn = QPushButton("✕ حذف")
        del_btn.setStyleSheet(
            "QPushButton { background:#fee2e2; color:#b91c1c; border:none; border-radius:6px; padding:3px 6px; font-size:11px; }"
            "QPushButton:hover { background:#fecaca; }"
        )
        image_id = img.get("id")
        del_btn.clicked.connect(lambda _=False, s=sku, p=pid, iid=image_id, cw=cell: self._delete_image(s, p, iid, cw))
        cell.addWidget(del_btn)
        holder = QWidget()
        holder.setLayout(cell)
        grid_holder.addWidget(holder)

    def _delete_image(self, sku, pid, image_id, cell_layout):
        answer = QMessageBox.question(
            self, "حذفِ عکس", f"این عکس از سایت برایِ محصولِ «{sku}» برایِ همیشه حذف بشه؟",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            if self.is_ps:
                from sync_app.core.ps_sync_helper import ps_delete_product_image

                ps_delete_product_image(self.cfg, pid, image_id)
            else:
                from sync_app.core.wc_sync_helper import update_wc_product_images

                _, remaining, _err = _fetch_wc_images(self.cfg, sku)
                new_images = [{"id": im["id"]} for im in remaining if im.get("id") != image_id]
                ok, _resp, err_msg = update_wc_product_images(self.cfg, pid, new_images, allow_empty=True)
                if not ok:
                    raise RuntimeError(err_msg or "حذف ناموفق بود")
            log.info(f"🗑️ عکس #{image_id} محصولِ {sku} از سایت حذف شد.")
        except Exception as exc:
            QMessageBox.critical(self, "خطا در حذف", f"حذفِ عکس ناموفق بود:\n{exc}")
            return
        for i in reversed(range(cell_layout.count())):
            w = cell_layout.itemAt(i).widget()
            if w is not None:
                w.deleteLater()
        parent_widget = cell_layout.parentWidget()
        if parent_widget is not None:
            parent_widget.deleteLater()
