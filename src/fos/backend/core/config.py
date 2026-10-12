from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


# Dangerous default values that must not be used in production
_DANGEROUS_JWT_KEYS = {
    "change-me",
    "please-change-me",
    "secret",
    "jwt-secret",
    "your-secret-key",
}
_DANGEROUS_ADMIN_PASSWORDS = {"zjucss107", "admin", "password", "changeme"}
_DANGEROUS_DB_PASSWORDS = {"fos", "postgres", "password", "admin"}


class Settings(BaseSettings):
    debug: bool = False
    app_name: str = "FOS Backend"
    api_prefix: str = "/api"
    backend_root_path: str = ""
    frontend_dist_path: str | None = None

    # Environment mode: "development", "test", or "production"
    app_env: str = "development"

    backend_host: str = "0.0.0.0"
    backend_port: int = 8000

    database_url: str = "sqlite+aiosqlite:///./fos.db"
    # Optional SQLAlchemy engine pool tuning
    db_pool_size: int | None = None
    db_max_overflow: int | None = None
    db_pool_timeout: int | None = None
    db_pool_recycle: int | None = None
    db_pool_pre_ping: bool | None = None

    jwt_signing_key: SecretStr = SecretStr("change-me")
    jwt_algorithm: str = "HS256"
    access_token_exp_minutes: int = 720  # 12 hours for long-running experiments
    refresh_token_exp_minutes: int = 60 * 24 * 14

    email_smtp_host: str | None = None
    email_smtp_port: int | None = None
    email_smtp_username: str | None = None
    email_smtp_password: SecretStr | None = None
    email_smtp_use_tls: bool = True
    email_smtp_use_ssl: bool = False
    email_from: str | None = None

    app_base_url: str | None = None
    verification_token_exp_minutes: int = 60 * 24
    require_email_verification: bool = False

    allowed_origins: list[str] = []
    admin_emails: list[str] = []

    # Admin bootstrap credentials (used by ensure_admin script)
    admin_email: str = ""
    admin_username: str = ""
    admin_password: str = ""

    # Simulation cost controls
    max_advance_multi_count: int = 20
    max_advance_turns_per_request: int = 50
    max_frontier_nodes_per_request: int = 50

    # In-memory simulation cache controls
    simtree_idle_ttl_seconds: int = 3600
    simtree_cleanup_interval_seconds: int = 300
    simtree_max_records: int | None = None

    # GAWorld integration
    gaworld_path: str | None = Field(
        default=None,
        validation_alias="GAWORLD_PATH",
        description="Filesystem path to the GAWorld repository",
    )

    # File upload configuration
    upload_dir: str = "uploads"
    upload_base_url: str = "/uploads"
    upload_max_mb: int = 5
    upload_docs_max_mb: int = 10
    upload_enable_ocr: bool = False
    upload_ocr_lang: str | None = None
    upload_backend: str = "local"  # local | cloud
    upload_cloud_base_url: str | None = (
        None  # used when upload_backend = cloud; still writes locally but returns cloud URL
    )
    upload_cloud_dir: str | None = (
        None  # optional: when cloud backend is enabled, write to this directory (e.g., mounted bucket)
    )

    # Vector Store (ChromaDB) Configuration
    use_chromadb: bool = False
    chromadb_persist_dir: str = "./chroma_db"

    model_config = SettingsConfigDict(
        extra="ignore",
        env_prefix="FOS_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    @property
    def email_enabled(self) -> bool:
        return (
            self.email_smtp_host is not None
            and self.email_smtp_port is not None
            and self.email_from is not None
        )

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in ("production", "prod")

    def validate_production_secrets(self) -> list[str]:
        """Validate that production-critical secrets are not using defaults.

        Returns a list of error messages. Empty list means all checks passed.
        Only runs checks when app_env is production.
        """
        if not self.is_production:
            return []

        errors: list[str] = []

        # JWT signing key
        jwt_key = self.jwt_signing_key.get_secret_value()
        if jwt_key.lower() in _DANGEROUS_JWT_KEYS:
            errors.append(
                "JWT_SIGNING_KEY is set to a known default value. "
                "Generate a secure key (e.g., openssl rand -hex 32) and set FOS_JWT_SIGNING_KEY."
            )
        elif len(jwt_key) < 32:
            errors.append(
                "JWT_SIGNING_KEY is too short (< 32 characters). "
                "Use a longer key for production."
            )

        # Admin password
        if (
            self.admin_password
            and self.admin_password.lower() in _DANGEROUS_ADMIN_PASSWORDS
        ):
            errors.append(
                "ADMIN_PASSWORD is set to a known default. "
                "Set ADMIN_PASSWORD to a strong, unique password."
            )

        # Database password (check PostgreSQL URLs)
        db_url = self.database_url.lower()
        for dangerous in _DANGEROUS_DB_PASSWORDS:
            if f":{dangerous}@" in db_url:
                errors.append(
                    "Database password in DATABASE_URL appears to be a default value. "
                    "Set a strong database password for production."
                )
                break

        return errors


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
