import asyncio
from contextlib import suppress

from .files import UserError


async def run(args: list[str], timeout: int, cancelled=None, guard=None) -> bytes:
    process = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )

    async def monitor():
        while process.returncode is None:
            if cancelled and await cancelled():
                raise UserError("Операция отменена.")
            if guard:
                guard()
            await asyncio.sleep(0.25)

    watcher = asyncio.create_task(monitor())
    output = asyncio.create_task(process.communicate())
    try:
        done, _ = await asyncio.wait(
            {watcher, output}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
        )
        if not done:
            raise UserError("Превышено время обработки.")
        if watcher in done:
            await watcher
        data, _ = await output
        if process.returncode:
            raise UserError("Не удалось обработать файл. Проверьте формат и целостность.")
        return data
    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()
        watcher.cancel()
        output.cancel()
        with suppress(asyncio.CancelledError):
            await watcher
        with suppress(asyncio.CancelledError):
            await output
