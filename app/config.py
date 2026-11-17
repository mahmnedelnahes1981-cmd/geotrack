from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    app_name: str = "GeoTrack"
    environment: str = "development"
    database_url: str = "sqlite:///./geotrack.db"

    # OpenAI-compatible LLM endpoint (Ollama by default; swap via .env)
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str = "qwen2.5vl:7b"
    llm_timeout: float = 120.0

    upload_dir: str = "./storage/uploads"

    # --- Quote defaults ---
    quote_tax_rate: float = 14.0          # VAT % — editable per quote
    quote_validity_days: int = 30

    # --- Company identity (rendered on quote PDFs) ---
    company_name_en: str = "GeoTrack Foundations & Drilling Co."
    company_name_ar: str = "شركة جيوتراك للحفر والأساسات"
    company_address_en: str = "(company address)"
    company_address_ar: str = "(عنوان الشركة)"
    company_phone: str = ""
    company_email: str = ""
    company_tax_id: str = ""              # الرقم الضريبي


@lru_cache
def get_settings() -> Settings:
    return Settings()
