from PyQt5.QtCore import Qt, QRect, QEvent
from PyQt5.QtGui import QPalette
from PyQt5.QtWidgets import (
    QStyledItemDelegate,
    QListWidgetItem,
    QStyle,
    QStyleOptionButton,
    QStyleOptionViewItem,
)


class RightAlignedItemDelegate(QStyledItemDelegate):
    """ راست‌چین واقعی توی Qt """

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.displayAlignment = Qt.AlignRight | Qt.AlignVCenter

    def paint(self, painter, option, index):
        view_option = QStyleOptionViewItem(option)
        self.initStyleOption(view_option, index)
        style = view_option.widget.style() if view_option.widget else self.parent().style()

        # پس‌زمینه select/hover
        panel_option = QStyleOptionViewItem(view_option)
        panel_option.text = ""
        style.drawPrimitive(QStyle.PE_PanelItemViewItem, panel_option, painter, view_option.widget)

        # متن راست‌چین
        text_rect = view_option.rect.adjusted(8, 0, -8, 0)
        text_role = (
            QPalette.HighlightedText
            if view_option.state & QStyle.State_Selected
            else QPalette.Text
        )
        style.drawItemText(
            painter,
            text_rect,
            Qt.AlignRight | Qt.AlignVCenter,
            view_option.palette,
            True,
            view_option.text,
            text_role,
        )


class RightAlignedCheckableItemDelegate(QStyledItemDelegate):
    """ چک‌باکس RTL """

    def _check_rect(self, option):
        style = option.widget.style() if option.widget else self.parent().style()
        indicator_width = style.pixelMetric(QStyle.PM_IndicatorWidth, None, option.widget)
        indicator_height = style.pixelMetric(QStyle.PM_IndicatorHeight, None, option.widget)
        margin = 10
        return QRect(
            option.rect.right() - indicator_width - margin,
            option.rect.center().y() - (indicator_height // 2),
            indicator_width,
            indicator_height,
        )

    def paint(self, painter, option, index):
        view_option = QStyleOptionViewItem(option)
        self.initStyleOption(view_option, index)
        style = view_option.widget.style() if view_option.widget else self.parent().style()

        panel_option = QStyleOptionViewItem(view_option)
        panel_option.text = ""
        style.drawPrimitive(QStyle.PE_PanelItemViewItem, panel_option, painter, view_option.widget)

        check_state = index.data(Qt.CheckStateRole)
        is_checkable = check_state is not None
        text_rect = view_option.rect.adjusted(10, 0, -10, 0)

        if is_checkable:
            check_rect = self._check_rect(view_option)
            text_rect = QRect(
                view_option.rect.left() + 10,
                view_option.rect.top(),
                max(0, check_rect.left() - view_option.rect.left() - 20),
                view_option.rect.height(),
            )

            indicator_option = QStyleOptionButton()
            indicator_option.rect = check_rect
            indicator_option.state = QStyle.State_Enabled
            if view_option.state & QStyle.State_MouseOver:
                indicator_option.state |= QStyle.State_MouseOver
            if check_state == Qt.Checked:
                indicator_option.state |= QStyle.State_On
            else:
                indicator_option.state |= QStyle.State_Off
            style.drawPrimitive(QStyle.PE_IndicatorItemViewItemCheck, indicator_option, painter, view_option.widget)

        text_role = QPalette.HighlightedText if view_option.state & QStyle.State_Selected else QPalette.Text
        style.drawItemText(
            painter,
            text_rect,
            Qt.AlignRight | Qt.AlignVCenter,
            view_option.palette,
            True,
            view_option.text,
            text_role,
        )

    def editorEvent(self, event, model, option, index):
        check_state = index.data(Qt.CheckStateRole)
        if check_state is None:
            return super().editorEvent(event, model, option, index)

        if event.type() == QEvent.MouseButtonRelease and self._check_rect(option).contains(event.pos()):
            new_state = Qt.Unchecked if check_state == Qt.Checked else Qt.Checked
            return model.setData(index, new_state, Qt.CheckStateRole)

        if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Space, Qt.Key_Select):
            new_state = Qt.Unchecked if check_state == Qt.Checked else Qt.Checked
            return model.setData(index, new_state, Qt.CheckStateRole)

        return super().editorEvent(event, model, option, index)


def make_rtl_item(text: str) -> QListWidgetItem:
    """ QListWidgetItem راست‌چین """
    item = QListWidgetItem(str(text or ""))
    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return item
