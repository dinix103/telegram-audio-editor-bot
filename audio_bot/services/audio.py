from ..models import Edits
from .files import UserError


def timestamp(value: str) -> float:
    parts = value.strip().split(":")
    if not 1 <= len(parts) <= 3:
        raise UserError("Введите время в формате ММ:СС.")
    try:
        values = [float(x) for x in parts]
        if any(x < 0 for x in values) or any(x >= 60 for x in values[1:]):
            raise ValueError
        result = 0.0
        for x in values:
            result = result * 60 + x
        if not __import__("math").isfinite(result):
            raise ValueError
        return result
    except ValueError:
        raise UserError("Некорректное время.") from None


def filters(edits: Edits, duration: float) -> list[str]:
    result = []
    if edits.trim:
        start, end = edits.trim
        if not 0 <= start < end <= duration:
            raise UserError("Начало должно быть меньше конца и в пределах записи.")
        result += [f"atrim=start={start}:end={end}", "asetpts=PTS-STARTPTS"]
    if edits.speed != 1:
        result += [f"atempo={edits.speed}"]
    if edits.volume:
        result += [f"volume={edits.volume}dB", "alimiter=limit=0.95:level=false"]
    if edits.normalize:
        result += ["loudnorm=I=-16:TP=-1.5:LRA=11"]
    if edits.silence:
        result += [
            "silenceremove=start_periods=1:start_duration=0.1:start_threshold=-50dB",
            "areverse",
            "silenceremove=start_periods=1:start_duration=0.1:start_threshold=-50dB",
            "areverse",
        ]
    return result
