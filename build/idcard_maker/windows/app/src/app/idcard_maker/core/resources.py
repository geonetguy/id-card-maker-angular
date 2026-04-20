# idcard_maker/core/resources.py
from pathlib import Path
from typing import Optional

import toga
from PIL import ImageFont


def resource_path(app: toga.App, name: str) -> Path:
    """
    Works in both dev and packaged modes:
    - Briefcase packages resources under app.paths.app / 'resources'
    - Dev uses local ./resources next to app.py
    """
    packaged = Path(app.paths.app) / "resources" / name
    if packaged.exists():
        return packaged
    return Path(__file__).resolve().parent.parent / "resources" / name


def load_font(font_path: Optional[Path], size: int) -> ImageFont.ImageFont:
    """
    Try a TTF at 'font_path'; fall back to default bitmap font if missing.
    """
    try:
        if font_path and font_path.exists():
            return ImageFont.truetype(str(font_path), size=size)
    except Exception:
        pass
    return ImageFont.load_default()
