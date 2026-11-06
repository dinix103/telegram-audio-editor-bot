"""Shared, escaped Telegram presentation and MP3 output policy."""

from html import escape

from .models import Edits

MUSIC_EMOJI = "5310045076531978942"
SPARK_EMOJI = "5309958691854754293"
CHECK_EMOJI = "5237699328843200968"
FIRE_EMOJI = "5312241539987020022"


def mp3_edits(values):
    """Migrate saved settings/old keyboards without allowing non-MP3 delivery."""
    data = values.model_dump() if isinstance(values, Edits) else dict(values or {})
    data["target"] = "mp3"
    if data.get("delivery") == "voice":
        data["delivery"] = "auto"
    return Edits.model_validate(data)


def quality(value):
    return f"{value} кбит/с" if value else "Авто · умный выбор"


def delivery(value):
    return "Документ .mp3" if value == "document" else "Музыка с плеером"


def clock(seconds):
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"


def on(value):
    return "Включено" if value else "Выключено"


def settings_text(edits):
    return (
        "⚙️ <b>Ваши настройки аудио</b>\n"
        "<i>Применяются к следующим загруженным файлам.</i>\n\n"
        "🎵 <b>Формат результата</b>  MP3\n"
        f"🎚 <b>Качество</b>  {quality(edits.bitrate)}\n"
        f"📤 <b>Отправка</b>  {delivery(edits.delivery)}\n"
        f"🏷 <b>Сохранять исходные теги</b>  {on(edits.preserve_tags)}\n"
        f"✅ <b>Подтверждать сохранение</b>  {on(edits.confirm)}\n\n"
        "<b>Как выбрать качество?</b>\n"
        "Авто — сохраняет звук MP3 без перекодирования, когда возможно; "
        "для остальных файлов подбирает переменный битрейт.\n"
        "128 — компактно · 192 — баланс · 256/320 — больше размер.\n"
        "<i>Высокий битрейт не улучшает качество исходной записи.</i>\n\n"
        "Нажмите на вариант ниже — отметка ✓ покажет ваш выбор."
    )


def effects_text(edits):
    trim = f"{clock(edits.trim[0])} → {clock(edits.trim[1])}" if edits.trim else "Весь трек"
    return (
        "🎛 <b>Обработка звука</b>\n\n"
        f"✂️ <b>Фрагмент:</b> {trim}\n"
        f"⏩ <b>Скорость:</b> {edits.speed:g}×\n"
        f"🔊 <b>Громкость:</b> {edits.volume:+g} дБ\n"
        f"📊 <b>Нормализация:</b> {on(edits.normalize)}\n"
        f"🤫 <b>Тишина по краям:</b> {on(edits.silence)}\n\n"
        "Нормализация выравнивает громкость. Удаление тишины доступно "
        "для записей до 10 минут. Скорость меняется без повышения тона.\n"
        "<i>Эффекты применятся при сохранении в MP3.</i>"
    )


def summary_text(job, fields):
    edits = mp3_edits(job.edits)
    tags = "\n".join(
        f"{fields.get(k, k)}: {escape(v[:40]) if v else 'Удалить'}" for k, v in edits.tags.items()
    ) or ("Исходные теги" if edits.preserve_tags else "Только добавленные теги")
    cover = {"keep": "Сохранить", "replace": "Заменить", "remove": "Удалить"}[edits.cover]
    trim = f"{clock(edits.trim[0])} → {clock(edits.trim[1])}" if edits.trim else "Весь трек"
    return (
        "✅ <b>Всё готово к сохранению</b>\n\n"
        f"📄 <b>Файл:</b> {escape(edits.filename[:80])}.mp3\n"
        f"🎵 <b>MP3</b> · {quality(edits.bitrate)}\n"
        f"📤 {delivery(edits.delivery)}\n\n"
        f"<b>Теги</b>\n{tags}\n"
        f"🖼 Обложка: {cover}\n\n"
        f"✂️ {trim} · ⏩ {edits.speed:g}× · 🔊 {edits.volume:+g} дБ\n"
        f"Нормализация: {on(edits.normalize)}\n"
        f"Удаление тишины: {on(edits.silence)}\n\n"
        "Нажмите «Получить MP3», чтобы начать обработку."
    )


def progress_text(title, frame=0, elapsed=0):
    bars = ("▰▱▱▱▱", "▱▰▱▱▱", "▱▱▰▱▱", "▱▱▱▰▱", "▱▱▱▱▰", "▱▱▱▰▱")
    return (
        f"🎶 <b>{escape(title)}</b>\n\n"
        f"<code>{bars[frame % len(bars)]}</code>  {clock(elapsed)}\n\n"
        "Готовим ваш MP3. Это может занять немного времени.\n"
        "<i>/cancel — отменить обработку</i>"
    )
