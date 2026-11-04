"""Optional real Redis/PostgreSQL smoke test, enabled by CI service containers."""

import os
import time
import uuid

import pytest
from redis.asyncio import Redis

from audio_bot.database import connect, preferences, set_preferences
from audio_bot.models import Job
from audio_bot.store import Store


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL") or not os.environ.get("TEST_REDIS_URL"),
    reason="Real PostgreSQL/Redis service URLs are required",
)
async def test_real_services():
    redis = Redis.from_url(os.environ["TEST_REDIS_URL"])
    pool = await connect(os.environ["TEST_DATABASE_URL"])
    store = Store(redis)
    user_id = -int(uuid.uuid4().hex[:12], 16)
    job = Job(
        id=uuid.uuid4().hex,
        user_id=user_id,
        chat_id=user_id,
        status_message_id=1,
        touched=time.time(),
    )
    try:
        await set_preferences(pool, user_id, {"target": "mp3", "bitrate": 192})
        assert (await preferences(pool, user_id))["bitrate"] == 192
        await redis.set(f"user:{user_id}", job.id)
        await store.enqueue(job, "analyze")
        assert (await store.current(user_id)).id == job.id
        token = await redis.blmove("queue", "processing", timeout=2, src="LEFT", dest="RIGHT")
        assert token == f"analyze:{job.id}".encode()
        lock = redis.lock(f"lease:{job.id}", timeout=10)
        assert await lock.acquire(blocking=False)
        await lock.release()
        await store.forget(job)
        assert await store.current(user_id) is None
    finally:
        await redis.lrem("queue", 0, f"analyze:{job.id}")
        await redis.lrem("processing", 0, f"analyze:{job.id}")
        await redis.delete(f"job:{job.id}", f"user:{user_id}", f"lease:{job.id}")
        await pool.execute("DELETE FROM preferences WHERE user_id=$1", user_id)
        await pool.close()
        await redis.aclose()
