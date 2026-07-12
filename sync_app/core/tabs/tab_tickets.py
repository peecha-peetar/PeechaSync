from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QTextEdit,
    QLineEdit,
    QComboBox,
    QFrame,
)


class TicketsTab(QWidget):
    """ تب تیکت دمو """

    def __init__(self):
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self._build_ui()
        self._seed_demo_data()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        header = QFrame()
        header.setObjectName("ticketHeaderCard")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 10, 12, 10)
        header_layout.setSpacing(8)

        title_col = QVBoxLayout()
        self.title_label = QLabel("مرکز تیکت پشتیبانی")
        self.title_label.setStyleSheet("font-weight: 800; font-size: 15px;")
        self.subtitle_label = QLabel("نسخه دمو - فعلا به سرویس بیرونی متصل نیست")
        self.subtitle_label.setStyleSheet("color: #64748b; font-size: 11px;")
        title_col.addWidget(self.title_label)
        title_col.addWidget(self.subtitle_label)
        header_layout.addLayout(title_col)
        header_layout.addStretch()

        self.new_ticket_btn = QPushButton("+ تیکت جدید")
        self.new_ticket_btn.setMinimumHeight(36)
        self.new_ticket_btn.clicked.connect(self._create_demo_ticket)
        header_layout.addWidget(self.new_ticket_btn)

        root.addWidget(header)

        body = QHBoxLayout()
        body.setSpacing(10)

        # ستون لیست تیکت‌ها
        left_col = QVBoxLayout()
        left_col.setSpacing(8)

        self.ticket_list_label = QLabel("تیکت‌های اخیر")
        self.ticket_list_label.setStyleSheet("font-weight: 700;")
        left_col.addWidget(self.ticket_list_label)

        self.ticket_list = QListWidget()
        self.ticket_list.setMinimumWidth(320)
        self.ticket_list.currentItemChanged.connect(self._on_ticket_selected)
        left_col.addWidget(self.ticket_list, 1)

        body.addLayout(left_col, 3)

        # ستون مکالمه + فرم ارسال
        right_col = QVBoxLayout()
        right_col.setSpacing(8)

        self.chat_title = QLabel("گفتگو")
        self.chat_title.setStyleSheet("font-weight: 700;")
        right_col.addWidget(self.chat_title)

        self.chat_view = QTextEdit()
        self.chat_view.setReadOnly(True)
        self.chat_view.setObjectName("ticketChatView")
        right_col.addWidget(self.chat_view, 1)

        form_card = QFrame()
        form_card.setObjectName("ticketFormCard")
        form_layout = QVBoxLayout(form_card)
        form_layout.setContentsMargins(10, 10, 10, 10)
        form_layout.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self.subject_input = QLineEdit()
        self.subject_input.setPlaceholderText("عنوان تیکت (دمو)...")
        self.subject_input.setMinimumHeight(36)
        top_row.addWidget(self.subject_input, 2)

        self.priority_combo = QComboBox()
        self.priority_combo.addItems(["کم", "متوسط", "بالا", "فوری"])
        self.priority_combo.setCurrentIndex(1)
        self.priority_combo.setMinimumHeight(36)
        top_row.addWidget(self.priority_combo, 1)

        form_layout.addLayout(top_row)

        self.message_input = QTextEdit()
        self.message_input.setPlaceholderText("متن پیام برای پشتیبانی (دمو)...")
        self.message_input.setMaximumHeight(120)
        form_layout.addWidget(self.message_input)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        self.clear_btn = QPushButton("پاک‌کردن متن")
        self.clear_btn.setMinimumHeight(36)
        self.clear_btn.clicked.connect(self._clear_form)
        action_row.addWidget(self.clear_btn)

        self.send_btn = QPushButton("ارسال پیام دمو")
        self.send_btn.setMinimumHeight(36)
        self.send_btn.clicked.connect(self._send_demo_message)
        action_row.addWidget(self.send_btn)

        form_layout.addLayout(action_row)
        right_col.addWidget(form_card)

        body.addLayout(right_col, 5)
        root.addLayout(body, 1)

        self._ticket_messages = {}

    def _seed_demo_data(self):
        self._add_ticket(
            ticket_id="TCK-1001",
            title="مشکل در همگام‌سازی موجودی",
            status="باز",
            priority="بالا",
            messages=[
                "کاربر: در ارسال موجودی برخی محصولات خطا دارم.",
                "پشتیبان: لطفا لاگ تب متغیرها را ارسال کنید.",
            ],
        )
        self._add_ticket(
            ticket_id="TCK-1002",
            title="پرسش درباره تنظیمات ورود",
            status="در حال بررسی",
            priority="متوسط",
            messages=[
                "کاربر: چگونه ورود خودکار را فعال/غیرفعال کنم؟",
                "پشتیبان: از تب تنظیمات بخش اطلاعات ورود، گزینه نمایش لاگین را تغییر دهید.",
            ],
        )
        if self.ticket_list.count() > 0:
            self.ticket_list.setCurrentRow(0)

    def _add_ticket(self, ticket_id, title, status, priority, messages):
        text = f"{ticket_id} | {title} | {status} | اولویت: {priority}"
        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, ticket_id)
        self.ticket_list.addItem(item)
        self._ticket_messages[ticket_id] = list(messages)

    def _on_ticket_selected(self, current, _previous):
        if current is None:
            self.chat_view.clear()
            self.chat_title.setText("گفتگو")
            return

        ticket_id = current.data(Qt.UserRole)
        self.chat_title.setText(f"گفتگو - {ticket_id}")
        lines = self._ticket_messages.get(ticket_id, [])
        self.chat_view.setPlainText("\n".join(lines))
        self.chat_view.verticalScrollBar().setValue(self.chat_view.verticalScrollBar().maximum())

    def _create_demo_ticket(self):
        new_id = f"TCK-{1000 + self.ticket_list.count() + 1}"
        title = (self.subject_input.text() or "تیکت جدید دمو").strip()
        priority = self.priority_combo.currentText().strip()
        self._add_ticket(new_id, title, "باز", priority, ["سیستم: تیکت دمو ایجاد شد."])
        self.ticket_list.setCurrentRow(self.ticket_list.count() - 1)

    def _send_demo_message(self):
        current = self.ticket_list.currentItem()
        if current is None:
            self._create_demo_ticket()
            current = self.ticket_list.currentItem()
            if current is None:
                return

        text = (self.message_input.toPlainText() or "").strip()
        if not text:
            return

        ticket_id = current.data(Qt.UserRole)
        self._ticket_messages.setdefault(ticket_id, []).append(f"کاربر: {text}")
        self._ticket_messages[ticket_id].append("پشتیبان (دمو): پیام شما ثبت شد و به‌زودی بررسی می‌شود.")
        self._on_ticket_selected(current, None)
        self.message_input.clear()

    def _clear_form(self):
        self.subject_input.clear()
        self.message_input.clear()