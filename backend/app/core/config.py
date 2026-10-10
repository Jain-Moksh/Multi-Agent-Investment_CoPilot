"""
Application settings, loaded from environment variables / backend/.env.

Every module should import `settings` from here instead of reading
os.environ directly, so all configuration lives in one place.
Real environment variables take priority over values in .env.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/.env — resolved from this file's location, so it is found no matter
# which folder uvicorn / alembic / pytest is started from.
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    # --- General ---
    APP_NAME: str = "Investment Copilot"
    ENVIRONMENT: str = "development"

    # --- Frontend origins allowed by CORS (comma-separated in .env) ---
    # 5173 = Vite dev server, 3000 = Create React App dev server.
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"
    # Where the browser is sent back to after the Zerodha login flow.
    FRONTEND_URL: str = "http://localhost:5173"

    # --- Database ---
    # Default matches .env.example so the app can start before .env exists;
    # /health will report the DB as unreachable until it is configured.
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/investment_copilot"

    # --- LLM provider ("gemini" or "openai") ---
    # Every service accepts one key (X_API_KEY) and/or a comma-separated list (X_API_KEYS).
    # Keys are tried in order: when one is rate-limited, out of quota, invalid or times out,
    # the next one is used (app/services/key_pool.py).
    LLM_PROVIDER: str = "gemini"
    GEMINI_API_KEY: str = ""
    GEMINI_API_KEYS: str = ""
    OPENAI_API_KEY: str = ""
    OPENAI_API_KEYS: str = ""
    # When every key of LLM_PROVIDER fails, try the other provider's keys too.
    LLM_CROSS_PROVIDER_FALLBACK: bool = True
    # Model names change often; override in .env if a default is retired. Comma-separated =
    # fallback models, tried in order when a model is overloaded (503) or times out.
    GEMINI_MODEL: str = "gemini-3.5-flash,gemini-3.8-flash,gemini-3.1-flash-lite"
    # Gemini 3 "thinking" effort (minimal/low/medium/high; empty = model default). Thinking tokens
    # count against the output limit, so GEMINI_THINKING_TOKENS is added on top of max_tokens.
    GEMINI_THINKING_LEVEL: str = "low"
    GEMINI_THINKING_TOKENS: int = 1024
    OPENAI_MODEL: str = "gpt-4o-mini"
    LLM_TIMEOUT_SECONDS: float = 20.0
    LLM_MAX_CONCURRENT_CALLS: int = 2   # free tiers allow only a few requests per minute

    # --- External data sources ---
    MARKETAUX_API_KEY: str = ""
    MARKETAUX_API_KEYS: str = ""
    ALPHAVANTAGE_API_KEY: str = ""
    ALPHAVANTAGE_API_KEYS: str = ""

    # --- Supabase project (the backend uses its Postgres through DATABASE_URL; kept for later use) ---
    SUPABASE_URL: str = ""
    SUPABASE_PUBLISHABLE_KEY: str = ""
    SUPABASE_SECRET_KEY: str = ""

    # --- Zerodha Kite Connect ---
    ZERODHA_API_KEY: str = ""
    ZERODHA_API_SECRET: str = ""

    # --- Vector store (ChromaDB, local) + embeddings (run locally, no API) ---
    CHROMA_PERSIST_DIR: str = str(ENV_FILE.parent / "chroma_data")  # backend/chroma_data (git-ignored)
    CHROMA_COLLECTION: str = "financial_news"
    EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    # Load the embedding model in the background at startup (a cold load takes ~40-60 s).
    EMBEDDING_WARMUP: bool = True

    # --- Background jobs (app/core/scheduler.py) ---
    SCHEDULER_ENABLED: bool = True
    NEWS_INGEST_INTERVAL_MINUTES: int = 10
    MARKET_UPDATE_INTERVAL_MINUTES: int = 30
    SCHEDULER_FIRST_RUN_DELAY_SECONDS: int = 60

    # --- Auth (JWT) ---
    # Short-lived access token (sent as "Authorization: Bearer ...") plus a
    # long-lived, rotating refresh token (httpOnly cookie). See context.md.
    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    @field_validator("JWT_SECRET_KEY")
    @classmethod
    def jwt_secret_not_blank(cls, value: str) -> str:
        # A blank secret would let anyone forge tokens, so refuse to start.
        if not value.strip():
            raise ValueError(
                'JWT_SECRET_KEY is empty. Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
            )
        return value

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT.lower() == "development"

    def api_keys(self, service: str) -> list[str]:
        """
        Ordered, de-duplicated keys for `service` ("gemini", "openai", "marketaux", "alphavantage"):
        {SERVICE}_API_KEY first, then {SERVICE}_API_KEYS. Read on every call, so tests and
        .env edits (after a restart) are picked up.
        """
        name = service.upper()
        raw = [getattr(self, f"{name}_API_KEY", "")] + getattr(self, f"{name}_API_KEYS", "").split(",")
        return list(dict.fromkeys(key.strip() for key in raw if key.strip()))


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (read .env only once)."""
    return Settings()


settings = get_settings()
