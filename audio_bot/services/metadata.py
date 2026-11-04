import base64
from pathlib import Path

import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, COMM, ID3, TALB, TCOM, TCON, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK
from mutagen.mp4 import MP4, MP4Cover

from .files import UserError

ID3_FIELDS = dict(
    title=TIT2,
    artist=TPE1,
    album=TALB,
    albumartist=TPE2,
    date=TDRC,
    genre=TCON,
    tracknumber=TRCK,
    discnumber=TPOS,
    composer=TCOM,
    comment=COMM,
)
MP4_FIELDS = dict(
    title="\xa9nam",
    artist="\xa9ART",
    album="\xa9alb",
    albumartist="aART",
    date="\xa9day",
    genre="\xa9gen",
    tracknumber="trkn",
    discnumber="disk",
    composer="\xa9wrt",
    comment="\xa9cmt",
)


def load(path):
    try:
        return mutagen.File(path)
    except (mutagen.MutagenError, ValueError, OSError):
        raise UserError("Не удалось прочитать метаданные.") from None


def read_tags(path: Path) -> dict[str, str]:
    audio = load(path)
    if audio is None or audio.tags is None:
        return {}
    tags = audio.tags
    result = {}
    for field, cls in ID3_FIELDS.items():
        if isinstance(tags, ID3):
            frames = tags.getall(cls.__name__)
            if frames:
                result[field] = str(frames[0])[:1000]
        elif isinstance(audio, MP4):
            value = tags.get(MP4_FIELDS[field])
            if value:
                result[field] = (
                    "/".join(map(str, value[0]))
                    if field in {"tracknumber", "discnumber"}
                    else str(value[0])
                )[:1000]
        else:
            value = tags.get(field)
            if value:
                result[field] = str(value[0])[:1000]
    return result


def cover_bytes(path: Path) -> bytes | None:
    audio = load(path)
    if audio is None:
        return None
    if isinstance(audio, FLAC):
        return audio.pictures[0].data if audio.pictures else None
    tags = audio.tags
    if not tags:
        return None
    if isinstance(tags, ID3):
        pictures = tags.getall("APIC")
        return pictures[0].data if pictures else None
    if isinstance(audio, MP4):
        pictures = tags.get("covr", [])
        return bytes(pictures[0]) if pictures else None
    blocks = tags.get("metadata_block_picture", [])
    if blocks:
        try:
            return Picture(base64.b64decode(blocks[0])).data
        except Exception:
            return None
    return None


def write_metadata(
    path: Path, changes: dict[str, str], cover_action="keep", cover: Path | None = None
):
    if not changes and cover_action == "keep":
        return
    audio = load(path)
    if audio is None or path.suffix in {".aac", ".wma"}:
        raise UserError(
            "Этот формат не поддерживает редактор тегов. Выберите MP3, M4A, FLAC или OGG."
        )
    if audio.tags is None:
        audio.add_tags()
    tags = audio.tags
    for field, value in changes.items():
        if field not in ID3_FIELDS:
            raise UserError("Неизвестное поле метаданных.")
        if isinstance(tags, ID3):
            cls = ID3_FIELDS[field]
            tags.delall(cls.__name__)
            if value:
                tags.add(
                    cls(
                        encoding=3,
                        text=[value],
                        **({"lang": "eng", "desc": ""} if field == "comment" else {}),
                    )
                )
        elif isinstance(audio, MP4):
            key = MP4_FIELDS[field]
            tags.pop(key, None)
            if value:
                if field in {"tracknumber", "discnumber"}:
                    try:
                        pair = [int(x) for x in value.split("/")]
                        if not 1 <= len(pair) <= 2 or any(x < 0 or x > 65535 for x in pair):
                            raise ValueError
                        tags[key] = [(pair[0], pair[1] if len(pair) > 1 else 0)]
                    except ValueError:
                        raise UserError(
                            "Номер трека/диска должен быть числом или парой 1/10."
                        ) from None
                else:
                    tags[key] = [value]
        else:
            if field in tags:
                del tags[field]
            if value:
                tags[field] = [value]
    if cover_action != "keep":
        data = cover.read_bytes() if cover_action == "replace" and cover else None
        if isinstance(tags, ID3):
            tags.delall("APIC")
            if data:
                tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=data))
        elif isinstance(audio, MP4):
            tags.pop("covr", None)
            if data:
                tags["covr"] = [MP4Cover(data, imageformat=MP4Cover.FORMAT_JPEG)]
        else:
            picture = Picture()
            picture.type, picture.mime = 3, "image/jpeg"
            if data:
                picture.data = data
            if isinstance(audio, FLAC):
                audio.clear_pictures()
                if data:
                    audio.add_picture(picture)
            else:
                for key in ("metadata_block_picture", "coverart", "coverartmime"):
                    if key in tags:
                        del tags[key]
                if data:
                    tags["metadata_block_picture"] = [base64.b64encode(picture.write()).decode()]
    try:
        audio.save()
    except (mutagen.MutagenError, OSError, ValueError):
        raise UserError("Не удалось сохранить метаданные в выбранном формате.") from None
