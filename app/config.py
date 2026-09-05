"""Application settings, loaded from the environment / .env file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime configuration for the ChronoTrace backend."""

    model_config = SettingsConfigDict(
        env_prefix="CHRONOTRACE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- MongoDB ---
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "chronotrace"
    mongo_timeout_ms: int = 5000

    # --- API ---
    api_title: str = "ChronoTrace"
    api_version: str = "0.1.0"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])

    # --- Paths ---
    dataset_path: Path = BASE_DIR / "data" / "chronotrace_network_5000.csv"
    model_path: Path = BASE_DIR / "app" / "ml" / "model.pkl"

    # --- Graph engine ---
    graph_cache_ttl: float = 300.0
    graph_max_events: int = 200_000

    # --- Collector ---
    collector_api_url: str = "http://127.0.0.1:8000"
    collector_interval: float = 5.0

    @property
    def model_meta_path(self) -> Path:
        """Sidecar JSON holding feature names and the score calibration table."""
        return self.model_path.with_name(self.model_path.stem + "_meta.json")

    def resolved(self, path: Path) -> Path:
        """Resolve a possibly-relative configured path against the project root."""
        return path if path.is_absolute() else (BASE_DIR / path)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
