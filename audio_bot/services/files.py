import re
import shutil
from pathlib import Path


class UserError(Exception):
    """Safe Russian error suitable for the user."""


def job_dir(root: Path, job_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise UserError("Некорректный идентификатор задачи.")
    path = root.resolve() / job_id
    if path.is_symlink() or path.resolve().parent != root.resolve():
        raise UserError("Недопустимый рабочий каталог.")
    return path


def safe_name(value: str) -> str:
    value = re.sub(r'[\x00-\x1f<>:"/\\|?*]', "_", value).strip(" .")[:100]
    if not value or value.upper().split(".")[0] in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(10)),
        *(f"LPT{i}" for i in range(10)),
    }:
        return "audio"
    return value


def space_check(root: Path, required: int, reserve: int):
    if shutil.disk_usage(root).free < required + reserve:
        raise UserError("Недостаточно свободного места. Попробуйте позже.")


def remove_job(root: Path, job_id: str):
    path = job_dir(root, job_id)
    if path.exists():
        shutil.rmtree(path)


def local_input(root: Path, value: str, limit: int) -> Path:
    path = Path(value).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise UserError("Файл недоступен локальному обработчику.")
    if path.stat().st_size > limit:
        raise UserError("Файл превышает установленный лимит.")
    return path
