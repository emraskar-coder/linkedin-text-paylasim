"""LinkedIn Text Paylaşım — orkestratör.

Pazartesi: Haftanın AI Haberleri  (Source: "LinkedIn Haber")
Perşembe: Haftalık AI Tavsiyesi   (Source: "LinkedIn Tavsiye")

Pipeline (her iki gün için aynı):
  Schedule → Perplexity → gpt-5.4 (post text) → öz-inceleme kalite kapısı
  → gpt-4o-mini (image prompt) → Kie AI (görsel) → yayıncı → Notion log

Kalite kapısı: post yazıldıktan sonra AYRI bir LLM-judge postu 1-10 puanlar.
Eşik altı → bir kez yeniden üret; hâlâ altıysa o koşu ATLANIR (abstain).

Yayın modu tarihe göre otomatik döner (config.AUTONOMOUS_AFTER):
  - KALİBRASYON (tarihten önce): Supabase'e 'draft' yazar + KENDİ onay mailini
    gönderir. kullanici maildeki butona basınca onay servisi slot atar, slot cron
    LinkedIn'e yayınlar.
  - OTONOM (tarihten sonra): Supabase'e 'scheduled' + slot yazar, MAIL ATMAZ.
    Slot cron onaysız yayınlar. Sessiz otonomi.
"""

import logging
import os
import time
from datetime import datetime, timezone, date

import schedule

from logger import setup_logging
from ops_logger import get_ops_logger, wait_all_loggers
from config import settings
from core.researcher import Researcher
from core.post_writer import PostWriter
from core.reviewer import Reviewer
from core.image_generator import ImageGenerator
from core.typefully_publisher import TypefullyDraftPublisher, TypefullyDraftError
from core.native_publisher import NativeDraftError
from core.notion_logger import NotionLogger

ops = get_ops_logger("LinkedIn_Text_Paylasim", "Pipeline")


def _utcnow_date() -> date:
    """Bugünün UTC tarihi. Test'te monkeypatch'lenebilir (flip testi için)."""
    return datetime.now(timezone.utc).date()


def _is_autonomous() -> bool:
    """AUTONOMOUS_AFTER tarihine ULAŞILDIYSA True (otonom sessiz yayın).

    Tarihe kadar kalibrasyon (draft + onay maili); tarihten itibaren otonom
    (scheduled + mail yok). Geçersiz/eksik tarihte güvenli tarafta kalır:
    kalibrasyon (mail'li onay) sürer.
    """
    raw = (getattr(settings, "AUTONOMOUS_AFTER", "") or "").strip()
    try:
        threshold = date.fromisoformat(raw)
    except (ValueError, TypeError):
        ops.warning(f"AUTONOMOUS_AFTER geçersiz ({raw!r}), kalibrasyon modunda kalınıyor")
        return False
    return _utcnow_date() >= threshold


# Eski post_type → yeni Source/Title eşleşmesi (Notion DB için)
_FLOW_MAP = {
    "haber": {
        "source": "LinkedIn Haber",
        "title_prefix": "Emre Aşkar AI Haberleri",
        "research_fn": "research_weekly_news",
        "writer_fn": "write_weekly_news_post",
        "account": "emre",
        "frequency": "weekly",
    },
    "tavsiye": {
        "source": "LinkedIn Tavsiye",
        "title_prefix": "Emre Aşkar AI Tavsiyesi",
        "research_fn": "research_weekly_tip",
        "writer_fn": "write_weekly_tip_post",
        "account": "emre",
        "frequency": "weekly",
    },
    "solido": {
        "source": "LinkedIn Solido",
        "title_prefix": "Solido Grup B2B Paylaşım",
        "research_fn": "research_solido_topic",
        "writer_fn": "write_solido_post",
        "account": "solido",
        "frequency": "triweekly",
    },
    "takalike": {
        "source": "LinkedIn Takalike",
        "title_prefix": "Takalike E-Ticaret & B2B Paylaşım",
        "research_fn": "research_takalike_topic",
        "writer_fn": "write_takalike_post",
        "account": "takalike",
        "frequency": "triweekly",
    },
}


def _run_flow(kind: str) -> None:
    """Ortak pipeline; kind = 'haber', 'tavsiye', 'solido', 'takalike'."""
    flow = _FLOW_MAP[kind]
    source = flow["source"]
    title_prefix = flow["title_prefix"]
    account_key = flow.get("account", "emre")

    # Hedef Typefully Social Set ID belirle (Hesap Karışmasını Önleme Güvenlik Kapısı)
    target_ss_id = settings.TYPEFULLY_SOCIAL_SET_ID
    if account_key == "solido":
        target_ss_id = getattr(settings, "TYPEFULLY_SOCIAL_SET_ID_SOLIDO", 0)
        if not target_ss_id:
            ops.error("Eksik Hesap Ayarı", "Solido Grup için TYPEFULLY_SOCIAL_SET_ID_SOLIDO tanımlı değil! Şahsi hesaba karışmaması için akış durduruldu.")
            return
    elif account_key == "takalike":
        target_ss_id = (
            getattr(settings, "TYPEFULLY_SOCIAL_SET_ID_TAKALIKE", 0)
            or getattr(settings, "TYPEFULLY_SOCIAL_SET_ID_TAKALİKE", 0)
        )
        if not target_ss_id:
            ops.error("Eksik Hesap Ayarı", "Takalike için TYPEFULLY_SOCIAL_SET_ID_TAKALIKE tanımlı değil! Şahsi hesaba karışmaması için akış durduruldu.")
            return

    ops.info("Workflow Başladı", f"{title_prefix} pipeline'ı (Hedef Social Set: {target_ss_id})")
    notion_logger = NotionLogger()

    # Haftalık dedup kontrolü (yalnızca haftalık akışlar için)
    if flow.get("frequency") == "weekly" and notion_logger.is_already_posted_this_week(source):
        ops.info("Duplicate Atlandı", f"Bu hafta zaten {source} draft/onay var")
        return

    image_path = None
    try:
        # 1) Araştırma
        researcher = Researcher()
        ops.info("Adım 1/4", f"Perplexity: {source} araştırması")
        research_content = getattr(researcher, flow["research_fn"])()
        ops.info("Araştırma Tamamlandı", f"{len(research_content)} char")

        # 2) Post yazımı + öz-inceleme kalite kapısı
        #    Eşik altı → BİR KEZ yeniden üret; hâlâ altıysa ABSTAIN (post/mail yok).
        #    Bu kapı HEM kalibrasyon HEM otonom modda çalışır (son güvenlik ağı).
        writer = PostWriter()
        reviewer = Reviewer()
        post_text = None
        review = None
        for attempt in range(2):
            ops.info("Adım 2/4", f"gpt-4o: LinkedIn post metni (deneme {attempt + 1}/2)")
            candidate = getattr(writer, flow["writer_fn"])(research_content)
            ops.info("Post Yazıldı", f"{len(candidate)} char")
            review = reviewer.review(candidate, kind=source)
            if review["score"] >= settings.QUALITY_THRESHOLD:
                post_text = candidate
                ops.info("Kalite Kapısı Geçildi",
                         f"skor={review['score']}/10 (eşik {settings.QUALITY_THRESHOLD})")
                break
            ops.info(
                "Kalite Eşiği Altı",
                f"skor={review['score']}/10 < {settings.QUALITY_THRESHOLD}"
                + (" — yeniden üretiliyor" if attempt == 0 else " — ikinci deneme de altı"),
            )
        if post_text is None:
            ops.info(
                "Atlandı (Abstain)",
                f"Kalite eşiği altı kaldı (skor={review['score'] if review else '?'}/10); "
                "bu koşu post ATILMADI, mail ATILMADI",
            )
            return

        # 3) Görsel
        img_gen = ImageGenerator()
        ops.info("Adım 3/4", "Kie AI: görsel üretimi")
        image_path = img_gen.generate_post_image(post_text)
        if not image_path and not settings.IS_DRY_RUN:
            raise RuntimeError("Görsel üretilemedi — görselsiz LinkedIn postu atılmaz")

        # 4) Yayıncı + Notion log + onay maili.
        from core.threads_adapter import ThreadsAdapter
        th_posts = ThreadsAdapter().adapt(post_text)

        autonomous = _is_autonomous() and settings.USE_NATIVE_PUBLISHER
        if settings.USE_NATIVE_PUBLISHER:
            from core.native_publisher import NativeDraftPublisher
            publisher = NativeDraftPublisher(
                settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY,
                source_project="LinkedIn_Text_Paylasim",
                dry_run=settings.IS_DRY_RUN, log=ops,
            )
            if autonomous:
                ops.info("Adım 4/4", "Otonom: LinkedIn + Threads scheduled (Supabase, onaysız)")
                draft = publisher.create_linkedin_only_scheduled(
                    text=post_text, image_path=image_path, threads_posts=th_posts or None)
            else:
                ops.info("Adım 4/4", "Kalibrasyon: LinkedIn + Threads draft (onay bekler)")
                draft = publisher.create_linkedin_only_draft(
                    text=post_text, image_path=image_path, threads_posts=th_posts or None)
        else:
            publisher = TypefullyDraftPublisher(social_set_id=target_ss_id)
            ops.info("Adım 4/4", f"Typefully'ye LinkedIn-only draft yükleniyor (ss_id={target_ss_id})")
            draft = publisher.create_linkedin_only_draft(
                text=post_text, image_path=image_path, threads_posts=th_posts or None,
                social_set_id=target_ss_id)

        notion_logger.log_draft(
            source=source,
            score=review["score"],
            linkedin_text=post_text,
            draft_url=draft.get("share_url", ""),
            draft_id=draft.get("draft_id", ""),
            title=f"{title_prefix} (draft)",
        )

        if autonomous:
            ops.success(
                "Workflow Tamamlandı (otonom)",
                f"{source} scheduled — slot {draft.get('publish_at', '?')}, onay maili YOK",
            )
        else:
            try:
                from core import mail_sender
                mail_sender.send_post_approval_mail(
                    account_key=account_key,
                    source=source,
                    title_prefix=title_prefix,
                    post_text=post_text,
                    image_path=image_path,
                    draft_url=draft.get("share_url", ""),
                    draft_id=draft.get("draft_id", ""),
                    social_set_id=target_ss_id,
                    score=review.get("score") if review else None,
                )
            except Exception as e:
                ops.warning("Onay maili gönderilemedi", str(e))
            ops.success(
                "Workflow Tamamlandı (onay bekliyor)",
                f"{source} draft yüklendi + onay maili iletildi: {draft.get('share_url', '')}",
            )

    except (TypefullyDraftError, NativeDraftError) as e:
        ops.error("Yayıncı hatası", message=str(e))
        notion_logger.log_failed(source=source, error=str(e), title=f"{title_prefix} (failed)")
    except Exception as e:
        ops.error(f"FATAL: {title_prefix}", exception=e, message=str(e)[:500])
        try:
            notion_logger.log_failed(source=source, error=str(e)[:2000],
                                     title=f"{title_prefix} (failed)")
        except Exception:
            pass
    finally:
        if image_path and os.path.exists(image_path):
            try:
                os.remove(image_path)
                logging.info(f"Geçici görsel silindi: {image_path}")
            except Exception:
                pass


def run_weekly_news():
    _run_flow("haber")


def run_weekly_tip():
    _run_flow("tavsiye")


def run_solido_post():
    _run_flow("solido")


def run_takalike_post():
    _run_flow("takalike")


if __name__ == "__main__":
    setup_logging()

    mode = os.environ.get("RUN_MODE", "cron").lower()

    if mode == "schedule":
        ops.info("Başlatıldı", "SCHEDULE mode (local dev)")
        # Emre Aşkar: Pazartesi haber, Perşembe tavsiye
        schedule.every().monday.at("08:00").do(run_weekly_news)
        schedule.every().thursday.at("08:00").do(run_weekly_tip)
        # Solido Grup: Salı, Çarşamba, Perşembe 09:30 (B2B 3-Pillar Stratejisi)
        schedule.every().tuesday.at("09:30").do(run_solido_post)
        schedule.every().wednesday.at("09:30").do(run_solido_post)
        schedule.every().thursday.at("09:30").do(run_solido_post)
        # Takalike: Pazartesi, Çarşamba, Cuma 11:00 (E-Ticaret & Tedarikçi 3-Pillar Stratejisi)
        schedule.every().monday.at("11:00").do(run_takalike_post)
        schedule.every().wednesday.at("11:00").do(run_takalike_post)
        schedule.every().friday.at("11:00").do(run_takalike_post)
        while True:
            schedule.run_pending()
            time.sleep(60)
    elif mode == "haber":
        run_weekly_news()
    elif mode == "tavsiye":
        run_weekly_tip()
    elif mode == "solido":
        run_solido_post()
    elif mode == "takalike":
        run_takalike_post()
    elif mode == "all":
        ops.info("Başlatıldı", "ALL mode — Solido + Takalike çalıştırılıyor")
        run_solido_post()
        run_takalike_post()
    else:
        # Railway Cron mode:
        today = datetime.now(timezone.utc).weekday()
        ops.info("Başlatıldı", f"CRON mode — weekday={today}")
        
        # 1) Solido Grup: Salı (1), Çarşamba (2), Perşembe (3) günleri
        if today in (1, 2, 3):
            ops.info("Solido Görevi", f"Solido Grup B2B gönderi akışı tetikleniyor (weekday={today})...")
            run_solido_post()
        else:
            ops.info("Solido Atlandı", f"Bugün (weekday={today}) Solido yayın günü değil (Salı, Çarşamba, Perşembe aktif).")

        # 2) Takalike: Pazartesi (0), Çarşamba (2), Cuma (4) günleri
        if today in (0, 2, 4):
            ops.info("Takalike Görevi", f"Takalike E-Ticaret/B2B gönderi akışı tetikleniyor (weekday={today})...")
            run_takalike_post()
        else:
            ops.info("Takalike Atlandı", f"Bugün (weekday={today}) Takalike yayın günü değil (Pazartesi, Çarşamba, Cuma aktif).")

        # 3) Emre Aşkar Kişisel: Pazartesi (0) haber, Perşembe (3) tavsiye
        if today == 0:
            run_weekly_news()
        elif today == 3:
            run_weekly_tip()

        ops.info("Job Bitti", "Container kapanıyor")
        wait_all_loggers()
