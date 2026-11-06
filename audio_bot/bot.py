import asyncio
import logging
import shutil
import time
import uuid
from contextlib import suppress
from html import escape
from pathlib import Path

from aiogram import BaseMiddleware, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.redis import RedisEventIsolation, RedisStorage
from aiogram.types import BotCommand, CallbackQuery, FSInputFile, Message
from redis.asyncio import Redis

from .config import Settings
from .database import connect, preferences, set_preferences
from .keyboards import (
    FIELDS,
    back,
    card,
    effects_keyboard,
    keyboard,
    main_menu,
    menu,
    quality_rows,
    settings_keyboard,
)
from .models import Edits, Job
from .services.audio import filters, timestamp
from .services.covers import normalize_cover
from .services.files import UserError, job_dir, local_input, remove_job, safe_name, space_check
from .states import Editor
from .store import Store
from .telegram import make_bot
from .ui import effects_text, mp3_edits, quality, settings_text, summary_text

router = Router()
log = logging.getLogger("audio-bot")
HELP = (
    "🎧 <b>AUDIX · ваша аудиостудия</b>\n"
    "<i>Любой поддерживаемый аудиофайл → MP3</i>\n\n"
    "<b>1.</b> Отправьте музыку, голосовое или документ.\n"
    "<b>2.</b> Измените теги, обложку или звучание.\n"
    "<b>3.</b> Нажмите «Сохранить в MP3» — получите готовый трек.\n\n"
    "🎚 Качество · ✂️ Обрезка · 🔊 Громкость · ⏩ Скорость\n\n"
    "/settings — настройки следующих файлов\n"
    "/merge — объединить · /batch — обработать несколько\n"
    "/order — порядок · /cancel — отменить\n"
    "/delete — удалить рабочие данные · /privacy — приватность"
)
PRIVACY = (
    "Аудио временно обрабатывается на нашем сервере без сторонних сервисов обработки. "
    "После отправки результата рабочие файлы удаляются; неактивные сессии — через 15 минут. "
    "Аварийные остатки удаляются фоновым процессом. Кэш локального Telegram Bot API "
    "имеет отдельный жизненный цикл. /delete отменяет задачу и удаляет рабочие данные "
    "и настройки. Это не удаляет сообщения и копии файлов из Telegram и с устройств."
)


class Guard(BaseMiddleware):
    async def __call__(self, handler, event, data):
        message = event.message if isinstance(event, CallbackQuery) else event
        if not isinstance(message, Message) or message.chat.type != "private":
            if isinstance(event, CallbackQuery):
                await event.answer("Бот работает только в личных сообщениях.", show_alert=True)
            return
        store = data["store"]
        lease = None
        job = await store.current(event.from_user.id)
        if job and job.status == "editing":
            lease = store.redis.lock(f"lease:{job.id}", timeout=120, blocking_timeout=0)
            if not await lease.acquire():
                await message.answer("Задача занята. Повторите действие через несколько секунд.")
                return
        try:
            return await handler(event, data)
        except Exception as exc:
            log.warning("handler error=%s", type(exc).__name__)
            await message.answer(
                escape(str(exc))
                if isinstance(exc, UserError)
                else "Не удалось выполнить действие. Попробуйте ещё раз или /cancel."
            )
        finally:
            if lease:
                with suppress(Exception):
                    await lease.release()


@router.message(Command("start", "help"))
async def start(message: Message):
    animation = Path("assets/studio.mp4")
    if message.text.split()[0].split("@")[0] == "/start" and animation.is_file():
        await message.answer_animation(
            FSInputFile(animation),
            caption=HELP,
            reply_markup=main_menu(),
        )
    else:
        await message.answer(HELP, reply_markup=main_menu())


@router.message(Command("privacy"))
async def privacy(message: Message):
    await message.answer(PRIVACY)


async def cancel_current(user_id, state, store, settings, pool=None):
    job = await store.current(user_id)
    await state.clear()
    await store.redis.delete(f"mode:{user_id}")
    if job:
        await store.redis.set(f"cancel:{job.id}", "1", ex=86400)
        if job.status == "editing":
            await asyncio.to_thread(remove_job, settings.jobs_dir, job.id)
            await store.forget(job)
    if pool:
        await pool.execute("DELETE FROM preferences WHERE user_id=$1", user_id)


@router.message(Command("cancel", "delete"))
async def cancel(message: Message, state: FSMContext, store, settings, pool):
    await cancel_current(
        message.from_user.id,
        state,
        store,
        settings,
        pool if message.text.split()[0] == "/delete" else None,
    )
    await message.answer(
        "Отмена запрошена. Рабочие файлы удаляются после остановки обработки. "
        "Копии в Telegram не удаляются."
    )


@router.message(Command("settings"))
async def settings_menu(message: Message, pool, user_id=None):
    current = mp3_edits(await preferences(pool, user_id or message.from_user.id))
    await message.answer(
        settings_text(current),
        reply_markup=settings_keyboard(current),
    )


@router.callback_query(F.data.startswith("settings:"))
async def setting_callback(callback: CallbackQuery, pool):
    action = callback.data.split(":", 1)[1]
    if action == "home":
        await callback.answer()
        await callback.message.edit_text(HELP, reply_markup=main_menu())
        return
    current = mp3_edits(await preferences(pool, callback.from_user.id)).model_dump()
    if action in {"toggle_tags", "toggle_confirm"}:
        key = "preserve_tags" if action == "toggle_tags" else "confirm"
        current[key] = not current[key]
    else:
        key, value = action.rsplit("_", 1)
        if key not in {
            "target",
            "bitrate",
            "delivery",
            "preserve_tags",
            "incompatible_cover",
            "confirm",
        }:
            await callback.answer()
            return
        current[key] = int(value) if key == "bitrate" else None if value == "none" else value
        if key in {"preserve_tags", "confirm"}:
            current[key] = value == "true"
    validated = mp3_edits(current)
    await set_preferences(pool, callback.from_user.id, validated.model_dump())
    await callback.answer("✓ Настройки сохранены")
    with suppress(Exception):
        await callback.message.edit_text(
            settings_text(validated),
            reply_markup=settings_keyboard(validated),
        )


@router.callback_query(F.data.startswith("home:"))
async def home_callback(callback: CallbackQuery, pool, store, state):
    await callback.answer()
    if callback.data == "home:settings":
        await settings_menu(callback.message, pool, callback.from_user.id)
    elif callback.data == "home:help":
        await callback.message.answer(HELP, reply_markup=main_menu())
    elif callback.data in {"home:merge", "home:batch"}:
        if await store.current(callback.from_user.id):
            raise UserError("Сначала сохраните текущий трек или нажмите /cancel.")
        await state.clear()
        mode = callback.data.split(":")[1]
        await store.redis.set(f"mode:{callback.from_user.id}", mode, ex=900)
        await callback.message.answer(
            f"📚 <b>{'Объединяем в один MP3' if mode == 'merge' else 'Обрабатываем несколько MP3'}</b>\n\n"
            "Отправляйте до 10 файлов по одному. Дождитесь анализа каждого, "
            "затем нажмите «Сохранить в MP3».\n\n/order — изменить порядок · /cancel — отменить"
        )
    else:
        await callback.message.answer(
            "📥 <b>Отправьте аудио</b>\n\n"
            "Подойдёт музыка, голосовое сообщение или файл документом. "
            "После анализа откроется студия с настройками. Результат — MP3."
        )


@router.message(Command("admin"))
async def admin(message: Message, settings, store, pool):
    if message.from_user.id not in settings.admin_ids:
        return
    parts = message.text.split()
    if len(parts) > 1 and parts[1] in {"pause", "resume"}:
        await store.redis.set("maintenance", "1" if parts[1] == "pause" else "0")
    if len(parts) == 3 and parts[1] == "limit":
        try:
            limit = int(parts[2])
            if not 1 <= limit <= settings.max_input_bytes // 1_000_000:
                raise ValueError
        except ValueError:
            raise UserError("Укажите лимит в МБ, не выше серверного MAX_INPUT_BYTES.") from None
        await store.redis.set("input_limit", limit * 1_000_000)
    disk = shutil.disk_usage(settings.jobs_dir)
    workers = len([key async for key in store.redis.scan_iter("health:worker:*")])
    sessions = len([key async for key in store.redis.scan_iter("user:*")])
    counts = await pool.fetch("SELECT outcome,sum(total) AS total FROM job_counts GROUP BY outcome")
    api_ok = True
    try:
        await message.bot.get_me()
    except Exception:
        api_ok = False
    await message.answer(
        f"Очередь: {await store.redis.llen('queue')}\n"
        f"Обработка: {await store.redis.llen('processing')}\n"
        f"Сессии: {sessions}\nWorkers: {workers}\nBot API: {api_ok}\n"
        f"Свободно: {disk.free // 1_000_000_000} ГБ\n"
        + "\n".join(f"{r['outcome']}: {r['total']}" for r in counts)
        + "\n/admin pause — обслуживание\n/admin resume — приём файлов\n/admin limit 500 — лимит входа в МБ"
    )


async def editable(store, user_id, job_id=None):
    job = await store.current(user_id)
    if not job or (job_id and job.id != job_id):
        raise UserError("Сессия устарела. Отправьте аудиофайл заново.")
    if job.status != "editing":
        raise UserError("Дождитесь завершения текущей операции или используйте /cancel.")
    return job


@router.message(Command("merge", "batch"))
async def collection(message: Message, state: FSMContext, store):
    if await store.current(message.from_user.id):
        raise UserError("Сначала завершите текущую задачу или /cancel.")
    mode = message.text.split()[0].split("@")[0][1:]
    await state.clear()
    await store.redis.set(f"mode:{message.from_user.id}", mode, ex=900)
    await message.answer(
        "Пришлите до 10 аудиофайлов по одному. Дождитесь анализа каждого. Затем выберите правки и сохраните. /order — порядок объединения."
    )


@router.message(Command("order"))
async def order(message: Message, state: FSMContext, store):
    job = await editable(store, message.from_user.id)
    if job.mode != "merge":
        raise UserError("Порядок доступен в режиме /merge.")
    await state.set_state(Editor.text)
    await state.update_data(job_id=job.id, field="order")
    await message.answer(
        "Введите все номера файлов в нужном порядке, например: 3 1 2", reply_markup=back(job.id)
    )


@router.callback_query()
async def action(callback: CallbackQuery, state: FSMContext, store, settings):
    await callback.answer()
    job_id, action = callback.data.split(":", 1)
    if action == "cancel":
        current = await store.current(callback.from_user.id)
        if current and current.id == job_id:
            await cancel_current(callback.from_user.id, state, store, settings)
        await callback.message.edit_text("Операция отменена.")
        return
    job = await editable(store, callback.from_user.id, job_id)
    job.edits = mp3_edits(job.edits)
    if action == "summary" and not job.edits.confirm:
        action = "save"
    await state.clear()
    text, markup = card(job), menu(job.id)
    if action.startswith("tag_") or action in {"trim", "volume"}:
        field = action.removeprefix("tag_")
        if field not in FIELDS and field not in {"trim", "volume"}:
            raise UserError("Неизвестное действие.")
        await state.set_state(Editor.text)
        await state.update_data(job_id=job.id, field=field)
        text = {
            "trim": "Введите начало и конец через пробел: 00:15 01:45",
            "volume": "Введите изменение громкости от −30 до +12 дБ. Усиление может исказить звук; включён ограничитель пиков.",
        }.get(field, f"Введите: {FIELDS.get(field, field)}. Знак - удаляет значение.")
        markup = back(job.id)
    elif action == "tags":
        text = "🏷 <b>Теги вашего трека</b>\n\nВыберите поле, которое хотите изменить."
        markup = keyboard(
            job.id,
            [[(name, f"tag_{field}")] for field, name in FIELDS.items()] + [[("⬅️ Назад", "menu")]],
        )
    elif action == "covers":
        text = "🖼 <b>Обложка MP3</b>\n\nЗагрузите изображение — оно будет встроено в трек. Можно также сохранить текущую обложку отдельно."
        markup = keyboard(
            job.id,
            [
                [("Загрузить", "cover_upload"), ("Извлечь / показать", "cover_extract")],
                [("Удалить", "cover_remove"), ("⬅️ Назад", "menu")],
            ],
        )
    elif action == "cover_upload":
        await state.set_state(Editor.cover)
        await state.update_data(job_id=job.id)
        text, markup = "Пришлите фотографию или JPEG/PNG документом (до 10 МБ).", back(job.id)
    elif action == "cover_remove":
        job.edits.cover = "remove"
        text = "Обложка будет удалена при сохранении."
    elif action == "cover_extract":
        directory = job_dir(settings.jobs_dir, job.id)
        picture = directory / (
            "cover.jpg" if job.edits.cover == "replace" else "original-cover.jpg"
        )
        if job.edits.cover == "remove" or not picture.exists():
            raise UserError("Обложки нет.")
        await callback.message.answer_document(FSInputFile(picture, filename="cover.jpg"))
    elif action == "formats":
        text = "🎵 <b>Результат всегда в MP3</b>\n\nВыберите качество или сразу сохраните трек."
        markup = keyboard(job.id, quality_rows(job.edits) + [[("⬅️ К треку", "menu")]])
    elif action.startswith("format_"):
        text = "🎵 <b>Выбран MP3</b>\n\nВсе результаты теперь сохраняются в этом формате."
    elif action == "quality":
        text = (
            "🎚 <b>Качество MP3</b>\n\n"
            f"Сейчас: <b>{quality(job.edits.bitrate)}</b>\n\n"
            "Авто — без лишнего перекодирования MP3; для других форматов — переменный битрейт.\n"
            "128 — компактно · 192 — баланс · 256/320 — больше размер.\n\n"
            "<i>Повышение битрейта не восстанавливает потерянные детали.</i>"
        )
        markup = keyboard(
            job.id,
            quality_rows(job.edits) + [[("⬅️ К треку", "menu")]],
        )
    elif action.startswith("bitrate_"):
        job.edits = Edits.model_validate({**job.edits.model_dump(), "bitrate": int(action[8:])})
        text = card(job)
    elif action == "delivery":
        text = "📤 <b>Как отправить MP3?</b>\n\nМузыка — встроенный плеер Telegram. Документ — обычный файл .mp3. Формат и качество одинаковые."
        markup = keyboard(
            job.id,
            [
                [
                    ("🎵 Музыка", "send_auto"),
                    ("📎 Документ", "send_document"),
                ],
                [("⬅️ Назад", "menu")],
            ],
        )
    elif action.startswith("send_"):
        job.edits = mp3_edits({**job.edits.model_dump(), "delivery": action[5:]})
        text = card(job)
    elif action == "effects":
        text = effects_text(job.edits)
        markup = effects_keyboard(job.id, job.edits)
    elif action.startswith("speed_"):
        job.edits = Edits.model_validate({**job.edits.model_dump(), "speed": float(action[6:])})
        text, markup = effects_text(job.edits), effects_keyboard(job.id, job.edits)
    elif action in {"normalize", "silence"}:
        setattr(job.edits, action, not getattr(job.edits, action))
        text = effects_text(job.edits)
        markup = effects_keyboard(job.id, job.edits)
    elif action == "summary":
        text = summary_text(job, FIELDS)
        markup = keyboard(
            job.id, [[("✅ Получить MP3", "save")], [("⬅️ Изменить настройки", "menu")]]
        )
    elif action == "save":
        filters(job.edits, job.info["duration"])
        await store.enqueue(job, "render")
        await callback.message.edit_text(
            "⏳ <b>Ваш MP3 в очереди</b>\n\nНачнём, как только освободится обработчик.\n/cancel — отменить"
        )
        return
    await store.save(job)
    with suppress(Exception):
        await callback.message.edit_text(text[:4000], reply_markup=markup)


@router.message(Editor.text, F.text)
async def text_input(message: Message, state: FSMContext, store):
    context = await state.get_data()
    job = await editable(store, message.from_user.id, context.get("job_id"))
    field, value = context["field"], message.text.strip()
    if len(value) > 500:
        raise UserError("Максимальная длина — 500 символов.")
    if field == "order":
        try:
            order = [int(v) - 1 for v in value.split()]
        except ValueError:
            raise UserError("Введите номера через пробел.") from None
        if sorted(order) != list(range(len(job.items))):
            raise UserError("Укажите каждый номер ровно один раз.")
        job.order = order
    elif field == "trim":
        parts = value.split()
        if len(parts) != 2:
            raise UserError("Введите два времени через пробел.")
        job.edits.trim = (timestamp(parts[0]), timestamp(parts[1]))
        filters(job.edits, job.info["duration"])
    elif field == "volume":
        try:
            job.edits = Edits.model_validate(
                {**job.edits.model_dump(), "volume": float(value.replace(",", "."))}
            )
        except ValueError:
            raise UserError("Введите число от −30 до +12.") from None
    elif field == "filename":
        job.edits.filename = safe_name(value)
    else:
        if field in {"tracknumber", "discnumber"} and value != "-":
            pieces = value.split("/")
            if len(pieces) > 2 or any(not p.isdigit() or int(p) > 65535 for p in pieces):
                raise UserError("Введите номер, например 1 или 1/10.")
        job.edits.tags[field] = "" if value == "-" else value
    await store.save(job)
    await state.clear()
    await message.answer(card(job), reply_markup=menu(job.id))


@router.message(Editor.cover)
async def cover_input(message: Message, state: FSMContext, store, settings):
    context = await state.get_data()
    job = await editable(store, message.from_user.id, context.get("job_id"))
    media = message.photo[-1] if message.photo else message.document
    if not media:
        raise UserError("Пришлите изображение.")
    if media.file_size and media.file_size > 10_000_000:
        raise UserError("Обложка должна быть меньше 10 МБ.")
    remote = await message.bot.get_file(media.file_id)
    source = local_input(settings.telegram_dir, remote.file_path, 10_000_000)
    await asyncio.to_thread(
        normalize_cover, source, job_dir(settings.jobs_dir, job.id) / "cover.jpg"
    )
    job.edits.cover = "replace"
    await store.save(job)
    await state.clear()
    await message.answer(
        "Обложка подготовлена и будет встроена при сохранении.", reply_markup=menu(job.id)
    )


@router.message(F.audio | F.voice | F.document)
async def receive(message: Message, state: FSMContext, store, settings, pool):
    if await store.redis.get("maintenance") == b"1":
        raise UserError("Бот на обслуживании. Попробуйте позже.")
    current = await store.current(message.from_user.id)
    if current and (current.mode == "single" or current.status != "editing"):
        raise UserError("Дождитесь анализа или завершите текущую задачу: /cancel.")
    media = message.audio or message.voice or message.document
    configured_limit = await store.redis.get("input_limit")
    input_limit = (
        min(settings.max_input_bytes, int(configured_limit))
        if configured_limit
        else settings.max_input_bytes
    )
    if media.file_size and media.file_size > input_limit:
        raise UserError("Файл превышает установленный лимит.")
    if current:
        if len(current.items) >= 10:
            raise UserError("В одной группе допускается до 10 файлов.")
        directory = job_dir(settings.jobs_dir, current.id)
        remote = await message.bot.get_file(media.file_id)
        source = local_input(settings.telegram_dir, remote.file_path, input_limit)
        used = sum(p.stat().st_size for p in directory.iterdir() if p.is_file())
        if used + source.stat().st_size * 2 > settings.job_quota_bytes:
            raise UserError("Группа превышает дисковую квоту.")
        space_check(directory, source.stat().st_size * 3, settings.disk_reserve_bytes)
        name = f"source_{len(current.items)}"
        await asyncio.to_thread(shutil.copyfile, source, directory / name)
        current.items.append({"source": name})
        current.order = []
        await state.clear()
        await store.enqueue(current, "analyze")
        await message.answer("Файл добавлен. Ожидание анализа…")
        return
    identifier = uuid.uuid4().hex
    defaults = mp3_edits(await preferences(pool, message.from_user.id))
    notice = await message.answer("📥 <b>Файл получен</b>\n\nПодготавливаю трек к анализу…")
    if not await store.redis.set(f"user:{message.from_user.id}", identifier, nx=True, ex=86400):
        raise UserError("У вас уже есть активная задача.")
    directory = job_dir(settings.jobs_dir, identifier)
    job = Job(
        id=identifier,
        user_id=message.from_user.id,
        chat_id=message.chat.id,
        status_message_id=notice.message_id,
        touched=time.time(),
        edits=defaults,
    )
    mode = await store.redis.getdel(f"mode:{message.from_user.id}")
    if mode:
        job.mode = mode.decode()
        job.items = [{"source": "source"}]
    await store.save(job)
    await store.redis.set(f"upload:{identifier}", "1", ex=600)
    try:
        directory.mkdir(mode=0o700, parents=True)
        remote = await message.bot.get_file(media.file_id)
        source = local_input(settings.telegram_dir, remote.file_path, input_limit)
        space_check(directory, source.stat().st_size * 3, settings.disk_reserve_bytes)
        await asyncio.to_thread(shutil.copyfile, source, directory / "source")
        job.edits.filename = safe_name(getattr(media, "file_name", None) or "audio")
        # Strip only the known incoming suffix; all paths remain generated internally.
        if "." in job.edits.filename:
            job.edits.filename = job.edits.filename.rsplit(".", 1)[0]
        await state.clear()
        await store.enqueue(job, "analyze")
        await notice.edit_text("Ожидание в очереди. /cancel — отменить")
    except Exception:
        await asyncio.to_thread(remove_job, settings.jobs_dir, identifier)
        await store.forget(job)
        raise
    finally:
        await store.redis.delete(f"upload:{identifier}")


@router.message()
async def fallback(message: Message):
    await message.answer("Отправьте аудиофайл или используйте /help.")


async def main():
    settings = Settings()
    settings.jobs_dir.mkdir(parents=True, exist_ok=True)
    redis = Redis.from_url(settings.redis_url)
    pool = await connect(settings.database_url.get_secret_value())
    bot = make_bot(settings)
    dispatcher = Dispatcher(
        storage=RedisStorage(redis, state_ttl=900, data_ttl=900),
        events_isolation=RedisEventIsolation(redis, lock_kwargs={"timeout": 600}),
        store=Store(redis),
        settings=settings,
        pool=pool,
    )
    router.message.outer_middleware(Guard())
    router.callback_query.outer_middleware(Guard())
    dispatcher.include_router(router)
    try:
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="🎧 Открыть аудиостудию"),
                BotCommand(command="settings", description="🎚 Качество и отправка MP3"),
                BotCommand(command="merge", description="🔗 Объединить аудио в один MP3"),
                BotCommand(command="batch", description="📚 Обработать несколько файлов"),
                BotCommand(command="cancel", description="✕ Отменить текущую задачу"),
                BotCommand(command="help", description="Как пользоваться студией"),
                BotCommand(command="privacy", description="Приватность и хранение файлов"),
                BotCommand(command="delete", description="Удалить рабочие данные и настройки"),
            ]
        )
        await bot.set_my_short_description(
            "🎧 AUDIX · Аудиостудия. Конвертация в MP3, теги, обложки и обработка звука."
        )
        await bot.set_my_description(
            "🎧 Ваша аудиостудия в Telegram\n\n"
            "Отправьте аудио или голосовое — получите MP3. "
            "Меняйте название, исполнителя, обложку, громкость и скорость. "
            "Обрезайте треки и объединяйте несколько записей.\n\n"
            "Начните с /start · Качество и отправка: /settings"
        )
        await dispatcher.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        await bot.session.close()
        await pool.close()
        await redis.aclose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(name)s %(message)s")
    asyncio.run(main())
