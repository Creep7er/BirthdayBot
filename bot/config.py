from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str = Field(min_length=1)
    allowed_chat_id: int = Field(lt=0)
    timezone: str = "Asia/Tashkent"
    birthday_check_hour: int = Field(default=9, ge=0, le=23)
    birthday_check_minute: int = Field(default=0, ge=0, le=59)
    database_path: Path = Path("/app/data/birthday_bot.sqlite3")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("bot_token")
    @classmethod
    def token_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("BOT_TOKEN must not be blank")
        return value

    @field_validator("timezone")
    @classmethod
    def timezone_must_exist(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown timezone: {value}") from exc
        return value

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
