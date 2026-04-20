# idcard_maker/core/csv_utils.py
from __future__ import annotations
from pathlib import Path
from typing import List, Dict
import csv

EXPECTED_COLUMNS = ["Name", "ID Number", "Date", "Email"]

def _normalize_header(h: str) -> str:
    return (h or "").strip().lower().replace(" ", "_")

def parse_csv(path: Path) -> List[Dict[str, str]]:
    """
    Parse a CSV with headers: name,id_number,date,email (case/space insensitive).
    Returns a list of dicts with normalized keys EXACTLY as EXPECTED_COLUMNS.
    Ignores extra columns; fills missing with empty strings.
    """
    rows: List[Dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return rows

        # Map incoming headers -> normalized
        incoming = [_normalize_header(h) for h in reader.fieldnames]
        # Build index mapping for the four columns
        idx = {col: (incoming.index(col) if col in incoming else None) for col in EXPECTED_COLUMNS}

        for raw in reader:
            out: Dict[str, str] = {}
            for col in EXPECTED_COLUMNS:
                if idx[col] is None:
                    out[col] = ""
                else:
                    # Access by original fieldname to preserve DictReader behavior
                    original_key = reader.fieldnames[idx[col]]
                    out[col] = (raw.get(original_key, "") or "").strip()
            rows.append(out)

    return rows
