"""Typefully Draft Publisher — LinkedIn-only mod.

LinkedIn_Text_Paylasim için: artık LinkedIn API'sini doğrudan çağırmıyoruz.
Pipeline post metni + görseli üretiyor, biz Typefully'ye LinkedIn-only draft
olarak yüklüyoruz. Yayın onay mailine basıldığında oluyor.

Twitter_Text_Paylasim/core/typefully_publisher.py ile aynı endpoint'leri
kullanır; sadece LinkedIn-only çağrıyı tutar (sade kalsın diye copy).
"""

import os
import time
from pathlib import Path
from typing import Callable

import requests

from ops_logger import get_ops_logger
from config import settings

ops = get_ops_logger("LinkedIn_Text_Paylasim", "TypefullyPublisher")

BASE = "https://api.typefully.com/v2"


# ---------------------------------------------------------------------------
# Typefully 429 retry helper.
#
# IMPORTANT: This helper is duplicated by hand across 4 services
# (Twitter_Text_Paylasim, Twitter_Video_Paylasim, LinkedIn_Text_Paylasim,
# LinkedIn_Video_Paylasim — when the latter migrates to Typefully).
# Per Antigravity shared-util constraint (`_skills/shared/` cannot be
# imported across Railway services because each service has its own
# rootDirectory), there is no central module. If you change behavior
# here, MIRROR THE EDIT into the other 3 typefully_publisher.py files.
# ---------------------------------------------------------------------------
def typefully_call_with_retry(
    fn: Callable[[], requests.Response],
    *,
    max_attempts: int = 3,
    log=None,
) -> requests.Response:
    """Wrap a Typefully HTTP call so 429s are retried with Retry-After-aware sleep.

    fn must be a zero-arg callable returning the requests.Response (no raise on
    non-2xx). On 429 we read Retry-After (seconds) or x-ratelimit-user-reset,
    sleep min 5s / max 120s, retry up to max_attempts. Other statuses are
    returned as-is for the caller to inspect.
    """
    resp: requests.Response | None = None
    for attempt in range(1, max_attempts + 1):
        resp = fn()
        if resp.status_code != 429 or attempt == max_attempts:
            return resp
        retry_after_raw = (
            resp.headers.get("Retry-After")
            or resp.headers.get("x-ratelimit-user-reset", "")
        )
        try:
            sleep_s = min(int(float(retry_after_raw)), 120)
        except (TypeError, ValueError):
            sleep_s = 30
        sleep_s = max(sleep_s, 5)
        if log is not None:
            try:
                log.warning(
                    "Typefully 429 — sleeping",
                    f"{sleep_s}s (attempt {attempt}/{max_attempts})",
                )
            except Exception:
                pass
        time.sleep(sleep_s)
    return resp  # type: ignore[return-value]


class TypefullyDraftError(Exception):
    pass


class TypefullyDraftPublisher:
    def __init__(self, social_set_id: int | None = None):
        self.api_key = settings.TYPEFULLY_API_KEY
        self.social_set_id = social_set_id or getattr(settings, "TYPEFULLY_SOCIAL_SET_ID", 334863)
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def get_connected_accounts(self) -> list[dict]:
        """Typefully üzerindeki tüm bağlı hesapları ve Social Set ID'lerini listeler."""
        try:
            r = requests.get(f"{BASE}/social-sets", headers=self.headers, timeout=15)
            if r.status_code == 200:
                return r.json().get("results", [])
        except Exception as e:
            ops.error(f"Typefully social-sets sorgu hatası: {e}")
        return []

    def _ss_url(self, suffix: str, target_ss_id: int | None = None) -> str:
        ss_id = target_ss_id or self.social_set_id
        return f"{BASE}/social-sets/{ss_id}{suffix}"

    def create_linkedin_only_draft(self, text: str, image_path: str | None = None,
                                   threads_posts: list[str] | None = None,
                                   social_set_id: int | None = None) -> dict:
        """LinkedIn-only draft. X devre dışı. Returns {draft_id, share_url}.

        threads_posts drop-in imza için kabul edilir ama Typefully Threads'e
        yayın yapamaz; sessizce yutmak yerine uyarı loglanır.
        """
        target_ss_id = social_set_id or self.social_set_id
        if threads_posts:
            ops.warning("Threads varyantı Typefully ile yayınlanamaz",
                        f"{len(threads_posts)} gönderi atlandı — USE_NATIVE_PUBLISHER=1 gerekir")
        if not text or not text.strip():
            raise TypefullyDraftError("LinkedIn metni boş")
        media_id = ""
        if image_path and os.path.exists(image_path):
            media_id = self._upload_image(image_path, social_set_id=target_ss_id) or ""
            if not media_id:
                ops.warning("Görsel upload başarısız; text-only LinkedIn draft'ına dönülüyor")

        post = {"text": text.strip()}
        if media_id:
            post["media_ids"] = [media_id]

        platforms = {
            "linkedin": {"enabled": True, "posts": [post], "settings": {}},
        }

        if settings.IS_DRY_RUN:
            ops.info("[DRY-RUN] LinkedIn draft create atlandı", f"ss_id={target_ss_id}")
            return {"draft_id": "dry-run", "share_url": "https://typefully.com/dry-run"}

        try:
            r = typefully_call_with_retry(
                lambda: requests.post(
                    self._ss_url("/drafts", target_ss_id),
                    headers=self.headers,
                    json={"platforms": platforms},
                    timeout=30,
                ),
                log=ops,
            )
            if r.status_code == 429:
                raise TypefullyDraftError(
                    f"Rate limit; reset={r.headers.get('x-ratelimit-user-reset','?')}"
                )
            if r.status_code not in (200, 201):
                raise TypefullyDraftError(f"draft create {r.status_code}: {r.text[:500]}")
            data = r.json()
            draft_id = data.get("id")
            # HTTP 200/201 ama gövdede gerçek bir draft id yoksa, bu "başarı"
            # değil belirsiz bir durum: draft gerçekten oluştu mu bilmiyoruz.
            # Sahte bir `typefully://draft/None` adresi üretip Success demek
            # yerine hata ver — pipeline bunu "failed" loglar ve sonraki koşu
            # tekrar dener (kardeş Twitter_Video silent_failure deseni).
            if not draft_id:
                raise TypefullyDraftError(
                    f"draft create {r.status_code} ama yanıtta draft id yok: {r.text[:300]}"
                )
            share_url = (
                data.get("share_url")
                or data.get("private_url")
                or f"https://typefully.com/?d={draft_id}&a={target_ss_id}"
            )
            ops.info("LinkedIn draft oluşturuldu", f"id={draft_id}, ss_id={target_ss_id}, url={share_url}")
            return {"draft_id": draft_id, "share_url": share_url}
        except TypefullyDraftError:
            raise
        except Exception as e:
            ops.error("draft create exception", exception=e)
            raise TypefullyDraftError(str(e))

    def _upload_image(self, image_path: str, social_set_id: int | None = None) -> str:
        """JPG/PNG upload → media_id. Twitter projesindeki ile aynı pattern."""
        target_ss_id = social_set_id or self.social_set_id
        if settings.IS_DRY_RUN:
            ops.info("[DRY-RUN] Görsel upload atlandı")
            return "dry-run-media"

        ext = Path(image_path).suffix.lower()
        if ext not in (".jpg", ".jpeg", ".png"):
            ops.error(f"Desteklenmeyen görsel uzantısı: {ext}")
            return ""
        safe_stem = "".join(c if ((c.isascii() and c.isalnum()) or c in "_.()-") else "_"
                            for c in Path(image_path).stem)[:200]
        file_name = f"{safe_stem}{ext}"
        try:
            r = typefully_call_with_retry(
                lambda: requests.post(self._ss_url("/media/upload", target_ss_id), headers=self.headers,
                                      json={"file_name": file_name}, timeout=20),
                log=ops,
            )
            if r.status_code != 201:
                ops.error(f"media/upload {r.status_code}: {r.text[:300]}")
                return ""
            data = r.json()
            media_id = data["media_id"]
            upload_url = data["upload_url"]
        except Exception as e:
            ops.error("media/upload exception", exception=e)
            return ""

        try:
            with open(image_path, "rb") as f:
                put = requests.put(upload_url, data=f, timeout=120)
            if put.status_code not in (200, 204):
                ops.error(f"S3 PUT {put.status_code}: {put.text[:300]}")
                return ""
        except Exception as e:
            ops.error("S3 PUT exception", exception=e)
            return ""

        poll = self._ss_url(f"/media/{media_id}", target_ss_id)
        deadline = time.time() + 120
        while time.time() < deadline:
            try:
                pr = requests.get(poll, headers=self.headers, timeout=15)
                pr.raise_for_status()
                pd = pr.json()
                status = pd.get("status", "")
                if status == "ready":
                    return media_id
                if status == "failed":
                    ops.error(f"media processing failed: {pd.get('error_reason','?')}")
                    return ""
            except Exception as e:
                ops.warning(f"media polling: {e}")
            time.sleep(3)
        ops.error("media ready olmadı (120s)")
        return ""
