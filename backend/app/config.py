from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://sitebot:sitebot@localhost:5433/sitebot"
    secret_key: str = "change-me"
    # Comma-separated emails that are always admins.
    admin_emails: str = ""
    google_client_id: str = ""
    cookie_secure: bool = False

    # Sending one-time codes. Resend (HTTPS API) is used if its key is set, else SMTP; with neither,
    # codes are printed to the server log so local testing still works.
    resend_api_key: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    mail_from: str = "SiteBot <no-reply@example.com>"

    openrouter_api_key: str = ""
    openrouter_model: str = "anthropic/claude-haiku-5.5"
    # Used for query rewriting and answer verification.
    openrouter_fast_model: str = "anthropic/claude-haiku-5.5"
    verify_answers: bool = True
    # Encrypts AI provider API keys saved in the Admin console. Any long random string. Without it, a key derived
    # from SECRET_KEY is used (so changing SECRET_KEY would make saved provider keys unreadable).
    provider_keys_secret: str = ""

    global_budget_usd: float = 10.0
    default_user_limit_usd: float = 1.0
    # Website embeds: the default daily spend cap per embed (admins can change it per embed), and extra
    # origins every embed may run on, for local testing only (e.g. http://localhost:5500).
    embed_daily_cap_usd: float = 0.5
    embed_dev_origins: str = ""
    # Public address of this app (e.g. https://sitebot.example.com), used for links in notification emails.
    app_url: str = ""

    # Error monitoring with Sentry. Off unless a DSN is set; the browser DSN is public by design.
    sentry_dsn: str = ""
    sentry_browser_dsn: str = ""
    sentry_environment: str = "production"

    # Whole sites are read; this is only a safety ceiling so a huge site can't run forever.
    max_pages: int = 5000
    max_depth: int = 8
    # Above this many pages, the user is warned (with a time estimate) before indexing starts.
    large_site_pages: int = 300
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
    def embed_dev_origin_list(self) -> list[str]:
        return [o.strip().rstrip("/").lower() for o in self.embed_dev_origins.split(",") if o.strip()]

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
