"""
Minimal backend API wrapper for the existing Python rendering pipeline.

STEP D2 (Backend API Extraction) - start with the preview endpoint.

Design goals:
- Do not modify existing rendering/business logic.
- Accept inputs over HTTP, call existing services, return PNG as base64.
- Keep dependencies to stdlib + existing project deps (Pillow, python-barcode).
"""

from __future__ import annotations

import base64
import datetime as _dt
import io
import json
import os
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional

from PIL import Image

from .services.generation import generate_single_card


def _strip_data_url_prefix(b64: str) -> str:
    """
    Accept either raw base64 or a data URL like:
      data:image/png;base64,AAAA...
    """
    s = (b64 or "").strip()
    if not s:
        return ""
    if s.lower().startswith("data:") and "," in s:
        return s.split(",", 1)[1].strip()
    return s


def _b64decode_bytes(b64: str) -> bytes:
    s = _strip_data_url_prefix(b64)
    if not s:
        raise ValueError("missing base64 payload")
    try:
        return base64.b64decode(s, validate=True)
    except Exception as e:
        raise ValueError(f"invalid base64: {e}") from e


def _normalize_date(s: str) -> str:
    """
    Behavior parity with Actions._normalize_date():
    - Accept common formats
    - Normalize to YYYY-MM-DD
    - Unparseable -> ""
    """
    s = (s or "").strip()
    if not s:
        return ""
    fmts = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y.%m.%d",
        "%m/%d/%Y",
        "%m-%d-%Y",
        "%m/%d/%y",
        "%m-%d-%y",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d/%m/%y",
        "%d-%m-%y",
    ]
    for fmt in fmts:
        try:
            return _dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def _pil_image_from_base64(b64: str) -> Image.Image:
    raw = _b64decode_bytes(b64)
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
        return img
    except Exception as e:
        raise ValueError(f"invalid image payload: {e}") from e


def _png_bytes_from_pil(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@dataclass(frozen=True)
class PreviewRequest:
    name: str
    id_number: str
    date: str
    email: str
    template_base64: str
    signature_base64: Optional[str] = None

    @staticmethod
    def from_json(obj: dict[str, Any]) -> "PreviewRequest":
        member = obj.get("member") or {}
        if not isinstance(member, dict):
            raise ValueError("member must be an object")

        template_b64 = obj.get("template_base64")
        if template_b64 is None:
            # allow an alternate key to reduce friction in early client experiments
            template_b64 = obj.get("template")

        signature_b64 = obj.get("signature_base64")
        if signature_b64 is None:
            signature_b64 = obj.get("signature")

        return PreviewRequest(
            name=(member.get("name", "") or "").strip(),
            id_number=(member.get("id_number", "") or "").strip(),
            date=(member.get("date", "") or "").strip(),
            email=(member.get("email", "") or "").strip(),
            template_base64=(template_b64 or "").strip(),
            signature_base64=(signature_b64 or None),
        )


def generate_preview_response(req: PreviewRequest) -> dict[str, Any]:
    """
    Core preview operation:
    - Decode template/signature
    - Normalize date (unparseable -> blank)
    - Call existing generate_single_card()
    - Return PNG base64 + optional warning
    """
    if not req.template_base64:
        raise ValueError("template_base64 is required")
    template = _pil_image_from_base64(req.template_base64).convert("RGBA")
    signature: Optional[Image.Image] = None
    if req.signature_base64:
        signature = _pil_image_from_base64(req.signature_base64).convert("RGBA")

    date_norm = _normalize_date(req.date)
    warning: Optional[str] = None
    if (req.date or "").strip() and not date_norm:
        warning = "unrecognized_date_format_left_blank"

    canvas = generate_single_card(
        name=req.name,
        id_number=req.id_number,
        date=(date_norm or ""),
        template=template,
        signature=signature,
        font_path=None,
    )

    png_bytes = _png_bytes_from_pil(canvas)
    return {
        "png_base64": base64.b64encode(png_bytes).decode("ascii"),
        "warning": warning,
    }


class _Handler(BaseHTTPRequestHandler):
    server_version = "IDCardMakerPreviewAPI/0.1"

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # Dev-friendly CORS (Angular local dev)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        try:
            if self.path.rstrip("/") != "/preview":
                self._send_json(404, {"error": "not_found"})
                return

            length = int(self.headers.get("Content-Length") or "0")
            if length <= 0:
                self._send_json(400, {"error": "empty_request"})
                return

            raw = self.rfile.read(length)
            try:
                obj = json.loads(raw.decode("utf-8"))
            except Exception:
                self._send_json(400, {"error": "invalid_json"})
                return
            if not isinstance(obj, dict):
                self._send_json(400, {"error": "json_must_be_object"})
                return

            req = PreviewRequest.from_json(obj)
            resp = generate_preview_response(req)
            self._send_json(200, resp)
        except ValueError as e:
            self._send_json(400, {"error": "bad_request", "message": str(e)})
        except Exception:
            self._send_json(500, {"error": "internal_error"})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # Keep stdout clean in dev; override if you want request logs.
        return


def main() -> None:
    host = os.environ.get("IDCARD_API_HOST", "127.0.0.1")
    port = int(os.environ.get("IDCARD_API_PORT", "8000"))
    httpd = ThreadingHTTPServer((host, port), _Handler)
    print(f"Preview API listening on http://{host}:{port}/preview")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
