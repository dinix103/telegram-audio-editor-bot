import json
from pathlib import Path

import asyncpg


async def connect(url):
    pool = await asyncpg.create_pool(url, min_size=1, max_size=5)
    async with pool.acquire() as connection, connection.transaction():
        await connection.execute("SELECT pg_advisory_xact_lock(819271)")
        await connection.execute(Path("migrations/001_initial.sql").read_text(encoding="utf-8"))
    return pool


async def preferences(pool, user_id):
    raw = await pool.fetchval("SELECT settings FROM preferences WHERE user_id=$1", user_id)
    return json.loads(raw) if raw else {}


async def set_preferences(pool, user_id, settings):
    await pool.execute(
        "INSERT INTO preferences(user_id,settings) VALUES($1,$2::jsonb) ON CONFLICT(user_id) DO UPDATE SET settings=excluded.settings",
        user_id,
        json.dumps(settings),
    )
