import time

from redis.asyncio import Redis

from .models import Job


class Store:
    def __init__(self, redis: Redis):
        self.redis = redis

    async def save(self, job: Job):
        job.touched = time.time()
        await self.redis.set(f"job:{job.id}", job.model_dump_json())
        await self.redis.expire(f"user:{job.user_id}", 86400)

    async def get(self, job_id: str) -> Job | None:
        raw = await self.redis.get(f"job:{job_id}")
        return Job.model_validate_json(raw) if raw else None

    async def current(self, user_id: int):
        value = await self.redis.get(f"user:{user_id}")
        return (
            await self.get(value.decode() if isinstance(value, bytes) else value) if value else None
        )

    async def forget(self, job: Job):
        await self.redis.eval(
            "if redis.call('GET',KEYS[1]) == ARGV[1] then return redis.call('DEL',KEYS[1]) end return 0",
            1,
            f"user:{job.user_id}",
            job.id,
        )
        await self.redis.delete(f"job:{job.id}", f"cancel:{job.id}")

    async def enqueue(self, job: Job, kind: str):
        job.status = "queued"
        job.touched = time.time()
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.set(f"job:{job.id}", job.model_dump_json())
            pipe.rpush("queue", f"{kind}:{job.id}")
            await pipe.execute()

    async def cancelled(self, job_id):
        return bool(await self.redis.exists(f"cancel:{job_id}"))
