"""
تب مشاور پیچا — دستیار هوشمند فروشگاه: جمع‌بندی سلامت فنی سایت +
میانگین امتیاز سئو + میانگین آمادگی محصولات، در یک لیست اولویت‌بندی‌شده
از مشکلات با راهنمای رفع (لینک به تب مربوطه).
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QAbstractItemView,
)
from PyQt5.QtCore import Qt

from sync_app.core.secure_config_loader import load_secure_config
from sync_app.core.threading_helper import run_in_thread
from sync_app.core.wc_sync_helper import build_wcapi, apply_network_overrides, wc_call
from sync_app.core.sql_connection_helper import open_sql_connection
from sync_app.core.category_resolver import load_category_map
from sync_app.core.category_rules import resolve_product_categories
from sync_app.core.article_price import resolve_article_price
from sync_app.core.product_woo_map_helper import load_product_woo_map
from sync_app.core.media_center import product_readiness, is_valid_image_data, is_valid_image_file
from sync_app.core.seo_helper import analyze_product_seo_live
from sync_app.core.site_health_helper import run_all_checks, overall_health_score

FIX_HINTS = {
    "اتصال SQL": "تب «⚙️ تنظیمات» → بخش SQL",
    "API ووکامرس": "تب «⚙️ تنظیمات» → بخش ووکامرس",
    "SSL": "سمت هاست/دامنه‌ی سایت — نصب یا تمدید گواهی SSL",
    "سرعت سایت": "بهینه‌سازی هاست/کش سایت (خارج از کنترل پیچا)",
    "سئو": "تب «🩺 سئو و سلامت سایت»",
    "آمادگی محصول": "تب «🖼️ مرکز رسانه» → بخش آمادگی انتشار",
}


class PeechaAdvisorTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        title = QLabel("🧭 مشاور پیچا — سلامت کلی فروشگاه")
        title.setProperty("role", "section-title")
        title.setAlignment(Qt.AlignCenter)
        outer.addWidget(title)

        subtitle = QLabel("جمع‌بندی سلامت فنی سایت + سئو + آمادگی محصولات، با اولویت‌بندی مشکلات")
        subtitle.setProperty("role", "caption")
        subtitle.setAlignment(Qt.AlignCenter)
        outer.addWidget(subtitle)

        self.run_btn = QPushButton("🔍 بررسی کامل سلامت فروشگاه")
        self.run_btn.setMinimumHeight(42)
        self.run_btn.clicked.connect(self._run_check)
        outer.addWidget(self.run_btn)

        self.score_label = QLabel("برای شروع، دکمه‌ی بالا را بزنید.")
        self.score_label.setAlignment(Qt.AlignCenter)
        self.score_label.setStyleSheet("font-size:20px; font-weight:800; padding:8px;")
        outer.addWidget(self.score_label)

        self.sub_scores_label = QLabel("")
        self.sub_scores_label.setAlignment(Qt.AlignCenter)
        self.sub_scores_label.setStyleSheet("color:#475569;")
        outer.addWidget(self.sub_scores_label)

        outer.addWidget(QLabel("مشکلات (اولویت‌بندی‌شده — بحرانی‌ها اول):"))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["اولویت", "مورد", "توضیح", "راهنمای رفع"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        outer.addWidget(self.table)

    def _run_check(self):
        config = load_secure_config(None) or {}
        selected_groups = [str(g).strip() for g in config.get("SELECTED_SUB_GROUPS", []) if str(g).strip()]

        self.run_btn.setEnabled(False)
        self.run_btn.setText("⏳ در حال بررسی کامل (چند لحظه طول می‌کشد)...")
        self.score_label.setText("")
        self.sub_scores_label.setText("")

        def _worker():
            site_results = run_all_checks(config)
            site_score = overall_health_score(site_results)

            seo_avg, seo_weak = self._seo_summary(config)
            readiness_avg, readiness_weak = self._readiness_summary(config, selected_groups)

            issues = []
            severity_order = {"critical": 0, "warning": 1, "info": 2}
            for r in sorted(site_results, key=lambda r: severity_order.get(r.severity, 1)):
                if not r.ok:
                    issues.append((r.severity, r.name, r.detail, FIX_HINTS.get(r.name, "-")))

            if seo_weak:
                issues.append((
                    "warning", "سئو", f"{seo_weak} محصول امتیاز سئوی زیر ۶۰ دارند.", FIX_HINTS["سئو"],
                ))
            if readiness_weak:
                issues.append((
                    "warning", "آمادگی محصول",
                    f"{readiness_weak} محصول آماده‌ی انتشار نیستند (عکس/قیمت/دسته/توضیحات ناقص).",
                    FIX_HINTS["آمادگی محصول"],
                ))

            overall = round((site_score + (seo_avg or 0) + (readiness_avg or 0)) / 3)
            return {
                "overall": overall,
                "site_score": site_score,
                "seo_avg": seo_avg,
                "readiness_avg": readiness_avg,
                "issues": issues,
            }

        def _done(result):
            self.run_btn.setEnabled(True)
            self.run_btn.setText("🔍 بررسی کامل سلامت فروشگاه")
            self._show_result(result)

        def _fail(msg):
            self.run_btn.setEnabled(True)
            self.run_btn.setText("🔍 بررسی کامل سلامت فروشگاه")
            QMessageBox.critical(self, "خطا", f"بررسی ناموفق بود:\n{msg}")

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    def _seo_summary(self, config):
        """میانگین امتیاز سئو و تعداد محصولات ضعیف — از روی داده‌ی زنده‌ی ووکامرس."""
        if not config.get("WC_URL"):
            return None, 0
        try:
            apply_network_overrides(config)
            wcapi = build_wcapi(config)
            scores = []
            page = 1
            while True:
                def _fetch(p=page):
                    resp = wcapi.get(
                        "products",
                        params={
                            "per_page": 50, "page": p, "status": "publish",
                            "_fields": "id,name,short_description,description,images,categories,meta_data",
                        },
                    )
                    data = resp.json()
                    return data if isinstance(data, list) else []

                batch = wc_call(wcapi, f"دریافت محصولات صفحه {page}", _fetch, retries=1)
                if not batch:
                    break
                for item in batch:
                    if isinstance(item, dict) and item.get("id"):
                        bundle = analyze_product_seo_live(item)
                        scores.append(bundle["current_score"])
                if len(batch) < 50:
                    break
                page += 1
                if page > 20:  # سقف ایمنی برای فروشگاه‌های خیلی بزرگ
                    break

            if not scores:
                return None, 0
            avg = round(sum(scores) / len(scores))
            weak = sum(1 for s in scores if s < 60)
            return avg, weak
        except Exception:
            return None, 0

    def _readiness_summary(self, config, selected_groups):
        """میانگین امتیاز آمادگی و تعداد محصولات ناقص — از روی SQL محلی."""
        if not selected_groups:
            return None, 0
        try:
            product_map = load_product_woo_map()
            cat_map = load_category_map()
            price_col = config.get("PRICE_LIST_COLUMN", "Sel_Price")

            conn, _, _ = open_sql_connection(config, timeout=8)
            cursor = conn.cursor()
            like_conditions = " OR ".join(["A_Code LIKE ?" for _ in selected_groups])
            cursor.execute(
                f"""SELECT A_Code, A_Name, Sel_Price, Sel_Price2, Sel_Price3, Sel_Price4, Sel_Price5,
                           Exist, Picture, PicturePath, Attribute
                    FROM Article WHERE {like_conditions}""",
                [f"{g}%" for g in selected_groups],
            )
            rows = cursor.fetchall()
            conn.close()

            scores = []
            for row in rows:
                sku = str(row[0]).strip()
                picture_blob = row[8]
                picture_path_raw = str(row[9] or "").strip()
                has_blob_image = is_valid_image_data(bytes(picture_blob)) if picture_blob else False
                has_path_image = is_valid_image_file(picture_path_raw) if picture_path_raw else False
                description = str(row[10] or "").strip() if len(row) > 10 else ""
                categories = resolve_product_categories(sku, cat_map, {})
                product = {
                    "has_image": has_blob_image or has_path_image,
                    "has_category": bool(categories),
                    "price": resolve_article_price(row, price_col, price_start_index=2),
                    "stock": int(row[7] or 0),
                    "description": description,
                    "synced_to_woo": sku in product_map,
                }
                scores.append(product_readiness(product).score)

            if not scores:
                return None, 0
            avg = round(sum(scores) / len(scores))
            weak = sum(1 for s in scores if s < 70)
            return avg, weak
        except Exception:
            return None, 0

    def _show_result(self, result):
        overall = result["overall"]
        color = "#166534" if overall >= 80 else ("#b45309" if overall >= 60 else "#b91c1c")
        self.score_label.setText(f"امتیاز سلامت کلی فروشگاه: {overall}/100")
        self.score_label.setStyleSheet(f"font-size:20px; font-weight:800; padding:8px; color:{color};")

        parts = [f"سلامت فنی سایت: {result['site_score']}"]
        if result["seo_avg"] is not None:
            parts.append(f"میانگین سئو: {result['seo_avg']}")
        if result["readiness_avg"] is not None:
            parts.append(f"میانگین آمادگی محصول: {result['readiness_avg']}")
        self.sub_scores_label.setText(" | ".join(parts))

        self.table.setRowCount(0)
        severity_icon = {"critical": "🔴 بحرانی", "warning": "🟡 هشدار", "info": "🔵 اطلاع"}
        for severity, name, detail, hint in result["issues"]:
            row = self.table.rowCount()
            self.table.insertRow(row)
            sev_item = QTableWidgetItem(severity_icon.get(severity, severity))
            if severity == "critical":
                sev_item.setForeground(Qt.red)
            self.table.setItem(row, 0, sev_item)
            self.table.setItem(row, 1, QTableWidgetItem(name))
            self.table.setItem(row, 2, QTableWidgetItem(detail))
            self.table.setItem(row, 3, QTableWidgetItem(hint))

        if not result["issues"]:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem("✅"))
            self.table.setItem(row, 1, QTableWidgetItem("همه‌چیز مرتب است"))
            self.table.setItem(row, 2, QTableWidgetItem("هیچ مشکل قابل‌توجهی پیدا نشد."))
            self.table.setItem(row, 3, QTableWidgetItem("-"))
