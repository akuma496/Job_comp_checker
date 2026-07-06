from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str = ""
    serper_api_key: str = ""
    db_path: str = "data/job_comp_checker.db"
    user_email: str = "akuma496@asu.edu"

    claude_model: str = "claude-sonnet-5"
    embedding_model: str = "all-MiniLM-L6-v2"

    @property
    def db_full_path(self) -> Path:
        path = Path(self.db_path)
        if not path.is_absolute():
            path = BASE_DIR / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()
