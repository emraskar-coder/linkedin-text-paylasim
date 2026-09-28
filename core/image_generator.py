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

# GPT Image 2 (görsel motoru) ve Gemini Omni Video (video motoru)
KIE_MODEL = "gpt-image-2-text-to-image"
KIE_RESOLUTION = "2K"
KIE_VIDEO_MODEL = os.getenv("KIE_VIDEO_MODEL", "gemini-omni-video")

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

    def generate_post_media(self, post_text: str, force_type: str | None = None) -> tuple[str, str]:
        """
        Post metnini analiz ederek dinamik olarak görsel veya video üretir.
        
        Returns:
            (media_path, media_type) -> (".../temp.mp4", "video") veya (".../temp.png", "image")
        """
        if settings.IS_DRY_RUN:
            ops.info("[DRY-RUN] Medya üretme atlanıyor.")
            return None, "image"

        intent = self._analyze_media_intent(post_text)
        media_type = force_type or intent.get("media_type", "image")
        scene_en = intent.get("scene_en", "")
        headline_tr = intent.get("headline_tr", "")

        ops.info("Medya Kararı", f"Seçilen format: {media_type.upper()} | Sebep: {intent.get('reason', '-')}")

        if media_type == "video":
            video_path = self._generate_and_download_video_from_kie(scene_en)
            if video_path and os.path.exists(video_path):
                return video_path, "video"
            ops.warning("Kie AI video üretimi tamamlanamadı; otomatik olarak statik görsele geçiliyor...")

        # Statik görsel üretimi (varsayılan veya video fallback)
        print_headline = os.getenv("LINKEDIN_IMAGE_HEADLINE", "0") == "1"
        if print_headline and headline_tr:
            prompt = _assemble_image_prompt(headline_tr, scene_en, "Wide 16:9 landscape composition")
        else:
            prompt = _assemble_image_prompt_clean(scene_en, "Wide 16:9 landscape composition")

        image_path = self._generate_and_download_from_kie(prompt)
        return image_path, "image"

    def generate_post_image(self, post_text: str) -> str:
        """Geriye dönük uyumluluk: doğrudan üretilen medya dosya yolunu döner."""
        path, _ = self.generate_post_media(post_text)
        return path

    def _analyze_media_intent(self, post_text: str) -> dict:
        """Post metninden: video mu görsel mi kararı + başlık + İngilizce sahne açıklaması çıkarır."""
        import json as _json
        system_message = (
            "You are an expert creative director for an executive LinkedIn channel in Turkey (covering Solido Grup B2B, Takalike e-commerce, and AI). "
            "Your job is to analyze a LinkedIn post and decide the best media format: VIDEO or IMAGE.\n\n"
            "CRITERIA:\n"
            "- Choose 'video' (16:9 cinematic video) if the post discusses: dynamic physical processes, warehouse logistics, "
            "shipping/delivery, tool workflows, automation in action, fast-paced marketplace operations, or tangible business momentum.\n"
            "- Choose 'image' (16:9 editorial photograph) if the post discusses: analytical metrics, strategic thinking, rules/checklists, "
            "mindset, questions/polls, or quiet executive reflection.\n\n"
            "HARD BANS for scene_en: no glowing holographic brains, no robot hands, no futuristic sci-fi neon, no cartoon/CGI characters, no money bags, no floating binary code.\n\n"
            "Output JSON with:\n"
            '  "media_type": "video" or "image",\n'
            '  "reason": "1 short sentence explaining why video or image was chosen",\n'
            '  "headline_tr": "Short punchy Turkish headline (max 7 words)",\n'
            '  "scene_en": "Concrete real-world cinematic description (camera movement if video, depth of field)"'
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
            if not data.get("scene_en"):
                data["scene_en"] = "Modern professional enterprise headquarters with natural daylight"
            return data
        except Exception as e:
            ops.warning("Medya intent analizi hatası, varsayılan görsele geçiliyor", str(e))
            return {
                "media_type": "image",
                "reason": "fallback",
                "headline_tr": "",
                "scene_en": "Modern professional corporate environment with warm natural light"
            }

    def _generate_and_download_video_from_kie(self, scene_en: str) -> str | None:
        """Kie AI jobs/createTask üzerinden 16:9 sinematik video üretir ve indirir."""
        KIE_BASE = "https://api.kie.ai/api/v1"
        headers = {
            "Authorization": f"Bearer {settings.KIE_API_KEY}",
            "Content-Type": "application/json",
        }
        prompt = (
            f"Cinematic 16:9 realistic corporate documentary footage, natural 4k lighting, "
            f"smooth steady camera movement, photorealistic texture. Scene: {scene_en}"
        )
        payload = {
            "model": KIE_VIDEO_MODEL,
            "input": {
                "prompt": prompt,
                "duration": "4",
                "aspect_ratio": "16:9",
            },
        }
        try:
            ops.info(f"Kie AI video task oluşturuluyor ({KIE_VIDEO_MODEL})...")
            r = requests.post(f"{KIE_BASE}/jobs/createTask", headers=headers, json=payload, timeout=30)
            r.raise_for_status()
            data = r.json()
            task_id = (data.get("data") or {}).get("taskId")
            if not task_id:
                ops.warning("Kie AI video taskId alınamadı", str(data)[:300])
                return None
            ops.info(f"Kie AI video task: {task_id}")
        except Exception as e:
            ops.warning("Kie AI video createTask hatası", str(e))
            return None

        poll_url = f"{KIE_BASE}/jobs/recordInfo"
        for _ in range(36):  # ~3 dakika polling
            time.sleep(5)
            try:
                pr = requests.get(poll_url, headers=headers, params={"taskId": task_id}, timeout=15)
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
                        video_url = urls[0]
                        ops.info(f"Video URL hazır: {video_url[:80]}…")
                        vid_resp = requests.get(video_url, timeout=60)
                        vid_resp.raise_for_status()
                        fd, temp_path = tempfile.mkstemp(suffix=".mp4")
                        with os.fdopen(fd, "wb") as f:
                            f.write(vid_resp.content)
                        ops.success("Video başarıyla indirildi", temp_path)
                        return temp_path
                elif state in ("failed", "error"):
                    msg = d.get("failMsg") or d.get("errorMsg", "?")
                    ops.warning(f"Kie AI video task FAILED: {msg}")
                    return None
            except Exception as e:
                ops.warning("Kie video polling hatası", str(e))
        ops.warning("Kie AI video zaman aşımı, görsele dönülecek")
        return None

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
