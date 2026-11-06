import time
import uuid
from unittest.mock import AsyncMock

import pytest
from fakeredis.aioredis import FakeRedis

from audio_bot.models import Edits, Job
from audio_bot.services.probe import probe
from audio_bot.services.process import run
from audio_bot.store import Store
from audio_bot.workers import execute


@pytest.mark.parametrize("mode", ["single", "batch", "merge"])
@pytest.mark.parametrize("delivery", ["auto", "document", "voice"])
async def test_analyze_render_delivery_cleanup(settings, tmp_path, mode, delivery):
    redis = FakeRedis()
    store = Store(redis)
    identifier = uuid.uuid4().hex
    directory = tmp_path / identifier
    directory.mkdir()
    items = []
    for index in range(2 if mode != "single" else 1):
        name = "source" if index == 0 else "source_1"
        await run(
            [
                settings.ffmpeg,
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=duration=1",
                "-f",
                "wav",
                str(directory / name),
            ],
            30,
        )
        items.append({"source": name})
    job = Job(
        id=identifier,
        user_id=1,
        chat_id=1,
        status_message_id=1,
        touched=time.time(),
        mode=mode,
        items=items if mode != "single" else [],
        edits=Edits(target="flac", delivery=delivery, tags={"title": "Тест"}),
    )
    await redis.set("user:1", identifier)
    await store.save(job)
    bot = AsyncMock()
    pool = AsyncMock()
    delivered = []

    async def capture(chat_id, file, **kwargs):
        assert chat_id == 1
        assert file.path.is_file()
        assert file.filename.endswith(".mp3")
        assert (await probe(file.path, settings.ffprobe))["codec"] == "mp3"
        delivered.append(file.path.stat().st_size)

    bot.send_audio.side_effect = capture
    bot.send_document.side_effect = capture
    await execute(store, bot, pool, settings, job, "analyze")
    assert (await store.get(identifier)).status == "editing"
    assert job.info["format"] == "wav"
    await execute(store, bot, pool, settings, job, "render")
    assert len(delivered) == (2 if mode == "batch" else 1)
    assert all(size > 1000 for size in delivered)
    bot.send_voice.assert_not_called()
    assert not directory.exists()
    assert await store.current(1) is None
    await redis.aclose()
