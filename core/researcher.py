"""
Perplexity API ile güncel AI haberleri araştırması.
n8n'deki "AI Haberleri" node'unun birebir karşılığı.
"""
from ops_logger import get_ops_logger
ops = get_ops_logger("LinkedIn_Text_Paylasim", "Researcher")
import requests
from datetime import datetime, timedelta

from config import settings


class Researcher:
    """Perplexity API kullanarak güncel AI haberleri/tipsler araştırır."""

    def __init__(self):
        self.api_key = settings.PERPLEXITY_API_KEY
        self.base_url = settings.PERPLEXITY_BASE_URL

    def research_weekly_news(self) -> str:
        """
        Haftanın AI haberlerini araştırır.
        n8n Workflow 1 (LinkedIn Automation) — "AI Haberleri" node'u.
        """
        today = datetime.now()
        current_date = today.strftime("%Y-%m-%d")
        window_start = (today - timedelta(days=7)).strftime("%Y-%m-%d")

        prompt = (
            f"You are a research assistant for a Turkish professional's LinkedIn page. "
            f"Audience: business people, founders, and knowledge workers in Turkey who follow "
            f"AI to use it at work. They are not researchers; they care about real, usable news.\n\n"
            f"Task: find the most important AI developments ANNOUNCED between {window_start} and "
            f"{current_date} (the last 7 days). Today is {current_date}.\n\n"
            f"HARD RULES:\n"
            f"1. Only include developments that were actually announced/published in this 7-day "
            f"window and that you can attribute to a named, reputable source (e.g. the company's "
            f"own announcement, Reuters, Bloomberg, TechCrunch, The Verge, official blog). "
            f"For each item, name the source.\n"
            f"2. NO speculation, rumors, leaks, or unconfirmed roadmaps. Do NOT invent product or "
            f"model version numbers. If you are not sure a model/product exists and was released in "
            f"this window, LEAVE IT OUT. It is better to report fewer, solid items than many shaky ones.\n"
            f"3. Prefer developments this audience can act on or would find genuinely useful: new "
            f"tools/features people can try, major product launches, notable funding, enterprise/"
            f"business moves, regulation that affects work. Skip pure academic papers and vague hype.\n"
            f"4. Give me 4 to 6 items. For each: one line on WHAT happened (concrete, with the real "
            f"name of the company/product), and one short line on WHY it matters for someone using "
            f"AI at work. Include the source name in parentheses.\n"
            f"5. Facts only. No filler sentences like 'AI is changing the world'.\n\n"
            f"Return a plain list, newest/biggest first."
        )

        return self._query_perplexity(prompt)

    def research_weekly_tip(self) -> str:
        """
        Haftanın AI tavsiyesini araştırır.
        n8n Workflow 2 (LinkedIn AI Tips) — "AI Haberleri" node'u.
        """
        current_date = datetime.now().strftime("%Y-%m-%d")

        prompt = (
            f"You are a research assistant for a LinkedIn post writer.\n\n"
            f"Find the latest AI tip of this week. Make sure this is non-technical "
            f"everyday tip that anyone can use. Use your gut feeling to make sure "
            f"this is not a tip that every single person would know, so we can "
            f"actually provide them something valuable. Make sure tips are not "
            f"extremely easy because people already know the basics, such as "
            f"providing as much context as possible to the AI. That's a known thing.\n\n"
            f"Instead, focus on more advanced topics such as:\n"
            f"1. Using DeepResearch functionality on ChatGPT or Claude Code\n"
            f"2. Using Kimi for great presentations\n"
            f"3. Why Claude is so popular\n\n"
            f"These three examples mentioned above are just examples. Do not copy "
            f"them, but let them inspire you.\n\n"
            f"Current Date: {current_date}"
        )

        return self._query_perplexity(prompt)

    def research_solido_topic(self, weekday: int | None = None) -> str:
        """
        Solido Grup için haftalık 3 sütunlu B2B stratejisine göre içgörü araştırır:
        - Salı (1): Kurumsal Web Mimarisi & Dönüşüm (SiteSepeti odağı)
        - Çarşamba (2): Performans Pazarlaması, Google Ads & Yerel SEO (BirMilyonNokta odağı)
        - Perşembe (3): Saha Verisi, B2B Otorite & KOBİ Büyümesi (Solido Grup kurumsal gücü)
        """
        now = datetime.now()
        current_date = now.strftime("%Y-%m-%d")
        day_idx = weekday if weekday is not None else now.weekday()

        if day_idx == 1:
            theme_name = "Kurumsal Web Mimarisi & Dönüşüm Optimizasyonu (SiteSepeti Odağı)"
            focus = (
                "Focus: Corporate website architecture, conversion rate optimization (CRO), "
                "mobile speed, high-converting WhatsApp & contact button placements, and "
                "the 3 critical mistakes SMEs make on their corporate websites that lose customers."
            )
        elif day_idx == 2:
            theme_name = "Performans Pazarlaması, Google Ads & Yerel Arama / SEO (BirMilyonNokta Odağı)"
            focus = (
                "Focus: Practical Google Ads / Meta Ads budget protection for SMEs, negative keywords, "
                "local search visibility (Google Maps / Business Profile, business directories), and "
                "driving inbound customer calls without wasting ad spend."
            )
        elif day_idx == 3:
            theme_name = "Saha Verisi, B2B Otorite & KOBİ Büyümesi (Solido Grup Ekosistemi)"
            focus = (
                "Focus: Practical B2B growth benchmarks for Turkish SMEs, why digital automation & professional "
                "agency management outperforms chaotic in-house efforts, and actionable data on scaling business online."
            )
        else:
            theme_name = "KOBİ Dijital Dönüşüm & B2B Büyüme Stratejisi"
            focus = (
                "Focus: High-impact web conversion, local search optimization, or smart ad budget management "
                "for Turkish SMEs and business owners."
            )

        prompt = (
            f"You are a B2B research strategist for Solido Grup in Turkey (180,000 SME clients, "
            f"70-person team, SiteSepeti web factory, BirMilyonNokta local SEO directory, Google Partner).\n"
            f"Theme: {theme_name}\n"
            f"{focus}\n\n"
            f"Find 1 concrete, highly actionable insight or field case that directly impacts an SME owner's revenue or efficiency.\n"
            f"Rules: Solid facts, practical takeaway, no generic motivational fluff. Date: {current_date}"
        )
        return self._query_perplexity(prompt)

    def research_takalike_topic(self, weekday: int | None = None) -> str:
        """
        Takalike için haftalık 3 sütunlu E-Ticaret & B2B stratejisine göre içgörü araştırır:
        - Pazartesi (0): Pazaryeri Dinamikleri, Algoritmalar & Kârlı Ürün Seçimi (Trendyol, Hepsiburada, Amazon)
        - Çarşamba (2): Stoksuz E-Ticaret (Dropshipping), Lojistik & Kargo Maliyet Yönetimi
        - Cuma (4): B2B Tedarikçi / İmalatçı Gücü, 500K+ Ürün Havuzu & Toptan Ticaretin Dijitalleşmesi
        """
        now = datetime.now()
        current_date = now.strftime("%Y-%m-%d")
        day_idx = weekday if weekday is not None else now.weekday()

        if day_idx == 0:
            theme_name = "Pazaryeri Satıcı Stratejileri, Fiyatlama & Kârlı Ürün Seçimi"
            focus = (
                "Focus: Practical marketplace dynamics in Turkey (Trendyol, Hepsiburada, Amazon TR), "
                "calculating real profit margins after marketplace commissions, avoiding price-war traps, "
                "high-converting product titles/descriptions, and identifying winning/trending product categories."
            )
        elif day_idx == 2:
            theme_name = "Stoksuz E-Ticaret (Dropshipping) Operasyonu, Lojistik & Kargo Maliyet Optimizasyonu"
            focus = (
                "Focus: Realistic stockless e-commerce operations, managing delivery and return shipping costs, "
                "preventing out-of-stock cancellations via automated multi-channel sync (ikas, IdeaSoft, Shopier), "
                "and how sellers protect margins against escalating logistics expenses."
            )
        elif day_idx == 4:
            theme_name = "B2B Tedarikçi, İmalatçı Dağıtım Gücü & Dijital Toptan Ticaret"
            focus = (
                "Focus: Manufacturers and wholesale suppliers expanding into multi-channel digital retail, "
                "how digitizing product catalog data enables thousands of sellers to sell their inventory simultaneously, "
                "and the modern synergy between production facilities and dropshipping seller networks."
            )
        else:
            theme_name = "E-Ticaret Büyümesi, Stoksuz Satış & Tedarik Zinciri Verimliliği"
            focus = (
                "Focus: Actionable tips for e-commerce entrepreneurs and suppliers on scaling sales, "
                "marketplace profit optimization, or inventory risk reduction."
            )

        prompt = (
            f"You are a senior e-commerce and retail analyst researching for Takalike's corporate LinkedIn page in Turkey "
            f"(Takalike: B2B/B2C stockless e-commerce platform with 500,000+ products, connecting verified Turkish suppliers "
            f"with online sellers and marketplace stores on Trendyol, Hepsiburada, Amazon, ikas, IdeaSoft).\n"
            f"Theme: {theme_name}\n"
            f"{focus}\n\n"
            f"Find 1 concrete, highly actionable insight, benchmark, or operational case study for Turkish e-commerce professionals.\n"
            f"HARD RULES:\n"
            f"- Strictly practical, operational, data-driven.\n"
            f"- NO cheap 'get rich quick with dropshipping' clichés or motivational fluff.\n"
            f"- Real dynamics, real pain points (shipping, commissions, returns, stock sync, supplier relations).\n"
            f"Date: {current_date}"
        )
        return self._query_perplexity(prompt)

    def _query_perplexity(self, prompt: str) -> str:
        """Perplexity API'ye sorgu gönderir ve sonucu döndürür."""
        if settings.IS_DRY_RUN:
            ops.info(f"[DRY-RUN] Perplexity sorgusu atlanıyor. Prompt: {prompt[:100]}...")
            return "[DRY-RUN] Bu hafta AI dünyasında önemli gelişmeler yaşandı. OpenAI yeni modelini tanıttı."

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "sonar",
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            ops.info(f"Perplexity araştırması tamamlandı ({len(content)} karakter)")
            return content
        except Exception as e:
            ops.error(f"Perplexity API hatası: {e}", exception=e)
            raise
