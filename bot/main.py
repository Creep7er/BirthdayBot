import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from .config import load_settings
from .database import Database
from .handlers import create_router
from .scheduler import check_birthdays, run_scheduler

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    logger.info("Starting birthday bot for allowed chat %s", settings.allowed_chat_id)

    database = Database(settings.database_path)
    await database.initialize()
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(create_router(database, settings.allowed_chat_id))
    stop_event = asyncio.Event()
    scheduler_task = asyncio.create_task(
        run_scheduler(bot, database, settings, stop_event),
        name="birthday-scheduler",
    )

    try:
        await bot.set_my_commands(
            [
                BotCommand(command="addbirth", description="Добавить день рождения"),
                BotCommand(command="rmbirth", description="Удалить день рождения"),
                BotCommand(command="birthdays", description="Показать дни рождения"),
                BotCommand(command="help", description="Показать помощь"),
            ]
        )
        await check_birthdays(bot, database, settings)
        await dispatcher.start_polling(bot)
    finally:
        stop_event.set()
        await scheduler_task
        await bot.session.close()
        logger.info("Birthday bot stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
