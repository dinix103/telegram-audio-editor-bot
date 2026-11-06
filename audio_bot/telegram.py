from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.exceptions import TelegramBadRequest


class EmojiFallback:
    """Keep all controls usable if Telegram disallows premium button icons."""

    def __init__(self):
        self.enabled = True

    async def __call__(self, make_request, bot, method):
        markup = getattr(method, "reply_markup", None)
        has_icons = markup and any(
            getattr(b, "icon_custom_emoji_id", None)
            for row in getattr(markup, "inline_keyboard", [])
            for b in row
        )
        if not self.enabled and has_icons:
            method = without_icons(method)
        try:
            return await make_request(bot, method)
        except TelegramBadRequest as exc:
            if not has_icons or not any(
                word in exc.message.lower() for word in ("emoji", "premium", "fragment")
            ):
                raise
            self.enabled = False
            return await make_request(bot, without_icons(method))


def without_icons(method):
    markup = method.reply_markup.model_copy(
        update={
            "inline_keyboard": [
                [button.model_copy(update={"icon_custom_emoji_id": None}) for button in row]
                for row in method.reply_markup.inline_keyboard
            ]
        }
    )
    return method.model_copy(update={"reply_markup": markup})


def make_bot(settings):
    session = AiohttpSession(
        api=TelegramAPIServer.from_base(settings.bot_api_url, is_local=True), timeout=300
    )
    session.middleware(EmojiFallback())
    return Bot(
        settings.bot_token.get_secret_value(),
        session=session,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
