"""Görsel promptu (OpenAI gpt-4o-mini) ve görsel üretimi (Kie AI gpt-image-2).

Post metninden JSON dönen prompt üretici (headline_tr + scene_en) ile Kie AI
jobs/createTask + recordInfo polling üzerinden 16:9 editoryal görsel indirir.
"""
from ops_logger import get_ops_logger
ops = get_ops_logger("LinkedIn_Text_Paylasim", "ImageGenerator")
import os
import requests
import tempfile
import time
from openai import OpenAI

from config import settings

# GPT Image 2 (kullanici isteği 2026-06-22). Eski "Kie'de 500" notu ESKİDİ — model bugün
# çalışıyor + Türkçe metni diakritikleriyle net basıyor + nano-banana-2'nin airbrushed
# dokusuna göre çok daha keskin/gerçekçi (canlı doğrulandı). Twitter_Text ile aynı motor.
KIE_MODEL = "gpt-image-2-text-to-image"
KIE_RESOLUTION = "2K"

_REALISM = (
    "Ultra-realistic editorial photograph, shot on a professional camera (Canon EOS R5, 50mm), "
    "natural light, shallow depth of field, photojournalistic, crisp fine grain and real material "
    "texture. NOT airbrushed, NOT plastic, NOT smooth CGI skin, NOT 3D render, NOT illustration, "
    "NOT cartoon, NOT flat vector."
)

# En bayat AI stok klişeleri — bunları görselden dışla. Baseline görsel (2026-07-04)
# tam bu klişeye düştü: parlayan mavi beyin hologramı + jenerik toplantı masası. İkinci
# tur: laptop ekranındaki parlayan mavi 'bulut/dashboard' UI de klişe → onu da dışla.
_NO_CLICHE = (
    "Absolutely AVOID these overused AI stock cliches: glowing blue holographic brain, "
    "neural-network node webs, humanoid robots or androids, robot hands, floating holographic "
    "UI panels, streams of glowing binary or code, circuit-board patterns, a diverse team in a "
    "boardroom staring at a screen, blue-tinted 'futuristic' lighting, the letters 'AI' as an "
    "object. Also AVOID glowing blue data dashboards, holographic clouds or charts on laptop/"
    "phone/monitor screens; if a device screen is visible keep it dim, plain and unremarkable, "
    "never a glowing tech UI. Instead: a specific, concrete, real-world moment with real people "
    "or real objects, natural warm colour, human scale."
)

# Görselde gibberish yazı çıkmasın (ekran/pano/kağıt üzerinde okunur sahte metin yasak).
_NO_TEXT_IN_SCENE = (
    "No readable text anywhere in the scene: no words, no letters, no numbers, no fake UI labels, "
    "no gibberish on screens, papers, signs or whiteboards, no watermark, no logo."
)


def _assemble_image_prompt(headline_tr: str, scene_en: str, aspect_clause: str) -> str:
    """Sahne (İngilizce) + görsele basılacak Türkçe başlık + keskinlik kuralları."""
    return (
        f"{_REALISM} {_NO_CLICHE} Scene: {scene_en}. Cinematic, dramatic, scroll-stopping, "
        f"documentary realism, single focal subject. "
        f"Render this exact Turkish headline cleanly at the top as bold modern sans-serif typography, "
        f"high contrast, correct Turkish spelling with proper diacritics (ç ğ ı ö ş ü), perfectly "
        f'legible: "{headline_tr}". '
        f"Only that exact Turkish text and nothing else — no other words, no English, no gibberish "
        f"letters, no numbers, no extra captions, no watermark, no logo, no readable signs in the scene. "
        f"{aspect_clause}, sharp focus, high resolution, magazine-cover quality."
    )


def _assemble_image_prompt_clean(scene_en: str, aspect_clause: str) -> str:
    """Metinsiz temiz editoryal görsel. Başlık LinkedIn caption'ında zaten var;
    görselin İÇİNE metin basmayız — böylece diakritik/gibberish riski sıfırlanır."""
    return (
        f"{_REALISM} {_NO_CLICHE} Scene: {scene_en}. Cinematic, dramatic, scroll-stopping, "
        f"documentary realism, single focal subject, strong composition with clear negative space. "
        f"{_NO_TEXT_IN_SCENE} "
        f"{aspect_clause}, sharp focus, high resolution, magazine-cover quality."
    )


class ImageGenerator:
    """Metinden görsel promptu çıkarır ve Kie AI ile görsel üretir."""

    def __init__(self):
        # Görsel prompt'u kalite-hassas değil; ücretsiz <WEBSITE> anahtarına yönlendir.
        api_key = os.getenv("OPENAI_API_KEY") or settings.OPENAI_API_KEY
        self.openai_client = OpenAI(api_key=api_key)

    def generate_post_image(self, post_text: str) -> str:
        """
        1. GPT-4.1-mini ile görsel promptu üretir.
        2. Kie AI API'sine istek atar.
        3. Üretilen görseli temp klasörüne indirir.
        
        Returns:
            İndirilen görselin lokal dosya yolu.
        """
        if settings.IS_DRY_RUN:
            ops.info("[DRY-RUN] Görsel prompt üretme atlanıyor.")
            ops.info("[DRY-RUN] Kie AI görsel üretme atlanıyor.")
            return None

        # Step 1: Prompt Üretimi (GPT-4o-mini)
        prompt = self._generate_image_prompt(post_text)

        # Step 2 & 3: Kie AI ile Üret ve İndir
        image_path = self._generate_and_download_from_kie(prompt)
        return image_path

    def _generate_image_prompt(self, post_text: str) -> str:
        """Post metninden: (ops.) kısa Türkçe başlık + İngilizce SOMUT sahne → tam prompt.

        LINKEDIN_IMAGE_HEADLINE=0 (varsayılan): görsel TEMİZ, metinsiz üretilir; başlık
        LinkedIn caption'ında zaten olduğundan görsele metin BASILMAZ (diakritik/gibberish
        riski sıfır). =1 yaparsan başlık yine görsele basılır (eski davranış).
        """
        import json as _json
        print_headline = os.getenv("LINKEDIN_IMAGE_HEADLINE", "0") == "1"
        system_message = (
            "You art-direct high-end editorial photographs for a Turkish business and executive LinkedIn channel "
            "(covering B2B technology, e-commerce, modern retail, warehouse logistics, and AI). "
            "The audience is business leaders, founders, and e-commerce entrepreneurs. "
            "The visual must look like an authentic documentary press photograph (National Geographic or Bloomberg Businessweek style), "
            "never a cheap 3D render, cartoon, or generic stock graphic.\n\n"
            "Given a Turkish LinkedIn post, output JSON with two keys:\n"
            '  "headline_tr": a SHORT punchy Turkish headline (max 7 words, no hashtags, no quotes, '
            "plain Turkish with correct diacritics). It must name the single most striking SPECIFIC "
            "fact or theme of the post (a concrete dynamic, marketplace metric, or core business takeaway) — NOT a generic label.\n"
            '  "scene_en": an English description of ONE specific, concrete, real-world photographic '
            "moment that embodies the post's core idea as a physical metaphor. Be concrete: real location "
            "(e.g., modern sleek fulfillment center, clean artisan workshop, focused e-commerce studio, freight transit, "
            "or authentic executive office), real objects, human scale, warm natural lighting, 50mm lens depth of field. "
            "If a laptop/screen appears, it is dim, incidental, and never glowing or holographic.\n"
            "HARD BANS for scene_en: no glowing brains, no neural-network webs, no humanoid robots, "
            "no robot hands, no holographic UI panels, no floating code/binary, no circuit patterns, "
            "no blue futuristic sci-fi glow, no cartoon/CGI characters, no floating coins or money bag illustrations.\n"
            "Output ONLY the JSON object."
        )
        user_message = f"LinkedIn post (Turkish):\n\n{post_text}"
        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message}
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
                max_tokens=400,
            )
            data = _json.loads(response.choices[0].message.content)
            headline = (data.get("headline_tr") or "").strip()
            scene = (data.get("scene_en") or "").strip()
            if not scene:
                raise ValueError("scene_en boş döndü")
            if print_headline:
                prompt = _assemble_image_prompt(headline, scene, "Wide 16:9 landscape composition")
                ops.info(f"Görsel promptu üretildi (başlık BASILI: {headline[:50]!r})")
            else:
                prompt = _assemble_image_prompt_clean(scene, "Wide 16:9 landscape composition")
                ops.info(f"Görsel promptu üretildi (TEMİZ/metinsiz; caption başlığı: {headline[:50]!r})")
            return prompt
        except Exception as e:
            ops.error(f"Görsel prompt üretme hatası: {e}", exception=e)
            raise

    def _generate_and_download_from_kie(self, prompt: str) -> str:
        """Kie AI'a task gönder (jobs/createTask), recordInfo ile polling, indir.
        16:9 LinkedIn formatı. Twitter projesindeki çalışan pattern'in kopyası.
        """
        KIE_BASE = "https://api.kie.ai/api/v1"
        headers = {
            "Authorization": f"Bearer {settings.KIE_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": KIE_MODEL,
            "input": {
                "prompt": prompt,
                "aspect_ratio": "16:9",
                "resolution": KIE_RESOLUTION,
            },
        }
        try:
            r = requests.post(f"{KIE_BASE}/jobs/createTask", headers=headers,
                              json=payload, timeout=30)
            r.raise_for_status()
            data = r.json()
            task_id = (data.get("data") or {}).get("taskId")
            if not task_id:
                ops.error("Kie AI taskId yok", message=str(data)[:300])
                raise Exception("Kie API yanıtında taskId yok")
            ops.info(f"Kie AI task: {task_id}")
        except Exception as e:
            ops.error("Kie AI createTask hatası", exception=e)
            raise

        poll_url = f"{KIE_BASE}/jobs/recordInfo"
        for i in range(72):  # ~6 dk
            time.sleep(5)
            try:
                pr = requests.get(poll_url, headers=headers,
                                  params={"taskId": task_id}, timeout=15)
                pr.raise_for_status()
                pd = pr.json()
                d = pd.get("data") or {}
                state = (d.get("state") or "").lower()
                if state in ("success", "completed", "succeeded"):
                    result = d.get("resultJson") or d.get("result") or {}
                    if isinstance(result, str):
                        import json as _json
                        try:
                            result = _json.loads(result)
                        except Exception:
                            result = {}
                    urls = result.get("resultUrls") or result.get("urls") or []
                    if urls and isinstance(urls, list):
                        image_url = urls[0]
                        ops.info(f"Görsel URL hazır: {image_url[:80]}…")
                        img_response = requests.get(image_url, timeout=30)
                        img_response.raise_for_status()
                        fd, temp_path = tempfile.mkstemp(suffix=".png")
                        with os.fdopen(fd, "wb") as f:
                            f.write(img_response.content)
                        ops.info(f"Görsel indirildi: {temp_path}")
                        return temp_path
                    ops.error("Kie AI tamam ama URL yok", message=str(pd)[:300])
                    raise Exception("Kie AI: URL bulunamadı")
                if state in ("failed", "error"):
                    msg = d.get("failMsg") or d.get("errorMsg", "?")
                    ops.error(f"Kie AI task FAILED: {msg}")
                    raise Exception(f"Kie AI Task Failed: {msg}")
            except requests.HTTPError as e:
                ops.warning(f"Kie polling HTTP hatası: {e}")
        raise Exception("Kie AI polling zaman aşımı (6dk)")
