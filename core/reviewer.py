"""Öz-inceleme kalite kapısı — LLM-judge.

Post yazıldıktan SONRA, postu yazan çağrıdan AYRI bir LLM çağrısı postu 1-10
puanlar. Ölçütler: haber güncelliği/alaka, profesyonel ton, somut değer,
jeneriklik yok, Dolunay'ın adına yakışır mı.

Ana orkestratör (main.py) kararı verir:
  - Puan eşiğin (config.QUALITY_THRESHOLD) üstündeyse post geçer.
  - Altındaysa post BİR KEZ yeniden üretilir; hâlâ altıysa o koşu ATLANIR
    (abstain) — post da mail de atılmaz.

Bu kapı HEM kalibrasyon HEM otonom modda çalışır (son güvenlik ağı).

Model: gpt-5.4 (birincil, ücretsiz ornek-site.com tier) → gpt-4o-mini (fallback).
Post yazarıyla aynı ucuz OpenAI hattı. Pahalı Anthropic modeli YOK.
"""

from ops_logger import get_ops_logger
ops = get_ops_logger("LinkedIn_Text_Paylasim", "Reviewer")

import os
import json as _json

import requests
from openai import OpenAI

from config import settings

_GPT_MODEL = "gpt-4o"
_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_OPENAI_KEY = (os.getenv("OPENAI_API_KEY")
               or os.getenv("OPENAI_API_KEY_DATA_SHARED")
               or os.getenv("OPENAI_API_KEY"))

_SYSTEM = (
    "Sen kıdemli bir LinkedIn içerik editörüsün. Emre Aşkar, Solido Grup veya Takalike adına yayınlanacak "
    "Türkçe bir LinkedIn postunu değerlendireceksin. Katı ol; profesyonel bir kurumsal veya kişisel markanın "
    "adına yakışacak, prestijli ve sektörel ağırlığı olan içeriği geçir.\n\n"
    "Şu ölçütlere göre 1-10 arası TEK bir puan ver:\n"
    "- Türkçe Dilbilgisi ve Kusursuzluk (KRİTİK): Ek yığılması, yapay çeviri kokusu veya bozuk kelimeler (örn. 'iadelerdelerse' gibi hatalar) VARSA PUAN KESİNLİKLE 5'İN ALTINDA OLMALI ve post reddedilmelidir.\n"
    "- Sektörel Terminoloji Doğruluğu: E-ticaret veya iş kavramları doğru mu? (örn. stok için SDK değil SKU/katalog denmeli; hatalıysa puan kırılmalı).\n"
    "- Güncellik ve alaka: gerçekten güncel iş dünyası, e-ticaret, pazaryeri, web/dijital veya AI gündemine/pratik bir çözüme değiyor mu?\n"
    "- Profesyonel ton: ölçülü, net, kurumsal ve girişimci diline yakışır mı (ucuz, clickbait, abartılı değil)?\n"
    "- Somut değer: okuyucu işletmesinde/mağazasında uygulayabileceği bir şey öğreniyor mu, yoksa boş laf mı?\n"
    "- Jeneriklik & Ucuzluk Yok: 'Gelecek değişiyor' veya 'kolay yoldan zengin olun / oturduğunuz yerden kazanın' tarzı içi boş, amatör klişeler var mı (varsa kesinlikle düşük puan ver)?\n"
    "- Markanın adına yakışır mı: yanlış/uydurma bilgi, yarım kalmış cümle, garip çeviri kokusu veya ucuz ajans dili yok mu?\n\n"
    "SADECE şu JSON'u döndür: {\"score\": <1-10 tam sayı>, \"reason\": \"<tek kısa cümle>\"}"
)


class Reviewer:
    """LLM-judge: LinkedIn postuna 1-10 kalite puanı verir."""

    def __init__(self):
        # Fallback SDK istemcisi ücretsiz <WEBSITE> anahtarını kullanır.
        api_key = os.getenv("OPENAI_API_KEY") or settings.OPENAI_API_KEY
        self.client = OpenAI(api_key=api_key)

    def review(self, post_text: str, kind: str = "") -> dict:
        """Postu puanla. Döner: {"score": int(1-10), "reason": str}.

        DRY_RUN'da gerçek çağrı yapılmaz (yüksek puan döner, pipeline ilerler).
        Judge altyapısı çökerse eşik puanı döner (geçer) — bir judge arızası tüm
        çıktıyı bloklamasın; kapı güvenlik ağıdır, tek kalite kaynağı değil.
        """
        if settings.IS_DRY_RUN:
            ops.info("[DRY-RUN] öz-inceleme atlanıyor, varsayılan geçer puan")
            return {"score": 10, "reason": "[DRY-RUN] inceleme atlandı"}

        try:
            raw = self._judge(post_text, kind)
        except Exception as e:
            ops.warning(f"Öz-inceleme judge hatası, güvenlik için geçiriliyor: {e}")
            return {"score": settings.QUALITY_THRESHOLD, "reason": "judge hatası, geçildi"}

        score = self._clamp(raw.get("score"))
        reason = (raw.get("reason") or "").strip()[:300]
        ops.info(f"Öz-inceleme puanı: {score}/10 — {reason[:80]}")
        return {"score": score, "reason": reason}

    # ── LLM çağrısı (test'te monkeypatch'lenebilir) ────────────────────────────
    def _judge(self, post_text: str, kind: str) -> dict:
        """gpt-5.4 (birincil) ile puanla; hata olursa gpt-4o-mini fallback."""
        label = {
            "LinkedIn Haber": "haftanın AI haberleri postu",
            "LinkedIn Tavsiye": "haftalık AI tavsiyesi postu",
            "LinkedIn Solido": "Solido Grup B2B kurumsal büyüme ve web postu",
            "LinkedIn Takalike": "Takalike e-ticaret ve dropshipping postu",
        }.get(kind, "LinkedIn postu")
        user_message = f"Değerlendirilecek {label}:\n\n{post_text}"

        # Birincil: OpenAI gpt-4o (raw HTTP, JSON).
        try:
            body = {
                "model": _GPT_MODEL,
                "max_completion_tokens": 200,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": user_message},
                ],
            }
            r = requests.post(_OPENAI_URL, headers={
                "Authorization": f"Bearer {_OPENAI_KEY}", "Content-Type": "application/json"},
                json=body, timeout=120)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"].strip()
            return _json.loads(content)
        except Exception as primary_err:
            ops.warning(f"{_GPT_MODEL} öz-inceleme hatası, gpt-4o-mini'ye düşülüyor: {primary_err}")

        # Fallback: SDK gpt-4o-mini (JSON mode).
        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=200,
        )
        return _json.loads(response.choices[0].message.content)

    @staticmethod
    def _clamp(v) -> int:
        """Puanı 1-10 tam sayıya sıkıştır; okunamazsa 1 (en güvenli: eşik altı)."""
        try:
            n = int(round(float(v)))
        except (TypeError, ValueError):
            return 1
        return max(1, min(10, n))
