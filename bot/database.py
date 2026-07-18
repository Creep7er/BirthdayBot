import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class Birthday:
    telegram_user_id: int
    username: str | None
    display_name: str
    birth_day: int
    birth_month: int


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as connection:
            await connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS birthdays (
                    telegram_user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    display_name TEXT NOT NULL,
                    birth_day INTEGER NOT NULL,
                    birth_month INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_birthdays_username
                    ON birthdays(username COLLATE NOCASE);

                CREATE TABLE IF NOT EXISTS birthday_notifications (
                    notification_date TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    UNIQUE(notification_date, signature)
                );
                """
            )
            await connection.commit()
        logger.info("SQLite database initialized at %s", self.path)

    async def upsert_birthday(self, birthday: Birthday) -> bool:
        async with aiosqlite.connect(self.path) as connection:
            cursor = await connection.execute(
                "SELECT 1 FROM birthdays WHERE telegram_user_id = ?",
                (birthday.telegram_user_id,),
            )
            existed = await cursor.fetchone() is not None
            await cursor.close()
            await connection.execute(
                """
                INSERT INTO birthdays (
                    telegram_user_id, username, display_name, birth_day, birth_month
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                    username = excluded.username,
                    display_name = excluded.display_name,
                    birth_day = excluded.birth_day,
                    birth_month = excluded.birth_month
                """,
                (
                    birthday.telegram_user_id,
                    birthday.username,
                    birthday.display_name,
                    birthday.birth_day,
                    birthday.birth_month,
                ),
            )
            await connection.commit()
        return existed

    async def get_by_username(self, username: str) -> Birthday | None:
        async with aiosqlite.connect(self.path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                """
                SELECT telegram_user_id, username, display_name, birth_day, birth_month
                FROM birthdays
                WHERE username = ? COLLATE NOCASE
                """,
                (username.lstrip("@"),),
            )
            row = await cursor.fetchone()
            await cursor.close()
        return self._to_birthday(row) if row else None

    async def delete_by_user_id(self, telegram_user_id: int) -> Birthday | None:
        async with aiosqlite.connect(self.path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                """
                SELECT telegram_user_id, username, display_name, birth_day, birth_month
                FROM birthdays WHERE telegram_user_id = ?
                """,
                (telegram_user_id,),
            )
            row = await cursor.fetchone()
            await cursor.close()
            if row:
                await connection.execute(
                    "DELETE FROM birthdays WHERE telegram_user_id = ?",
                    (telegram_user_id,),
                )
                await connection.commit()
        return self._to_birthday(row) if row else None

    async def delete_by_username(self, username: str) -> Birthday | None:
        birthday = await self.get_by_username(username)
        if birthday is None:
            return None
        return await self.delete_by_user_id(birthday.telegram_user_id)

    async def list_birthdays(self) -> list[Birthday]:
        async with aiosqlite.connect(self.path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                """
                SELECT telegram_user_id, username, display_name, birth_day, birth_month
                FROM birthdays ORDER BY birth_month, birth_day, display_name
                """
            )
            rows = await cursor.fetchall()
            await cursor.close()
        return [self._to_birthday(row) for row in rows]

    async def birthdays_for_date(self, current_date: date) -> list[Birthday]:
        day = current_date.day
        month = current_date.month
        include_leap_birthdays = month == 2 and day == 28 and not _is_leap_year(current_date.year)
        async with aiosqlite.connect(self.path) as connection:
            connection.row_factory = aiosqlite.Row
            if include_leap_birthdays:
                cursor = await connection.execute(
                    """
                    SELECT telegram_user_id, username, display_name, birth_day, birth_month
                    FROM birthdays
                    WHERE birth_month = 2 AND birth_day IN (28, 29)
                    ORDER BY telegram_user_id
                    """
                )
            else:
                cursor = await connection.execute(
                    """
                    SELECT telegram_user_id, username, display_name, birth_day, birth_month
                    FROM birthdays
                    WHERE birth_month = ? AND birth_day = ?
                    ORDER BY telegram_user_id
                    """,
                    (month, day),
                )
            rows = await cursor.fetchall()
            await cursor.close()
        return [self._to_birthday(row) for row in rows]

    async def notification_exists(self, notification_date: date, signature: str) -> bool:
        async with aiosqlite.connect(self.path) as connection:
            cursor = await connection.execute(
                """
                SELECT 1 FROM birthday_notifications
                WHERE notification_date = ? AND signature = ?
                """,
                (notification_date.isoformat(), signature),
            )
            exists = await cursor.fetchone() is not None
            await cursor.close()
        return exists

    async def save_notification(self, notification_date: date, signature: str) -> None:
        async with aiosqlite.connect(self.path) as connection:
            await connection.execute(
                """
                INSERT OR IGNORE INTO birthday_notifications (notification_date, signature)
                VALUES (?, ?)
                """,
                (notification_date.isoformat(), signature),
            )
            await connection.commit()

    @staticmethod
    def _to_birthday(row: aiosqlite.Row) -> Birthday:
        return Birthday(
            telegram_user_id=row["telegram_user_id"],
            username=row["username"],
            display_name=row["display_name"],
            birth_day=row["birth_day"],
            birth_month=row["birth_month"],
        )


def _is_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
