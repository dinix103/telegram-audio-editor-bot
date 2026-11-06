from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .ui import CHECK_EMOJI, FIRE_EMOJI, MUSIC_EMOJI, SPARK_EMOJI, clock, delivery, quality

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


def button_style(action, title):
    if action in {"cancel", "cover_remove"}:
        return "danger"
    if action in {"save", "summary"} or title.startswith("✓"):
        return "success"
    if action in {"convert", "formats", "settings", "quality", "effects", "tags"}:
        return "primary"
    return None


def keyboard(job_id, rows):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=title,
                    callback_data=f"{job_id}:{action}",
                    style=button_style(action, title),
                    icon_custom_emoji_id=(
                        CHECK_EMOJI
                        if action in {"save", "summary"}
                        else FIRE_EMOJI
                        if action == "effects"
                        else SPARK_EMOJI
                        if action in {"settings", "quality"}
                        else MUSIC_EMOJI
                        if action in {"convert", "formats"}
                        else None
                    ),
                )
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
            [("🏷 Остальные теги", "tags"), ("🖼 Обложка", "covers")],
            [("🎛 Обработка звука", "effects"), ("🎚 Качество MP3", "quality")],
            [("📤 Отправка", "delivery"), ("📄 Имя файла", "tag_filename")],
            [("✅ Сохранить в MP3", "summary")],
            [("✕ Отменить", "cancel")],
        ],
    )


def back(job_id):
    return keyboard(job_id, [[("⬅️ Назад", "menu"), ("❌ Отменить", "cancel")]])


def main_menu():
    return keyboard(
        "home",
        [
            [("🎵 Любое аудио → MP3", "convert")],
            [("✏️ Теги и обложка", "tags"), ("🎛 Обработка звука", "effects")],
            [("🔗 Объединить", "merge"), ("📚 Несколько файлов", "batch")],
            [("⚙️ Настройки", "settings"), ("❓ Помощь", "help")],
        ],
    )


def card(job):
    info, edits = job.info, job.edits
    tags = {**info.get("tags", {}), **edits.tags}
    collection = ""
    if job.mode != "single":
        collection = (
            f"📚 {'Объединение' if job.mode == 'merge' else 'Пакет'} · {len(job.items)}/10 файлов\n"
        )
        collection += (
            "Порядок: "
            + " ".join(str(i + 1) for i in (job.order or range(len(job.items))))
            + "\nДобавьте следующий файл или сохраните. /order — порядок.\n\n"
        )
    return collection + (
        "🎧 <b>Аудиостудия · ваш трек</b>\n\n"
        f"<b>{escape((tags.get('title') or 'Без названия')[:150])}</b>\n"
        f"👤 {escape((tags.get('artist') or 'Исполнитель не указан')[:150])}\n\n"
        f"<b>Исходник</b>  {escape(info.get('format', '?').upper())} · "
        f"{clock(info.get('duration', 0))} · {info.get('size', 0) / 1_000_000:.1f} МБ\n"
        f"<b>Результат</b>  MP3 · {quality(edits.bitrate)}\n"
        f"<b>Отправка</b>  {delivery(edits.delivery)}\n\n"
        "<b>1.</b> Выберите правки  →  <b>2.</b> Сохраните в MP3\n"
        "<i>Все изменения применятся вместе при сохранении.</i>"
    )


def selected(title, active):
    return f"✓ {title}" if active else title


def quality_rows(edits, prefix="bitrate_"):
    return [
        [(selected("Авто", edits.bitrate == 0), f"{prefix}0")],
        [(selected(f"{v} кбит/с", edits.bitrate == v), f"{prefix}{v}") for v in (128, 192)],
        [(selected(f"{v} кбит/с", edits.bitrate == v), f"{prefix}{v}") for v in (256, 320)],
    ]


def settings_keyboard(edits):
    return keyboard(
        "settings",
        quality_rows(edits)
        + [
            [
                (selected("🎵 Музыка", edits.delivery != "document"), "delivery_auto"),
                (selected("📎 Документ", edits.delivery == "document"), "delivery_document"),
            ],
            [(selected("🏷 Сохранять теги", edits.preserve_tags), "toggle_tags")],
            [(selected("✅ Подтверждать", edits.confirm), "toggle_confirm")],
            [("⌂ Главное меню", "home")],
        ],
    )


def effects_keyboard(job_id, edits):
    return keyboard(
        job_id,
        [
            [("✂️ Обрезка", "trim"), ("🔊 Громкость", "volume")],
            [
                (selected("Нормализация", edits.normalize), "normalize"),
                (selected("Убрать тишину", edits.silence), "silence"),
            ],
            [(selected(f"{v:g}×", edits.speed == v), f"speed_{v}") for v in (0.5, 1, 1.5)],
            [(selected(f"{v:g}×", edits.speed == v), f"speed_{v}") for v in (0.75, 1.25, 2)],
            [("⬅️ К треку", "menu")],
        ],
    )
