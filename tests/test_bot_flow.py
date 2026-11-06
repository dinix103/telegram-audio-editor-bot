import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, Document, File, Message, Update, User
from fakeredis.aioredis import FakeRedis

from audio_bot.bot import Guard, router
from audio_bot.services.process import run
from audio_bot.store import Store
from audio_bot.workers import execute


class TelegramSession(BaseSession):
    def __init__(self, source):
        super().__init__()
        self.source = source
        self.calls = []

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if method.__api_method__ == "getFile":
            return File(file_id="file", file_unique_id="unique", file_path=str(self.source))
        if method.__api_method__ == "answerCallbackQuery":
            return True
        return Message(
            message_id=len(self.calls),
            date=datetime.now(timezone.utc),
            chat=Chat(id=int(method.chat_id), type="private"),
            text=getattr(method, "text", None),
        ).as_(bot)

    async def stream_content(self, *args, **kwargs):
        yield b""


async def test_private_editor_and_duplicate_confirmation(settings, tmp_path):
    settings.telegram_dir.mkdir(exist_ok=True)
    source = settings.telegram_dir / "bot-flow.wav"
    await run(
        [settings.ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=duration=1", str(source)],
        30,
    )
    session = TelegramSession(source)
    bot = Bot("123456:TEST", session=session)
    redis = FakeRedis()
    store = Store(redis)
    pool = AsyncMock()
    pool.fetchval.return_value = None
    dispatcher = Dispatcher(storage=MemoryStorage(), store=store, settings=settings, pool=pool)
    router.message.outer_middleware(Guard())
    router.callback_query.outer_middleware(Guard())
    dispatcher.include_router(router)
    user = User(id=10, is_bot=False, first_name="Test")
    chat = Chat(id=10, type="private")
    count = 0

    async def message(text=None, document=None):
        nonlocal count
        count += 1
        await dispatcher.feed_update(
            bot,
            Update(
                update_id=count,
                message=Message(
                    message_id=count,
                    date=datetime.now(timezone.utc),
                    chat=chat,
                    from_user=user,
                    text=text,
                    document=document,
                ),
            ),
        )

    async def callback(data, owner=user):
        nonlocal count
        count += 1
        await dispatcher.feed_update(
            bot,
            Update(
                update_id=count,
                callback_query=CallbackQuery(
                    id=str(count),
                    chat_instance="test",
                    from_user=owner,
                    data=data,
                    message=Message(
                        message_id=1,
                        date=datetime.now(timezone.utc),
                        chat=Chat(id=owner.id, type="private"),
                    ),
                ),
            ),
        )

    try:
        await message("/start")
        assert any(c.__api_method__ == "sendAnimation" for c in session.calls)
        await message("/settings")
        await callback("settings:bitrate_256")
        settings_call = session.calls[-1]
        assert "256 кбит/с" in settings_call.text
        assert any(
            b.text.startswith("✓") and b.callback_data == "settings:bitrate_256"
            for row in settings_call.reply_markup.inline_keyboard
            for b in row
        )
        pool.fetchval.return_value = json.dumps({"target": "wav", "delivery": "voice"})
        await message(
            document=Document(
                file_id="file",
                file_unique_id="unique",
                file_name="../track.wav",
                file_size=source.stat().st_size,
            )
        )
        job = await store.current(10)
        assert job and job.status == "queued"
        assert job.edits.target == "mp3" and job.edits.delivery == "auto"
        await redis.lpop("queue")
        await execute(store, bot, pool, settings, job, "analyze")
        await callback(f"{job.id}:tag_title")
        await message("Новая композиция")
        assert (await store.current(10)).edits.tags["title"] == "Новая композиция"
        await callback(f"{job.id}:normalize")
        assert "Нормализация:</b> Включено" in session.calls[-1].text
        await callback(f"{job.id}:speed_1.25")
        assert "1.25×" in session.calls[-1].text
        stranger = User(id=20, is_bot=False, first_name="Other")
        await callback(f"{job.id}:save", stranger)
        assert await redis.llen("queue") == 0
        await callback(f"{job.id}:summary")
        await callback(f"{job.id}:save")
        await callback(f"{job.id}:save")
        assert await redis.llen("queue") == 1
        assert (await store.current(10)).status == "queued"
    finally:
        source.unlink(missing_ok=True)
        await bot.session.close()
        await dispatcher.storage.close()
        await redis.aclose()
