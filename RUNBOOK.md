# RUNBOOK - LinkedIn Text Paylaşım

## Amaç

Haftada iki LinkedIn postu üreten cron. Pazartesi haftanın AI haberleri, Perşembe pratik AI tavsiyesi. Perplexity araştırır, OpenAI (gpt-5.4 birincil / gpt-4o-mini yedek) post metnini yazar. Post yazıldıktan sonra AYRI bir LLM kalite kapısı postu 1-10 puanlar; eşik altı post bir kez yeniden yazılır, yine geçemezse o koşu atlanır (abstain). Görsel Kie AI (gpt-image-2) ile üretilir. Yayın modu tarihe göre döner: kalibrasyonda Supabase'e taslak + kendi onay maili; otonomda Supabase'e slotlu scheduled + mail yok. Slot cron (Sosyal_Slot_Yayinci) yayınlar.

## Kalibrasyon → Otonomi geçişi

- `AUTONOMOUS_AFTER` (config, varsayılan `2026-07-27`) tarihinden ÖNCE = kalibrasyon: her post tek-tık onaya gelir (draft + Resend maili).
- Tarihten İTİBAREN = otonom: mail atılmaz, post doğrudan `scheduled` + slot yazılır, slot cron onaysız yayınlar.
- Geçiş tarihini kaydırmak: Railway'de `AUTONOMOUS_AFTER` env'ini ISO tarih (`YYYY-MM-DD`) olarak set et. Geçersiz/boşsa güvenli tarafta kalır (kalibrasyon sürer).
- Kalite kapısı eşiği: `QUALITY_THRESHOLD` (varsayılan 7). İki modda da çalışır.

## Deploy

- Platform: Railway, CronJob. Servis adı: `linkedin-text-cron`.
- rootDirectory: `Projeler/LinkedIn_Text_Paylasim` (Railway servis ayarında ZORUNLU; boşsa servis sessizce FAILED).
- Builder: NIXPACKS (railway.json). Python 3.
- Start: `python3 main.py` (weekday'a bakar: Pazartesi haber, Perşembe tavsiye, diğer günler atlanır).
- Cron: `cronSchedule: 0 5 * * 1,4` (05:00 UTC = 08:00 TR, Pazartesi + Perşembe).
- Deploy yöntemi: `git push origin main` auto-deploy tetikler. Olmazsa Railway GraphQL redeploy.
- Lokal test: `DRY_RUN=1 RUN_MODE=haber python3 main.py` veya `RUN_MODE=tavsiye`.

## Triage / Sık Hatalar

- **Açılışta `BOOT ERROR` ile çöküyor:** Fail-fast config; zorunlu env eksik (`PERPLEXITY_API_KEY`, `OPENAI_API_KEY`, `KIE_API_KEY`, `TYPEFULLY_API_KEY`, `TYPEFULLY_SOCIAL_SET_ID`, `NOTION_SOCIAL_TOKEN`, `NOTION_X_DB_ID`).
- **`NameError: settings` (geçmiş arıza, 2026-07-04'te düzeltildi):** main.py `settings`'i kullanıyor ama import etmiyordu; her koşu yayıncı adımında patlıyordu, proje 2 hafta ölüydü. Artık `from config import settings` üstte. Tekrarında importu kontrol et.
- **Cron çalıştı ama taslak yok:** (1) Bu hafta aynı Source ile draft/onay zaten varsa duplicate koruması atlar. (2) Kalite kapısı iki kez eşik altı verdiyse post bilinçli atlanır (abstain) - bu bir hata değildir, log'da "Atlandı (Abstain)" satırı olur. Notion X DB'de Source = "LinkedIn Haber"/"LinkedIn Tavsiye" kayıtlarına bak.
- **Onay maili gelmiyor (kalibrasyon):** `RESEND_API_KEY` + `APPROVAL_SECRET` (Twitter ile AYNI 64 karakter) + `APPROVAL_BASE_URL` set olmalı. Bunlardan biri eksikse buton üretilmez / mail atılmaz; iş yine de taslağı yazar.
- **Onay butonu çalışmıyor:** Onay URL şeması Twitter_Text ile birebir aynı; `APPROVAL_SECRET` iki serviste ve onay servisinde AYNI olmalı. Farklıysa imza tutmaz.
- **Otonom moda beklenmedik geçiş / geçmeme:** `AUTONOMOUS_AFTER` env'ini ve container'ın UTC gününü kontrol et. USE_NATIVE_PUBLISHER=0 ise otonom yol devre dışıdır (Typefully fallback sadece draft üretir).
- **Görsel üretilemedi hatası:** Bilinçli kural; görselsiz LinkedIn postu atılmaz, iş failed loglanır. `KIE_API_KEY` kotası veya Kie polling zaman aşımı (6 dk) en olası sebep.
- **Araştırma boş / hata:** `PERPLEXITY_API_KEY` kotası veya `PERPLEXITY_BASE_URL` yanlış.
- **Beklenmedik DRY-RUN:** `ENV=production` + `DRY_RUN=0` olmalı; aksi halde gerçek draft/mail atılmaz.

## Env Değişkenleri

| Değişken | Ne işe yarar |
|---|---|
| ENV | production / development (development = dry-run) |
| DRY_RUN | 1 ise gerçek draft/mail atmaz |
| RUN_MODE | cron (default) / haber / tavsiye / schedule (lokal dev) |
| PERPLEXITY_API_KEY | Haftalık araştırma (sonar) |
| PERPLEXITY_BASE_URL | Perplexity API adresi (default api.perplexity.ai) |
| OPENAI_API_KEY | Post metni + görsel promptu + kalite kapısı (yedek anahtar) |
| OPENAI_API_KEY | Ücretsiz tier (gpt-5.4) - post + kalite kapısı birincil |
| KIE_API_KEY | Görsel üretimi (gpt-image-2) |
| TYPEFULLY_API_KEY | Typefully draft API (native kapalıyken fallback) |
| TYPEFULLY_SOCIAL_SET_ID | Sayısal social set ID (LinkedIn içermeli) |
| NOTION_SOCIAL_TOKEN | Notion API erişimi (fallback: NOTION_TOKEN) |
| NOTION_X_DB_ID | Ortak sosyal draft DB (Twitter projesiyle aynı) |
| USE_NATIVE_PUBLISHER | 1 ise Supabase native yayın (draft/scheduled); 0 ise Typefully fallback |
| SUPABASE_URL | Supabase projesi (scheduled_posts) |
| SUPABASE_SERVICE_ROLE_KEY | Supabase service role anahtarı |
| AUTONOMOUS_AFTER | Kalibrasyon→otonomi geçiş tarihi (ISO, varsayılan 2026-07-27) |
| QUALITY_THRESHOLD | Öz-inceleme eşiği 1-10 (varsayılan 7) |
| RESEND_API_KEY | Kendi onay maili (kalibrasyon modu) |
| APPROVAL_SECRET | Onay URL imzası (Twitter ile AYNI olmalı) |
| APPROVAL_BASE_URL | Onay servisi adresi (Sosyal_Onay_Servisi) |
| NOTION_LINKEDIN_DB_ID | Opsiyonel; eski LinkedIn-only DB (haftalık dedup) |

## Loglar

- Çalışma adımları hem stdout'a hem Notion Operations Log DB'sine yazılır (`ops_logger.py`).
- Railway deploy log'unda stdout görünür; cron bitince container kapanır.
- Başarısız işler Notion X DB'ye "(failed)" başlıklı kayıt olarak da düşer. Abstain (kalite eşiği altı) FAILED değildir, sadece log satırıdır.

## Rollback

1. Son sağlıklı commit'i bul: `git log --oneline -10`.
2. Bozuk commit'i geri al: `git revert <hash>`.
3. `git push origin main` auto-deploy geri alınmış sürümü deploy eder.
4. Auto-deploy tetiklenmezse Railway GraphQL `serviceInstanceRedeploy` ile son SUCCESS deploy'a dön.
5. Cron yanlış kalmışsa Railway'de `cronSchedule`'ı `0 5 * * 1,4` olarak doğrula.
6. Otonom modu geri almak (yeniden onay kapısı): `AUTONOMOUS_AFTER`'ı ileri bir tarihe çek.
7. Doğrulama: Pazartesi/Perşembe cron sonrası Notion X DB'de yeni kayıt + (kalibrasyonsa) onay maili var mı kontrol et.
