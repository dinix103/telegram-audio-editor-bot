import asyncio
import sys

import pytest

from audio_bot.config import Settings
from audio_bot.models import Edits
from audio_bot.services.audio import filters, timestamp
from audio_bot.services.files import UserError, job_dir, local_input, safe_name, space_check
from audio_bot.services.process import run


@pytest.mark.parametrize("value", ["../secret", "x" * 32, "a" * 31, "/tmp", "a" * 32 + "/.."])
def test_reject_traversal(tmp_path, value):
    with pytest.raises(UserError):
        job_dir(tmp_path, value)


def test_file_outside_telegram_root(tmp_path):
    source = tmp_path / "secret"
    source.write_text("private")
    with pytest.raises(UserError):
        local_input(tmp_path / "telegram", str(source), 100)


def test_names():
    assert "/" not in safe_name("../../secret.mp3")
    assert "\\" not in safe_name("..\\secret")
    assert safe_name("CON") == "audio"


def test_public_api_rejected():
    with pytest.raises(ValueError):
        Settings(_env_file=None, bot_token="123:abc", bot_api_url="https://api.telegram.org")


@pytest.mark.parametrize("value", ["-1", "00:90", "nan", "inf", "1:2:3:4", "hello"])
def test_bad_timestamp(value):
    with pytest.raises(UserError):
        timestamp(value)


def test_trim_validation():
    assert timestamp("01:30") == 90
    with pytest.raises(UserError):
        filters(Edits(trim=(10, 2)), 30)
    with pytest.raises(UserError):
        filters(Edits(trim=(0, 31)), 30)


def test_no_space(tmp_path):
    with pytest.raises(UserError):
        space_check(tmp_path, 10**30, 0)


async def test_process_timeout():
    with pytest.raises(UserError, match="время"):
        await run([sys.executable, "-c", "import time; time.sleep(30)"], 0.1)


async def test_process_cancellation():
    async def cancelled():
        return True

    with pytest.raises(UserError, match="отменена"):
        await run([sys.executable, "-c", "import time; time.sleep(30)"], 5, cancelled)


async def test_parent_cancellation():
    task = asyncio.create_task(run([sys.executable, "-c", "import time; time.sleep(30)"], 60))
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
