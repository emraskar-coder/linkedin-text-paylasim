"""LinkedIn post yazımı (OpenAI gpt-5.4 birincil, gpt-4o-mini fallback).

Perplexity araştırmasından bir LinkedIn postu üretir. Birincil çağrı ücretsiz
ornek-site.com tier'ı üzerinden gpt-5.4 (raw HTTP); hata olursa gpt-4o-mini SDK
fallback'ine düşer. Kalite değerlendirmesi core/reviewer.py'nin işi.
"""
from ops_logger import get_ops_logger
ops = get_ops_logger("LinkedIn_Text_Paylasim", "PostWriter")
import os
from datetime import datetime
import requests
from openai import OpenAI

from config import settings

_GPT_MODEL = "gpt-4o"
_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_OPENAI_KEY = (os.getenv("OPENAI_API_KEY")
               or os.getenv("OPENAI_API_KEY_DATA_SHARED")
               or os.getenv("OPENAI_API_KEY"))


def _post_openai_text(system, user, max_tokens=500):
    body = {"model": _GPT_MODEL, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    r = requests.post(_OPENAI_URL, headers={
        "Authorization": f"Bearer {_OPENAI_KEY}", "Content-Type": "application/json"},
        json=body, timeout=120)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


class PostWriter:
    """gpt-4o (birincil) ile LinkedIn postu yazar, gpt-4o-mini fallback."""

    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY") or settings.OPENAI_API_KEY
        self.client = OpenAI(api_key=api_key)

    def write_weekly_news_post(self, research_content: str) -> str:
        """
        Haftanın AI haberlerinden LinkedIn postu yazar (Emre Aşkar kişisel profil).
        """
        current_date = datetime.now().isoformat()

        system_message = (
            f"Bu haftanın yapay zeka gelişmeleri: \n{research_content}\n\n"
            f"Date: {current_date}"
        )

        user_message = (
            "Yukarıdaki araştırmadan, isimli kaynağa dayanan ve DOĞRULANABİLİR 3 gelişmeyi seç. "
            "Bunlardan Türkiye'deki profesyonellerin işinde işine yarayacak, en somut olanları öncele. "
            "Emre Aşkar'ın kişisel LinkedIn profili için profesyonel bir LinkedIn postu yaz.\n\n"
            "KURALLAR (KESİNLİKLE UYULACAK):\n"
            "1. Toplam uzunluk 600 karakteri geçmesin; yine de kısa ve taranabilir olsun.\n"
            "2. Kısa bir başlık satırıyla başla. Sonra 3 madde (-). HER madde: gerçek şirket/ürün "
            "ADINI ver + TAM OLARAK ne değişti onu yaz (belirsiz fiil değil). 8-16 kelime.\n"
            "3. DOĞRULUK önce gelir. Araştırmadaki niteleyiciyi koru, abartma, uydurma ekleme.\n"
            "4. Son satır: tek cümlelik çıkarım — bu hafta AI'yi işinde kullanan biri için ne anlama geliyor.\n"
            "5. Boş giriş/çıkış cümlesi yok ('Hey ağım' vb. YASAK). Emoji en fazla 1 adet.\n\n"
            "Sadece LinkedIn'de paylaşılacak yazıyı çıktı olarak ver. Başka hiçbir açıklama ekleme."
        )

        return self._generate(system_message, user_message)

    def write_weekly_tip_post(self, research_content: str) -> str:
        """
        AI tavsiyesinden LinkedIn postu yazar (Emre Aşkar kişisel profil).
        """
        current_date = datetime.now().isoformat()

        system_message = (
            f"Kullanman için araştırma: {research_content}\n\n"
            f"Date: {current_date}"
        )

        user_message = (
            "İnsanların günlük hayatlarında kullanabilecekleri değerli fakat az bilinen bir AI tavsiyesini KISA ve ÖZ bir LinkedIn postu olarak yaz.\n\n"
            "KURALLAR (KESİNLİKLE UYULACAK):\n"
            "1. Gönderi UZUNLUĞU KESİNLİKLE MAKSİMUM 450 KARAKTER olmalıdır. Kesinlikle geçme.\n"
            "2. Çok kısa bir başlık cümlesiyle başla, ardından doğrudan uygulamanın adını vererek nasıl kullanılacağını SADECE 1-2 çok kısa cümle ile açıkla.\n"
            "3. Metni ASLA yarıda kesme, anlamlı bir şekilde bitir.\n"
            "4. YZ yerine AI kısaltmasını kullan.\n"
            "5. Boş giriş veya çıkış cümleleri kullanma ('Hey ağım', 'İşte harika ipucu' vb. YASAK).\n"
            "6. Emojileri minimumda tut (maksimum 2 adet).\n\n"
            "Sadece LinkedIn'de paylaşılacak yazıyı çıktı olarak ver. Başka hiçbir açıklama ekleme."
        )

        return self._generate(system_message, user_message)

    def write_solido_post(self, topic_or_research: str) -> str:
        """
        Solido Grup kurumsal LinkedIn sayfası için 70/20/10 stratejisine uygun B2B gönderisi yazar.
        Ekosistem: Solido Grup (Çatı / Google Partner), SiteSepeti (Web Fabrikası), BirMilyonNokta (Yerel SEO).
        Portföy: 180.000+ işletme tecrübesi, 70 kişilik ekip.
        """
        current_date = datetime.now().isoformat()
        system_message = (
            "Sen 180.000'e yakın işletmeye dokunan, Google Partner sertifikalı, bünyesinde SiteSepeti "
            "(günde 10-12 kurumsal site üreten altyapı) ve BirMilyonNokta (yerel firma rehberi & yerel SEO ağı) "
            "markalarını barındıran, 70 kişilik operasyona sahip Solido Grup'un B2B Baş İçerik Stratejistisin.\n\n"
            "Hedef Kitle: KOBİ sahipleri, şirket kurucuları, pazarlama yöneticileri ve işletme ortakları.\n"
            f"Gündem / Araştırma: {topic_or_research}\nTarih: {current_date}"
        )
        user_message = (
            "Solido Grup LinkedIn sayfası için '70/20/10 Değer-Güven-Aksiyon' modelinde profesyonel bir B2B gönderisi yaz.\n\n"
            "İÇERİK MİMARİSİ (ZORUNLU):\n"
            "1. KANCA (Hook): İşletme sahibinin sahada karşılaştığı somut bir maliyet, kayıp veya dönüşüm sorunuyla başla.\n"
            "2. DEĞER & ÇÖZÜM (%70): Teknik jargona boğmadan, işletmenin hemen uygulayabileceği 2-3 net rehberlik/içgörü maddesi ver.\n"
            "3. SAHA KANITI & OTORİTE (%20): Solido Grup ekosisteminin (SiteSepeti web altyapısı, BirMilyonNokta yerel ağı veya Google Partner tecrübesi) sahadaki gözlemine veya verisine atıf yap.\n"
            "4. KAPANIŞ (%10): Tartışma açan kaliteli bir B2B sorusu veya kurumsal profesyonel danışmanlık çağrısı ile tamamla.\n\n"
            "KURALLAR:\n"
            "- Uzunluk: 450 - 750 karakter arasında olsun (LinkedIn için optimum taranabilir uzunluk).\n"
            "- Paragraflar arasında boşluk bırak; nefes alan, mobilde kolay okunan bir düzen kur.\n"
            "- Ucuz reklam, 'hemen bizi arayın / kampanya' gibi ajans klişeleri KESİNLİKLE YASAK.\n"
            "- Maksimum 2 profesyonel emoji (örn. 📌, 💡).\n"
            "- En fazla 2 kurumsal hashtag ekle (örn: #SolidoGrup #B2BBüyüme).\n\n"
            "Sadece LinkedIn post metnini döndür."
        )
        return self._generate(system_message, user_message)

    def write_takalike_post(self, topic_or_research: str) -> str:
        """
        Takalike kurumsal LinkedIn sayfası için 70/20/10 modelinde E-Ticaret / Tedarikçi / Dropshipping gönderisi yazar.
        Ekosistem: Takalike Eticaret ve Teknoloji Ltd. Şti. (500.000+ ürün havuzu, tedarikçi & satıcı ağı,
        pazaryeri tek tık entegrasyonu [Trendyol, Hepsiburada, Amazon], ikas/IdeaSoft/Shopier altyapısı).
        """
        current_date = datetime.now().isoformat()
        system_message = (
            "Sen 500.000'den fazla ürün havuzuna sahip, binlerce e-ticaret satıcısı ile Türkiye'nin önde gelen "
            "imalatçı ve toptancılarını buluşturan, sıfır stok riskiyle pazaryerlerinde (Trendyol, Hepsiburada, "
            "Amazon) ve e-ticaret mağazalarında tek tıkla satış sağlayan Takalike'ın (Takalike Eticaret ve Teknoloji) "
            "Kıdemli E-Ticaret ve B2B Stratejistisin.\n\n"
            "Hedef Kitle: E-ticaret girişimcileri, pazaryeri mağaza sahipleri, toptancılar, imalatçılar ve kurumsal e-ticaret yöneticileri.\n"
            f"Gündem / Araştırma: {topic_or_research}\nTarih: {current_date}"
        )
        user_message = (
            "Takalike LinkedIn sayfası için '70/20/10 Değer-Güven-Aksiyon' modelinde profesyonel, modern ve dinamik bir sektör gönderisi yaz.\n\n"
            "İÇERİK MİMARİSİ (ZORUNLU):\n"
            "1. KANCA (Hook): E-ticaret satıcısının veya imalatçısının sahada karşılaştığı somut bir maliyet (komisyon, kargo, stok batığı, iade vb.) veya operasyonel zorlukla başla.\n"
            "2. DEĞER & ÇÖZÜM (%70): Klişelerden uzak, satıcının veya tedarikçinin işinde hemen uygulayabileceği 2-3 net, madde imli stratejik içgörü/çözüm sun.\n"
            "3. SAHA KANITI & EKOSİSTEM (%20): Takalike ekosisteminin (500K+ ürün havuzu, otomatik stok/fiyat senkronizasyonu veya tedarikçi ağı) sahadaki operasyonel gücüne atıf yap.\n"
            "4. KAPANIŞ (%10): Tartışma açan kaliteli bir soru veya ekosisteme katılma daveti ile tamamla.\n\n"
            "KURALLAR:\n"
            "- DİL VE GRAMER: Türkçesi kusursuz, pürüzsüz ve doğal olmalı. Ek yığılması, yapay çeviri kokusu veya bozuk kelimeler (örn. 'iadelerdelerse' gibi morfolojik hatalar) KESİNLİKLE YASAKTIR.\n"
            "- SEKTÖREL TERİMLER: E-ticaret kavramlarını doğru kullan. 'SDK' gibi ilgisiz yazılım terimleri yerine 'SKU', 'stok kodu', 'katalog verisi' veya 'pazaryeri entegrasyonu' gibi doğru terimleri kullan.\n"
            "- Uzunluk: 450 - 750 karakter arasında olsun (LinkedIn için optimum taranabilir uzunluk).\n"
            "- Paragraflar arasında nefes payı bırak; mobilde kolay taranabilir olsun.\n"
            "- Ucuz 'oturduğunuz yerden zengin olun', 'kolay dropshipping' gibi amatör söylemler KESİNLİKLE YASAK. Ciddi, operasyonel ve teknolojik bir duruş sergile.\n"
            "- Maksimum 2 profesyonel emoji (örn. 📦, 💡).\n"
            "- En fazla 2 hashtag (#Takalike #Eticaret).\n\n"
            "Sadece LinkedIn post metnini döndür."
        )
        return self._generate(system_message, user_message)

    def _generate(self, system_message: str, user_message: str) -> str:
        """gpt-4o (birincil) ile post üretir; hata olursa gpt-4o-mini fallback."""
        if settings.IS_DRY_RUN:
            ops.info("[DRY-RUN] post yazma atlanıyor.")
            return "[DRY-RUN] 🚀 LinkedIn Gönderisi Simülasyonu:\n\nİş dünyasında dijital dönüşüm ve operasyonel verimlilik her zamankinden kritik."

        # Birincil: OpenAI gpt-4o
        try:
            content = _post_openai_text(system_message, user_message, max_tokens=600)
            ops.info(f"Post yazıldı (gpt-4o, {len(content)} karakter)")
            return content
        except Exception as primary_err:
            ops.warning(f"gpt-4o post yazma hatası, gpt-4o-mini'ye düşülüyor: {primary_err}")

        # Fallback: SDK gpt-4o-mini
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.7,
                max_tokens=500
            )
            content = response.choices[0].message.content.strip()
            ops.info(f"Post yazıldı (gpt-4o-mini fallback, {len(content)} karakter)")
            return content
        except Exception as e:
            ops.error(f"GPT-4o-mini post yazma hatası: {e}", exception=e)
            raise
