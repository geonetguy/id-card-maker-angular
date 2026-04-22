"""
Entrypoint for `python -m idcard_maker` (used by Briefcase dev/run/package).

On Windows, user/system Python environment variables and user site-packages can
leak into a packaged app process and cause extension module ABI conflicts
(e.g., importing a stdlib extension from a different Python install).

We proactively isolate `sys.path` to the Briefcase bundle to avoid crashes like:
    ImportError: Module use of python313.dll conflicts with this version of Python.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _isolate_runtime() -> None:
    # Prevent user site-packages from being added (even if `site` is imported).
    os.environ.setdefault("PYTHONNOUSERSITE", "1")

    # These can force Python to use a different stdlib/site-packages location.
    os.environ.pop("PYTHONHOME", None)
    os.environ.pop("PYTHONPATH", None)

    # Keep only absolute paths that live inside the Briefcase bundle directory.
    try:
        this_file = Path(__file__).resolve()
        # .../<bundle>/app/idcard_maker/__main__.py -> bundle = parents[2]
        bundle_dir = this_file.parents[2]
    except Exception:
        return

    new_path: list[str] = []
    for p in list(sys.path):
        if not p:
            new_path.append(p)
            continue
        try:
            if os.path.isabs(p):
                rp = Path(p).resolve()
                if rp == bundle_dir or bundle_dir in rp.parents:
                    new_path.append(p)
            else:
                # Relative entries like "python313.zip" are expected in embedded builds.
                new_path.append(p)
        except Exception:
            # If anything goes wrong resolving a path, keep it (conservative).
            new_path.append(p)

    sys.path[:] = new_path


_isolate_runtime()

from .app import main  # noqa: E402  (import after isolation)

if __name__ == "__main__":
    main().main_loop()
