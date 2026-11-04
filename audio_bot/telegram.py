from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer


def make_bot(settings):
    return Bot(
        settings.bot_token.get_secret_value(),
        session=AiohttpSession(
            api=TelegramAPIServer.from_base(settings.bot_api_url, is_local=True), timeout=300
        ),
    )
