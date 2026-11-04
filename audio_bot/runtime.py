import asyncio
import signal
from contextlib import suppress


def run_service(main):
    async def supervised():
        task = asyncio.create_task(main())
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGTERM, signal.SIGINT):
            with suppress(NotImplementedError):
                loop.add_signal_handler(signum, task.cancel)
        with suppress(asyncio.CancelledError):
            await task

    asyncio.run(supervised())
