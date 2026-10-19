from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://sitebot:sitebot@localhost:5433/sitebot"
    secret_key: str = "change-me"
    # Comma-separated emails that are always admins.
    admin_emails: str = ""
    google_client_id: str = ""
    # Local testing only: allows signing in by typing an email. Never enable in production.
    dev_auth: bool = False
    cookie_secure: bool = False

    openrouter_api_key: str = ""
    openrouter_model: str = "anthropic/claude-haiku-5.5"
    # Used for query rewriting and answer verification.
    openrouter_fast_model: str = "anthropic/claude-haiku-5.5"
    verify_answers: bool = True

    global_budget_usd: float = 10.0
    default_user_limit_usd: float = 1.0

    max_pages: int = 100
    max_depth: int = 3
    crawl_concurrency: int = 8
    enable_playwright: bool = True

    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    # Minimum cosine similarity of the best chunk; below this we refuse without calling the LLM.
    min_similarity: float = 0.55
    top_k: int = 6
    history_turns: int = 4

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}

    @property
    def sqlalchemy_url(self) -> str:
        # Railway provides postgres:// or postgresql:// URLs; force the psycopg v3 driver.
        url = self.database_url
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
