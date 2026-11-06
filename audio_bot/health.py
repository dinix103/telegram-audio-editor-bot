import asyncio
import sys

from redis.asyncio import Redis

from .config import Settings


async def main():
    settings = Settings()
    redis = Redis.from_url(settings.redis_url)
    try:
        await redis.ping()
        mode = sys.argv[1]
        if mode == "bot":
            from .telegram import make_bot

            bot = make_bot(settings)
            try:
                await bot.get_me()
            finally:
                await bot.session.close()
        elif mode == "worker":
            if not [key async for key in redis.scan_iter("health:worker:*")]:
                raise RuntimeError("Worker heartbeat missing")
        elif not await redis.exists("health:cleanup"):
            raise RuntimeError("Cleanup heartbeat missing")
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
