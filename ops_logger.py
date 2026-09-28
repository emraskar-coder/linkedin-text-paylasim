"""
ops_logger.py — Merkezi Notion Operations Logger
==================================================
Blog_Yazici NotionLogger pattern'ından türetilmiş, tüm Antigravity
projeleri için ortak operational log modülü.

Özellikler:
  - Asenkron kuyruk (threading.Queue) ile ana pipeline'ı bloklamaz
  - Hem stdout hem Notion'a aynı anda log basar
  - Level (INFO/WARNING/ERROR/SUCCESS), Component, Project, Title, Message, Details, Zaman
  - NOTION_SOCIAL_TOKEN veya NOTION_API_TOKEN ile çalışır
  - NOTION_DB_OPS_LOG env variable'ı ile DB ID alır
"""

import os
import sys
import logging
import requests
import traceback
import threading
import queue
import time
from datetime import datetime, timezone

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ── Token & DB ID Çözümleme ──────────────────────────────────────────────
def _get_env(key, default=""):
    """Environment variable oku: önce os.environ, sonra master.env fallback."""
    val = os.environ.get(key)
    if val:
        return val
    # Lokal fallback: env_loader varsa kullan
    try:
        from env_loader import get_env as _loader_get
        return _loader_get(key, default)
    except ImportError:
        pass
    return default


NOTION_TOKEN = _get_env("NOTION_SOCIAL_TOKEN") or _get_env("NOTION_API_TOKEN")
NOTION_DB_OPS_LOG = _get_env("NOTION_DB_OPS_LOG", "0ff1ce00-0000-4000-8000-2e9d48d4f889")


class _NotionLogWorker(threading.Thread):
    """Background worker: kuyruktan log alır, Notion API'ye yazar."""

    def __init__(self, log_queue, token, db_id):
        super().__init__(daemon=True)
        self.log_queue = log_queue
        self.token = token
        self.db_id = db_id
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }

    def run(self):
        while True:
            try:
                log_data = self.log_queue.get()
                if log_data is None:  # Sentinel value — durdurma sinyali
                    break
                self._send_to_notion(log_data)
                self.log_queue.task_done()
            except Exception as e:
                print(f"[OpsLogger Error] Notion'a log gönderilemedi: {e}", file=sys.stderr)
                try:
                    self.log_queue.task_done()
                except ValueError:
                    pass

    def _send_to_notion(self, log_data):
        title = (log_data.get("title") or "")[:250]
        message = (log_data.get("message") or "")[:1990]
        level = log_data.get("level", "INFO")
        component = log_data.get("component", "Pipeline")
        project = log_data.get("project", "Unknown")
        details = (log_data.get("details") or "")[:1990]

        payload = {
            "parent": {"database_id": self.db_id},
            "properties": {
                "Title": {"title": [{"text": {"content": title}}]},
                "Message": {"rich_text": [{"text": {"content": message}}]},
                "Zaman": {"date": {"start": datetime.now(timezone.utc).isoformat()}},
                "Level": {"select": {"name": level}},
                "Component": {"select": {"name": component}},
                "Project": {"select": {"name": project}},
            },
        }

        if details:
            payload["properties"]["Details"] = {
                "rich_text": [{"text": {"content": details}}]
            }

        last_err = None
        for attempt in range(3):
            try:
                response = requests.post(
                    "https://api.notion.com/v1/pages",
                    headers=self.headers,
                    json=payload,
                    timeout=15,
                )
                response.raise_for_status()
                return
            except requests.exceptions.RequestException as e:
                last_err = e
                if attempt < 2:
                    time.sleep(2 ** attempt)  # 1sn, 2sn backoff
        raise last_err


class OpsLogger:
    """
    Unified logger: stdout + Notion Operations Log.

    Kullanım:
        from ops_logger import get_ops_logger
        ops = get_ops_logger("LinkedIn_Text_Paylasim", "Pipeline")
        ops.info("Workflow başladı", "AI Haberleri pipeline'ı")
        ops.error("Notion yazım hatası", exception=e)
    """

    def __init__(self, project_name: str, component: str = "Pipeline"):
        self.project_name = project_name
        self.component = component
        self.token = NOTION_TOKEN
        self.db_id = NOTION_DB_OPS_LOG

        self._queue = queue.Queue()
        self._worker = None

        if self.token and self.db_id:
            self._worker = _NotionLogWorker(self._queue, self.token, self.db_id)
            self._worker.start()
        else:
            print(
                f"[OpsLogger] ⚠️ NOTION token/DB ID eksik — sadece console'a log basılacak. "
                f"(token={'var' if self.token else 'YOK'}, db={'var' if self.db_id else 'YOK'})"
            )

        # Standart Python logger
        self._std = logging.getLogger(f"OpsLog_{project_name}_{component}")
        if not self._std.handlers:
            handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter(
                "%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            handler.setFormatter(formatter)
            self._std.addHandler(handler)
            self._std.setLevel(logging.INFO)
            # Watchdog FP fix: root logger'a propagate etme — basicConfig stderr handler'ına çift düşmesin
            self._std.propagate = False

    def _enqueue(self, level, title, message="", details=""):
        if self._worker:
            self._queue.put({
                "level": level,
                "title": title,
                "message": message,
                "component": self.component,
                "project": self.project_name,
                "details": details,
            })

    def info(self, title, message=""):
        self._std.info(f"{title}: {message}" if message else title)
        self._enqueue("INFO", title, message)

    def success(self, title, message=""):
        self._std.info(f"✅ {title}: {message}" if message else f"✅ {title}")
        self._enqueue("SUCCESS", title, message)

    def warning(self, title, message="", details=""):
        self._std.warning(f"⚠️ {title}: {message}" if message else f"⚠️ {title}")
        self._enqueue("WARNING", title, message, details=details)

    def error(self, title, exception=None, message=""):
        details = ""
        if exception:
            if isinstance(exception, BaseException):
                details = "".join(
                    traceback.format_exception(type(exception), exception, exception.__traceback__)
                )
            else:
                message = f"{exception} {message}".strip()
        self._std.error(f"❌ {title}: {message}\n{details}" if details else f"❌ {title}: {message}")
        self._enqueue("ERROR", title, message, details=details)

    def wait_for_logs(self):
        """Kuyruktaki tüm logların Notion'a yazılmasını bekle."""
        if self._worker:
            self._queue.join()


# ── Factory Fonksiyonu ────────────────────────────────────────────────────

_instances: dict = {}


def get_ops_logger(project_name: str, component: str = "Pipeline") -> OpsLogger:
    """Proje + component bazlı tekil OpsLogger instance'ı döner."""
    key = f"{project_name}_{component}"
    if key not in _instances:
        _instances[key] = OpsLogger(project_name, component)
    return _instances[key]


def wait_all_loggers():
    """Tüm OpsLogger instance'larının kuyruklarını boşaltır.
    CronJob container'ları kapanmadan önce çağrılmalıdır.
    Aksi halde core modüllerdeki (Publisher, ImageGen vb.) loglar kaybolur.
    """
    for key, logger in _instances.items():
        logger.wait_for_logs()

