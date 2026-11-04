FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 10001 audioapp && useradd -u 10001 -g audioapp -m audioapp
WORKDIR /app
COPY pyproject.toml ./
COPY requirements.lock ./
COPY audio_bot ./audio_bot
COPY migrations ./migrations
COPY tools/purge_api_cache.py ./tools/purge_api_cache.py
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps . \
    && mkdir -p /work/jobs && chown -R 10001:10001 /work
USER 10001:10001
CMD ["python", "-m", "audio_bot.bot"]
