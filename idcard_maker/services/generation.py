# idcard_maker/services/generation.py
from __future__ import annotations
from pathlib import Path
from typing import AsyncGenerator, Iterable, Optional
from PIL import Image

from ..core.render import generate_id_card


def project_output_dir() -> Path:
    """Always use project-root/generated_cards."""
    return Path(__file__).resolve().parents[1] / "generated_cards"


def safe_filename(stem: str) -> str:
    stem = (stem or "idcard").strip().replace(" ", "_")
    safe = "".join(c for c in stem if c.isalnum() or c in ("-", "_"))
    return safe or "idcard"


def next_available(path: Path) -> Path:
    if not path.exists():
        return path
    base = path.stem
    suffix = path.suffix
    i = 1
    while True:
        candidate = path.with_name(f"{base}-{i}{suffix}")
        if not candidate.exists():
            return candidate
        i += 1


def generate_single_card(
    *, name: str, id_number: str, date: str,
    template: Image.Image, signature: Optional[Image.Image], font_path: Optional[Path]
) -> Image.Image:
    return generate_id_card(
        name=name, id_number=id_number, date=date,
        template=template, signature=signature, font_path=font_path
    )


async def generate_batch_cards(
    rows: Iterable[dict[str, str]],
    template: Image.Image,
    signature: Optional[Image.Image],
    font_path: Optional[Path],
    out_dir: Path,
) -> AsyncGenerator[tuple[int, str], None]:
    """
    Yields (index, result) for each row; result in {"ok","skip","error"}.
    """
    import asyncio

    for idx, row in enumerate(rows, start=1):
        try:
            name = (row.get("name", "") or "").strip()
            idnum = (row.get("id_number", "") or "").strip()
            date = (row.get("date", "") or "").strip()
            # email = (row.get("email", "") or "").strip()  # reserved

            if not idnum:
                yield idx, "skip"
                await asyncio.sleep(0)
                continue

            canvas = generate_id_card(
                name=name, id_number=idnum, date=date,
                template=template, signature=signature, font_path=font_path,
            )
            filename = f"{safe_filename(idnum)}.png"
            out_path = next_available(out_dir / filename)
            canvas.convert("RGB").save(out_path, format="PNG")
            yield idx, "ok"
        except Exception:
            yield idx, "error"
        finally:
            # let UI repaint
            await asyncio.sleep(0)


# idcard_maker/services/generation.py  (append)
def attachment_path_for_id(id_number: str) -> Path:
    """Return the expected PNG path for a given id_number in project output dir."""
    # We only attach the exact "<id>.png" if it exists; we don't guess -1, -2 variants.
    return project_output_dir() / f"{safe_filename(id_number)}.png"
