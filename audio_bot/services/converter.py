import asyncio
import shutil
from pathlib import Path

from ..models import Job
from .audio import filters
from .covers import normalize_cover
from .files import UserError, space_check
from .metadata import cover_bytes, read_tags, write_metadata
from .probe import DEMUXERS
from .process import run

CODECS = {
    "mp3": ["-c:a", "libmp3lame"],
    "m4a": ["-c:a", "aac"],
    "aac": ["-c:a", "aac"],
    "opus": ["-c:a", "libopus"],
    "ogg": ["-c:a", "libvorbis"],
    "wav": ["-c:a", "pcm_s16le"],
    "flac": ["-c:a", "flac"],
    "aiff": ["-c:a", "pcm_s16be"],
    "wma": ["-c:a", "wmav2"],
}
COMPATIBLE = {
    "mp3": {"mp3"},
    "m4a": {"aac", "alac"},
    "aac": {"aac"},
    "opus": {"opus"},
    "ogg": {"vorbis", "opus"},
    "flac": {"flac"},
    "wav": {"pcm_s16le", "pcm_s24le"},
    "aiff": {"pcm_s16be"},
    "wma": {"wmav2"},
}


async def convert(
    job: Job, directory: Path, settings, cancelled, source_name="source", output_name="result"
):
    edits = job.edits
    target = "opus" if edits.delivery == "voice" else edits.target or job.info["format"]
    if target not in CODECS:
        raise UserError("Неподдерживаемый целевой формат.")
    source = directory / source_name
    result = directory / f"{output_name}.{target}"
    effects = filters(edits, job.info["duration"])
    # areverse buffers the whole track; reject long recordings before launching FFmpeg.
    if edits.silence and job.info["duration"] > 600:
        raise UserError("Удаление тишины доступно для записей до 10 минут.")
    space_check(
        directory,
        min(settings.job_quota_bytes, source.stat().st_size * 3),
        settings.disk_reserve_bytes,
    )

    def guard():
        total = sum(p.stat().st_size for p in directory.iterdir() if p.is_file())
        if total > settings.job_quota_bytes:
            raise UserError("Превышена дисковая квота задачи.")
        space_check(directory, 0, settings.disk_reserve_bytes)

    unchanged = (
        target == job.info["format"] and not effects and not edits.bitrate and edits.preserve_tags
    )
    if unchanged:
        await asyncio.to_thread(shutil.copyfile, source, result)
    else:
        copy = not effects and not edits.bitrate and job.info["codec"] in COMPATIBLE[target]
        args = [
            settings.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-protocol_whitelist",
            "file",
            "-format_whitelist",
            DEMUXERS,
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-vn",
            "-map_metadata",
            "-1",
            "-threads",
            "1",
        ]
        args += ["-c:a", "copy"] if copy else CODECS[target]
        if not copy:
            if target == "mp3":
                args += ["-b:a", f"{edits.bitrate}k"] if edits.bitrate else ["-q:a", "2"]
            elif target in {"m4a", "aac", "wma", "opus"}:
                args += ["-b:a", "128k" if target == "opus" else "192k"]
            if target == "opus":
                args += ["-ar", "48000"]
        if effects:
            args += ["-af", ",".join(effects)]
        args += [str(result)]
        await run(args, settings.operation_timeout, cancelled, guard)
    if await cancelled():
        raise UserError("Операция отменена.")
    guard()
    tags = (
        {} if unchanged or not edits.preserve_tags else await asyncio.to_thread(read_tags, source)
    )
    tags.update(edits.tags)
    action, cover = edits.cover, directory / "cover.jpg"
    if not unchanged and action == "keep":
        existing = await asyncio.to_thread(cover_bytes, source)
        if existing:
            await asyncio.to_thread(normalize_cover, existing, cover)
            action = "replace"
    if target in {"aac", "wma"}:
        if action == "replace" and edits.incompatible_cover == "error":
            raise UserError(
                "Выбранный формат не поддерживает обложку. Измените формат или настройку обложек."
            )
        if edits.tags or edits.cover == "replace":
            raise UserError("Для редактирования тегов и обложек выберите MP3, M4A, FLAC или OGG.")
    else:
        await asyncio.to_thread(write_metadata, result, tags, action, cover)
    if result.stat().st_size > settings.max_output_bytes:
        raise UserError("Результат превышает лимит отправки. Выберите сжатый формат или обрезку.")
    return result
