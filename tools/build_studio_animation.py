"""Build the small looping welcome graphic. Requires Pillow and FFmpeg."""

import math
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
WIDTH, HEIGHT, FPS = 640, 320, 24


def font(size, bold=False):
    candidates = [
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    return ImageFont.truetype(str(next(p for p in candidates if p.exists())), size)


def frame(index):
    image = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        draw.line((0, y, WIDTH, y), fill=(12 + y // 40, 18 + y // 45, 37 + y // 18))
    draw.rounded_rectangle((24, 20, 616, 298), radius=26, outline="#2b3c60", width=1)
    draw.text((48, 38), "A U D I X", font=font(32, True), fill="#f2f5ff")
    draw.text((48, 84), "АУДИОСТУДИЯ В TELEGRAM", font=font(13), fill="#96aaca")
    draw.rounded_rectangle((510, 42, 584, 78), radius=18, fill="#28d8ae")
    draw.text((527, 49), "MP3", font=font(16, True), fill="#092a2a")
    t = 2 * math.pi * index / (FPS * 4)
    for i in range(36):
        height = int(
            18 + 59 * (0.5 + 0.5 * math.sin(i * 0.65 + t * 3)) + 13 * math.sin(i * 0.37 - t * 2)
        )
        x = 49 + i * 15
        color = (int(77 + 85 * i / 35), int(210 - 83 * i / 35), 245)
        draw.rounded_rectangle(
            (x, 180 - height // 2, x + 8, 180 + height // 2), radius=4, fill=color
        )
    draw.text((48, 252), "ТЕГИ  /  ОБЛОЖКА  /  ЗВУК", font=font(14), fill="#b6c6df")
    return image


if __name__ == "__main__":
    output = ROOT / "assets" / "studio.mp4"
    output.parent.mkdir(exist_ok=True)
    ffmpeg = shutil.which("ffmpeg") or str(ROOT / "tools/bin/ffmpeg.exe")
    process = subprocess.Popen(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{WIDTH}x{HEIGHT}",
            "-r",
            str(FPS),
            "-i",
            "-",
            "-an",
            "-c:v",
            "libx264",
            "-crf",
            "25",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output),
        ],
        stdin=subprocess.PIPE,
    )
    for index in range(FPS * 4):
        process.stdin.write(frame(index).tobytes())
    process.stdin.close()
    if process.wait():
        raise RuntimeError("FFmpeg failed")
    frame(18).save(ROOT / "tmp" / "studio-preview.png")
    print(f"Generated {output.name}: {output.stat().st_size} bytes")
