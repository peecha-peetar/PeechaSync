""" فقط یک instance برنامه """

import io
import os
import sys
import time
import logging
from pathlib import Path

LAUNCHER_MODULE = "sync_app.core.peecha_launcher"


def _psutil():
    import psutil

    return psutil


class SafeConsoleHandler(logging.StreamHandler):
    """ کنسول encoding بد """

    def __init__(self, stream=None):
        stream = stream or sys.stderr
        if hasattr(stream, "buffer") and not isinstance(stream, io.TextIOBase):
            stream = io.TextIOWrapper(stream.buffer, encoding=getattr(stream, "encoding", None) or "utf-8", errors="replace")
        self._fallback_encoding = getattr(stream, "encoding", None) or "utf-8"
        super().__init__(stream)

    def emit(self, record):
        try:
            message = self.format(record)
            try:
                self.stream.write(message + self.terminator)
            except UnicodeEncodeError:
                safe_message = message.encode(self._fallback_encoding, errors="replace").decode(self._fallback_encoding, errors="replace")
                self.stream.write(safe_message + self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)


def _single_instance_log_path():
    """لاگ در AppData — نه Program Files (بدون دسترسی نوشتن)."""
    try:
        from sync_app.core.sync_utils import app_path

        return app_path("single_instance.log")
    except Exception:
        base = os.getenv("LOCALAPPDATA") or os.path.expanduser("~")
        folder = Path(base) / "PeechaSync" / "default"
        folder.mkdir(parents=True, exist_ok=True)
        return str(folder / "single_instance.log")


_log_handlers = [SafeConsoleHandler()]
try:
    _log_handlers.insert(0, logging.FileHandler(_single_instance_log_path(), encoding="utf-8"))
except OSError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s',
    handlers=_log_handlers,
)
logger = logging.getLogger(__name__)


class SingleInstanceManager:
    """ یک نسخه برنامه """

    def __init__(self, app_name="peecha_launcher"):
        self.app_name = app_name
        self.lock_file = self._get_lock_file()
        self.current_pid = os.getpid()
        self._related_pids = None

    def _get_lock_file(self):
        """ مسیر lock file """
        temp_dir = Path(os.getenv("TEMP", "/tmp"))
        return temp_dir / f"{self.app_name}.lock"

    def _related_process_pids(self):
        if self._related_pids is not None:
            return self._related_pids

        psutil = _psutil()
        related = {self.current_pid}
        try:
            me = psutil.Process(self.current_pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            self._related_pids = related
            return related

        parent = me.parent()
        while parent is not None:
            related.add(parent.pid)
            try:
                parent = parent.parent()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break

        try:
            for child in me.children(recursive=True):
                related.add(child.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        self._related_pids = related
        return related

    def _cmdline_is_launcher(self, cmdline):
        joined = " ".join(cmdline or []).lower().replace("\\", "/")
        return LAUNCHER_MODULE.lower() in joined

    def _pid_is_launcher(self, pid: int) -> bool:
        psutil = _psutil()
        try:
            proc = psutil.Process(pid)
            return self._cmdline_is_launcher(proc.cmdline())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    def _read_lock_pid(self):
        try:
            raw = self.lock_file.read_text(encoding="utf-8").strip()
            return int(raw)
        except (OSError, ValueError):
            return None

    def _write_lock_pid(self) -> None:
        try:
            self.lock_file.write_text(str(self.current_pid), encoding="utf-8")
        except OSError as exc:
            logger.debug("Could not write lock file: %s", exc)

    def _remove_lock_file(self) -> None:
        try:
            if self.lock_file.exists():
                self.lock_file.unlink()
        except OSError:
            pass

    def _pid_is_alive(self, pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            try:
                import ctypes

                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                handle = ctypes.windll.kernel32.OpenProcess(
                    PROCESS_QUERY_LIMITED_INFORMATION, False, pid
                )
                if not handle:
                    return False
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            except Exception:
                pass
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _fast_single_instance_check(self) -> bool:
        """بدون اسکن همه processها — مسیر معمول بعد از خروج تمیز."""
        if not self.lock_file.exists():
            self._write_lock_pid()
            logger.info("No lock file - starting fresh")
            return True

        lock_pid = self._read_lock_pid()
        if lock_pid is None:
            self._remove_lock_file()
            self._write_lock_pid()
            logger.info("Invalid lock file - starting fresh")
            return True

        if lock_pid in self._related_process_pids():
            self._write_lock_pid()
            return True

        if not self._pid_is_alive(lock_pid):
            self._write_lock_pid()
            logger.info("Stale lock PID %s - starting fresh", lock_pid)
            return True

        if not self._pid_is_launcher(lock_pid):
            self._write_lock_pid()
            logger.info("Lock PID %s is not PeechaSync - starting fresh", lock_pid)
            return True

        return False

    def _get_running_instances(self):
        """ instanceهای در حال اجرا (غیر از این process tree) """
        psutil = _psutil()
        instances = []
        related = self._related_process_pids()

        try:
            for proc in psutil.process_iter(["pid", "cmdline"]):
                try:
                    if proc.pid in related:
                        continue
                    cmdline = proc.info.get("cmdline") or []
                    if not self._cmdline_is_launcher(cmdline):
                        continue
                    instances.append(proc)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception:
            pass

        return instances

    def ensure_single_instance(self):
        """ instance قدیمی بود ببند """
        if self._fast_single_instance_check():
            return True

        lock_pid = self._read_lock_pid()
        old_instances = []
        if lock_pid and lock_pid not in self._related_process_pids():
            psutil = _psutil()
            try:
                old_instances.append(psutil.Process(lock_pid))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        if not old_instances:
            old_instances = self._get_running_instances()

        if old_instances:
            logger.info(f"Found {len(old_instances)} running instances")
            self._handle_existing_instances(old_instances)
        else:
            logger.info("No old instances found - starting fresh")

        self._write_lock_pid()
        return True

    def _handle_existing_instances(self, instances):
        """ بستن instanceهای قبلی """
        psutil = _psutil()
        logger.info(f"Closing {len(instances)} old instances...")

        for proc in instances:
            try:
                if proc.pid in self._related_process_pids():
                    continue
                logger.info(f"Terminating process {proc.pid} gracefully...")
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                    logger.info(f"Process {proc.pid} closed successfully")
                except psutil.TimeoutExpired:
                    logger.warning(f"Process {proc.pid} did not respond - force killing...")
                    try:
                        proc.kill()
                        proc.wait(timeout=3)
                        logger.info(f"Process {proc.pid} force-killed")
                    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                        logger.warning(f"Could not force-kill process {proc.pid}: {e}")
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    logger.warning(f"Could not wait for process {proc.pid}: {e}")
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                logger.warning(f"Could not close process {getattr(proc, 'pid', '?')}: {e}")
            except Exception as e:
                logger.warning(f"Unexpected error closing process {getattr(proc, 'pid', '?')}: {e}")

        time.sleep(0.5)
        remaining = self._get_running_instances()
        if remaining:
            logger.warning(
                f"{len(remaining)} PeechaSync instance(s) still running (PIDs: "
                f"{', '.join(str(p.pid) for p in remaining)})"
            )
        else:
            logger.info("Old instances closed - starting new instance...")

    def cleanup(self):
        """ lock file پاک """
        try:
            lock_pid = self._read_lock_pid()
            if lock_pid is None or lock_pid == self.current_pid:
                self._remove_lock_file()
                logger.debug("Lock file removed")
        except Exception as e:
            logger.warning(f"Could not remove lock file: {e}")
