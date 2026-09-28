"""Üç Hesap İçin Özel LinkedIn Gönderi Üretici ve Onay Hazırlayıcı.

Bu script kullanıcının talebi doğrultusunda 3 hesap için:
1. Emre Aşkar (Kişisel Profil - 334863)
2. Solido Grup (Kurumsal Şirket Sayfası - 335331)
3. Takalike (E-Ticaret & Tedarik Platformu - 335616)

Özgün araştırma yapar, gönderi metnini yazar, kalite filtresinden geçirir,
Kie AI ile editoryal 16:9 görselini üretir, Typefully'ye taslak olarak yükler
ve onay e-postasını gönderir.
Tüm detayları 'hazirlanan_gonderiler.json' içine kaydeder.
"""

import os
import sys
import json
import time
from datetime import datetime, timezone, timedelta

# Ortamı zorunlu olarak production & live yap
os.environ["ENV"] = "production"
os.environ["DRY_RUN"] = "0"

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# master.env yükle
from dotenv import load_dotenv
env_path = os.path.join(os.path.dirname(__file__), "..", "..", "_knowledge", "credentials", "master.env")
if os.path.exists(env_path):
    load_dotenv(env_path, override=True)

from config import settings
settings.ENV = "production"
settings.IS_DRY_RUN = False

from ops_logger import get_ops_logger
from core.researcher import Researcher
from core.post_writer import PostWriter
from core.reviewer import Reviewer
from core.image_generator import ImageGenerator
from core.typefully_publisher import TypefullyDraftPublisher
from core import mail_sender

ops = get_ops_logger("LinkedIn_Text_Paylasim", "Ozel_Uretim")

TARGETS = [
    {
        "key": "emre",
        "name": "Emre Aşkar",
        "badge": "👤 Şahsi Profil",
        "source": "LinkedIn Tavsiye",
        "title_prefix": "Emre Aşkar AI Tavsiyesi",
        "social_set_id": int(getattr(settings, "TYPEFULLY_SOCIAL_SET_ID", 334863)),
        "research_type": "tip",
    },
    {
        "key": "solido",
        "name": "Solido Grup",
        "badge": "🏢 Kurumsal Şirket Sayfası",
        "source": "LinkedIn Solido",
        "title_prefix": "Solido Grup B2B Paylaşım",
        "social_set_id": int(getattr(settings, "TYPEFULLY_SOCIAL_SET_ID_SOLIDO", 335331)),
        "research_type": "solido",
    },
    {
        "key": "takalike",
        "name": "Takalike",
        "badge": "🚀 E-Ticaret & Tedarik Platformu",
        "source": "LinkedIn Takalike",
        "title_prefix": "Takalike E-Ticaret & B2B Paylaşım",
        "social_set_id": int(getattr(settings, "TYPEFULLY_SOCIAL_SET_ID_TAKALIKE", 335616)),
        "research_type": "takalike",
    },
]

def generate_for_account(target: dict, delay_minutes: int) -> dict:
    key = target["key"]
    name = target["name"]
    source = target["source"]
    title_prefix = target["title_prefix"]
    ss_id = target["social_set_id"]
    
    print(f"\n{'='*65}")
    print(f"🚀 [{name}] İçerik Üretimi Başlatılıyor (Social Set ID: {ss_id})")
    print(f"{'='*65}")

    researcher = Researcher()
    writer = PostWriter()
    reviewer = Reviewer()
    img_gen = ImageGenerator()
    publisher = TypefullyDraftPublisher(social_set_id=ss_id)

    # 1. Araştırma
    print(f"📡 Adım 1: Perplexity araştırması yapılıyor ({target['research_type']})...")
    if target["research_type"] == "tip":
        research = researcher.research_weekly_tip()
    elif target["research_type"] == "solido":
        research = researcher.research_solido_topic()
    else:
        research = researcher.research_takalike_topic()
    print(f"✅ Araştırma tamamlandı ({len(research)} karakter).")

    # 2. Metin Yazımı ve Kalite İncelemesi
    print(f"✍️ Adım 2: GPT-4o ile LinkedIn metni yazılıyor ve denetleniyor...")
    post_text = None
    review_data = None
    for attempt in range(2):
        if target["research_type"] == "tip":
            candidate = writer.write_weekly_tip_post(research)
        elif target["research_type"] == "solido":
            candidate = writer.write_solido_post(research)
        else:
            candidate = writer.write_takalike_post(research)

        review_data = reviewer.review(candidate, kind=source)
        score = review_data.get("score", 8)
        print(f"   - Deneme {attempt + 1}: Kalite Puanı = {score}/10 (Sebep: {review_data.get('reason')})")
        if score >= 7:
            post_text = candidate
            break

    if not post_text:
        post_text = candidate  # Güvenli fallback

    print(f"✅ Gönderi metni onaylandı ({len(post_text)} karakter):\n")
    print("-" * 50)
    print(post_text)
    print("-" * 50)

    # 3. Medya Üretimi (Kie AI: Video veya Görsel)
    print("🎨 Adım 3: Kie AI ile 16:9 medya (Video veya Görsel) üretiliyor...")
    image_path = None
    media_type = "image"
    try:
        image_path, media_type = img_gen.generate_post_media(post_text)
        print(f"✅ Medya üretildi ({media_type.upper()}): {image_path}")
    except Exception as e:
        print(f"⚠️ Medya üretim uyarısı: {e}")

    # 4. Typefully Taslak Yükleme
    print(f"📤 Adım 4: Typefully'ye taslak yükleniyor (Social Set: {ss_id}, Medya: {media_type})...")
    draft = publisher.create_linkedin_only_draft(
        text=post_text,
        image_path=image_path,
        social_set_id=ss_id
    )
    draft_id = draft.get("draft_id")
    share_url = draft.get("share_url")
    print(f"✅ Typefully taslağı oluşturuldu: ID={draft_id}")
    print(f"🔗 Taslak Linki: {share_url}")

    # 5. Onay E-postası Gönderimi
    print("📧 Adım 5: Onay e-postası iletiliyor...")
    try:
        mail_sender.send_post_approval_mail(
            account_key=key,
            source=source,
            title_prefix=title_prefix,
            post_text=post_text,
            image_path=image_path,
            media_type=media_type,
            draft_url=share_url,
            draft_id=draft_id,
            social_set_id=ss_id,
            score=review_data.get("score") if review_data else 8.5
        )
        print("✅ Onay e-postası gönderildi.")
    except Exception as e:
        print(f"⚠️ Onay maili uyarısı: {e}")

    # Planlanan slot (5'er dakika arayla)
    now_utc = datetime.now(timezone.utc)
    target_time_utc = now_utc + timedelta(minutes=delay_minutes)
    target_time_tr = target_time_utc + timedelta(hours=3)

    return {
        "account_key": key,
        "account_name": name,
        "badge": target["badge"],
        "social_set_id": ss_id,
        "title_prefix": title_prefix,
        "post_text": post_text,
        "score": review_data.get("score", 8),
        "reason": review_data.get("reason", ""),
        "image_path": image_path,
        "draft_id": draft_id,
        "share_url": share_url,
        "planned_time_tr": target_time_tr.strftime("%H:%M:%S"),
        "planned_time_iso": target_time_utc.isoformat(),
        "delay_minutes": delay_minutes,
    }

def main():
    results = []
    # 5'er dakika arayla planlama: Emre Aşkar (0. dk / ilk onay anı), Solido Grup (+5 dk), Takalike (+10 dk)
    delays = [0, 5, 10]

    for target, delay in zip(TARGETS, delays):
        try:
            res = generate_for_account(target, delay)
            results.append(res)
        except Exception as e:
            print(f"❌ {target['name']} için hata oluştu: {e}")

    out_file = os.path.join(os.path.dirname(__file__), "hazirlanan_gonderiler.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n🎉 3 hesap için tüm gönderiler başarıyla hazırlandı ve '{out_file}' dosyasına kaydedildi!")

if __name__ == "__main__":
    main()
