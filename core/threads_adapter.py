"""LinkedIn uzun-form postunu tek bir Threads gönderisine indirger.

Twitter_Text_Paylasim/core/threads_adapter.py'nin KARDEŞİ ama aynı dosya DEĞİL:
  - Kaynak farklı: orada X thread'i, burada 600-1300 karakterlik LinkedIn postu.
  - Altyapı farklı: bu proje Anthropic LLMClient kullanmaz, OpenAI'ye ham HTTP atar.

Threads'in sert sınırı gönderi başına 500 karakter. LinkedIn postu neredeyse her
zaman bunu aşar, o yüzden burada iş "biçim çevirisi" değil ÖZ ÇIKARMAdır: postun
tek en güçlü fikrini al, Threads diline sohbet tonunda yeniden yaz.

Model: gpt-4.1-mini (LLM politikası: ücretsiz/ucuz kademe; pahalı model onaya tabi).
"""

import os
import re

import requests

from ops_logger import get_ops_logger
from core.dil_denetim import bozuk_dil

ops = get_ops_logger("LinkedIn_Text_Paylasim", "ThreadsAdapter")

_MODEL = "gpt-4.1-mini"
_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_OPENAI_KEY = (os.getenv("OPENAI_API_KEY")
               or os.getenv("OPENAI_API_KEY_DATA_SHARED")
               or os.getenv("OPENAI_API_KEY"))

MAX_CHARS = 500

SYSTEM_PROMPT = """Sen Dolunay'ın Threads hesabı için yazıyorsun. Elindeki LinkedIn
postunu Threads'e uygun TEK bir gönderiye indirgeyeceksin.

KİTLE: AI'ı işine katmak isteyen KOBİ sahipleri, yaratıcılar, meraklılar.
TON: Sohbet eder gibi, samimi, iddialı ama dürüst. Satış dili YOK.

KURALLAR
1. SERT SINIR: 500 karakter. Aşarsan içerik reddedilir. 400 civarını hedefle.
2. TEK FİKİR: LinkedIn postundaki en güçlü tek fikri seç. Hepsini sıkıştırmaya
   çalışma; özet değil, seçim yap.
3. İLK CÜMLE merak uyandırsın ya da doğrudan iddia etsin.
4. Kısa cümleler. Tek cümlede en fazla 15 kelime.
5. Em-dash (—) YASAK. Hashtag YASAK. En fazla 1 emoji.
6. "LinkedIn'de yazdım", "postumda anlattım" gibi self-referans YASAK.
7. Klişe YASAK: "devrim", "oyun değiştirici", "ilham", "potansiyelini keşfet".
8. Kaynakta olmayan sayı, araç ya da özellik UYDURMA. Kaynaktaki sayıları
   BİREBİR koru; emin değilsen sayıyı hiç yazma.

ÇIKTI: Sadece gönderi metni. Başlık, tırnak, açıklama, "İşte gönderi:" YOK.
"""


_EM_DASH = re.compile(r"[ \t]*—[ \t]*")
_HASHTAG = re.compile(r"#\S+")

# ── Sayı uydurma nöbeti ──────────────────────────────────────────────────────
# Kardeş adapter'da (Twitter_Text) 2026-07-10'da canlı yakalandı: kaynakta "3 dakika"
# yazarken model "Beş dakika" yazdı. Prompt'a "uydurma" demek YETMİYOR. Yalnızca
# rakam denetlemek de yetmez: model rakamı YAZIYLA yazınca kaçar.
_RAKAM = re.compile(r"\d+")
_SAYI_KELIME = {
    "bir": 1, "iki": 2, "üç": 3, "uc": 3, "dört": 4, "dort": 4, "beş": 5, "bes": 5,
    "altı": 6, "alti": 6, "yedi": 7, "sekiz": 8, "dokuz": 9, "on": 10,
    "yirmi": 20, "otuz": 30, "kırk": 40, "kirk": 40, "elli": 50, "altmış": 60,
    "altmis": 60, "yetmiş": 70, "yetmis": 70, "seksen": 80, "doksan": 90,
    "yüz": 100, "yuz": 100, "bin": 1000, "milyon": 1000000,
}


def _sayilar(metin: str) -> set:
    bulunan = {int(x) for x in _RAKAM.findall(metin or "")}
    for kelime in re.findall(r"[a-zçğıöşü]+", (metin or "").lower()):
        if kelime in _SAYI_KELIME:
            bulunan.add(_SAYI_KELIME[kelime])
    return bulunan


def _uydurma_sayilar(metin: str, kaynak: str) -> set:
    """Çıktıda olup kaynakta OLMAYAN sayılar. Boş küme = temiz."""
    return _sayilar(metin) - _sayilar(kaynak)


def _post_clean(text: str) -> str:
    t = _EM_DASH.sub(", ", text or "")
    t = _HASHTAG.sub("", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip().strip('"').strip()


def _kirp(text: str) -> str:
    """500 karakteri aşan metni cümle sınırında kırpar (motor 500'ü reddeder)."""
    if len(text) <= MAX_CHARS:
        return text
    kesit = text[:MAX_CHARS]
    for ayirac in (". ", ".\n", "! ", "? ", "\n\n"):
        yer = kesit.rfind(ayirac)
        if yer > MAX_CHARS * 0.5:
            return kesit[: yer + 1].strip()
    yer = kesit.rfind(" ")
    return (kesit[:yer] if yer > 0 else kesit).strip()


class ThreadsAdapter:
    def adapt(self, post_text: str) -> list[str]:
        """LinkedIn postundan Threads gönderisi üretir.

        Returns: tek elemanlı liste. Üretilemezse BOŞ LİSTE (çağıran Threads'i atlar,
        LinkedIn yayını etkilenmez).
        """
        if not post_text or len(post_text.strip()) < 40:
            return []
        if not _OPENAI_KEY:
            ops.warning("OPENAI anahtarı yok, Threads varyantı atlandı")
            return []

        metin = self._uret(post_text)
        if not metin:
            return []

        # İki kapı: sayı uydurma + bozuk dil. Sorun varsa bir kez düzeltmen notuyla
        # yeniden dene; yine varsa Threads'i ATLA. LinkedIn yayını etkilenmez.
        ek = self._sorunlar(metin, post_text)
        if ek:
            ops.warning("Threads varyantında sorun", f"{ek[:200]} — tek sefer yeniden deneniyor")
            metin = self._uret(post_text, ek=ek)
            if not metin:
                return []
            if self._sorunlar(metin, post_text):
                ops.warning("Threads varyantı ATLANDI (sorun düzelmedi)")
                return []

        ops.info(f"Threads varyantı üretildi ({len(metin)} karakter)")
        return [metin]

    def _sorunlar(self, metin: str, kaynak: str) -> str:
        """Sayı uydurma + bozuk dil kapıları. Sorun varsa düzeltmen notu, yoksa ''."""
        notlar = []
        uydurma = _uydurma_sayilar(metin, kaynak)
        if uydurma:
            notlar.append(f"Kaynakta OLMAYAN şu sayıları yazdın: {sorted(uydurma)}. "
                          f"Kaynaktaki sayıları birebir koru; emin değilsen sayıyı hiç yazma.")
        bozuk = bozuk_dil(metin, log=ops)
        if bozuk:
            notlar.append(f"Şu ifadeler bozuk/uydurma/yazım hatası: {bozuk}. "
                          f"Düzgün, hatasız Türkçe yaz.")
        return ("UYARI: " + " ".join(notlar)) if notlar else ""

    def _uret(self, post_text: str, ek: str = "") -> str:
        """Tek LLM çağrısı + temizlik + kırpma. Üretilemezse boş string."""
        user = f"LinkedIn postu:\n\n{post_text}"
        if ek:
            user += "\n\n" + ek
        try:
            r = requests.post(
                _OPENAI_URL,
                headers={"Authorization": f"Bearer {_OPENAI_KEY}",
                         "Content-Type": "application/json"},
                json={
                    "model": _MODEL,
                    "temperature": 0.6,
                    "max_tokens": 400,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user},
                    ],
                },
                timeout=90,
            )
            r.raise_for_status()
            ham = r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            ops.error("Threads adapt hatası", exception=e)
            return ""

        metin = _kirp(_post_clean(ham))
        if len(metin) < 20:
            ops.warning("Threads adapt boş döndü")
            return ""
        return metin
