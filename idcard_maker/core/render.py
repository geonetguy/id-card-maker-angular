# idcard_maker/core/render.py
import io
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont
import barcode
from barcode.writer import ImageWriter

from ..constants import FONT_SIZE_NAME, FONT_SIZE_OTHER


def _generate_barcode(id_number: str, font_path: Optional[Path]) -> Image.Image:
    CODE39 = barcode.get_barcode_class("code39")
    code39 = CODE39(id_number, writer=ImageWriter(), add_checksum=False)
    writer_opts = {
        "module_height": 10.0,
        "quiet_zone": 1.0,
    }
    if font_path and font_path.exists():
        writer_opts["font_path"] = str(font_path)
    return code39.render(writer_options=writer_opts)


def _text_width_px(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return int(bbox[2] - bbox[0])
    except Exception:
        try:
            return int(draw.textlength(text, font=font))  # type: ignore[arg-type]
        except Exception:
            return len(text) * 10


def _fit_font_to_width_px(
    *,
    draw: ImageDraw.ImageDraw,
    text: str,
    font_path: Optional[Path],
    start_size: int,
    min_size: int,
    max_width_px: int,
) -> ImageFont.ImageFont:
    if not (font_path and font_path.exists()):
        return ImageFont.load_default()

    for size in range(start_size, max(min_size, 1) - 1, -1):
        try:
            font = ImageFont.truetype(str(font_path), size)
        except OSError:
            return ImageFont.load_default()
        if _text_width_px(draw, text, font) <= max_width_px:
            return font

    try:
        return ImageFont.truetype(str(font_path), max(min_size, 1))
    except OSError:
        return ImageFont.load_default()


def _fit_font_to_width_px_result(
    *,
    draw: ImageDraw.ImageDraw,
    text: str,
    font_path: Optional[Path],
    start_size: int,
    min_size: int,
    max_width_px: int,
) -> tuple[ImageFont.ImageFont, bool]:
    """
    Like _fit_font_to_width_px, but also reports whether the returned font actually fits.
    """
    if not (font_path and font_path.exists()):
        font = ImageFont.load_default()
        return font, (_text_width_px(draw, text, font) <= max_width_px)

    for size in range(start_size, max(min_size, 1) - 1, -1):
        try:
            font = ImageFont.truetype(str(font_path), size)
        except OSError:
            font = ImageFont.load_default()
            return font, (_text_width_px(draw, text, font) <= max_width_px)
        if _text_width_px(draw, text, font) <= max_width_px:
            return font, True

    try:
        font = ImageFont.truetype(str(font_path), max(min_size, 1))
    except OSError:
        font = ImageFont.load_default()
    return font, (_text_width_px(draw, text, font) <= max_width_px)


def _best_two_line_split(
    *,
    draw: ImageDraw.ImageDraw,
    text: str,
    font_path: Optional[Path],
    start_size: int,
    min_size: int,
    max_width_px: int,
) -> tuple[str, str, ImageFont.ImageFont]:
    words = [w for w in (text or "").split() if w]
    if len(words) < 2:
        font, _ = _fit_font_to_width_px_result(
            draw=draw,
            text=text,
            font_path=font_path,
            start_size=start_size,
            min_size=min_size,
            max_width_px=max_width_px,
        )
        return text, "", font

    # Choose the largest font size that can accommodate *some* 2-line split.
    for size in range(start_size, max(min_size, 1) - 1, -1):
        try:
            font = ImageFont.truetype(str(font_path), size) if (font_path and font_path.exists()) else ImageFont.load_default()
        except OSError:
            font = ImageFont.load_default()

        best: tuple[int, str, str] | None = None
        for i in range(1, len(words)):
            a = " ".join(words[:i])
            b = " ".join(words[i:])
            w = max(_text_width_px(draw, a, font), _text_width_px(draw, b, font))
            if w <= max_width_px:
                if best is None or w < best[0]:
                    best = (w, a, b)

        if best is not None:
            _, a, b = best
            return a, b, font

    # Fallback: force split near the middle using min_size font; may still overflow, but avoids "hard" truncation.
    mid = max(1, len(words) // 2)
    a = " ".join(words[:mid])
    b = " ".join(words[mid:])
    font, _ = _fit_font_to_width_px_result(
        draw=draw,
        text=max(a, b, key=len),
        font_path=font_path,
        start_size=start_size,
        min_size=min_size,
        max_width_px=max_width_px,
    )
    return a, b, font


def _draw_centered_in_xrange(
    *,
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    y: int,
    x_left: int,
    x_right: int,
    fill: str = "black",
) -> None:
    x_left = int(x_left)
    x_right = int(x_right)
    width = max(1, x_right - x_left)
    text_w = _text_width_px(draw, text, font)
    x = x_left + max(0, int((width - text_w) / 2))
    draw.text((x, y), text, fill=fill, font=font)


def generate_id_card(
    *,
    name: str,
    id_number: str,
    date: str,
    template: Image.Image,
    signature: Optional[Image.Image],
    font_path: Optional[Path],
) -> Image.Image:
    """
    Renderer adapted from your other app:
    - Fixed coordinates
    - Character-based centering via str.center
    - Signature now fits into a defined bounding box (scaled proportionally & centered)
    - Barcode centered horizontally
    """
    img = template.copy().convert("RGBA")
    draw = ImageDraw.Draw(img)
    tpl_w, _ = img.size

    # Fonts
    try:
        # Use the provided TTF (courbd.ttf) when available to preserve monospace alignment.
        # Name is the most prominent field: slightly larger for readability.
        font_name = ImageFont.truetype(str(font_path), FONT_SIZE_NAME + 6) if font_path else ImageFont.load_default()
        font_other = ImageFont.truetype(str(font_path), FONT_SIZE_OTHER) if font_path else ImageFont.load_default()
    except OSError:
        font_name = font_other = ImageFont.load_default()

    # Field bounds (pixel-based). This template is currently fixed-layout.
    # Adjust these bounds if the artwork changes.
    NAME_X1, NAME_X2 = 70, tpl_w - 70
    ID_X1, ID_X2 = 0, 185
    # Date was visually landing slightly right; shift the date field a bit left.
    DATE_X1, DATE_X2 = 172, 337

    name_text = (name or "").strip()
    id_text = (id_number or "").strip()
    date_text = (date or "").strip()

    # Fixed text positions
    if name_text:
        cleaned = " ".join(name_text.split())
        max_name_w = (NAME_X2 - NAME_X1)
        name_font, fits = _fit_font_to_width_px_result(
            draw=draw,
            text=cleaned,
            font_path=font_path,
            start_size=FONT_SIZE_NAME + 6,
            min_size=12,
            max_width_px=max_name_w,
        )
        if fits:
            _draw_centered_in_xrange(draw=draw, text=cleaned, font=name_font, y=98, x_left=NAME_X1, x_right=NAME_X2)
        else:
            a, b, two_font = _best_two_line_split(
                draw=draw,
                text=cleaned,
                font_path=font_path,
                start_size=FONT_SIZE_NAME + 4,
                min_size=11,
                max_width_px=max_name_w,
            )
            _draw_centered_in_xrange(draw=draw, text=a, font=two_font, y=88, x_left=NAME_X1, x_right=NAME_X2)
            if b:
                _draw_centered_in_xrange(draw=draw, text=b, font=two_font, y=110, x_left=NAME_X1, x_right=NAME_X2)

    if id_text:
        id_font = _fit_font_to_width_px(
            draw=draw,
            text=id_text,
            font_path=font_path,
            start_size=FONT_SIZE_OTHER,
            min_size=12,
            max_width_px=(ID_X2 - ID_X1),
        )
        _draw_centered_in_xrange(draw=draw, text=id_text, font=id_font, y=220, x_left=ID_X1, x_right=ID_X2)

    if date_text:
        date_font = _fit_font_to_width_px(
            draw=draw,
            text=date_text,
            font_path=font_path,
            start_size=FONT_SIZE_OTHER,
            min_size=12,
            max_width_px=(DATE_X2 - DATE_X1),
        )
        _draw_centered_in_xrange(draw=draw, text=date_text, font=date_font, y=220, x_left=DATE_X1, x_right=DATE_X2)

    # Signature (optional) - scale to fit bounding box and center within it
    if signature is not None:
        # Bounding box definition (top-left + size) — adjust as needed for your template
        box_x, box_y = 360, 190
        box_w, box_h = 135, 50

        sig = signature.convert("RGBA")
        sig_w, sig_h = sig.size

        # Proportional scale factor to fit within both width and height limits
        scale = min(box_w / sig_w, box_h / sig_h)
        if scale < 1.0:
            new_w = max(1, int(sig_w * scale))
            new_h = max(1, int(sig_h * scale))
            sig = sig.resize((new_w, new_h), Image.LANCZOS)
            sig_w, sig_h = sig.size  # update after resize

        # Center the (possibly resized) signature within the bounding box
        offset_x = box_x + (box_w - sig_w) // 2
        offset_y = box_y + (box_h - sig_h) // 2

        img.alpha_composite(sig, (offset_x, offset_y))

    # Barcode (centered using template width)
    if id_number:
        code_img = _generate_barcode(id_number, font_path).convert("RGBA")
        code_img = code_img.resize((350, 50), Image.LANCZOS)
        barcode_x = (tpl_w - 350) // 2
        img.alpha_composite(code_img, (barcode_x, 266))

    return img
