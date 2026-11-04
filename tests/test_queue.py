import time
import uuid
from types import SimpleNamespace

import pytest
from fakeredis.aioredis import FakeRedis

from audio_bot.bot import editable
from audio_bot.cleanup import sweep
from audio_bot.models import Job
from audio_bot.services.files import UserError
from audio_bot.store import Store


async def make_job(store, root, user_id=1):
    job = Job(
        id=uuid.uuid4().hex,
        user_id=user_id,
        chat_id=user_id,
        status_message_id=1,
        status="editing",
        touched=time.time(),
    )
    (root / job.id).mkdir()
    (root / job.id / "source").write_bytes(b"audio")
    await store.redis.set(f"user:{user_id}", job.id)
    await store.save(job)
    return job


async def test_owner_isolation_and_forget(tmp_path):
    redis = FakeRedis()
    store = Store(redis)
    first = await make_job(store, tmp_path, 1)
    second = await make_job(store, tmp_path, 2)
    with pytest.raises(UserError):
        await editable(store, 2, first.id)
    await store.forget(first)
    assert await store.current(1) is None
    assert (await store.current(2)).id == second.id
    await redis.aclose()


async def test_queue_transition_atomic(tmp_path):
    redis = FakeRedis()
    store = Store(redis)
    job = await make_job(store, tmp_path)
    await store.enqueue(job, "render")
    assert (await store.get(job.id)).status == "queued"
    assert await redis.lpop("queue") == f"render:{job.id}".encode()
    with pytest.raises(UserError):
        await editable(store, job.user_id, job.id)
    await redis.aclose()


@pytest.mark.parametrize("protected", [True, False])
async def test_cleanup_does_not_remove_active(tmp_path, protected):
    redis = FakeRedis()
    store = Store(redis)
    job = await make_job(store, tmp_path)
    job.touched = time.time() - 1000
    await redis.set(f"job:{job.id}", job.model_dump_json())
    if protected:
        await redis.set(f"active:{job.id}", "1", ex=60)
    await sweep(store, SimpleNamespace(jobs_dir=tmp_path, idle_seconds=900))
    assert (tmp_path / job.id).exists() is protected
    assert bool(await store.get(job.id)) is protected
    await redis.aclose()


async def test_cancel_cleanup(tmp_path):
    redis = FakeRedis()
    store = Store(redis)
    job = await make_job(store, tmp_path)
    await redis.set(f"cancel:{job.id}", "1")
    await sweep(store, SimpleNamespace(jobs_dir=tmp_path, idle_seconds=900))
    assert not (tmp_path / job.id).exists()
    assert await store.current(1) is None
    await redis.aclose()


async def test_restart_orphan_cleanup(tmp_path):
    import os

    redis = FakeRedis()
    directory = tmp_path / uuid.uuid4().hex
    directory.mkdir()
    (directory / "source").write_bytes(b"orphan")
    os.utime(directory, (time.time() - 4000, time.time() - 4000))
    await sweep(Store(redis), SimpleNamespace(jobs_dir=tmp_path, idle_seconds=900))
    assert not directory.exists()
    await redis.aclose()
