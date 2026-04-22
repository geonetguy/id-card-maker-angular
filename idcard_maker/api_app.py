"""
FastAPI wrapper around existing ID Card Maker business logic.

STEP D2 – Backend API Extraction
- Do not change existing rendering/generation/email logic.
- Wrap existing functionality in HTTP endpoints for the Angular UI.

Currently implemented:
- GET  /health
- POST /preview   -> returns PNG as base64
- POST /generate  -> saves PNG to generated_cards, returns filename/path
"""

from __future__ import annotations

import csv
import base64
import datetime as _dt
import io
import json
import os
import re
import webbrowser
import smtplib
import socket
import sys
import uuid
from pathlib import Path
from typing import Callable
from typing import Optional
from typing import Literal

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from PIL import Image

from .api_preview import PreviewRequest, generate_preview_response, _normalize_date, _pil_image_from_base64
from .services.generation import (
    project_output_dir,
    safe_filename,
    next_available,
    generate_single_card,
    generate_batch_cards,
    attachment_path_for_id,
)
from .services.mailer import SMTPConfig, Mailer, build_message


app = FastAPI(title="ID Card Maker API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Packaged Angular UI (served from inside the app bundle)
# ---------------------------------------------------------------------------

_WEB_DIR = Path(__file__).resolve().parent / "resources" / "web"


def _safe_web_path(request_path: str) -> Path | None:
    if not _WEB_DIR.exists():
        return None
    p = (request_path or "").lstrip("/")
    try:
        candidate = (_WEB_DIR / p).resolve()
        if candidate == _WEB_DIR or _WEB_DIR in candidate.parents:
            return candidate
    except Exception:
        return None
    return None


@app.get("/ui/", include_in_schema=False)
@app.get("/ui/{path:path}", include_in_schema=False)
def ui(path: str = ""):
    """
    Serve the packaged Angular UI.

    This is used by the desktop shell (Toga WebView) in deployment builds so we
    don't rely on a separate Python HTTP server, and we avoid loopback/proxy
    issues.
    """
    base = _safe_web_path(path)
    if base is None:
        raise HTTPException(status_code=404, detail="UI not bundled")

    if base.exists() and base.is_dir():
        base = base / "index.html"

    # Serve file if present; otherwise fall back to SPA entrypoint.
    if base.exists() and base.is_file():
        return FileResponse(base)

    index = _WEB_DIR / "index.html"
    if index.exists():
        return FileResponse(index, media_type="text/html")
    raise HTTPException(status_code=404, detail="UI entrypoint not found")

_DEFAULT_FONT_PATH: Optional[Path] = Path(__file__).resolve().parent / "resources" / "courbd.ttf"
if not _DEFAULT_FONT_PATH.exists():
    _DEFAULT_FONT_PATH = None

_choose_output_dir_callback: Optional[Callable[[Optional[str]], Optional[str]]] = None
_choose_asset_callback: Optional[Callable[[str, Optional[str]], Optional[str]]] = None
_open_help_callback: Optional[Callable[[], None]] = None


def set_choose_output_dir_callback(cb: Callable[[Optional[str]], Optional[str]]) -> None:
    """
    Injected by the Toga shell at runtime.

    The callback is expected to display a native folder picker and return a
    filesystem path (string), or None if the user cancels.
    """
    global _choose_output_dir_callback
    _choose_output_dir_callback = cb


def set_choose_asset_callback(cb: Callable[[str, Optional[str]], Optional[str]]) -> None:
    """
    Injected by the Toga shell at runtime.

    Callback args: (kind, initial_dir). kind is "template" or "signature".
    Returns a filesystem path (string), or None if cancelled.
    """
    global _choose_asset_callback
    _choose_asset_callback = cb


def set_open_help_callback(cb: Callable[[], None]) -> None:
    """
    Injected by the Toga shell at runtime.

    Callback is expected to open the local help file in the system browser.
    """
    global _open_help_callback
    _open_help_callback = cb


def _default_output_dir() -> Path:
    override = (os.environ.get("IDCARD_OUTPUT_DIR") or "").strip()
    if override:
        return Path(override).expanduser()
    return project_output_dir()


class MemberIn(BaseModel):
    name: str = ""
    id_number: str = Field(..., min_length=1)
    date: str = ""
    email: str = ""


class MemberLooseIn(BaseModel):
    """
    Relaxed member model for batch-oriented endpoints where missing fields
    are handled as skips (mirrors existing UI/service behavior).
    """

    name: str = ""
    id_number: str = ""
    date: str = ""
    email: str = ""


class PreviewIn(BaseModel):
    member: MemberLooseIn
    template_base64: str = Field(..., min_length=1)
    signature_base64: Optional[str] = None


class PreviewOut(BaseModel):
    png_base64: str
    warning: Optional[str] = None


class GenerateIn(BaseModel):
    member: MemberIn
    template_base64: str = Field(..., min_length=1)
    signature_base64: Optional[str] = None
    output_dir: Optional[str] = None


class GenerateOut(BaseModel):
    filename: str
    path: str
    output_dir: str


class GenerateBatchIn(BaseModel):
    members: list[MemberLooseIn] = Field(default_factory=list)
    template_base64: str = Field(..., min_length=1)
    signature_base64: Optional[str] = None
    output_dir: Optional[str] = None


class GenerateBatchResult(BaseModel):
    index: int
    result: str  # ok | skip | error


class GenerateBatchOut(BaseModel):
    total: int
    ok: int
    skipped: int
    errors: int
    output_dir: str
    results: list[GenerateBatchResult]


class UploadCsvOut(BaseModel):
    members: list[MemberLooseIn]


class ConfigOut(BaseModel):
    output_dir: Optional[str] = None


class OutputSettings(BaseModel):
    output_dir: Optional[str] = None


class ChooseOutputDirIn(BaseModel):
    initial_dir: Optional[str] = None


class ChooseOutputDirOut(BaseModel):
    output_dir: Optional[str] = None


class AssetSettings(BaseModel):
    template_path: Optional[str] = None
    signature_path: Optional[str] = None
    # Optional: store defaults directly as base64 so the web UI can persist
    # selections made via <input type="file"> (which doesn't expose a full path).
    template_base64: Optional[str] = None
    signature_base64: Optional[str] = None


class ChooseAssetIn(BaseModel):
    kind: Literal["template", "signature"]
    initial_dir: Optional[str] = None


class ChooseAssetOut(BaseModel):
    kind: Literal["template", "signature"]
    path: Optional[str] = None
    base64: Optional[str] = None


class AssetDefaultsOut(BaseModel):
    template_path: Optional[str] = None
    signature_path: Optional[str] = None
    template_base64: Optional[str] = None
    signature_base64: Optional[str] = None


_DEFAULT_SUBJECT_TPL = "Your ID card, {name}"
_DEFAULT_BODY_TPL = "Hi {name},\n\nAttached is your ID card.\nID: {id_number}\nDate: {date}\n\nBest,\n{sender}"


EmailProvider = Literal["microsoft", "gmail"]
EmailSender = Literal["President", "Vice President", "Membership Officer"]


class EmailAccountSettings(BaseModel):
    email: str = ""
    password: str = ""
    from_name: str = ""
    subject_tpl: str = _DEFAULT_SUBJECT_TPL
    body_tpl: str = _DEFAULT_BODY_TPL


class EmailProviderDefaults(BaseModel):
    imap_server: str
    imap_port: int
    imap_encryption: str  # "SSL/TLS"
    smtp_server: str
    smtp_port: int
    smtp_encryption: str  # "STARTTLS" or "SSL/TLS"


class UnionManagementSettings(BaseModel):
    enabled: bool = False
    email: str = ""


class EmailSettingsV2(BaseModel):
    active: EmailProvider = "microsoft"
    active_sender: EmailSender = "Membership Officer"
    microsoft: EmailAccountSettings = Field(default_factory=EmailAccountSettings)
    gmail: EmailAccountSettings = Field(default_factory=EmailAccountSettings)
    microsoft_senders: dict[EmailSender, EmailAccountSettings] = Field(default_factory=dict)
    gmail_senders: dict[EmailSender, EmailAccountSettings] = Field(default_factory=dict)
    union_management: UnionManagementSettings = Field(default_factory=UnionManagementSettings)
    defaults: dict[EmailProvider, EmailProviderDefaults] = Field(default_factory=dict)


def _settings_path() -> Path:
    """
    Location for persisted user settings.

    In the packaged app, this is injected by the Toga shell via
    `IDCARD_SETTINGS_PATH`. In development, it falls back to a file in the
    user config directory.
    """
    override = (os.environ.get("IDCARD_SETTINGS_PATH") or "").strip()
    if override:
        return Path(override).expanduser()
    return get_default_settings_path()


def get_default_settings_path() -> Path:
    """
    Stable default settings location across run modes.

    This avoids having different settings files depending on whether you run
    via Briefcase/Toga or run the API directly via uvicorn.
    """
    if sys.platform.startswith("win"):
        base = (os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or "").strip()
        if base:
            return Path(base) / "ID Card Maker" / "settings.json"
        return Path.home() / "AppData" / "Local" / "ID Card Maker" / "settings.json"

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ID Card Maker" / "settings.json"

    xdg = (os.environ.get("XDG_CONFIG_HOME") or "").strip()
    base = Path(xdg) if xdg else (Path.home() / ".config")
    return base / "idcard_maker" / "settings.json"


def _read_settings_json() -> dict:
    path = _settings_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_settings_json(data: dict) -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp_path.replace(path)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def _email_defaults() -> dict[EmailProvider, EmailProviderDefaults]:
    return {
        "microsoft": EmailProviderDefaults(
            imap_server="outlook.office365.com",
            imap_port=993,
            imap_encryption="SSL/TLS",
            smtp_server="smtp.office365.com",
            smtp_port=587,
            smtp_encryption="STARTTLS",
        ),
        "gmail": EmailProviderDefaults(
            imap_server="imap.gmail.com",
            imap_port=993,
            imap_encryption="SSL/TLS",
            smtp_server="smtp.gmail.com",
            smtp_port=587,
            smtp_encryption="STARTTLS",
        ),
    }


def _email_settings_from_json(data: dict) -> EmailSettingsV2:
    """
    Load settings; supports migrating the older single-account schema.
    """
    defaults = _email_defaults()

    raw = data.get("email") if isinstance(data, dict) else None
    if isinstance(raw, dict) and ("microsoft" in raw or "gmail" in raw or "active" in raw):
        try:
            settings = EmailSettingsV2(**raw)
            settings.defaults = defaults
            # Passwords are never persisted; always clear any loaded values.
            settings.microsoft.password = ""
            settings.gmail.password = ""
            for p in (settings.microsoft_senders or {}).values():
                try:
                    p.password = ""
                except Exception:
                    pass
            for p in (settings.gmail_senders or {}).values():
                try:
                    p.password = ""
                except Exception:
                    pass
            # If sender profiles exist but active_sender isn't set, pick a safe default.
            if not getattr(settings, "active_sender", None):
                settings.active_sender = "Membership Officer"
            return settings
        except Exception:
            pass

    # Migration from prior schema (host/port/use_tls/use_ssl/username/password/from_*/subject_tpl/body_tpl)
    ms = EmailAccountSettings()
    if isinstance(raw, dict):
        from_email = (raw.get("from_email") or raw.get("username") or "").strip()
        ms.email = str(from_email)
        ms.from_name = str(raw.get("from_name") or "")
        ms.subject_tpl = str(raw.get("subject_tpl") or _DEFAULT_SUBJECT_TPL)
        ms.body_tpl = str(raw.get("body_tpl") or _DEFAULT_BODY_TPL)
        ms.password = ""

    settings = EmailSettingsV2(active="microsoft", microsoft=ms, gmail=EmailAccountSettings(), defaults=defaults)
    return settings


def _email_settings_to_json(settings: EmailSettingsV2) -> dict:
    # Do not persist provider defaults; they're built-in.
    return {
        "active": settings.active,
        "active_sender": settings.active_sender,
        "microsoft": settings.microsoft.model_dump(),
        "gmail": settings.gmail.model_dump(),
        "microsoft_senders": {k: v.model_dump() for k, v in (settings.microsoft_senders or {}).items()},
        "gmail_senders": {k: v.model_dump() for k, v in (settings.gmail_senders or {}).items()},
        "union_management": settings.union_management.model_dump(),
    }


class DownloadIn(BaseModel):
    output_dir: Optional[str] = None
    filename: str = Field(..., min_length=1)


class OpenPathIn(BaseModel):
    path: str = Field(..., min_length=1)


class OpenPathOut(BaseModel):
    ok: bool


class ClearCardsIn(BaseModel):
    output_dir: Optional[str] = None


class ClearCardsOut(BaseModel):
    output_dir: str
    deleted: int


class CardsCountOut(BaseModel):
    output_dir: str
    count: int


class OpenHelpOut(BaseModel):
    ok: bool


class SMTPConfigIn(BaseModel):
    host: str = ""
    port: int = 587
    use_tls: bool = True
    use_ssl: bool = False
    username: str = ""
    password: str = ""
    from_name: str = ""
    from_email: str = ""


class EmailIn(BaseModel):
    members: list[MemberLooseIn] = Field(default_factory=list)
    smtp: Optional[SMTPConfigIn] = None
    subject_tpl: str = _DEFAULT_SUBJECT_TPL
    body_tpl: str = _DEFAULT_BODY_TPL
    # Note: kept for backwards compatibility with the UI payload.
    # Email sending no longer creates missing cards automatically.
    template_base64: Optional[str] = None
    signature_base64: Optional[str] = None
    output_dir: Optional[str] = None


class EmailResult(BaseModel):
    index: int
    result: str  # sent | skipped | error
    message: Optional[str] = None


class EmailOut(BaseModel):
    total: int
    sent: int
    skipped: int
    errors: int
    results: list[EmailResult]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/config", response_model=ConfigOut)
def config() -> ConfigOut:
    override = (os.environ.get("IDCARD_OUTPUT_DIR") or "").strip()
    if override:
        return ConfigOut(output_dir=override)

    data = _read_settings_json()
    if isinstance(data, dict):
        out = (data.get("output", {}) or {}) if isinstance(data.get("output", {}), dict) else {}
        val = (out.get("output_dir") or "").strip()
        if val:
            return ConfigOut(output_dir=val)

    return ConfigOut(output_dir=None)


@app.get("/settings/output", response_model=OutputSettings)
def get_output_settings() -> OutputSettings:
    data = _read_settings_json()
    raw = data.get("output", {}) if isinstance(data, dict) else {}
    try:
        return OutputSettings(**(raw or {}))
    except Exception:
        return OutputSettings()


@app.put("/settings/output", response_model=OutputSettings)
def put_output_settings(body: OutputSettings) -> OutputSettings:
    data = _read_settings_json()
    if not isinstance(data, dict):
        data = {}
    data["output"] = body.model_dump()
    _write_settings_json(data)
    return body


@app.get("/settings/email", response_model=EmailSettingsV2)
def get_email_settings() -> EmailSettingsV2:
    data = _read_settings_json()
    return _email_settings_from_json(data if isinstance(data, dict) else {})


@app.put("/settings/email", response_model=EmailSettingsV2)
def put_email_settings(body: EmailSettingsV2) -> EmailSettingsV2:
    data = _read_settings_json()
    if not isinstance(data, dict):
        data = {}

    # Never persist passwords.
    body.microsoft.password = ""
    body.gmail.password = ""
    for p in (body.microsoft_senders or {}).values():
        try:
            p.password = ""
        except Exception:
            pass
    for p in (body.gmail_senders or {}).values():
        try:
            p.password = ""
        except Exception:
            pass

    data["email"] = _email_settings_to_json(body)
    _write_settings_json(data)

    # Always return with baked-in defaults.
    body.defaults = _email_defaults()
    return body


@app.get("/settings/assets", response_model=AssetSettings)
def get_asset_settings() -> AssetSettings:
    data = _read_settings_json()
    raw = data.get("assets", {}) if isinstance(data, dict) else {}
    try:
        return AssetSettings(**(raw or {}))
    except Exception:
        return AssetSettings()


@app.put("/settings/assets", response_model=AssetSettings)
def put_asset_settings(body: AssetSettings) -> AssetSettings:
    data = _read_settings_json()
    if not isinstance(data, dict):
        data = {}
    data["assets"] = body.model_dump()
    _write_settings_json(data)
    return body


@app.post("/choose-asset", response_model=ChooseAssetOut)
def choose_asset(body: ChooseAssetIn) -> ChooseAssetOut:
    if _choose_asset_callback is None:
        raise HTTPException(status_code=501, detail="file_picker_not_available")

    path = _choose_asset_callback(body.kind, (body.initial_dir or "").strip() or None)
    if not path:
        return ChooseAssetOut(kind=body.kind, path=None, base64=None)

    p = Path(path).expanduser()
    if not p.exists():
        raise HTTPException(status_code=404, detail="not_found")

    try:
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        return ChooseAssetOut(kind=body.kind, path=str(p), base64=b64)
    except Exception:
        raise HTTPException(status_code=500, detail="internal_error")


@app.get("/assets/defaults", response_model=AssetDefaultsOut)
def asset_defaults() -> AssetDefaultsOut:
    settings = get_asset_settings()
    out = AssetDefaultsOut(
        template_path=settings.template_path,
        signature_path=settings.signature_path,
    )

    def try_load(path_str: Optional[str]) -> Optional[str]:
        if not path_str:
            return None
        p = Path(path_str).expanduser()
        if not p.exists():
            return None
        try:
            return base64.b64encode(p.read_bytes()).decode("ascii")
        except Exception:
            return None

    out.template_base64 = (settings.template_base64 or "").strip() or try_load(settings.template_path)
    out.signature_base64 = (settings.signature_base64 or "").strip() or try_load(settings.signature_path)
    return out


@app.post("/choose-output-dir", response_model=ChooseOutputDirOut)
def choose_output_dir(body: ChooseOutputDirIn) -> ChooseOutputDirOut:
    if _choose_output_dir_callback is None:
        raise HTTPException(status_code=501, detail="folder_picker_not_available")

    try:
        chosen = _choose_output_dir_callback((body.initial_dir or "").strip() or None)
        return ChooseOutputDirOut(output_dir=chosen)
    except Exception:
        raise HTTPException(status_code=500, detail="internal_error")


@app.post("/preview", response_model=PreviewOut)
def preview(body: PreviewIn) -> PreviewOut:
    try:
        req = PreviewRequest(
            name=(body.member.name or "").strip(),
            id_number=(body.member.id_number or "").strip(),
            date=(body.member.date or "").strip(),
            email=(body.member.email or "").strip(),
            template_base64=(body.template_base64 or "").strip(),
            signature_base64=(body.signature_base64 or None),
        )
        resp = generate_preview_response(req)
        return PreviewOut(**resp)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail="internal_error") from e


def _require_all_member_fields(m: MemberIn | MemberLooseIn, *, index: Optional[int] = None) -> dict[str, str]:
    """
    Enforce that all member fields are present.

    Returns a normalized dict with a normalized date (YYYY-MM-DD).
    Raises 400 if anything is missing/invalid.
    """
    prefix = f"member[{index}]." if index is not None else "member."

    name = (getattr(m, "name", "") or "").strip()
    idnum = (getattr(m, "id_number", "") or "").strip()
    date_raw = (getattr(m, "date", "") or "").strip()
    email = (getattr(m, "email", "") or "").strip()

    if not name:
        raise HTTPException(status_code=400, detail=f"{prefix}name is required")
    if not idnum:
        raise HTTPException(status_code=400, detail=f"{prefix}id_number is required")
    if not date_raw:
        raise HTTPException(status_code=400, detail=f"{prefix}date is required")
    if not email:
        raise HTTPException(status_code=400, detail=f"{prefix}email is required")

    # ID Number: simplest rule requested - exactly 7 digits.
    if not re.fullmatch(r"\d{7}", idnum):
        raise HTTPException(status_code=400, detail=f"{prefix}id_number is invalid (expected 7 digits)")

    # Date must be strict ISO (YYYY-MM-DD) and a real date.
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_raw):
        raise HTTPException(status_code=400, detail=f"{prefix}date is invalid (expected YYYY-MM-DD)")
    try:
        date_norm = _dt.date.fromisoformat(date_raw).isoformat()
    except Exception:
        raise HTTPException(status_code=400, detail=f"{prefix}date is invalid (expected YYYY-MM-DD)")

    # Email: basic sanity check (not a full RFC parser, but prevents obvious mistakes).
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(status_code=400, detail=f"{prefix}email is invalid")

    return {"name": name, "id_number": idnum, "date": date_norm, "email": email}


def _normalize_optional_cc_email(value: str) -> Optional[str]:
    v = (value or "").strip()
    if not v:
        return None
    # Keep validation intentionally light; must be good enough for SMTP RCPT.
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v):
        return None
    return v


@app.post("/generate", response_model=GenerateOut)
def generate(body: GenerateIn) -> GenerateOut:
    """
    Generate and save a single card PNG.
    Mirrors existing batch generation semantics:
    - requires id_number
    - date is normalized (unparseable -> blank)
    - filename derived from safe_filename(id_number)
    - if file exists, uses next_available() to avoid overwriting
    """
    try:
        member = _require_all_member_fields(body.member)
        idnum = member["id_number"]

        template = _pil_image_from_base64(body.template_base64).convert("RGBA")
        signature: Optional[Image.Image] = None
        if body.signature_base64:
            signature = _pil_image_from_base64(body.signature_base64).convert("RGBA")

        canvas = generate_single_card(
            name=member["name"],
            id_number=idnum,
            date=member["date"],
            template=template,
            signature=signature,
            font_path=_DEFAULT_FONT_PATH,
        )

        out_dir = Path(body.output_dir).expanduser() if body.output_dir else _default_output_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{safe_filename(idnum)}.png"
        out_path: Path = next_available(out_dir / filename)

        canvas.convert("RGB").save(out_path, format="PNG")
        return GenerateOut(filename=out_path.name, path=str(out_path), output_dir=str(out_dir))
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail="internal_error") from e


@app.post("/download")
def download(body: DownloadIn):
    """
    Download a generated PNG.

    Safety: file access is restricted to the provided output_dir (or default output dir).
    """
    out_dir = Path(body.output_dir).expanduser() if body.output_dir else _default_output_dir()
    try:
        out_dir = out_dir.resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_output_dir")

    filename = safe_filename(Path(body.filename).stem) + Path(body.filename).suffix
    if not filename.lower().endswith(".png"):
        filename = filename + ".png"

    path = (out_dir / filename)
    try:
        path = path.resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_path")

    if out_dir not in path.parents and path != out_dir:
        raise HTTPException(status_code=400, detail="path_outside_output_dir")

    if not path.exists():
        raise HTTPException(status_code=404, detail="not_found")

    return FileResponse(path, media_type="image/png", filename=path.name)


@app.post("/open-path", response_model=OpenPathOut)
def open_path(body: OpenPathIn) -> OpenPathOut:
    """
    Best-effort open a file or folder in the OS file manager.
    """
    try:
        p = Path(body.path).expanduser()
        if not p.exists():
            raise HTTPException(status_code=404, detail="not_found")

        # Windows supports os.startfile; other platforms best-effort.
        if hasattr(os, "startfile"):
            os.startfile(str(p))  # type: ignore[attr-defined]
            return OpenPathOut(ok=True)

        import subprocess
        import sys

        if sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
        return OpenPathOut(ok=True)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="internal_error")


@app.post("/clear-cards", response_model=ClearCardsOut)
def clear_cards(body: ClearCardsIn) -> ClearCardsOut:
    """
    Delete generated card images in the output directory.

    Safety: deletes only *.png files (recursively) under output_dir (or default output dir).
    """
    out_dir = Path(body.output_dir).expanduser() if body.output_dir else _default_output_dir()
    try:
        out_dir = out_dir.resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_output_dir")

    if out_dir.exists() and not out_dir.is_dir():
        raise HTTPException(status_code=400, detail="output_dir_is_not_a_directory")

    if not out_dir.exists():
        return ClearCardsOut(output_dir=str(out_dir), deleted=0)

    try:
        deleted = 0
        for p in out_dir.rglob("*.png"):
            try:
                if p.is_file() or p.is_symlink():
                    p.unlink(missing_ok=True)
                    deleted += 1
            except Exception:
                # Best-effort: keep clearing other files.
                pass

        # Best-effort: remove empty directories left behind.
        for d in sorted((p for p in out_dir.rglob("*") if p.is_dir()), key=lambda x: len(str(x)), reverse=True):
            try:
                d.rmdir()
            except Exception:
                pass

        return ClearCardsOut(output_dir=str(out_dir), deleted=deleted)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="internal_error") from e


@app.get("/cards/count", response_model=CardsCountOut)
def cards_count(output_dir: Optional[str] = None) -> CardsCountOut:
    out_dir = Path(output_dir).expanduser() if output_dir else _default_output_dir()
    try:
        out_dir = out_dir.resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_output_dir")

    if not out_dir.exists() or not out_dir.is_dir():
        return CardsCountOut(output_dir=str(out_dir), count=0)

    try:
        count = sum(1 for _ in out_dir.rglob("*.png"))
        return CardsCountOut(output_dir=str(out_dir), count=count)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="internal_error") from e


@app.post("/open-help", response_model=OpenHelpOut)
def open_help() -> OpenHelpOut:
    """
    Open the local help file in the system browser.
    Used by the Angular UI (e.g., F1).
    """
    try:
        if _open_help_callback is not None:
            _open_help_callback()
            return OpenHelpOut(ok=True)

        # Fallback for API-only usage (uvicorn without Toga app).
        help_path = Path(__file__).resolve().parent / "resources" / "help.html"
        ok = help_path.exists()
        if ok:
            try:
                webbrowser.open(help_path.as_uri())
            except Exception:
                pass
        return OpenHelpOut(ok=ok)
    except Exception as e:
        raise HTTPException(status_code=500, detail="internal_error") from e


@app.post("/generate-batch", response_model=GenerateBatchOut)
async def generate_batch(body: GenerateBatchIn) -> GenerateBatchOut:
    """
    Batch-generate cards from a list of members.
    Wraps services.generation.generate_batch_cards() unchanged.
    """
    if not body.members:
        raise HTTPException(status_code=400, detail="members is required")

    try:
        template = _pil_image_from_base64(body.template_base64).convert("RGBA")
        signature: Optional[Image.Image] = None
        if body.signature_base64:
            signature = _pil_image_from_base64(body.signature_base64).convert("RGBA")

        out_dir = Path(body.output_dir).expanduser() if body.output_dir else _default_output_dir()
        out_dir.mkdir(parents=True, exist_ok=True)

        rows: list[dict[str, str]] = []
        for idx, m in enumerate(body.members, start=1):
            member = _require_all_member_fields(m, index=idx)
            rows.append(member)

        ok = skipped = errors = 0
        results: list[GenerateBatchResult] = []
        async for idx, result in generate_batch_cards(rows, template, signature, _DEFAULT_FONT_PATH, out_dir):
            if result == "ok":
                ok += 1
            elif result == "skip":
                skipped += 1
            else:
                errors += 1
            results.append(GenerateBatchResult(index=idx, result=result))

        return GenerateBatchOut(
            total=len(rows),
            ok=ok,
            skipped=skipped,
            errors=errors,
            output_dir=str(out_dir),
            results=results,
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail="internal_error") from e


@app.post("/upload-csv", response_model=UploadCsvOut)
async def upload_csv(file: UploadFile = File(...)) -> UploadCsvOut:
    """
    Parse a CSV file into normalized members.
    Behavior parity with the existing Toga controller's CSV loader:
    - Requires headers mapping to: name, id_number, date, email (case/space insensitive)
    - Date is normalized; unparseable -> blank
    """
    try:
        raw = await file.read()
        if not raw:
            raise HTTPException(status_code=400, detail="empty_file")

        # utf-8-sig handles Excel CSVs with BOM
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise HTTPException(status_code=400, detail="csv_missing_header")

        def norm_header(h: str) -> str:
            return (h or "").strip().lower().replace(" ", "_")

        header_map = {orig: norm_header(orig) for orig in reader.fieldnames}
        rev: dict[str, str] = {}
        for orig, norm in header_map.items():
            # first wins if duplicates
            if norm and norm not in rev:
                rev[norm] = orig

        required = ["name", "id_number", "date", "email"]
        missing = [col for col in required if col not in rev]
        if missing:
            raise HTTPException(status_code=400, detail="csv_missing_required_columns: " + ", ".join(missing))

        members: list[MemberLooseIn] = []
        for rec in reader:
            def get(col: str) -> str:
                return (rec.get(rev[col], "") or "").strip()

            members.append(
                MemberLooseIn(
                    name=get("name"),
                    id_number=get("id_number"),
                    date=_normalize_date(get("date")),
                    email=get("email"),
                )
            )

        return UploadCsvOut(members=members)
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="invalid_encoding_expected_utf8")


@app.post("/email", response_model=EmailOut)
async def email(body: EmailIn) -> EmailOut:
    """
    Email cards for provided members.
    Wraps services.mailer (SMTPConfig/Mailer/build_message) unchanged.
    """
    if not body.members:
        raise HTTPException(status_code=400, detail="members is required")

    settings_for_cc = _email_settings_from_json(_read_settings_json())
    union_cc: Optional[str] = None
    if settings_for_cc.union_management.enabled:
        union_cc = _normalize_optional_cc_email(settings_for_cc.union_management.email)
        if union_cc is None:
            raise HTTPException(status_code=400, detail="union_management_email_is_invalid")

    # Use provided SMTP config if present; otherwise, use the active saved account.
    if body.smtp is not None:
        cfg = SMTPConfig(
            host=body.smtp.host,
            port=body.smtp.port,
            use_tls=body.smtp.use_tls,
            use_ssl=body.smtp.use_ssl,
            username=body.smtp.username,
            password=body.smtp.password,
            from_name=body.smtp.from_name,
            from_email=body.smtp.from_email,
        )
        subject_tpl = body.subject_tpl
        body_tpl = body.body_tpl
    else:
        provider = settings_for_cc.active
        acct = settings_for_cc.microsoft if provider == "microsoft" else settings_for_cc.gmail
        d = settings_for_cc.defaults.get(provider) or _email_defaults()[provider]

        email_addr = (acct.email or "").strip()
        password = (acct.password or "").strip()
        if not email_addr or not password:
            raise HTTPException(status_code=400, detail="active_email_account_requires_email_and_password")

        cfg = SMTPConfig(
            host=d.smtp_server,
            port=d.smtp_port,
            use_tls=(d.smtp_encryption.upper().startswith("STARTTLS")),
            use_ssl=(d.smtp_encryption.upper().startswith("SSL")),
            username=email_addr,
            password=password,
            from_name=acct.from_name,
            from_email=email_addr,
        )
        subject_tpl = acct.subject_tpl or _DEFAULT_SUBJECT_TPL
        body_tpl = acct.body_tpl or _DEFAULT_BODY_TPL

    if not (cfg.host or "").strip() or not (cfg.from_email or "").strip():
        raise HTTPException(status_code=400, detail="smtp.host and smtp.from_email are required")

    # Validate members up-front (require all fields) so we don't partially send.
    members_valid: list[MemberLooseIn] = []
    for idx, m in enumerate(body.members, start=1):
        mv = _require_all_member_fields(m, index=idx)
        members_valid.append(
            MemberLooseIn(
                name=mv["name"],
                id_number=mv["id_number"],
                date=mv["date"],
                email=mv["email"],
            )
        )

    out_dir = Path(body.output_dir).expanduser() if body.output_dir else _default_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    def render_tpl(tpl: str, m: MemberIn) -> str:
        safe = {
            "name": (m.name or "").strip(),
            "id_number": (m.id_number or "").strip(),
            "date": (m.date or "").strip(),
            "email": (m.email or "").strip(),
            "sender": cfg.from_name or cfg.from_email,
        }
        try:
            return tpl.format(**safe)
        except Exception:
            return tpl

    sent = skipped = errors = 0
    results: list[EmailResult] = []

    try:
        with Mailer(cfg) as mailer:
            for i, m in enumerate(members_valid, start=1):
                try:
                    idnum = (m.id_number or "").strip()
                    to_email = (m.email or "").strip()

                    attach = attachment_path_for_id(idnum, out_dir=out_dir)
                    if not attach.exists():
                        skipped += 1
                        results.append(
                            EmailResult(index=i, result="skipped", message="missing card file; create cards first")
                        )
                        continue

                    msg = build_message(
                        smtp=cfg,
                        to_email=to_email,
                        subject=render_tpl(subject_tpl, m),
                        body_text=render_tpl(body_tpl, m),
                        attachments=[attach],
                    )
                    if union_cc and union_cc.strip().lower() != to_email.strip().lower():
                        msg["Cc"] = union_cc
                    mailer.send(msg)
                    sent += 1
                    results.append(EmailResult(index=i, result="sent"))
                except Exception as e:
                    errors += 1
                    results.append(EmailResult(index=i, result="error", message=str(e)))
    except HTTPException:
        raise
    except (smtplib.SMTPAuthenticationError,) as e:
        raise HTTPException(status_code=400, detail=f"smtp_auth_failed: {e}") from e
    except (
        smtplib.SMTPConnectError,
        smtplib.SMTPServerDisconnected,
        smtplib.SMTPRecipientsRefused,
        smtplib.SMTPSenderRefused,
        smtplib.SMTPDataError,
        smtplib.SMTPHeloError,
        smtplib.SMTPNotSupportedError,
        smtplib.SMTPException,
        TimeoutError,
        socket.gaierror,
        ConnectionError,
        OSError,
    ) as e:
        # Surface the underlying SMTP/network error so the UI can show actionable feedback.
        raise HTTPException(status_code=400, detail=f"email_failed: {type(e).__name__}: {e}") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"internal_error: {type(e).__name__}") from e

    return EmailOut(total=len(body.members), sent=sent, skipped=skipped, errors=errors, results=results)
