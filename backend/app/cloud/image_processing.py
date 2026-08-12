from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError


MAX_IMAGE_PIXELS = 40_000_000
DISPLAY_MAX_EDGE = 2560
THUMBNAIL_MAX_EDGE = 640
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


@dataclass(frozen=True, slots=True)
class NormalizedImage:
    display_content: bytes
    thumbnail_content: bytes
    width: int
    height: int
    content_type: str = "image/webp"


def _webp_bytes(image: Image.Image, quality: int) -> bytes:
    output = BytesIO()
    image.save(output, format="WEBP", quality=quality, method=6, exif=b"")
    return output.getvalue()


def normalize_health_image(content: bytes) -> NormalizedImage:
    if not content:
        raise ValueError("图片内容为空")
    try:
        with Image.open(BytesIO(content)) as candidate:
            candidate.verify()
        with Image.open(BytesIO(content)) as opened:
            if opened.width * opened.height > MAX_IMAGE_PIXELS:
                raise ValueError("图片分辨率过大")
            if getattr(opened, "is_animated", False):
                opened.seek(0)
            display = ImageOps.exif_transpose(opened).convert("RGB")
            display.thumbnail((DISPLAY_MAX_EDGE, DISPLAY_MAX_EDGE), Image.Resampling.LANCZOS)
            thumbnail = display.copy()
            thumbnail.thumbnail((THUMBNAIL_MAX_EDGE, THUMBNAIL_MAX_EDGE), Image.Resampling.LANCZOS)
            return NormalizedImage(
                display_content=_webp_bytes(display, 88),
                thumbnail_content=_webp_bytes(thumbnail, 80),
                width=display.width,
                height=display.height,
            )
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError("无法识别这张图片，请重新拍照或选择 JPEG、PNG、WebP 图片") from exc
