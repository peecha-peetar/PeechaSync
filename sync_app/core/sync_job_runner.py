"""sync توی thread جدا."""

from PyQt5.QtCore import QObject, QThread, pyqtSignal

from sync_app.core.sync_cancel import begin_sync, request_cancel, SyncCancelled


class SyncJobWorker(QObject):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, job_callable):
        super().__init__()
        self._job_callable = job_callable

    def run(self):
        try:
            result = self._job_callable()
            self.finished.emit(result)
        except SyncCancelled as exc:
            self.error.emit(str(exc))
        except Exception as exc:
            self.error.emit(str(exc))


def run_background_sync(
    parent,
    job_callable,
    on_success=None,
    on_error=None,
    *,
    need_sql=True,
    need_wc=False,
    wait_on_disconnect=None,
):
    """
    اجرای تابع sync (مثلاً ordersync.main) در QThread.
    اگر thread قبلی هنوز فعال است False برمی‌گرداند.
    on_success(result) در صورت موفقیت — result خروجی job_callable است.
    wait_on_disconnect: منتظر اتصال به‌جای خطا (پیش‌فرض: وقتی need_wc=True)
    """
    from sync_app.core.connectivity_guard import ensure_connectivity

    if wait_on_disconnect is None:
        wait_on_disconnect = bool(need_wc)

    if not ensure_connectivity(
        parent,
        need_sql=need_sql,
        need_wc=need_wc,
        live=False,
        wait=wait_on_disconnect,
    ):
        return False

    begin_sync()
    thread_attr = "_peecha_bg_sync_thread"
    worker_attr = "_peecha_bg_sync_worker"

    old_thread = getattr(parent, thread_attr, None)
    if old_thread is not None and old_thread.isRunning():
        return False

    thread = QThread(parent)
    worker = SyncJobWorker(job_callable)
    worker.moveToThread(thread)

    def _cleanup():
        setattr(parent, thread_attr, None)
        setattr(parent, worker_attr, None)

    def _on_ok(result=None):
        if callable(on_success):
            try:
                on_success(result)
            except TypeError:
                on_success()
        _cleanup()

    def _on_err(msg):
        if callable(on_error):
            on_error(msg)
        _cleanup()

    thread.started.connect(worker.run)
    worker.finished.connect(_on_ok)
    worker.error.connect(_on_err)
    worker.finished.connect(thread.quit)
    worker.error.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    worker.error.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.finished.connect(_cleanup)

    setattr(parent, thread_attr, thread)
    setattr(parent, worker_attr, worker)
    thread.start()
    return True


def cancel_background_sync(parent) -> bool:
    """درخواست توقف job در حال اجرا روی parent."""
    thread_attr = "_peecha_bg_sync_thread"
    thread = getattr(parent, thread_attr, None)
    if thread is None or not thread.isRunning():
        return False
    request_cancel()
    try:
        thread.requestInterruption()
    except Exception:
        pass
    return True
