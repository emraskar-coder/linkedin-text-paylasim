"""LinkedIn draft logger — ortak Sosyal Medya DB (NOTION_X_DB_ID).

Eski mimari LinkedIn-only ayrı DB'ye yazıyordu. Yeni mimaride Twitter projesi
ile aynı DB kullanılıyor; mail-onay akışı ve dedup tek noktadan yönetiliyor.
Geriye uyumluluk için weekly-dedup hâlâ eski LinkedIn DB'sinde yapılabilir
(env'de NOTION_LINKEDIN_DB_ID set ise).

Race condition mitigation:
  Twitter ve LinkedIn cron'ları aynı NOTION_X_DB_ID'ye yazıyor. Aynı dakikada
  ikisi birden çalışırsa (Pzt/Per UTC 05:00 + 07:10 penceresi) klasik
  check-then-create race'i duplicate satır üretebiliyordu. Soft idempotency:
  her satırın Title'ı `[<source_slug>:<sha1(key)[:12]>] ...` deterministik
  prefix ile başlar; _create_page() önce bu prefix'i arar (varsa skip),
  sonra create eder, sonra tekrar arar (>1 ise yenisini archive eder).
  Bu mantık Twitter_Text_Paylasim/core/notion_logger.py ile birebir aynı —
  Railway monorepo rootDirectory yüzünden shared util mümkün değil; iki
  dosyayı manuel hizalı tutuyoruz.
"""

import hashlib
import re
from datetime import datetime, timezone, timedelta

import requests

from ops_logger import get_ops_logger
from config import settings

ops = get_ops_logger("LinkedIn_Text_Paylasim", "NotionLogger")

API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def make_dedup_prefix(source: str, key: str) -> str:
    """Deterministik title prefix: `[<source_slug>:<sha1(key)[:12]>] `.

    source: Notion'daki Source select adı (örn. "GitHub", "AI Use Case",
            "LinkedIn Haber").
    key:    İçeriği tekilleştiren string (URL, title, weekly bucket vs.).
            Boş key gönderilirse prefix üretilmez (boş string döner).
    """
    if not source or not key:
        return ""
    src_slug = re.sub(r"[^a-z0-9]+", "_", source.lower()).strip("_")[:20] or "src"
    digest = hashlib.sha1(key.encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"[{src_slug}:{digest}] "


def _iso_week_bucket(now: datetime | None = None) -> str:
    """Geçerli ISO yıl-hafta bucket'ı (örn. "2026-W19"). Haftalık dedup key."""
    now = now or datetime.now(timezone.utc)
    iso = now.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


class NotionLogger:
    def __init__(self):
        self.token = settings.NOTION_TOKEN
        self.db_id = settings.NOTION_X_DB_ID
        self.legacy_db_id = settings.NOTION_LINKEDIN_DB_ID  # opsiyonel, weekly-dedup için
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def is_already_posted_this_week(self, source: str) -> bool:
        """Aynı source bu hafta (Pazartesi başı) bir Draft veya Approved olarak loglanmış mı?

        source: "LinkedIn Haber" veya "LinkedIn Tavsiye"
        """
        try:
            now = datetime.now(timezone.utc)
            week_start = (now - timedelta(days=now.weekday())).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            payload = {
                "filter": {
                    "and": [
                        {"property": "Source", "select": {"equals": source}},
                        {"property": "Date", "date": {"on_or_after": week_start.date().isoformat()}},
                        {"or": [
                            {"property": "Status", "select": {"equals": "Draft"}},
                            {"property": "Status", "select": {"equals": "Approved"}},
                        ]},
                    ]
                },
                "page_size": 1,
            }
            r = requests.post(f"{API}/databases/{self.db_id}/query",
                              headers=self.headers, json=payload, timeout=15)
            r.raise_for_status()
            return len(r.json().get("results", [])) > 0
        except Exception as e:
            ops.warning(f"Weekly dedup hatası: {e}")
            return False

    def log_draft(self, source: str, score: int, linkedin_text: str,
                  draft_url: str, draft_id: str, title: str, image_url: str = ""):
        """LinkedIn-only draft kaydı (Twitter projesinin DB schema'sıyla uyumlu)."""
        base_title = (title or linkedin_text[:60] or f"{source} draft")[:200]
        # LinkedIn pipeline weekly: dedup key = source + ISO hafta bucket.
        # Aynı hafta aynı source iki kez log atılmaz.
        dedup_key = f"{source}:{_iso_week_bucket()}"
        prefix = make_dedup_prefix(source, dedup_key)
        full_title = (prefix + base_title)[:200]
        props = {
            "Title": {"title": [{"text": {"content": full_title}}]},
            "Source": {"select": {"name": source}},
            "Score": {"number": score},
            "Status": {"select": {"name": "Draft"}},
            "Tweet Text": {"rich_text": []},
            "Thread": {"rich_text": []},
            "LinkedIn Text": {"rich_text": [{"text": {"content": linkedin_text[:1990]}}]},
            "Source URL": {"url": None},
            "Typefully Draft URL": {"url": draft_url or None},
            "Typefully Draft ID": (
                {"rich_text": [{"text": {"content": str(draft_id)[:200]}}]}
                if draft_id else {"rich_text": []}
            ),
            "Date": {"date": {"start": datetime.now(timezone.utc).isoformat()}},
        }
        if image_url:
            props["Image URL"] = {"url": image_url}
        self._create_page(props, dedup_prefix=prefix)

    def log_failed(self, source: str, error: str, title: str = ""):
        base_title = (title or f"{source} failed")[:200]
        # Failed satır: weekly bucket + "failed" sufiksi → aynı hata haftada
        # birden fazla loglanmaz (cron retry'larında gürültüyü azaltır).
        dedup_key = f"{source}:{_iso_week_bucket()}:failed"
        prefix = make_dedup_prefix(source, dedup_key)
        full_title = (prefix + base_title)[:200]
        self._create_page({
            "Title": {"title": [{"text": {"content": full_title}}]},
            "Source": {"select": {"name": source}},
            "Status": {"select": {"name": "Failed"}},
            "Skip Reason": {"rich_text": [{"text": {"content": error[:1990]}}]},
            "Date": {"date": {"start": datetime.now(timezone.utc).isoformat()}},
        }, dedup_prefix=prefix)

    # ------------------------------------------------------------------
    # Race condition helpers (Twitter_Text_Paylasim ile birebir aynı tutuluyor)
    # ------------------------------------------------------------------

    def _enabled(self) -> bool:
        if not self.db_id:
            ops.warning("NOTION_X_DB_ID set değil, log atlanıyor")
            return False
        return True

    def _query_pages_by_prefix(self, prefix: str, page_size: int = 5) -> list:
        """Title `starts_with` prefix olan satırları döner (en eski → en yeni)."""
        if not prefix or not self._enabled():
            return []
        payload = {
            "filter": {"property": "Title", "title": {"starts_with": prefix}},
            "sorts": [{"timestamp": "created_time", "direction": "ascending"}],
            "page_size": page_size,
        }
        try:
            r = requests.post(f"{API}/databases/{self.db_id}/query",
                              headers=self.headers, json=payload, timeout=15)
            r.raise_for_status()
            return r.json().get("results", []) or []
        except Exception as e:
            ops.warning(f"Prefix query hatası: {e}")
            return []

    def _archive_page(self, page_id: str) -> bool:
        try:
            r = requests.patch(f"{API}/pages/{page_id}",
                               headers=self.headers,
                               json={"archived": True}, timeout=15)
            return r.status_code in (200, 201)
        except Exception as e:
            ops.warning(f"Archive hatası ({page_id}): {e}")
            return False

    def _create_page(self, properties: dict, dedup_prefix: str | None = None):
        if not self._enabled():
            return

        # 1) Pre-create check: prefix zaten varsa create etme.
        if dedup_prefix:
            existing = self._query_pages_by_prefix(dedup_prefix, page_size=1)
            if existing:
                winner_id = existing[0].get("id", "")
                ops.info("Duplicate detected (race winner exists), skipping create",
                         f"prefix={dedup_prefix!r} winner={winner_id}")
                return

        try:
            r = requests.post(f"{API}/pages", headers=self.headers,
                              json={"parent": {"database_id": self.db_id},
                                    "properties": properties},
                              timeout=20)
            if r.status_code not in (200, 201):
                ops.error(f"Notion log başarısız ({r.status_code}): {r.text[:300]}")
                return
            ops.info("Notion'a loglandı")
        except Exception as e:
            ops.error("Notion log exception", exception=e)
            return

        # 2) Post-create race detection: aynı prefix'ten >1 varsa loser'ı archive et.
        if dedup_prefix:
            try:
                rows = self._query_pages_by_prefix(dedup_prefix, page_size=5)
                if len(rows) > 1:
                    keeper = rows[0].get("id", "")
                    losers = [row for row in rows[1:] if row.get("id")]
                    ops.warning(
                        f"Race detected: prefix={dedup_prefix!r} keeper={keeper} "
                        f"archiving {len(losers)} loser(s)"
                    )
                    for row in losers:
                        self._archive_page(row["id"])
            except Exception as e:
                ops.warning(f"Race detection sonrası hata: {e}")
