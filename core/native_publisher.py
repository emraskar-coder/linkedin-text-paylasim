"""Native draft publisher — Typefully arayuzunun yerine gecen kopru.

Typefully gocu (2026-06-18). TypefullyDraftPublisher ile AYNI metot imzalari, ama
Typefully draft'i yerine Supabase scheduled_posts'a status='draft' (onay bekleyen,
publish_at=NULL) bir satir yazar. Onay servisi onaya basilinca slot atar -> 'scheduled';
slot cron'u zamani gelince native X/LinkedIn yayinlar.

Boylece main.py neredeyse HIC degismeden, tek import ile gecis yapilabilir.

Tek FARK: gorselli metotlar artik local image_path yerine durable image_url alir
(yayin onay sonrasi SAATLER sonra olabilir; o an local dosya silinmis olur, ama
image_generator zaten hosted bir image_url uretiyor). main.py'da use_case cagri
noktalari image_url gecirecek sekilde guncellenir.

KANONIK KAYNAK: Twitter_Text_Paylasim/core/native_publisher.py
Davranis degisirse diger servis kopyalarina MIRROR.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json as _json

import requests


class NativeDraftError(Exception):
    pass


class NativeDraftPublisher:
    def __init__(
        self,
        supabase_url: str,
        service_role_key: str,
        *,
        source_project: str = "Twitter_Text_Paylasim",
        dry_run: bool = False,
        log=None,
    ):
        if not supabase_url or not service_role_key:
            raise NativeDraftError("SUPABASE_URL / SERVICE_ROLE_KEY eksik")
        self.base = supabase_url.rstrip("/") + "/rest/v1/scheduled_posts"
        self.headers = {
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
        }
        self.source_project = source_project
        self.dry_run = dry_run
        self.log = log

    # ── İç: draft satırı yaz ───────────────────────────────────────────────────
    def _write_draft(self, x: dict | None, linkedin: dict | None,
                     threads: dict | None = None) -> dict:
        if not x and not linkedin and not threads:
            raise NativeDraftError("İçerik yok: X, LinkedIn ve Threads boş")

        platform = "+".join(
            [p for p, v in (("x", x), ("linkedin", linkedin), ("threads", threads)) if v]
        ) or "x"
        payload = {"x": x, "linkedin": linkedin, "threads": threads}

        if self.dry_run:
            if self.log:
                self.log.info("[DRY-RUN] draft satırı atlandı", f"platform={platform}")
            return {"draft_id": "dry-run", "share_url": "native://draft/dry-run"}

        row = {
            "platform": platform,
            "source_project": self.source_project,
            "publish_at": None,
            "payload": payload,
            "status": "draft",
            "created_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        }
        r = requests.post(
            self.base,
            headers={**self.headers, "Prefer": "return=representation"},
            json=row,
            timeout=20,
        )
        if r.status_code not in (200, 201):
            raise NativeDraftError(f"draft insert {r.status_code}: {r.text[:300]}")
        rows = r.json() or []
        if not rows or "id" not in rows[0]:
            raise NativeDraftError(f"draft insert 2xx ama id yok: {r.text[:200]}")
        rid = str(rows[0]["id"])
        if self.log:
            self.log.info("Draft kaydedildi", f"id={rid}, platform={platform}")
        return {"draft_id": rid, "share_url": f"native://draft/{rid}"}

    @staticmethod
    def _x(tweets: list[str], image_url: str | None = None, link: str | None = None) -> dict:
        return {"tweets": [t for t in tweets if t and t.strip()], "image_url": image_url, "link": link}

    @staticmethod
    def _li(text: str | None, image_url: str | None = None) -> dict | None:
        if not text or not text.strip():
            return None
        return {"text": text, "image_url": image_url}

    @staticmethod
    def _th(posts: list[str] | None, image_url: str | None = None,
            link: str | None = None) -> dict | None:
        """Threads payload'i. Zincir olabilecegi icin metin DEGIL liste tutar."""
        temiz = [p for p in (posts or []) if p and p.strip()]
        if not temiz:
            return None
        return {"posts": temiz, "image_url": image_url, "link": link}

    # ── Typefully ile AYNI imzalar ──────────────────────────────────────────────
    def create_single_draft(self, text: str, linkedin_text: str | None = None,
                            threads_posts: list[str] | None = None) -> dict:
        return self._write_draft(self._x([text]), self._li(linkedin_text),
                                 self._th(threads_posts))

    def create_thread_draft(self, tweets: list[str], linkedin_text: str | None = None,
                            threads_posts: list[str] | None = None) -> dict:
        if not tweets:
            raise NativeDraftError("Boş thread")
        return self._write_draft(self._x(tweets), self._li(linkedin_text),
                                 self._th(threads_posts))

    # ── Görsel: local path -> Supabase Storage durable URL ─────────────────────
    def _upload_to_storage(self, image_path: str) -> str | None:
        """Local gorseli social-media bucket'ina yukler, public URL doner.
        Deferred yayinda (onay/slot saatler sonra) local dosya silinmis olur;
        kalici URL sart. Typefully arayuzuyle ayni kalmak icin image_path alir."""
        import os, secrets as _sec
        if self.dry_run:
            return "https://example.test/dry-run.jpg"
        if not image_path or not os.path.exists(image_path):
            return None
        ext = os.path.splitext(image_path)[1].lower() or ".jpg"
        ctype = "image/png" if ext == ".png" else "image/jpeg"
        key = f"{self.source_project}/{_sec.token_hex(12)}{ext}"
        base = self.base.rsplit("/rest/v1/", 1)[0]
        up = f"{base}/storage/v1/object/social-media/{key}"
        try:
            with open(image_path, "rb") as f:
                r = requests.post(up, headers={
                    "apikey": self.headers["apikey"],
                    "Authorization": self.headers["Authorization"],
                    "Content-Type": ctype,
                }, data=f.read(), timeout=120)
            if r.status_code not in (200, 201):
                if self.log:
                    self.log.warning("Storage upload başarısız", f"{r.status_code} {r.text[:150]}")
                return None
            return f"{base}/storage/v1/object/public/social-media/{key}"
        except Exception as e:
            if self.log:
                self.log.warning("Storage upload exception", str(e))
            return None

    def create_single_draft_with_image(self, text: str, image_path: str,
                                       linkedin_text: str | None = None,
                                       threads_posts: list[str] | None = None) -> dict:
        url = self._upload_to_storage(image_path)
        return self._write_draft(self._x([text], image_url=url),
                                 self._li(linkedin_text, image_url=url),
                                 self._th(threads_posts, image_url=url))

    def create_thread_draft_with_image(self, tweets: list[str], image_path: str,
                                       linkedin_text: str | None = None,
                                       threads_posts: list[str] | None = None) -> dict:
        if not tweets:
            raise NativeDraftError("Boş thread")
        url = self._upload_to_storage(image_path)
        return self._write_draft(self._x(tweets, image_url=url),
                                 self._li(linkedin_text, image_url=url),
                                 self._th(threads_posts, image_url=url))

    def create_linkedin_only_draft(self, text: str, image_path: str | None = None,
                                   threads_posts: list[str] | None = None) -> dict:
        # KAPI YUKLEMEDEN ONCE KOSAR. Bos metinde cagri reddediliyordu ama
        # gorsel kovaya coktan yuklenmis oluyordu: hicbir satira baglanmayan
        # oksuz dosya kalirdi. `_li` yalniz metne bakiyor, `image_url`e degil,
        # yani kontrolu one almak davranisi degistirmez.
        if not (text or "").strip():
            raise NativeDraftError("LinkedIn metni boş")
        url = self._upload_to_storage(image_path) if image_path else None
        li = self._li(text, image_url=url)
        if not li:
            raise NativeDraftError("LinkedIn metni boş")
        return self._write_draft(None, li, self._th(threads_posts, image_url=url))

    # ── Otonom yayın yolu (onay ATLANIR) ───────────────────────────────────────
    # LinkedIn_Text kalibrasyon → otonomi geçişinde kullanılır. status='scheduled'
    # + publish_at=bir sonraki boş slot doğrudan yazılır; onay maili YOK; slot cron
    # zamanı gelince onaysız yayınlar. SADECE bu proje kopyasına eklendi.
    def _fetch_occupied_slots(self) -> list[str]:
        """scheduled_posts'tan dolu slotları (publish_at set) oku — çakışmayı önle."""
        if self.dry_run:
            return []
        params = {
            "select": "publish_at",
            "publish_at": "not.is.null",
            "status": "in.(scheduled,publishing,published)",
        }
        try:
            r = requests.get(self.base, headers=self.headers, params=params, timeout=20)
            if r.status_code not in (200, 201):
                if self.log:
                    self.log.warning("occupied slot okuma başarısız", f"{r.status_code} {r.text[:120]}")
                return []
            return [row["publish_at"] for row in (r.json() or []) if row.get("publish_at")]
        except Exception as e:
            if self.log:
                self.log.warning("occupied slot exception", str(e))
            return []

    # ---- MUKERRER YAYIN KAPISI (2026-09-04) -------------------------------
    # Kardes projede olculdu: bir kosu yayin/insert yapip KAYDINI yazamadan
    # olurse is "yarim" degil "hic baslamamis" gorunur ve bir sonraki kosu
    # ayni icerigi bastan yayinlar. Yayin_Zamanlayici'da ayni videoyu
    # Dolunay'in Instagram ve Facebook'una iki kez cikaran mekanizma budur.
    # Burada da ayni delik vardi: `_write_scheduled` her cagrida kosulsuz
    # insert ediyordu, dedup bayragi ise insert'in cevabi dondukten SONRA
    # yaziliyordu. Cevap kaybolursa ikinci bir `scheduled` satir olusur ve
    # slot cron'u ayni metni LinkedIn'e IKINCI KEZ atar.
    #
    # Ders: kendi defterine bakan kapi, defterin yazilamadigi vakayi goremez.
    # Bu yuzden kapi geri donusu olmayan islemden ONCE tablonun KENDISINE
    # sorar: "bu icerik zaten planlanmis mi".

    @staticmethod
    def _icerik_anahtari(payload: dict) -> str:
        """Ayni metnin ayni anahtari uretmesi icin kanonik ozet.

        YALNIZ METNE BAKAR (olculdu 2026-09-04, kendi duzeltmemin arkasi).
        Ilk hali payload'in TAMAMINI ozetliyordu ve bu kapiyi gorselli her
        gonderide OLU KODA cevirir: `_upload_to_storage` her yuklemede
        `token_hex(12)` ile rastgele bir dosya adi uretir, yani ayni metin
        ayni gorselle iki kez gonderilse bile `image_url` farkli olur, ozet
        farkli cikar ve mukerrer hic yakalanmazdi. Kapi yesil gorunur,
        korudugu sey yoktur. Bu yuzden yalnizca insanin yazdigi metin
        anahtarin icine girer; adres, link ve zaman damgasi girmez.
        """
        parcalar = []
        for ad in ("x", "linkedin", "threads"):
            v = payload.get(ad)
            if not isinstance(v, dict):
                continue
            if v.get("text"):
                parcalar.append(str(v["text"]))
            for liste_adi in ("tweets", "posts"):
                for parca in (v.get(liste_adi) or []):
                    parcalar.append(str(parca))
        sade = " ".join(" ".join(parcalar).split()).lower()
        return hashlib.sha256(sade.encode("utf-8")).hexdigest()[:32]

    def _zaten_planlandi_mi(self, payload: dict, saat: int = 48) -> dict | None:
        """Bu icerik son `saat` saat icinde zaten planlanmis mi.

        Doner: eslesen satir (varsa), yoksa None.
        SORU SORULAMAZSA HATA FIRLATIR - bu bilincli fail-closed'dir.
        Sorulamayan kapi "temiz" demek, korumayi hic koymamakla ayni seydir;
        insert'i atlamanin bedeli tek kosu gecikmesi, yanlis atmanin bedeli
        LinkedIn'de ikinci bir gonderi.
        """
        if self.dry_run:
            return None
        esik = (_dt.datetime.now(_dt.timezone.utc)
                - _dt.timedelta(hours=saat)).isoformat()
        params = {
            "select": "id,payload,publish_at,created_at,status",
            "status": "in.(scheduled,publishing,published)",
            "created_at": f"gte.{esik}",
        }
        if self.source_project:
            params["source_project"] = f"eq.{self.source_project}"
        r = requests.get(self.base, headers=self.headers, params=params, timeout=20)
        if r.status_code not in (200, 201):
            raise NativeDraftError(
                f"mukerrer kontrolu sorulamadi ({r.status_code}): {r.text[:200]}")
        hedef = self._icerik_anahtari(payload)
        for satir in (r.json() or []):
            if self._icerik_anahtari(satir.get("payload") or {}) == hedef:
                return satir
        return None

    def _write_scheduled(self, x: dict | None, linkedin: dict | None,
                         threads: dict | None = None) -> dict:
        """_write_draft gövdesinin kardeşi: status='scheduled' + publish_at=slot."""
        if not x and not linkedin and not threads:
            raise NativeDraftError("İçerik yok: X, LinkedIn ve Threads boş")

        from core.slots import next_free_slot

        platform = "+".join(
            [p for p, v in (("x", x), ("linkedin", linkedin), ("threads", threads)) if v]
        ) or "x"
        payload = {"x": x, "linkedin": linkedin, "threads": threads}

        if self.dry_run:
            slot = next_free_slot([])
            if self.log:
                self.log.info("[DRY-RUN] scheduled satırı atlandı",
                              f"platform={platform} slot={slot.isoformat()}")
            return {"draft_id": "dry-run", "share_url": "native://scheduled/dry-run",
                    "publish_at": slot.isoformat()}

        varolan = self._zaten_planlandi_mi(payload)
        if varolan:
            rid = str(varolan.get("id"))
            if self.log:
                self.log.warning(
                    "MUKERRER ENGELLENDI",
                    f"bu icerik zaten planli (id={rid}, "
                    f"slot={varolan.get('publish_at')}) - ikinci satir yazilmadi")
            return {"draft_id": rid, "share_url": f"native://scheduled/{rid}",
                    "publish_at": varolan.get("publish_at"),
                    "mukerrer_engellendi": True}

        slot = next_free_slot(self._fetch_occupied_slots())
        row = {
            "platform": platform,
            "source_project": self.source_project,
            "publish_at": slot.isoformat(),
            "payload": payload,
            "status": "scheduled",
            "created_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        }
        r = requests.post(
            self.base,
            headers={**self.headers, "Prefer": "return=representation"},
            json=row,
            timeout=20,
        )
        if r.status_code not in (200, 201):
            raise NativeDraftError(f"scheduled insert {r.status_code}: {r.text[:300]}")
        rows = r.json() or []
        if not rows or "id" not in rows[0]:
            raise NativeDraftError(f"scheduled insert 2xx ama id yok: {r.text[:200]}")
        rid = str(rows[0]["id"])
        if self.log:
            self.log.info("Scheduled kaydedildi", f"id={rid}, platform={platform}, slot={slot.isoformat()}")
        return {"draft_id": rid, "share_url": f"native://scheduled/{rid}",
                "publish_at": slot.isoformat()}

    def create_linkedin_only_scheduled(self, text: str, image_path: str | None = None,
                                       threads_posts: list[str] | None = None) -> dict:
        """Onaysız otonom LinkedIn yayını için scheduled satır.

        NOT: main local image_path geçirir; ertelenmiş yayında (slot saatler sonra)
        local dosya silinmiş olacağı için burada da durable Storage URL'e yükleriz
        (create_linkedin_only_draft ile aynı davranış)."""
        # KAPI YUKLEMEDEN ONCE KOSAR. Bos metinde cagri reddediliyordu ama
        # gorsel kovaya coktan yuklenmis oluyordu: hicbir satira baglanmayan
        # oksuz dosya kalirdi. `_li` yalniz metne bakiyor, `image_url`e degil,
        # yani kontrolu one almak davranisi degistirmez.
        if not (text or "").strip():
            raise NativeDraftError("LinkedIn metni boş")
        url = self._upload_to_storage(image_path) if image_path else None
        li = self._li(text, image_url=url)
        if not li:
            raise NativeDraftError("LinkedIn metni boş")
        return self._write_scheduled(None, li, self._th(threads_posts, image_url=url))
