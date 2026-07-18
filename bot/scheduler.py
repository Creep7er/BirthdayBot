import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from .config import Settings
from .congratulations import build_congratulation
from .database import Database

logger = logging.getLogger(__name__)


async def check_birthdays(bot: Bot, database: Database, settings: Settings) -> None:
    current_date = datetime.now(settings.tzinfo).date()
    logger.info("Checking birthdays for %s", current_date)
    try:
        birthdays = await database.birthdays_for_date(current_date)
        logger.info("Found %d birthday(s)", len(birthdays))
        if not birthdays:
            return

        signature = ",".join(
            str(item.telegram_user_id)
            for item in sorted(birthdays, key=lambda item: item.telegram_user_id)
        )
        if await database.notification_exists(current_date, signature):
            logger.info("Birthday notification already sent; skipping signature %s", signature)
            return

        await bot.send_message(
            chat_id=settings.allowed_chat_id,
            text=build_congratulation(birthdays),
        )
        await database.save_notification(current_date, signature)
        logger.info("Birthday notification sent for %d user(s)", len(birthdays))
    except TelegramAPIError:
        logger.exception("Telegram API error during birthday check")
    except Exception:
        logger.exception("Unexpected error during birthday check")


async def run_scheduler(
    bot: Bot,
    database: Database,
    settings: Settings,
    stop_event: asyncio.Event,
) -> None:
    logger.info(
        "Daily scheduler started for %02d:%02d %s",
        settings.birthday_check_hour,
        settings.birthday_check_minute,
        settings.timezone,
    )
    while not stop_event.is_set():
        now = datetime.now(settings.tzinfo)
        next_run = now.replace(
            hour=settings.birthday_check_hour,
            minute=settings.birthday_check_minute,
            second=0,
            microsecond=0,
        )
        if next_run <= now:
            next_run += timedelta(days=1)
        delay = max(0.0, (next_run - now).total_seconds())
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=delay)
        except TimeoutError:
            await check_birthdays(bot, database, settings)
    logger.info("Daily scheduler stopped")
