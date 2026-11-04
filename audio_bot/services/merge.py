from pathlib import Path

from .files import UserError, space_check
from .probe import DEMUXERS
from .process import run


async def merge(job, directory: Path, settings, cancelled):
    if len(job.items) < 2:
        raise UserError("Для объединения нужны хотя бы два файла.")
    order = job.order or list(range(len(job.items)))
    if sorted(order) != list(range(len(job.items))):
        raise UserError("Некорректный порядок файлов.")
    duration = sum(item["info"]["duration"] for item in job.items)
    estimated = int(duration * 48000 * 2 * 2)
    used = sum(p.stat().st_size for p in directory.iterdir() if p.is_file())
    if estimated + used > settings.job_quota_bytes:
        raise UserError(
            "Объединение превысит дисковую квоту. Уменьшите число или длительность файлов."
        )
    space_check(directory, estimated * 2, settings.disk_reserve_bytes)
    args = [settings.ffmpeg, "-v", "error", "-nostdin", "-y"]
    for index in order:
        args += [
            "-protocol_whitelist",
            "file",
            "-format_whitelist",
            DEMUXERS,
            "-i",
            str(directory / job.items[index]["source"]),
        ]
    graph = ";".join(
        f"[{i}:a:0]aresample=48000,aformat=sample_fmts=s16:channel_layouts=stereo[a{i}]"
        for i in range(len(order))
    )
    graph += (
        ";" + "".join(f"[a{i}]" for i in range(len(order))) + f"concat=n={len(order)}:v=0:a=1[out]"
    )
    result = directory / "merged.wav"
    args += [
        "-filter_complex_threads",
        "1",
        "-filter_complex",
        graph,
        "-map",
        "[out]",
        "-c:a",
        "pcm_s16le",
        "-threads",
        "1",
        str(result),
    ]

    def guard():
        if (
            sum(p.stat().st_size for p in directory.iterdir() if p.is_file())
            > settings.job_quota_bytes
        ):
            raise UserError("Превышена дисковая квота.")
        space_check(directory, 0, settings.disk_reserve_bytes)

    await run(args, settings.operation_timeout, cancelled, guard)
    return result
