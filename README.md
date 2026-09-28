# LinkedIn Çoklu Hesap & Otomatik Paylaşım Sistemi

Emre Aşkar'ın kişisel profili ile **Solido Grup** ve **Takalike** şirket sayfaları için otomatik LinkedIn içerik üretim ve paylaşım pipeline'ı.

### Desteklenen Hesaplar & Yayın Akışı:
1. **Solido Grup (Kurumsal Sayfa):** Haftada 3 gün (Salı, Çarşamba, Perşembe saat 09:30) 70/20/10 içerik mimarisiyle B2B paylaşımları:
   - *Salı:* Kurumsal Web Mimarisi & Dönüşüm / CRO (SiteSepeti odağı)
   - *Çarşamba:* Performans Pazarlaması, Google Ads & Yerel Arama / Haritalar (BirMilyonNokta odağı)
   - *Perşembe:* Saha Verisi, B2B Otorite & KOBİ Büyümesi (180.000 portföy & 70 kişilik ekip tecrübesi)
2. **Takalike (Kurumsal Sayfa):** Haftada 3 gün (Pazartesi, Çarşamba, Cuma saat 11:00) 70/20/10 içerik mimarisiyle E-Ticaret & B2B Tedarik paylaşımları:
   - *Pazartesi:* Pazaryeri Satıcı Stratejileri, Fiyatlama & Kârlı Ürün Seçimi (Trendyol, Hepsiburada, Amazon dinamikleri)
   - *Çarşamba:* Stoksuz E-Ticaret (Dropshipping) Operasyonu, Lojistik & Kargo Maliyet Yönetimi (ikas, IdeaSoft entegrasyonu)
   - *Cuma:* B2B Tedarikçi, İmalatçı Dağıtım Gücü & Dijital Toptan Ticaret (500K+ ürün havuzunun gücü)
3. **Emre Aşkar (Kişisel Profil):** Pazartesi haftanın önemli AI gelişmeleri (08:00), Perşembe pratik AI ve iş dünyası tavsiyeleri (08:00).

Metin ve 16:9 görsel otomatik üretilir. Post yazıldıktan sonra bağımsız bir LLM kalite kapısı (Reviewer) içeriği 1-10 puanlar; eşiği geçemeyen post bir kez yeniden üretilir.

## Stack

- Python 3 (`requests`, `openai`, `schedule`, `python-dotenv`)
- Perplexity API (`sonar`) ile gerçek zamanlı web ve sektör araştırması
- OpenAI `gpt-4o` (birincil) / `gpt-4o-mini` (yedek) ile post metni + kalite kapısı
- OpenAI `gpt-4o-mini` ile görsel promptu, Kie AI (`gpt-image-2` / `nano-banana-2`) ile 16:9 görsel üretimi
- Typefully API v2 ile doğrudan LinkedIn yayın / taslak yönetimi (token süresi dolma derdi yok, çoklu Social Set desteği)
- Notion (opsiyonel loglama) & E-posta onay akışı

## Çalışma Şekli

1. Railway cron `main.py`'ı tetikler. Gün kontrolü: Pazartesi "haber",
   Perşembe "tavsiye", diğer günler atlanır.
2. Notion'da bu haftanın taslağı zaten varsa iş atlanır (duplicate koruması).
3. Perplexity araştırır, `gpt-5.4` LinkedIn postunu yazar.
4. **Öz-inceleme kalite kapısı:** ayrı bir LLM çağrısı postu 1-10 puanlar.
   Eşik altı (`QUALITY_THRESHOLD`, varsayılan 7) → bir kez yeniden üret; yine
   altıysa o koşu atlanır (post/mail yok).
5. Kie AI görseli üretir. Görsel üretilemezse post atılmaz.
6. Tarihe göre dallanır: kalibrasyonda taslak + onay maili, otonomda slotlu
   scheduled + mail yok. Sonuç Notion'a loglanır.

Dosyalar: `main.py` (orkestratör), `core/researcher.py`, `core/post_writer.py`,
`core/reviewer.py` (kalite kapısı), `core/image_generator.py`,
`core/native_publisher.py` (Supabase draft + scheduled), `core/slots.py`
(TR 11/13/15:30 slot hesabı), `core/mail_sender.py` (kendi onay maili),
`core/notion_logger.py`.

## Environment Setup

Detay için `.env.example`'a bak:

- `PERPLEXITY_API_KEY`, `OPENAI_API_KEY`, `OPENAI_API_KEY`, `KIE_API_KEY`
- `NOTION_SOCIAL_TOKEN`, `NOTION_X_DB_ID`
- `USE_NATIVE_PUBLISHER=1`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
- `AUTONOMOUS_AFTER` (ISO tarih, varsayılan `2026-07-27`), `QUALITY_THRESHOLD` (varsayılan 7)
- Kalibrasyon maili için: `RESEND_API_KEY`, `APPROVAL_SECRET` (Twitter ile AYNI),
  `APPROVAL_BASE_URL`
- `ENV=production`, `DRY_RUN=0`, `RUN_MODE=cron`

Lokal test:

```bash
DRY_RUN=1 RUN_MODE=haber python3 main.py     # Pazartesi akışı
DRY_RUN=1 RUN_MODE=tavsiye python3 main.py   # Perşembe akışı
```

## Deploy

- Railway CronJob `linkedin-text-cron`, monorepo Root Dir:
  `Projeler/LinkedIn_Text_Paylasim`.
- `railway.json`: `startCommand: python main.py`,
  `cronSchedule: 0 5 * * 1,4` (UTC 05:00 = TR 08:00, Pazartesi + Perşembe).
- Deploy: `git push` (monorepo auto-deploy) veya Railway GraphQL redeploy.
