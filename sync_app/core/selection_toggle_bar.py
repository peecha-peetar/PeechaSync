"""نوار فشرده انتخاب همه / هیچ — کنار جستجو."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QPushButton, QSizePolicy, QWidget


class SelectionToggleBar(QFrame):
  """دکمه‌های کوچک همه/هیچ با استایل pill."""

  def __init__(self, parent=None, *, on_select_all=None, on_select_none=None):
    super().__init__(parent)
    self.setObjectName("selectionToggleBar")
    self.setLayoutDirection(Qt.RightToLeft)
    self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    self.setStyleSheet(
      "#selectionToggleBar {"
      "  background: #f1f5f9;"
      "  border: 1px solid #cbd5e1;"
      "  border-radius: 14px;"
      "  padding: 2px;"
      "}"
      "#selectionToggleBar QPushButton {"
      "  border: none;"
      "  background: transparent;"
      "  color: #334155;"
      "  font-size: 11px;"
      "  font-weight: 600;"
      "  padding: 2px 10px;"
      "  min-height: 24px;"
      "  max-height: 26px;"
      "  border-radius: 12px;"
      "}"
      "#selectionToggleBar QPushButton:hover {"
      "  background: #e2e8f0;"
      "}"
      "#selectionToggleBar QPushButton:pressed {"
      "  background: #cbd5e1;"
      "}"
      "#selectionToggleBar QPushButton:disabled {"
      "  color: #94a3b8;"
      "}"
    )

    row = QHBoxLayout(self)
    row.setContentsMargins(2, 2, 2, 2)
    row.setSpacing(2)

    self.all_btn = QPushButton("همه")
    self.all_btn.setCursor(Qt.PointingHandCursor)
    self.all_btn.setToolTip("انتخاب همه موارد قابل‌مشاهده")
    if on_select_all:
      self.all_btn.clicked.connect(on_select_all)

    self.none_btn = QPushButton("هیچ")
    self.none_btn.setCursor(Qt.PointingHandCursor)
    self.none_btn.setToolTip("لغو انتخاب همه")
    if on_select_none:
      self.none_btn.clicked.connect(on_select_none)

    row.addWidget(self.all_btn)
    row.addWidget(self.none_btn)

  def set_busy(self, busy: bool) -> None:
    self.all_btn.setEnabled(not busy)
    self.none_btn.setEnabled(not busy)


def attach_selection_toggle(search_row: QHBoxLayout, parent: QWidget, *, on_select_all, on_select_none):
  """افزودن toggle به انتهای ردیف جستجو."""
  bar = SelectionToggleBar(parent, on_select_all=on_select_all, on_select_none=on_select_none)
  search_row.addWidget(bar, 0, Qt.AlignVCenter)
  return bar
