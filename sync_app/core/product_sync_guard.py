"""پیش‌نمایش و تأیید نهایی قبل از ارسال محصولات به ووکامرس."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from sync_app.core.article_price import resolve_article_price
from sync_app.core.category_resolver import load_category_map, resolve_wc_category_id
from sync_app.core.currency_helper import erp_price_divisor
from sync_app.core.product_woo_map_helper import load_product_woo_map
from sync_app.core.product_woo_map_meta import get_product_link_meta, is_manual_product_link
from sync_app.core.secure_config_loader import load_secure_config
from sync_app.core.sql_connection_helper import open_sql_connection


@dataclass
class ProductSyncPreviewRow:
    erp_sku: str
    erp_name: str
    price: str
    stock: int
    category_label: str
    wc_id: int | None
    wc_label: str
    manual_link: bool
    notes: list[str]


def _category_label_for_sku(sku: str, cat_map: dict) -> str:
    sku = str(sku or "").strip()
    cat_id = None
    if len(sku) >= 4:
        cat_id = resolve_wc_category_id(sku[:4], cat_map)
    if not cat_id and len(sku) >= 2:
        cat_id = resolve_wc_category_id(sku[:2], cat_map)
    return str(cat_id) if cat_id else "—"


def build_products_sync_preview(config: dict | None = None) -> list[ProductSyncPreviewRow]:
    """لیست محصولاتی که sync_fullproduct.main ارسال می‌کند + مقصد Woo از تب تطبیق."""
    config = config or load_secure_config(None) or {}
    groups = [str(g).strip() for g in (config.get("SELECTED_SUB_GROUPS") or []) if str(g).strip()]
    disabled = set(config.get("DISABLED_PRODUCT_SKUS") or [])
    price_col = config.get("PRICE_LIST_COLUMN", "Sel_Price")
    price_div = erp_price_divisor(config)
    cat_map = load_category_map() or {}
    product_map = load_product_woo_map()

    if not groups:
        return []

    conn, _, _ = open_sql_connection(config, timeout=10)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT A_Code, A_Name, Sel_Price, Sel_Price2, Sel_Price3, Sel_Price4, Sel_Price5, Exist "
        "FROM Article WHERE LEN(A_Code) >= 4"
    )
    rows = cursor.fetchall()
    conn.close()

    previews: list[ProductSyncPreviewRow] = []
    for row in rows:
        sku = str(row[0]).strip()
        if sku in disabled:
            continue
        if not any(sku.startswith(g) for g in groups):
            continue

        raw_price = resolve_article_price(row, price_col, price_start_index=2)
        price = str(int(raw_price / price_div)) if raw_price > 0 else "0"
        stock = int(row[7] or 0)
        wc_id = int(product_map.get(sku) or 0) or None
        meta = get_product_link_meta(sku) or {}
        wc_label = str(meta.get("wc_label") or "").strip()
        if wc_id and not wc_label:
            wc_label = f"Woo #{wc_id}"
        manual = is_manual_product_link(sku)
        notes: list[str] = []
        if not wc_id:
            notes.append("هنوز در تب تطبیق ثبت نشده — ممکن است با SKU در سایت پیدا شود یا محصول جدید ساخته شود")
        if manual:
            notes.append("تطبیق دستی — داده ERP فقط روی محصول ثبت‌شده در تب تطبیق اعمال می‌شود")
        conflict_id = meta.get("sku_conflict_wc_id")
        if conflict_id:
            notes.append(f"تضاد SKU: محصول دیگر سایت #{conflict_id} همین SKU را دارد")

        previews.append(
            ProductSyncPreviewRow(
                erp_sku=sku,
                erp_name=str(row[1] or "").strip(),
                price=price,
                stock=stock,
                category_label=_category_label_for_sku(sku, cat_map),
                wc_id=wc_id,
                wc_label=wc_label,
                manual_link=manual,
                notes=notes,
            )
        )
    return previews


class ProductSyncPreviewDialog(QDialog):
    def __init__(self, parent, previews: list[ProductSyncPreviewRow], site_host: str):
        super().__init__(parent)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowTitle("پیش‌نمایش ارسال محصولات")
        self.setModal(True)
        self.setMinimumWidth(620)
        self._confirmed = False
        self._build_ui(previews, site_host)

    def _build_ui(self, previews: list[ProductSyncPreviewRow], site_host: str):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        banner = QFrame()
        banner.setStyleSheet("QFrame { background-color: #1e3a8a; }")
        bl = QVBoxLayout(banner)
        bl.setContentsMargins(18, 14, 18, 14)
        title = QLabel("📋 پیش‌نمایش قبل از ارسال به سایت")
        title.setStyleSheet("color: #fff; font-size: 16px; font-weight: 800; background: transparent;")
        bl.addWidget(title)
        sub = QLabel(
            f"سایت: {site_host or '—'} | {len(previews)} محصول از ERP ارسال می‌شود.\n"
            "ملاک مقصد = تب «تطبیق» (product_woo_map.json)."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet("color: #dbeafe; font-size: 12px; background: transparent;")
        bl.addWidget(sub)
        root.addWidget(banner)

        body = QScrollArea()
        body.setWidgetResizable(True)
        body.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        vl = QVBoxLayout(host)
        vl.setSpacing(8)

        for index, row in enumerate(previews, start=1):
            card = QFrame()
            border = "#dc2626" if row.manual_link else "#cbd5e1"
            card.setStyleSheet(
                f"QFrame {{ background: #fff; border: 2px solid {border}; border-radius: 10px; }}"
            )
            cl = QVBoxLayout(card)
            cl.setContentsMargins(12, 10, 12, 10)
            head = QLabel(f"{index}. {row.erp_name or '—'}  (SKU {row.erp_sku})")
            head.setStyleSheet("font-weight: 700; color: #0f172a; background: transparent;")
            cl.addWidget(head)
            target = (
                f"{row.wc_label} (#{row.wc_id})"
                if row.wc_id
                else "⚠️ مقصد Woo مشخص نیست"
            )
            cl.addWidget(QLabel(f"→ مقصد سایت: {target}"))
            cl.addWidget(
                QLabel(
                    f"قیمت: {row.price} | موجودی: {row.stock} | دسته Woo: {row.category_label}"
                )
            )
            for note in row.notes:
                nl = QLabel(f"• {note}")
                nl.setWordWrap(True)
                nl.setStyleSheet("color: #b45309; font-weight: 600; background: transparent;")
                cl.addWidget(nl)
            vl.addWidget(card)

        vl.addStretch(1)
        body.setWidget(host)
        root.addWidget(body, 1)

        manual_any = any(r.manual_link for r in previews)
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(16, 10, 16, 14)
        cancel = QPushButton("انصراف")
        cancel.setMinimumHeight(40)
        cancel.clicked.connect(self.reject)
        confirm = QPushButton(
            "می‌دانم — ارسال به سایت" if manual_any else "تأیید و ارسال"
        )
        confirm.setMinimumHeight(40)
        confirm.setStyleSheet(
            "QPushButton { background: #166534; color: #fff; font-weight: 700; border-radius: 8px; }"
        )
        confirm.clicked.connect(self._accept)
        btn_row.addWidget(cancel)
        btn_row.addWidget(confirm)
        root.addLayout(btn_row)

    def _accept(self):
        self._confirmed = True
        self.accept()

    @staticmethod
    def ask(parent, previews: list[ProductSyncPreviewRow], config: dict | None = None) -> bool:
        config = config or load_secure_config(None) or {}
        from sync_app.core.integrations.commerce_provider import is_prestashop

        url_key = "PS_URL" if is_prestashop(config) else "WC_URL"
        host = urlparse(str(config.get(url_key) or "")).netloc or "فروشگاه"
        dialog = ProductSyncPreviewDialog(parent, previews, host)
        dialog.exec_()
        return dialog._confirmed


def confirm_products_sync_send(parent, config: dict | None = None) -> bool:
    previews = build_products_sync_preview(config)
    if not previews:
        return False
    return ProductSyncPreviewDialog.ask(parent, previews, config)
