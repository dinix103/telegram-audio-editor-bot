import asyncio
from unittest.mock import AsyncMock
from xml.etree.ElementTree import fromstring

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage

from audio_bot.keyboards import FIELDS, card, main_menu, settings_keyboard
from audio_bot.models import Job
from audio_bot.telegram import EmojiFallback
from audio_bot.ui import mp3_edits, settings_text, summary_text
from audio_bot.workers import animated


def test_safe_cards_and_readable_settings():
    edits = mp3_edits({"target": "wav", "delivery": "voice", "bitrate": 256})
    assert edits.target == "mp3" and edits.delivery == "auto"
    job = Job(
        id="a" * 32,
        user_id=1,
        chat_id=1,
        status_message_id=1,
        touched=0,
        info={"tags": {"title": '<bad> & "' * 300}},
        edits=edits,
    )
    job.edits.tags = {field: '<unsafe> & "' * 50 for field in FIELDS}
    job.edits.filename = "&" * 200
    for text in [card(job), settings_text(edits), summary_text(job, FIELDS)]:
        fromstring(f"<root>{text}</root>")
        assert "<unsafe>" not in text
        assert len(text) < 4000
    buttons = [b for row in settings_keyboard(edits).inline_keyboard for b in row]
    assert next(b for b in buttons if b.callback_data == "settings:bitrate_256").style == "success"
    assert not any("voice" in b.callback_data or "target_wav" in b.callback_data for b in buttons)


async def test_premium_fallback_preserves_colors_and_actions():
    method = SendMessage(chat_id=1, text="Студия", reply_markup=main_menu())
    request = AsyncMock(
        side_effect=[
            TelegramBadRequest(method=method, message="CUSTOM_EMOJI_NOT_ALLOWED"),
            True,
            True,
        ]
    )
    fallback = EmojiFallback()
    assert await fallback(request, None, method)
    retried = request.call_args.args[1]
    for row in retried.reply_markup.inline_keyboard:
        assert all(b.icon_custom_emoji_id is None for b in row)
    assert retried.reply_markup.inline_keyboard[0][0].style == "primary"
    assert retried.reply_markup.inline_keyboard[0][0].callback_data == "home:convert"
    # Later messages avoid repeating a failed premium-only request.
    assert await fallback(request, None, method)
    assert request.call_count == 3


async def test_animation_stops_on_conversion_error():
    bot = AsyncMock()
    job = Job(id="a" * 32, user_id=1, chat_id=1, status_message_id=1, touched=0)

    async def failed():
        await asyncio.sleep(0)
        raise ValueError("test")

    before = asyncio.all_tasks()
    with pytest.raises(ValueError):
        await animated(bot, job, "MP3", failed())
    assert asyncio.all_tasks() == before
