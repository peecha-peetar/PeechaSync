"""هشدار تطبیق دستی — مقایسه نام و SKU قبل از ثبت نگاشت."""

from __future__ import annotations

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

from sync_app.core.app_theme import (
    build_reconciliation_link_warning_stylesheet,
    get_active_theme_palette,
)
from sync_app.core.reconciliation_service import (
    ENTITY_LABELS,
    LinkPairRisk,
    assess_commit_link_risks,
    assess_link_pair_risks,
)


class ReconciliationLinkWarningDialog(QDialog):
    """دیالوگ هشدار وقتی نام یا SKU طرفین تطبیق همخوان نیست."""

    def __init__(self, parent, entity: str, risks: list[LinkPairRisk]):
        super().__init__(parent)
        self.setObjectName("reconLinkWarningDialog")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowTitle("بررسی تطبیق — احتمال خطا")
        self.setModal(True)
        self.setMinimumWidth(560)
        self._confirmed = False
        _theme_name, palette = get_active_theme_palette()
        self.setStyleSheet(build_reconciliation_link_warning_stylesheet(palette))
        self._build_ui(entity, risks)

    def _build_ui(self, entity: str, risks: list[LinkPairRisk]):
        from sync_app.core.integrations.erp_provider import erp_provider_label

        erp_label = erp_provider_label(getattr(self.parent(), "config", None))
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 16)
        root.setSpacing(12)

        banner = QFrame()
        banner.setObjectName("reconLinkWarningBanner")
        banner_layout = QHBoxLayout(banner)
        banner_layout.setContentsMargins(14, 12, 14, 12)
        banner_layout.setSpacing(12)

        icon_badge = QLabel("⚠️")
        icon_badge.setObjectName("reconLinkWarningIconBadge")
        icon_badge.setAlignment(Qt.AlignCenter)
        banner_layout.addWidget(icon_badge)

        banner_text = QVBoxLayout()
        banner_text.setSpacing(4)

        title = QLabel("احتمال تطبیق اشتباه")
        title.setObjectName("reconLinkWarningTitle")
        title.setWordWrap(True)
        banner_text.addWidget(title)

        entity_label = ENTITY_LABELS.get(entity, entity)
        subtitle = QLabel(
            f"برای {len(risks)} جفت {entity_label}، نام یا شناسه طرفین با هم فرق دارد. "
            "اگر اشتباه تطبیق دهید، قیمت و موجودی روی کالای اشتباه در سایت اعمال می‌شود."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("reconLinkWarningSubtitle")
        banner_text.addWidget(subtitle)
        banner_layout.addLayout(banner_text, 1)
        root.addWidget(banner)

        scroll = QScrollArea()
        scroll.setObjectName("reconLinkWarningScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        list_host = QWidget()
        list_layout = QVBoxLayout(list_host)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(10)

        for index, risk in enumerate(risks, start=1):
            card = QFrame()
            card.setObjectName("reconLinkWarningCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)
            card_layout.setSpacing(6)

            head = QLabel(f"جفت {index}")
            head.setObjectName("reconLinkWarningCardHead")
            card_layout.addWidget(head)

            erp_line = QLabel(f"<b>نرم‌افزار:</b> {risk.erp_name or '—'}")
            erp_line.setWordWrap(True)
            erp_line.setTextFormat(Qt.RichText)
            erp_line.setObjectName("reconLinkWarningCardLine")
            card_layout.addWidget(erp_line)

            wc_line = QLabel(f"<b>فروشگاه:</b> {risk.wc_name or '—'}")
            wc_line.setWordWrap(True)
            wc_line.setTextFormat(Qt.RichText)
            wc_line.setObjectName("reconLinkWarningCardLine")
            card_layout.addWidget(wc_line)

            if risk.erp_sku or risk.wc_sku:
                sku_line = QLabel(
                    f"<b>SKU/کلید:</b> {erp_label} «{risk.erp_sku or '—'}» ↔ Woo «{risk.wc_sku or '—'}»"
                )
                sku_line.setWordWrap(True)
                sku_line.setTextFormat(Qt.RichText)
                sku_line.setObjectName("reconLinkWarningCardLine")
                card_layout.addWidget(sku_line)

            for warning in risk.warnings:
                warn = QLabel(f"• {warning}")
                warn.setWordWrap(True)
                warn.setObjectName("reconLinkWarningCardWarn")
                card_layout.addWidget(warn)

            list_layout.addWidget(card)

        list_layout.addStretch(1)
        scroll.setWidget(list_host)
        root.addWidget(scroll, 1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        cancel_btn = QPushButton("انصراف — تطبیق نکن")
        cancel_btn.setObjectName("reconLinkWarningCancel")
        cancel_btn.setMinimumHeight(40)
        cancel_btn.clicked.connect(self.reject)

        confirm_btn = QPushButton("می‌دانم — همین تطبیق را ثبت کن")
        confirm_btn.setObjectName("reconLinkWarningConfirm")
        confirm_btn.setMinimumHeight(40)
        confirm_btn.clicked.connect(self._accept_confirmed)

        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(confirm_btn)
        root.addLayout(btn_row)

    def _accept_confirmed(self):
        self._confirmed = True
        self.accept()

    @staticmethod
    def ask(parent, entity: str, risks: list[LinkPairRisk]) -> bool:
        dialog = ReconciliationLinkWarningDialog(parent, entity, risks)
        dialog.exec_()
        return dialog._confirmed


def confirm_reconciliation_link_risks(
    parent,
    entity: str,
    pairs: list[tuple],
    *,
    wc_rows=None,
) -> bool:
    """
    اگر جفت‌های پرخطر وجود داشته باشد از کاربر تأیید می‌گیرد.
    True = ادامه ثبت، False = انصراف.
    """
    config = getattr(parent, "config", None)
    if wc_rows is not None:
        risks = assess_commit_link_risks(entity, pairs, wc_rows, config)
    else:
        risks = [
            risk
            for erp, wc in pairs
            if (risk := assess_link_pair_risks(entity, erp, wc, config)).warnings
        ]
    if not risks:
        return True
    return ReconciliationLinkWarningDialog.ask(parent, entity, risks)
