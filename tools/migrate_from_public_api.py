"""Run once before starting an existing bot against the local API."""

import asyncio
import os

from aiogram import Bot


async def main():
    bot = Bot(os.environ["BOT_TOKEN"])
    try:
        await bot.log_out()
        print("logOut выполнен. Теперь запускайте локальный Bot API.")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
