import json
from pathlib import Path

from .files import UserError
from .process import run

DEMUXERS = "mp3,mov,ogg,wav,flac,aac,aiff,asf"


async def probe(path: Path, executable="ffprobe") -> dict:
    raw = await run(
        [
            executable,
            "-v",
            "error",
            "-protocol_whitelist",
            "file",
            "-format_whitelist",
            DEMUXERS,
            "-show_entries",
            "format=format_name,duration,bit_rate:stream=codec_type,codec_name,duration,sample_rate",
            "-of",
            "json",
            str(path),
        ],
        30,
    )
    data = json.loads(raw)
    streams = [s for s in data.get("streams", []) if s["codec_type"] == "audio"]
    if not streams:
        raise UserError("В файле нет поддерживаемого аудиопотока.")
    stream, fmt = streams[0], data["format"]
    name = fmt["format_name"].split(",")[0]
    ext = {"mov": "m4a", "asf": "wma"}.get(name, name)
    if name == "ogg" and stream["codec_name"] == "opus":
        ext = "opus"
    duration = float(fmt.get("duration", stream.get("duration", 0)))
    if duration <= 0:
        raise UserError("Не удалось определить длительность записи.")
    return dict(
        format=ext,
        codec=stream["codec_name"],
        duration=duration,
        size=path.stat().st_size,
        bitrate=int(fmt.get("bit_rate", 0)),
        sample_rate=int(stream.get("sample_rate", 0)),
    )
