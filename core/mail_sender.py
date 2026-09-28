"""LinkedIn Onay Maili — Çift Butonlu (Hemen Yayınla + Düzenle) Önizleme Kapısı.

Pipeline gönderi metnini ve görselini ürettikten sonra Typefully'ye 'draft' (taslak)
olarak yükler. Ardından bu modül kullanıcıya şık bir e-posta gönderir.

E-posta içeriğinde 2 Aksiyon Butonu yer alır:
  1. [🚀 Hemen Yayınla] -> Web servisi üzerinden Typefully API'sini tetikleyip anında LinkedIn'e canlı yayınlar.
  2. [✏️ Düzenle]       -> Doğrudan Typefully taslak arayüzünü açar, kullanıcı ufak düzeltmeleri yapabilir.

Gönderim yöntemi:
  - Gmail SMTP (SSL Port 465 / STARTTLS Port 587) - master.env içindeki GMAIL_PERSONAL_APP_PASSWORD ile
"""

import os
import smtplib
import html
import hmac
import json
import base64
import hashlib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from datetime import datetime, timezone

from ops_logger import get_ops_logger
from config import settings

ops = get_ops_logger("LinkedIn_Text_Paylasim", "MailSender")

# Hesap görsel meta bilgileri
ACCOUNT_INFO = {
    "emre": {
        "title": "Emre Aşkar",
        "badge": "👤 Şahsi Profil",
        "theme_color": "#0a66c2",
    },
    "solido": {
        "title": "Solido Grup",
        "badge": "🏢 Kurumsal Şirket Sayfası",
        "theme_color": "#0284c7",
    },
    "takalike": {
        "title": "Takalike",
        "badge": "🚀 E-Ticaret & Tedarik Platformu",
        "theme_color": "#6366f1",
    },
}

SOURCE_EMOJI = {
    "LinkedIn Haber": "📰",
    "LinkedIn Tavsiye": "💡",
    "LinkedIn Solido": "🏢",
    "LinkedIn Takalike": "🚀",
}


def _get_approval_secret() -> str:
    return (
        os.environ.get("APPROVAL_SECRET")
        or "82cd106c5de33f02ed381251782269fa64275ebae1956ab24a4d4f4d50e99ab7"
    )


def _get_approval_base_url() -> str:
    return (os.environ.get("APPROVAL_BASE_URL") or "").rstrip("/")


def _get_recipient_email() -> str:
    return (
        os.environ.get("ALERT_RECIPIENT_EMAIL")
        or os.environ.get("GMAIL_PERSONAL_EMAIL")
        or "emraskar@gmail.com"
    ).strip()


def make_publish_token(draft_id: str | int, social_set_id: str | int, account_key: str = "emre", title: str = "") -> str:
    """HMAC-SHA256 imzalı tek kullanımlık yayınlama token'ı üretir."""
    secret = _get_approval_secret()
    payload = {
        "d": str(draft_id),
        "s": int(social_set_id) if str(social_set_id).isdigit() else 0,
        "acc": account_key,
        "title": title[:60],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(payload, ensure_ascii=False).encode()
    ).decode().rstrip("=")
    sig = hmac.new(
        secret.encode(), payload_b64.encode(), hashlib.sha256
    ).hexdigest()
    return f"{payload_b64}.{sig}"


def _build_single_post_html(
    account_key: str,
    title_prefix: str,
    post_text: str,
    score: float | int | None,
    draft_url: str,
    publish_url: str = "",
    has_inline_image: bool = False,
) -> str:
    """Tek bir gönderi için çift butonlu (Hemen Yayınla + Düzenle) HTML e-posta gövdesi oluşturur."""
    acc = ACCOUNT_INFO.get(account_key, {
        "title": title_prefix,
        "badge": "💼 LinkedIn Hesabı",
        "theme_color": "#0a66c2",
    })

    score_badge = ""
    if score is not None:
        score_val = float(score)
        score_color = "#16a34a" if score_val >= 7.0 else "#ca8a04"
        score_badge = (
            f'<span style="background:{score_color}15;color:{score_color};padding:4px 10px;'
            f'border-radius:20px;font-size:12px;font-weight:700;border:1px solid {score_color}40;">'
            f'⭐ Kalite: {score_val:.1f}/10</span>'
        )

    # Görsel bloğu (CID referansı)
    image_html = ""
    if has_inline_image:
        image_html = (
            '<div style="margin:16px 0;text-align:center;">'
            '<img src="cid:post_image" alt="LinkedIn Görseli" '
            'style="max-width:100%;height:auto;border-radius:10px;border:1px solid #e2e8f0;'
            'box-shadow:0 4px 14px rgba(0,0,0,0.06);display:block;margin:0 auto;" />'
            '</div>'
        )

    # Post metni (HTML escape + satır sonları)
    escaped_text = html.escape(post_text.strip()).replace("\n", "<br>")

    # Çift Buton Bölümü (Hemen Yayınla + Düzenle)
    buttons_html = f"""
    <table role="presentation" style="width:100%;margin:26px 0 16px;border-collapse:separate;border-spacing:8px 0;" cellpadding="0" cellspacing="0">
      <tr>
        <!-- 1. Buton: Hemen Yayınla (Yeşil) -->
        <td style="width:50%;text-align:center;padding:0;">
          <a href="{html.escape(publish_url)}" target="_blank"
             style="display:block;background:#10b981;color:#ffffff;text-decoration:none;
                    padding:15px 12px;border-radius:10px;font-size:15px;font-weight:800;
                    text-align:center;box-shadow:0 4px 14px rgba(16,185,129,0.3);letter-spacing:0.3px;">
            🚀 Hemen Yayınla
          </a>
        </td>
        <!-- 2. Buton: Düzenle (Typefully Mavi) -->
        <td style="width:50%;text-align:center;padding:0;">
          <a href="{html.escape(draft_url)}" target="_blank"
             style="display:block;background:#0a66c2;color:#ffffff;text-decoration:none;
                    padding:15px 12px;border-radius:10px;font-size:15px;font-weight:700;
                    text-align:center;box-shadow:0 4px 14px rgba(10,102,194,0.25);letter-spacing:0.3px;">
            ✏️ Düzenle (Taslak)
          </a>
        </td>
      </tr>
    </table>
    """

    today_str = datetime.now().strftime("%d %B %Y, %H:%M")

    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>LinkedIn Gönderi Onayı</title>
</head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;background-color:#f4f6f9;margin:0;padding:24px 12px;color:#1e293b;">
  <table role="presentation" style="max-width:620px;width:100%;margin:0 auto;background:#ffffff;border-radius:14px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.07);border:1px solid #e2e8f0;" cellpadding="0" cellspacing="0">
    
    <!-- Üst Başlık Şeridi -->
    <tr>
      <td style="background:{acc['theme_color']};padding:20px 24px;color:#ffffff;">
        <table style="width:100%;">
          <tr>
            <td>
              <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;opacity:0.9;">LinkedIn Otopilot Paylaşım Onayı</div>
              <h1 style="font-size:20px;margin:4px 0 0;font-weight:800;color:#ffffff;">{html.escape(acc['title'])}</h1>
            </td>
            <td style="text-align:right;">
              <span style="background:rgba(255,255,255,0.2);padding:6px 12px;border-radius:16px;font-size:12px;font-weight:600;">{acc['badge']}</span>
            </td>
          </tr>
        </table>
      </td>
    </tr>

    <!-- Ana Gövde -->
    <tr>
      <td style="padding:24px;">
        
        <!-- Gönderi Meta Bilgisi -->
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
          <div style="font-size:13px;color:#64748b;font-weight:600;">📅 {today_str} · {html.escape(title_prefix)}</div>
          <div>{score_badge}</div>
        </div>

        <!-- Üretilen Görsel -->
        {image_html}

        <!-- Post Metni Kartı -->
        <div style="background:#f8fafc;border-left:4px solid {acc['theme_color']};border-radius:8px;padding:16px;margin:16px 0;font-size:14px;line-height:1.65;color:#334155;border-top:1px solid #f1f5f9;border-right:1px solid #f1f5f9;border-bottom:1px solid #f1f5f9;">
          <div style="font-size:11px;color:{acc['theme_color']};font-weight:700;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">
            📝 Hazırlanan LinkedIn Metni
          </div>
          <div>{escaped_text}</div>
        </div>

        <!-- Çift Buton: Hemen Yayınla / Düzenle -->
        {buttons_html}

        <!-- Bilgilendirme Kutusu -->
        <div style="background:#f1f5f9;border-radius:10px;padding:16px;margin-top:16px;font-size:13px;color:#475569;line-height:1.55;">
          <div style="font-weight:700;color:#1e293b;margin-bottom:8px;">💡 Buton Seçenekleri:</div>
          <ul style="margin:0;padding-left:18px;">
            <li style="margin-bottom:6px;"><b>🚀 Hemen Yayınla:</b> Gönderiyi doğrudan ve anında LinkedIn hesabınıza canlıya alır; Typefully arayüzüne girmeniz gerekmez.</li>
            <li style="margin-bottom:6px;"><b>✏️ Düzenle:</b> Metin veya görsel üzerinde ufak bir değişiklik yapmak isterseniz Typefully editörünü açar.</li>
            <li><b>🗑️ Beğenmediyseniz:</b> Butonlara basmadığınız sürece LinkedIn'de <b>asla paylaşılmaz</b>. Antigravity chat'ine gelip <i>"Beğenmedim, baştan yaz"</i> diyerek yeni bir tane ürettirebilirsiniz.</li>
          </ul>
        </div>

      </td>
    </tr>

    <!-- Alt Bilgi / Footer -->
    <tr>
      <td style="background:#f8fafc;border-top:1px solid #e2e8f0;padding:16px 24px;text-align:center;font-size:12px;color:#94a3b8;">
        Antigravity LinkedIn Otopilot · Typefully Taslak Güvencesiyle
      </td>
    </tr>

  </table>
</body>
</html>"""


def _send_via_gmail_smtp(msg: MIMEMultipart, recipient: str) -> bool:
    """Gmail SMTP (SSL 465 -> Fallback TLS 587) üzerinden e-posta gönderir."""
    sender_email = (os.environ.get("GMAIL_PERSONAL_EMAIL") or "").strip()
    raw_password = (os.environ.get("GMAIL_PERSONAL_APP_PASSWORD") or "").strip()
    clean_password = raw_password.replace(" ", "")

    if not sender_email or not clean_password:
        ops.warning("Gmail SMTP ayarları eksik (GMAIL_PERSONAL_EMAIL veya GMAIL_PERSONAL_APP_PASSWORD yok)")
        return False

    # 1. Deneme: Port 465 SSL
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
            server.login(sender_email, clean_password)
            server.send_message(msg)
        ops.success("Onay maili gönderildi (Gmail SMTP Port 465 SSL)", f"Alıcı: {recipient}")
        return True
    except Exception as e_ssl:
        ops.warning("Gmail Port 465 SSL başarısız, Port 587 deneniyor", str(e_ssl))

    # 2. Deneme: Port 587 STARTTLS
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as server:
            server.starttls()
            server.login(sender_email, clean_password)
            server.send_message(msg)
        ops.success("Onay maili gönderildi (Gmail SMTP Port 587 TLS)", f"Alıcı: {recipient}")
        return True
    except Exception as e_tls:
        ops.error("Gmail SMTP gönderim hatası", message=f"Port 465 ve 587 başarısız: {e_tls}")
        return False


def send_post_approval_mail(
    account_key: str,
    source: str,
    title_prefix: str,
    post_text: str,
    draft_url: str = "",
    draft_id: str | int = "",
    social_set_id: str | int = "",
    image_path: str | None = None,
    score: float | int | None = None,
    recipient: str | None = None,
) -> bool:
    """Üretilen LinkedIn postu için çift butonlu onay ve önizleme e-postasını gönderir."""
    recipient_email = recipient or _get_recipient_email()
    sender_email = (os.environ.get("GMAIL_PERSONAL_EMAIL") or "emraskar@gmail.com").strip()

    acc_title = ACCOUNT_INFO.get(account_key, {}).get("title", title_prefix)
    subject = f"[Onay Bekliyor] LinkedIn: {acc_title} — {title_prefix}"

    # Yayınlama URL'i (onay_web /yayinla ucu)
    base_url = _get_approval_base_url()
    token = make_publish_token(draft_id=draft_id, social_set_id=social_set_id, account_key=account_key, title=title_prefix)
    if base_url:
        publish_url = f"{base_url}/yayinla?t={token}"
    else:
        # Webhook URL'i henüz Railway üzerinde set edilmediyse Typefully taslak linkine düşer
        publish_url = draft_url or f"https://typefully.com/?d={draft_id}&a={social_set_id}"

    # Düzenleme linki: her zaman doğrudan Typefully editörüdür
    edit_url = draft_url or f"https://typefully.com/?d={draft_id}&a={social_set_id}"

    has_inline_image = bool(image_path and os.path.exists(image_path))
    html_body = _build_single_post_html(
        account_key=account_key,
        title_prefix=title_prefix,
        post_text=post_text,
        score=score,
        draft_url=edit_url,
        publish_url=publish_url,
        has_inline_image=has_inline_image,
    )
    plain_fallback = (
        f"{title_prefix}\n\n{post_text}\n\n"
        f"🚀 Hemen Yayınla: {publish_url}\n"
        f"✏️ Düzenle: {edit_url}"
    )

    # MIME Yapısı (Inline CID görsel destekli)
    msg = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"] = f"LinkedIn Otopilot <{sender_email}>"
    msg["To"] = recipient_email

    # Alternatif metin/HTML gövdesi
    msg_alt = MIMEMultipart("alternative")
    msg.attach(msg_alt)

    msg_alt.attach(MIMEText(plain_fallback, "plain", "utf-8"))
    msg_alt.attach(MIMEText(html_body, "html", "utf-8"))

    # Görseli CID olarak göm
    if has_inline_image:
        try:
            with open(image_path, "rb") as f:
                img_data = f.read()
            img_part = MIMEImage(img_data)
            img_part.add_header("Content-ID", "<post_image>")
            img_part.add_header("Content-Disposition", "inline", filename=os.path.basename(image_path))
            msg.attach(img_part)
        except Exception as e:
            ops.warning("Görsel e-postaya iliştirilemedi", str(e))

    return _send_via_gmail_smtp(msg, recipient_email)


def send_approval_mail(drafts: list[dict] | None = None) -> bool:
    """Geriye dönük uyumluluk: parametresiz çağrıldığında çalışır."""
    if not drafts:
        ops.info("send_approval_mail: Gönderilecek taslak listesi boş")
        return False

    first = drafts[0]
    return send_post_approval_mail(
        account_key=first.get("account_key", "emre"),
        source=first.get("source", "LinkedIn"),
        title_prefix=first.get("title", "LinkedIn Paylaşımı"),
        post_text=first.get("linkedin_text", ""),
        draft_url=first.get("draft_url", ""),
        draft_id=first.get("draft_id", ""),
        social_set_id=first.get("social_set_id", ""),
        score=first.get("score"),
    )
