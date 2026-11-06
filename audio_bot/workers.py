import asyncio
import logging
import os
import socket
from contextlib import suppress

from aiogram.types import FSInputFile
from redis.asyncio import Redis

from .config import Settings
from .database import connect
from .keyboards import card, menu
from .services.converter import convert
from .services.covers import normalize_cover
from .services.files import UserError, job_dir, remove_job, safe_name
from .services.merge import merge
from .services.metadata import cover_bytes, read_tags
from .services.probe import probe
from .store import Store
from .telegram import make_bot

log = logging.getLogger("audio-worker")


async def status(bot, job, text, markup=None):
    with suppress(Exception):
        await bot.edit_message_text(
            text, chat_id=job.chat_id, message_id=job.status_message_id, reply_markup=markup
        )


async def heartbeat(redis, key):
    while True:
        await redis.set(key, "1", ex=60)
        await asyncio.sleep(10)


async def execute(store, bot, pool, settings, job, kind):
    directory = job_dir(settings.jobs_dir, job.id)
    if await store.cancelled(job.id):
        raise UserError("Операция отменена.")
    if kind == "analyze":
        job.status = "analyzing"
        await store.save(job)
        await status(bot, job, "Анализ файла…")
        if job.mode != "single":
            for item in job.items:
                if "info" not in item:
                    item["info"] = await probe(directory / item["source"], settings.ffprobe)
                    item["info"]["tags"] = await asyncio.to_thread(
                        read_tags, directory / item["source"]
                    )
            job.info = dict(job.items[0]["info"])
            if job.mode == "merge":
                job.info["duration"] = sum(item["info"]["duration"] for item in job.items)
        else:
            job.info = await probe(directory / "source", settings.ffprobe)
            job.info["tags"] = await asyncio.to_thread(read_tags, directory / "source")
        picture = await asyncio.to_thread(cover_bytes, directory / "source")
        if picture:
            try:
                await asyncio.to_thread(normalize_cover, picture, directory / "original-cover.jpg")
                await bot.send_photo(job.chat_id, FSInputFile(directory / "original-cover.jpg"))
            except Exception:
                pass  # An invalid cover must not reject valid audio.
        if await store.cancelled(job.id):
            raise UserError("Операция отменена.")
        job.status = "editing"
        await store.save(job)
        await status(bot, job, card(job), menu(job.id))
        return
    job.status = "processing"
    await store.save(job)
    await status(bot, job, "Обработка… /cancel — отменить")
    source_name = "source"
    if job.mode == "merge":
        merged = await merge(job, directory, settings, lambda: store.cancelled(job.id))
        source_name = merged.name
        original_format = job.info["format"]
        original_tags = job.info.get("tags", {})
        job.info = await probe(merged, settings.ffprobe)
        job.edits.target = job.edits.target or original_format
        if job.edits.preserve_tags:
            job.edits.tags = {**original_tags, **job.edits.tags}
        if job.edits.cover == "keep" and (directory / "original-cover.jpg").exists():
            import shutil

            await asyncio.to_thread(
                shutil.copyfile, directory / "original-cover.jpg", directory / "cover.jpg"
            )
            job.edits.cover = "replace"
    items = job.items if job.mode == "batch" else [{"source": source_name, "info": job.info}]
    for index, item in enumerate(items):
        job.info = item["info"]
        job.status = "processing"
        await store.save(job)
        await status(bot, job, f"Обработка {index + 1}/{len(items)}… /cancel — отменить")
        result = await convert(
            job,
            directory,
            settings,
            lambda: store.cancelled(job.id),
            item["source"],
            f"result_{index}",
        )
        if await store.cancelled(job.id):
            raise UserError("Операция отменена.")
        job.status = "sending"
        await store.save(job)
        await status(bot, job, f"Отправка результата {index + 1}/{len(items)}…")
        suffix = f"_{index + 1}" if len(items) > 1 else ""
        payload = FSInputFile(
            result, filename=safe_name(job.edits.filename) + suffix + result.suffix
        )
        delivery = job.edits.delivery
        if delivery == "voice":
            await bot.send_voice(job.chat_id, payload)
        elif delivery != "document" and result.suffix in {".mp3", ".m4a"}:
            await bot.send_audio(job.chat_id, payload)
        else:
            await bot.send_document(job.chat_id, payload)
        result.unlink()
    await asyncio.to_thread(remove_job, settings.jobs_dir, job.id)
    await store.forget(job)
    await status(
        bot, job, "Готово. Рабочие файлы удалены. Отправьте новый файл для следующей операции."
    )
    await pool.execute(
        "INSERT INTO job_counts(outcome,total) VALUES('success',1) ON CONFLICT(day,outcome) DO UPDATE SET total=job_counts.total+1"
    )


async def main():
    settings = Settings()
    settings.jobs_dir.mkdir(parents=True, exist_ok=True)
    # The socket deadline must exceed BLMOVE's five-second idle wait.
    redis = Redis.from_url(settings.redis_url, socket_timeout=15)
    store = Store(redis)
    bot = make_bot(settings)
    pool = await connect(settings.database_url.get_secret_value())
    health = asyncio.create_task(
        heartbeat(redis, f"health:worker:{socket.gethostname()}:{os.getpid()}")
    )
    try:
        while True:
            item = await redis.blmove("queue", "processing", timeout=5, src="LEFT", dest="RIGHT")
            if not item:
                continue
            token = item.decode()
            kind, job_id = token.split(":", 1)
            lease = redis.lock(
                f"lease:{job_id}", timeout=settings.operation_timeout + 600, blocking_timeout=0
            )
            if not await lease.acquire():
                async with redis.pipeline(transaction=True) as pipe:
                    pipe.lrem("processing", 1, item)
                    pipe.rpush("queue", item)
                    await pipe.execute()
                await asyncio.sleep(0.25)
                continue
            live = asyncio.create_task(heartbeat(redis, f"active:{job_id}"))
            job = None
            try:
                job = await store.get(job_id)
                if job:
                    async with asyncio.timeout(settings.operation_timeout + 300):
                        await execute(store, bot, pool, settings, job, kind)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("job=%s error=%s", job_id, type(exc).__name__)
                if job:
                    message = (
                        str(exc)
                        if isinstance(exc, UserError)
                        else "Не удалось завершить задачу. Отправьте файл повторно."
                    )
                    await status(bot, job, message)
                    await asyncio.to_thread(remove_job, settings.jobs_dir, job.id)
                    await store.forget(job)
                    await pool.execute(
                        "INSERT INTO job_counts(outcome,total) VALUES($1,1) ON CONFLICT(day,outcome) DO UPDATE SET total=job_counts.total+1",
                        type(exc).__name__,
                    )
            finally:
                live.cancel()
                with suppress(asyncio.CancelledError):
                    await live
                await redis.delete(f"active:{job_id}")
                await redis.lrem("processing", 1, item)
                with suppress(Exception):
                    await lease.release()
    finally:
        health.cancel()
        with suppress(asyncio.CancelledError):
            await health
        await bot.session.close()
        await pool.close()
        await redis.aclose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(name)s %(message)s")
    from .runtime import run_service

    run_service(main)
