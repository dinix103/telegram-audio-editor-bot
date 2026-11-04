import os
import shutil
from pathlib import Path

import pytest

from audio_bot.config import Settings


@pytest.fixture
def settings(tmp_path):
    def binary(name):
        local = Path(__file__).parents[1] / "tools" / "bin" / f"{name}.exe"
        result = (
            os.environ.get(name.upper())
            or shutil.which(name)
            or (str(local) if local.exists() else None)
        )
        if not result:
            pytest.skip(f"{name} is required for media integration tests")
        return result

    return Settings(
        _env_file=None,
        bot_token="123456:TEST",
        jobs_dir=tmp_path,
        telegram_dir=tmp_path.parent / "telegram-cache",
        ffmpeg=binary("ffmpeg"),
        ffprobe=binary("ffprobe"),
        disk_reserve_bytes=0,
        job_quota_bytes=100_000_000,
    )
