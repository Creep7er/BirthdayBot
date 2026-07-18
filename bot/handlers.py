import re
from datetime import datetime
from html import escape

from aiogram import Bot, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import Message, User

from .database import Birthday, Database

MONTHS = (
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
DATE_PATTERN = re.compile(r"^(\d{2})\.(\d{2})$")
USERNAME_PATTERN = re.compile(r"^@[A-Za-z0-9_]{5,32}$")
ADMIN_STATUSES = {ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR}
MESSAGE_LIMIT = 3900


def create_router(database: Database, allowed_chat_id: int) -> Router:
    router = Router()

    async def allowed_chat(message: Message) -> bool:
        return (
            message.chat.id == allowed_chat_id
            and message.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}
        )

    router.message.filter(allowed_chat)

    @router.message(Command("help"))
    async def help_command(message: Message) -> None:
        await message.answer(
            "Команды бота:\n"
            "<code>/addbirth 17.06</code> — ответом на сообщение пользователя\n"
            "<code>/addbirth @username 17.06</code>\n"
            "<code>/rmbirth</code> — ответом на сообщение пользователя\n"
            "<code>/rmbirth @username</code>\n"
            "<code>/birthdays</code> — показать список\n\n"
            "Добавление и удаление доступны только администраторам чата."
        )

    @router.message(Command("birthdays"))
    async def birthdays_command(message: Message) -> None:
        birthdays = await database.list_birthdays()
        if not birthdays:
            await message.answer("Список дней рождения пока пуст.")
            return
        lines = [format_birthday_line(item) for item in birthdays]
        for chunk in split_lines(lines, "🎂 <b>Дни рождения</b>\n\n"):
            await message.answer(chunk)

    @router.message(Command("addbirth"))
    async def add_birthday_command(message: Message, bot: Bot) -> None:
        if not await is_admin(message, bot):
            await message.answer("Эта команда доступна только администраторам чата.")
            return
        args = command_args(message)
        target: Birthday | None = None
        date_text: str | None = None

        if len(args) == 1 and message.reply_to_message and message.reply_to_message.from_user:
            target = birthday_from_user(message.reply_to_message.from_user, 1, 1)
            date_text = args[0]
        elif len(args) == 2 and USERNAME_PATTERN.fullmatch(args[0]):
            date_text = args[1]
            target = await resolve_username(args[0], database, bot)
            if target is None:
                await message.answer(
                    f"Не удалось определить Telegram ID пользователя {escape(args[0])}. "
                    "Используйте команду ответом на его сообщение."
                )
                return
        else:
            await message.answer(
                "Использование: <code>/addbirth 17.06</code> ответом на сообщение "
                "или <code>/addbirth @username 17.06</code>."
            )
            return

        parsed_date = parse_birth_date(date_text)
        if parsed_date is None:
            await message.answer("Некорректная дата. Используйте формат <code>ДД.ММ</code>, например 17.06.")
            return
        day, month = parsed_date
        saved = Birthday(
            telegram_user_id=target.telegram_user_id,
            username=target.username,
            display_name=target.display_name,
            birth_day=day,
            birth_month=month,
        )
        existed = await database.upsert_birthday(saved)
        action = "обновлён" if existed else "сохранён"
        icon = "♻️" if existed else "🎂"
        await message.answer(
            f"{icon} День рождения пользователя {escape(saved.display_name)} {action}: "
            f"{day} {MONTHS[month]}."
        )

    @router.message(Command("rmbirth"))
    async def remove_birthday_command(message: Message, bot: Bot) -> None:
        if not await is_admin(message, bot):
            await message.answer("Эта команда доступна только администраторам чата.")
            return
        args = command_args(message)
        removed: Birthday | None
        if not args and message.reply_to_message and message.reply_to_message.from_user:
            removed = await database.delete_by_user_id(message.reply_to_message.from_user.id)
        elif len(args) == 1 and USERNAME_PATTERN.fullmatch(args[0]):
            removed = await database.delete_by_username(args[0])
        else:
            await message.answer(
                "Использование: <code>/rmbirth</code> ответом на сообщение "
                "или <code>/rmbirth @username</code>."
            )
            return
        if removed is None:
            await message.answer("Запись о дне рождения этого пользователя не найдена.")
            return
        await message.answer(
            f"🗑 День рождения пользователя {escape(removed.display_name)} удалён из списка."
        )

    return router


async def is_admin(message: Message, bot: Bot) -> bool:
    if message.from_user is None:
        return False
    try:
        member = await bot.get_chat_member(message.chat.id, message.from_user.id)
    except TelegramAPIError:
        return False
    return member.status in ADMIN_STATUSES


async def resolve_username(username: str, database: Database, bot: Bot) -> Birthday | None:
    saved = await database.get_by_username(username)
    if saved:
        return saved
    try:
        chat = await bot.get_chat(username)
    except TelegramAPIError:
        return None
    if chat.type != ChatType.PRIVATE:
        return None
    display_name = " ".join(part for part in (chat.first_name, chat.last_name) if part)
    return Birthday(chat.id, chat.username, display_name or username.lstrip("@"), 1, 1)


def birthday_from_user(user: User, day: int, month: int) -> Birthday:
    return Birthday(user.id, user.username, user.full_name, day, month)


def command_args(message: Message) -> list[str]:
    if not message.text:
        return []
    return message.text.split()[1:]


def parse_birth_date(value: str) -> tuple[int, int] | None:
    match = DATE_PATTERN.fullmatch(value)
    if not match:
        return None
    day, month = map(int, match.groups())
    try:
        datetime(2000, month, day)
    except ValueError:
        return None
    return day, month


def format_birthday_line(birthday: Birthday) -> str:
    username = f" (@{escape(birthday.username)})" if birthday.username else ""
    return (
        f"{birthday.birth_day} {MONTHS[birthday.birth_month]} — "
        f"{escape(birthday.display_name)}{username}"
    )


def split_lines(lines: list[str], header: str) -> list[str]:
    chunks: list[str] = []
    current = header
    for line in lines:
        addition = line + "\n"
        if len(current) + len(addition) > MESSAGE_LIMIT and current != header:
            chunks.append(current.rstrip())
            current = ""
        current += addition
    if current.strip():
        chunks.append(current.rstrip())
    return chunks
