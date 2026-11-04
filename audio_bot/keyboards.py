from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

FIELDS = {
    "title": "Название",
    "artist": "Исполнитель",
    "album": "Альбом",
    "albumartist": "Исполнитель альбома",
    "date": "Год",
    "genre": "Жанр",
    "tracknumber": "Номер трека",
    "discnumber": "Номер диска",
    "composer": "Композитор",
    "comment": "Комментарий",
    "filename": "Имя файла",
}


def keyboard(job_id, rows):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=title, callback_data=f"{job_id}:{action}")
                for title, action in row
            ]
            for row in rows
        ]
    )


def menu(job_id):
    return keyboard(
        job_id,
        [
            [("✏️ Название", "tag_title"), ("👤 Исполнитель", "tag_artist")],
            [("💿 Альбом", "tag_album"), ("📅 Год", "tag_date")],
            [("🏷 Все теги", "tags"), ("🖼 Обложка", "covers")],
            [("🔄 Конвертировать", "formats"), ("✂️ Обработать", "effects")],
            [("📤 Способ отправки", "delivery"), ("🎚 Качество", "quality")],
            [("✅ Сохранить", "summary"), ("❌ Отменить", "cancel")],
        ],
    )


def back(job_id):
    return keyboard(job_id, [[("⬅️ Назад", "menu"), ("❌ Отменить", "cancel")]])


def main_menu():
    return keyboard(
        "home",
        [
            [("🎵 Конвертер", "convert"), ("✏️ Редактор тегов", "tags")],
            [("🖼 Обложки", "covers"), ("✂️ Обработка аудио", "effects")],
            [("⚙️ Настройки", "settings"), ("❓ Помощь", "help")],
        ],
    )


def card(job):
    info, edits = job.info, job.edits
    tags = {**info.get("tags", {}), **edits.tags}
    collection = ""
    if job.mode != "single":
        collection = f"Режим: {'объединение' if job.mode == 'merge' else 'пакет'}. Файлов: {len(job.items)}/10\n"
        collection += (
            "Порядок: "
            + " ".join(str(i + 1) for i in (job.order or range(len(job.items))))
            + "\nДобавьте следующий файл или сохраните. /order — порядок.\n\n"
        )
    return (
        collection
        + (
            f"🎵 {tags.get('title') or 'Без названия'}\n"
            f"👤 {tags.get('artist') or 'Не указан'}\n"
            f"{info.get('format', '?').upper()} · {info.get('codec', '?')}\n"
            f"Длительность: {info.get('duration', 0):.1f} с\n"
            f"Размер: {info.get('size', 0) / 1_000_000:.1f} МБ\n"
            f"Битрейт: {info.get('bitrate', 0) // 1000} кбит/с · {info.get('sample_rate', 0)} Гц\n\n"
            "Изменения применятся после подтверждения сохранения."
        )[:3500]
    )
