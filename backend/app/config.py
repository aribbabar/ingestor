from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Ingestor"
    project_root: Path = Field(default_factory=lambda: Path(__file__).resolve().parents[1])
    data_dir: Path | None = None
    cors_origins: list[str] = [
        "http://localhost:1420",
        "http://127.0.0.1:1420",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://tauri.localhost",
        "https://tauri.localhost",
        "null",
    ]
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_timeout_seconds: float = 60.0

    model_config = SettingsConfigDict(env_prefix="INGESTOR_", env_file=".env")

    @property
    def resolved_data_dir(self) -> Path:
        return self.data_dir or self.project_root / "data"

    @property
    def database_path(self) -> Path:
        return self.resolved_data_dir / "ingestor.sqlite"

    @property
    def job_log_dir(self) -> Path:
        return self.resolved_data_dir / "jobs"

    @property
    def web_output_dir(self) -> Path:
        return self.resolved_data_dir / "web"

    @property
    def local_source_dir(self) -> Path:
        return self.resolved_data_dir / "local"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.resolved_data_dir.mkdir(parents=True, exist_ok=True)
    settings.job_log_dir.mkdir(parents=True, exist_ok=True)
    settings.web_output_dir.mkdir(parents=True, exist_ok=True)
    settings.local_source_dir.mkdir(parents=True, exist_ok=True)
    return settings
