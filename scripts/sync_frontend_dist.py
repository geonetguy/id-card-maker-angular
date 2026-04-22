from __future__ import annotations

import shutil
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    src_dir = repo_root / "frontend" / "dist" / "frontend" / "browser"
    dst_dir = repo_root / "idcard_maker" / "resources" / "web"

    if not src_dir.exists():
        raise SystemExit(f"Angular build output not found: {src_dir}")

    dst_dir.mkdir(parents=True, exist_ok=True)

    # Clear existing contents (keep folder).
    for child in dst_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    # Copy dist/browser -> resources/web
    for child in src_dir.iterdir():
        target = dst_dir / child.name
        if child.is_dir():
            shutil.copytree(child, target)
        else:
            shutil.copy2(child, target)

    index = dst_dir / "index.html"
    if not index.exists():
        raise SystemExit(f"Expected index.html missing after copy: {index}")

    print(f"Synced Angular UI: {src_dir} -> {dst_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

