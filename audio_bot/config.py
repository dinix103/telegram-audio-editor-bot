from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    bot_token: SecretStr
    bot_api_url: str = "http://telegram-bot-api:8081"
    redis_url: str = "redis://redis:6379/0"
    database_url: SecretStr = SecretStr("postgresql://audio:audio@postgres/audio")
    jobs_dir: Path = Path("/work/jobs")
    telegram_dir: Path = Path("/telegram")
    max_input_bytes: int = Field(default=2_000_000_000, gt=0)
    max_output_bytes: int = Field(default=2_000_000_000, gt=0, le=2_000_000_000)
    job_quota_bytes: int = Field(default=6_000_000_000, gt=0)
    disk_reserve_bytes: int = Field(default=2_000_000_000, ge=0)
    idle_seconds: int = Field(default=900, gt=0)
    operation_timeout: int = Field(default=1800, gt=0)
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    admin_ids: list[int] = []

    @model_validator(mode="after")
    def separate_storage(self):
        work, telegram = self.jobs_dir.resolve(), self.telegram_dir.resolve()
        if work.is_relative_to(telegram) or telegram.is_relative_to(work):
            raise ValueError("Рабочие файлы и каталог Bot API должны быть разделены")
        return self

    @field_validator("bot_api_url")
    @classmethod
    def local_api(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Нужен адрес локального Bot API")
        if parsed.hostname == "api.telegram.org":
            raise ValueError("Публичный Bot API запрещён")
        return value.rstrip("/")
