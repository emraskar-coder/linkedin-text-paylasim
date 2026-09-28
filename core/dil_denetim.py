"""Bozuk dil freni — üretilen Türkçe metinde anlamsız kelime / yazım hatası tarar.

Neden regex değil LLM: 2026-07-10'da ucuz model kaynaktan "utopikal", "İS'in için",
"kalmassın" gibi UYDURMA kelime ve yazım hataları üretti (Dolunay'ın adına yayına
gidecekti). Bunları regex yakalayamaz — "utopikal" fonetik olarak geçerli görünür,
sözlükte yok. Bir dil modeli ise yakalar. Düzeltmen çağrısı da ücretsiz gpt-4.1-mini
olduğu için maliyeti yok.

Kapı EK bir güvenlik katmanıdır, birincil çözüm değil: birincil çözüm zaten kaliteli
model (gpt-4.1-mini) kullanmak. Bu fren o modelin nadir kaçağını yakalar.

fail-open: düzeltmen çağrısı başarısız olursa metni TEMİZ sayar (fren, üretimi
büsbütün durdurmasın; kötü senaryo eksik gönderi değil, yayının hiç olmaması).

KANONIK KAYNAK: Twitter_Text_Paylasim/core/dil_denetim.py — kopyaları MIRROR.
"""

from __future__ import annotations

import json
import os

import requests

_URL = "https://api.openai.com/v1/chat/completions"


def _key() -> str | None:
    return (os.getenv("OPENAI_API_KEY")
            or os.getenv("OPENAI_API_KEY_DATA_SHARED")
            or os.getenv("OPENAI_API_KEY"))


_SISTEM = (
    "Sen bir Türkçe dil denetçisisin. Sana verilen metinde SADECE şu DİL bozukluklarını ara: "
    "(1) Türkçede olmayan uydurma/anlamsız kelime (örnek: 'utopikal', 'kalmassın'), "
    "(2) yazım hatası, (3) bozuk ya da yarım kalmış cümle, "
    "(4) bir kelimenin ortasında ya da başında yersiz büyük harf / bozuk kısaltma (örnek: \"İS'in\"). "
    "\n\nSORUN SAYMA (bunlar DOĞRUDUR, asla işaretleme): ürün ve marka adları, İngilizce "
    "teknik terimler ve yabancı özel adlar. Örnekler: Claude, Claude Code, Antigravity, "
    "VS Code, ChatGPT, Notion, ManyChat, terminal, IDE, Mac, Windows, OS. Bunlar Türkçe "
    "kelime değildir ama METİN İÇİN DOĞRUDUR. "
    "\n\nYALNIZCA TEK TEK KELİMELERE bak: o kelime gerçek bir Türkçe kelime mi, yoksa uydurma "
    "ya da yazım hatası mı. Bir ifade GARİP, devrik ya da üslupça zayıf olabilir ama kelimeleri "
    "doğruysa SORUN YOKTUR. Cümle kuruluşunu, üslubu, akıcılığı, devrikliği ASLA işaretleme. "
    "Örnek: 'hatalı bir sırada gitmek' garip ama tüm kelimeleri gerçek Türkçe, TEMİZDİR. "
    "İçerik doğruluğu, ton ve uzunluk da seni İLGİLENDİRMEZ. "
    "Emin değilsen temiz de; ama açık uydurma kelimeyi ya da yazım hatasını KAÇIRMA. "
    '\n\nYanıtı yalnızca şu JSON ile ver: {"temiz": true} ya da '
    '{"temiz": false, "sorunlar": ["<bozuk kelime/ifade>", ...]}.'
)


def bozuk_dil(metin: str, *, log=None) -> list[str]:
    """Metindeki dil sorunlarını döndürür. Boş liste = temiz (ya da denetlenemedi).

    fail-open: anahtar yoksa veya çağrı patlarsa boş liste döner (metni engellemez).
    """
    metin = (metin or "").strip()
    if not metin:
        return []
    key = _key()
    if not key:
        return []
    try:
        r = requests.post(
            _URL,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": "gpt-4.1-mini",
                "temperature": 0,
                "max_tokens": 300,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": _SISTEM},
                    {"role": "user", "content": metin},
                ],
            },
            timeout=60,
        )
        r.raise_for_status()
        data = json.loads(r.json()["choices"][0]["message"]["content"])
    except Exception as e:  # noqa: BLE001
        if log:
            log.warning("Dil denetimi yapılamadı (fail-open)", str(e)[:120])
        return []

    if data.get("temiz") is True:
        return []
    sorunlar = data.get("sorunlar") or []
    return [str(s) for s in sorunlar if s][:12] or (["bozuk ifade"] if data.get("temiz") is False else [])
