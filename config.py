import os
import sys
from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), "..", "..", "_knowledge", "credentials", "master.env")
if os.path.exists(env_path):
    load_dotenv(env_path)

# Antigravity V2 Fail-Fast Environment Validation
class Config:
    def __init__(self):
        # 1. Environment mode
        self.ENV = os.environ.get("ENV", "development").lower()
        self.IS_DRY_RUN = self.ENV == "development" or os.environ.get("DRY_RUN", "0") == "1"

        # Perplexity — AI haberleri araştırması
        self.PERPLEXITY_API_KEY = self._require_env("PERPLEXITY_API_KEY")
        self.PERPLEXITY_BASE_URL = os.environ.get("PERPLEXITY_BASE_URL", "https://api.perplexity.ai")

        # OpenAI — Post yazma (GPT-4.1) + Görsel prompt (GPT-4.1-mini)
        self.OPENAI_API_KEY = self._require_env("OPENAI_API_KEY")

        # Kie AI — Görsel üretme (Nano Banana 2)
        self.KIE_API_KEY = self._require_env("KIE_API_KEY")

        # Typefully — LinkedIn artık Typefully üzerinden yayınlanıyor (token expire derdi yok)
        self.TYPEFULLY_API_KEY = self._require_env("TYPEFULLY_API_KEY")
        self.TYPEFULLY_SOCIAL_SET_ID = int(os.environ.get("TYPEFULLY_SOCIAL_SET_ID", "334863"))
        # Çoklu hesap desteği (Solido Grup ve Takalike)
        self.TYPEFULLY_SOCIAL_SET_ID_SOLIDO = int(os.environ.get("TYPEFULLY_SOCIAL_SET_ID_SOLIDO") or os.environ.get("TYPEFULLY_SOCIAL_SET_ID_SOLIDOGRUP") or 0)
        self.TYPEFULLY_SOCIAL_SET_ID_TAKALIKE = int(os.environ.get("TYPEFULLY_SOCIAL_SET_ID_TAKALIKE") or os.environ.get("TYPEFULLY_SOCIAL_SET_ID_TAKALİKE") or os.environ.get("TYPEFULLY_SOCIAL_SET_ID_TAKA") or 0)
        self.TYPEFULLY_SOCIAL_SET_ID_TAKALİKE = self.TYPEFULLY_SOCIAL_SET_ID_TAKALIKE

        # Notion — Sosyal medya draft DB (Notion bağlı değilse opsiyonel geçer, çökmez)
        self.NOTION_TOKEN = os.environ.get("NOTION_SOCIAL_TOKEN") or os.environ.get("NOTION_TOKEN", "")
        self.NOTION_X_DB_ID = os.environ.get("NOTION_X_DB_ID", "")
        # Geriye uyumluluk: eski LinkedIn-only DB hâlâ kullanılabilir (örn. weekly-dedup)
        self.NOTION_LINKEDIN_DB_ID = os.environ.get("NOTION_LINKEDIN_DB_ID", "")

        # Native göç (Typefully -> LinkedIn native). USE_NATIVE_PUBLISHER=1 ile aktif;
        # kapalıyken (varsayılan) davranış AYNEN Typefully. Native'de içerik Supabase
        # scheduled_posts'a 'draft' yazılır (Twitter_Text ile aynı mail/onay akışı).
        self.USE_NATIVE_PUBLISHER = os.environ.get("USE_NATIVE_PUBLISHER", "0") == "1"
        self.SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
        self.SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

        # Kalibrasyon → Otonomi geçişi (ISO tarih, UTC gün). Bu tarihe KADAR
        # (kalibrasyon) her post tek-tık onaya gelir; tarihten İTİBAREN sistem
        # sessiz otonoma geçer (mail yok, kendi yayınlar). kullanici kararı:
        # ~3 hafta kalibrasyon. Erken/geç geçiş için env ile override edilebilir.
        self.AUTONOMOUS_AFTER = os.environ.get("AUTONOMOUS_AFTER") or "2026-07-27"

        # Öz-inceleme kalite eşiği (1-10). Post bu puanın altındaysa bir kez
        # yeniden üretilir; hâlâ altıysa o koşu atlanır (post/mail yok).
        try:
            self.QUALITY_THRESHOLD = int(os.environ.get("QUALITY_THRESHOLD", "7"))
        except ValueError:
            self.QUALITY_THRESHOLD = 7

    def _require_env(self, key, default=None):
        """Fetches an environment variable, raises error if missing."""
        val = os.environ.get(key, default)
        if not val:
            raise EnvironmentError(f"CRITICAL STARTUP FAILURE: Gerekli ortam değişkeni {key} bulunamadı!")
        return val

# Instantiating the config globally so it fails fast on module load.
try:
    settings = Config()
except EnvironmentError as e:
    print(f"BOOT ERROR: {e}")
    sys.exit(1)
