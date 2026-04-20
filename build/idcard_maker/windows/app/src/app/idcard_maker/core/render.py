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

    # Fonts
    try:
        font_name = ImageFont.truetype(str(font_path), FONT_SIZE_NAME) if font_path else ImageFont.load_default()
        font_other = ImageFont.truetype(str(font_path), FONT_SIZE_OTHER) if font_path else ImageFont.load_default()
    except OSError:
        font_name = font_other = ImageFont.load_default()

    # Character-based centering (faithful to original)
    name_text = f"{(name or '').center(39)}"
    id_text = f"{(id_number or '').center(14)}"
    date_text = f"{(date or '').center(11)}"

    # Fixed text positions
    draw.text((0, 98), name_text, fill="black", font=font_name)
    draw.text((0, 220), id_text, fill="black", font=font_other)
    draw.text((185, 220), date_text, fill="black", font=font_other)

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
        tpl_w, _ = img.size
        barcode_x = (tpl_w - 350) // 2
        img.alpha_composite(code_img, (barcode_x, 266))

    return img
