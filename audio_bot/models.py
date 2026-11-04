from typing import Literal

from pydantic import BaseModel, Field


class Edits(BaseModel):
    tags: dict[str, str] = Field(default_factory=dict)
    target: Literal["mp3", "m4a", "opus", "ogg", "wav", "flac", "aac", "aiff", "wma"] | None = None
    bitrate: Literal[0, 128, 192, 256, 320] = 0
    delivery: Literal["auto", "document", "audio", "voice"] = "auto"
    filename: str = "audio"
    cover: Literal["keep", "replace", "remove"] = "keep"
    trim: tuple[float, float] | None = None
    volume: float = Field(default=0, ge=-30, le=12)
    speed: float = Field(default=1, ge=0.5, le=2)
    normalize: bool = False
    silence: bool = False
    preserve_tags: bool = True
    incompatible_cover: Literal["drop", "error"] = "drop"
    confirm: bool = True


class Job(BaseModel):
    id: str
    user_id: int
    chat_id: int
    status_message_id: int
    status: str = "receiving"
    touched: float
    info: dict = Field(default_factory=dict)
    edits: Edits = Field(default_factory=Edits)
    error: str | None = None
    mode: Literal["single", "merge", "batch"] = "single"
    items: list[dict] = Field(default_factory=list)
    order: list[int] = Field(default_factory=list)
