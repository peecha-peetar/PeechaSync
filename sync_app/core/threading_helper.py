"""
Threading Helper - برای جلوگیری از UI hang هنگام درخواست‌های طولانی
"""

import threading

from PyQt5.QtCore import QObject, Qt, pyqtSignal


class ThreadWorker(QObject):
    """Worker برای اجرای کار در thread جداگانه"""
    finished = pyqtSignal()
    error = pyqtSignal(str)
    result = pyqtSignal(object)

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            result = self.func(*self.args, **self.kwargs)
            self.result.emit(result)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()


def run_in_thread(func, *args, on_complete=None, on_error=None, **kwargs):
    """
    اجرای تابع در thread جداگانه (بدون blocking UI).
    callbackها با QueuedConnection روی thread اصلی UI اجرا می‌شوند.
    """
    worker = ThreadWorker(func, *args, **kwargs)
    thread = threading.Thread(target=worker.run, daemon=True)
    # نگه‌داشتن worker تا پایان thread — وگرنه GC باعث قطع signal می‌شود
    thread._peecha_worker = worker

    if on_complete:
        worker.result.connect(on_complete, Qt.QueuedConnection)
    if on_error:
        worker.error.connect(on_error, Qt.QueuedConnection)

    thread.start()
    return thread
