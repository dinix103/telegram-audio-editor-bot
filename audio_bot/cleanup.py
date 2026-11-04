import asyncio
import time

from redis.asyncio import Redis

from .config import Settings
from .services.files import remove_job
from .store import Store


async def sweep(store, settings):
    now = time.time()
    # Crash between reserving a user and creating its directory must not block the user forever.
    async for key in store.redis.scan_iter("job:*"):
        raw = key.decode() if isinstance(key, bytes) else key
        job = await store.get(raw[4:])
        if job and now - job.touched > settings.idle_seconds:
            if not (settings.jobs_dir / job.id).exists() and not await store.redis.exists(
                f"lease:{job.id}", f"upload:{job.id}"
            ):
                await store.forget(job)
    for directory in settings.jobs_dir.iterdir():
        if not directory.is_dir() or directory.is_symlink():
            continue
        job_id = directory.name
        if len(job_id) != 32 or any(x not in "0123456789abcdef" for x in job_id):
            continue
        if await store.redis.exists(f"active:{job_id}", f"lease:{job_id}", f"upload:{job_id}"):
            continue
        job = await store.get(job_id)
        age = now - (job.touched if job else directory.stat().st_mtime)
        limit = settings.idle_seconds if job and job.status == "editing" else 3600
        if await store.cancelled(job_id) or age > limit:
            lock = store.redis.lock(f"lease:{job_id}", timeout=300, blocking_timeout=0)
            if not await lock.acquire():
                continue
            try:
                # Re-read after acquiring lease to avoid deleting a newly touched session.
                job = await store.get(job_id)
                if job and not await store.cancelled(job_id) and now - job.touched <= limit:
                    continue
                await asyncio.to_thread(remove_job, settings.jobs_dir, job_id)
                if job:
                    await store.forget(job)
                for kind in ("analyze", "render"):
                    await store.redis.lrem("processing", 0, f"{kind}:{job_id}")
                    await store.redis.lrem("queue", 0, f"{kind}:{job_id}")
            finally:
                await lock.release()


async def main():
    settings = Settings()
    settings.jobs_dir.mkdir(parents=True, exist_ok=True)
    redis = Redis.from_url(settings.redis_url)
    try:
        while True:
            await redis.set("health:cleanup", str(time.time()), ex=120)
            await sweep(Store(redis), settings)
            await asyncio.sleep(30)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    from .runtime import run_service

    run_service(main)
