import hashlib
import time
import uuid

import pytest
from PIL import Image

from audio_bot.models import Edits, Job
from audio_bot.services.converter import convert
from audio_bot.services.covers import normalize_cover
from audio_bot.services.files import UserError
from audio_bot.services.metadata import cover_bytes, read_tags, write_metadata
from audio_bot.services.probe import probe
from audio_bot.services.process import run


async def not_cancelled():
    return False


async def fixture_audio(settings, directory, fmt="wav", seconds=2):
    path = directory / f"fixture.{fmt}"
    await run(
        [
            settings.ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-y",
            str(path),
        ],
        30,
    )
    return path


async def create_job(settings, tmp_path, fmt="wav", edits=None):
    directory = tmp_path / uuid.uuid4().hex
    directory.mkdir()
    path = await fixture_audio(settings, directory, fmt)
    info = await probe(path, settings.ffprobe)
    path.rename(directory / "source")
    return Job(
        id=directory.name,
        user_id=1,
        chat_id=1,
        status_message_id=1,
        touched=time.time(),
        info=info,
        edits=edits or Edits(),
    ), directory


@pytest.mark.parametrize(
    "source,target",
    [
        ("opus", "mp3"),
        ("mp3", "m4a"),
        ("m4a", "mp3"),
        ("flac", "mp3"),
        ("wav", "opus"),
        ("mp3", "ogg"),
        ("mp3", "wav"),
        ("wav", "flac"),
        ("aac", "mp3"),
        ("aiff", "mp3"),
        ("wma", "mp3"),
    ],
)
async def test_real_conversions(settings, tmp_path, source, target):
    job, directory = await create_job(settings, tmp_path, source, Edits(target=target))
    output = await convert(job, directory, settings, not_cancelled)
    info = await probe(output, settings.ffprobe)
    assert info["format"] == target
    assert 1.8 < info["duration"] < 2.3


@pytest.mark.parametrize("fmt", ["mp3", "m4a", "flac", "ogg", "opus", "wav", "aiff"])
async def test_tags_covers_and_lossless_edit(settings, tmp_path, fmt):
    job, directory = await create_job(settings, tmp_path, fmt)
    source = directory / "source"
    raw = directory / "cover.png"
    Image.new("RGB", (64, 64), "blue").save(raw)
    normalize_cover(raw, directory / "cover.jpg")
    job.edits = Edits(
        tags={
            "title": "Тест",
            "artist": "Артист",
            "album": "Альбом",
            "date": "2026",
            "tracknumber": "1/10",
            "comment": "Комментарий",
        },
        cover="replace",
    )

    async def decoded_digest(path):
        data = await run(
            [
                settings.ffmpeg,
                "-v",
                "error",
                "-i",
                str(path),
                "-map",
                "0:a:0",
                "-f",
                "s16le",
                "-c:a",
                "pcm_s16le",
                "-",
            ],
            30,
        )
        return hashlib.sha256(data).digest()

    before = await decoded_digest(source)
    result = await convert(job, directory, settings, not_cancelled)
    assert read_tags(result)["title"] == "Тест"
    assert read_tags(result)["artist"] == "Артист"
    assert cover_bytes(result)
    assert await decoded_digest(result) == before
    write_metadata(result, {"title": ""}, "remove")
    assert "title" not in read_tags(result)
    assert cover_bytes(result) is None


async def test_voice(settings, tmp_path):
    job, directory = await create_job(settings, tmp_path, "mp3", Edits(delivery="voice"))
    result = await convert(job, directory, settings, not_cancelled)
    assert (await probe(result, settings.ffprobe))["codec"] == "opus"


async def test_effects(settings, tmp_path):
    job, directory = await create_job(
        settings, tmp_path, "wav", Edits(trim=(0.5, 1.5), speed=2, volume=3, normalize=True)
    )
    result = await convert(job, directory, settings, not_cancelled)
    assert 0.4 < (await probe(result, settings.ffprobe))["duration"] < 0.65


async def test_corrupt_and_spoofed_input(settings, tmp_path):
    bad = tmp_path / "fake.mp3"
    bad.write_bytes(b"not audio")
    with pytest.raises(UserError):
        await probe(bad, settings.ffprobe)
    source = await fixture_audio(settings, tmp_path)
    source.replace(bad)
    assert (await probe(bad, settings.ffprobe))["format"] == "wav"


async def test_result_limit(settings, tmp_path):
    job, directory = await create_job(settings, tmp_path)
    settings.max_output_bytes = 10
    with pytest.raises(UserError, match="лимит отправки"):
        await convert(job, directory, settings, not_cancelled)


def test_bad_cover(tmp_path):
    with pytest.raises(UserError):
        normalize_cover(b"not an image", tmp_path / "cover.jpg")


async def test_merge_different_formats(settings, tmp_path):
    from audio_bot.services.merge import merge

    job, directory = await create_job(settings, tmp_path, "mp3")
    second = await fixture_audio(settings, directory, "wav")
    second.rename(directory / "source_1")
    job.items = [
        {"source": "source", "info": job.info},
        {"source": "source_1", "info": await probe(directory / "source_1", settings.ffprobe)},
    ]
    job.order = [1, 0]
    job.mode = "merge"
    output = await merge(job, directory, settings, not_cancelled)
    assert 3.8 < (await probe(output, settings.ffprobe))["duration"] < 4.2


async def test_metadata_survives_conversion(settings, tmp_path):
    job, directory = await create_job(settings, tmp_path, "mp3", Edits(target="flac"))
    source = directory / "source"
    write_metadata(source, {"title": "Сохранённый тег"})
    output = await convert(job, directory, settings, not_cancelled)
    assert read_tags(output)["title"] == "Сохранённый тег"
