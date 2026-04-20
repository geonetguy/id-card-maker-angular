from __future__ import annotations

import base64
import io
import os
import shutil
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from idcard_maker.api_app import app
from idcard_maker.services.generation import project_output_dir


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _png_b64(w: int = 507, h: int = 318) -> str:
    img = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_config_exists(client: TestClient) -> None:
    r = client.get("/config")
    assert r.status_code == 200
    assert "output_dir" in r.json()


def test_email_settings_roundtrip(client: TestClient) -> None:
    td = Path(__file__).resolve().parents[1] / ".tmp" / f"test-settings-{uuid.uuid4().hex}"
    td.mkdir(parents=True, exist_ok=True)
    try:
        settings_path = td / "settings.json"
        os.environ["IDCARD_SETTINGS_PATH"] = str(settings_path)

        r = client.get("/settings/email")
        assert r.status_code == 200

        payload = r.json()
        assert payload["defaults"]["microsoft"]["smtp_server"] == "smtp.office365.com"
        assert payload["defaults"]["microsoft"]["smtp_port"] == 587
        assert payload["defaults"]["gmail"]["smtp_server"] == "smtp.gmail.com"
        assert payload["defaults"]["gmail"]["smtp_port"] == 587

        payload["active"] = "microsoft"
        payload["microsoft"]["email"] = "sender@example.com"
        payload["microsoft"]["password"] = "secret"
        payload["microsoft"]["save_password"] = True

        r2 = client.put("/settings/email", json=payload)
        assert r2.status_code == 200

        r3 = client.get("/settings/email")
        assert r3.status_code == 200
        data = r3.json()
        assert data["active"] == "microsoft"
        assert data["microsoft"]["email"] == "sender@example.com"
        assert data["microsoft"]["password"] == "secret"
        assert data["defaults"]["microsoft"]["smtp_server"] == "smtp.office365.com"
    finally:
        try:
            shutil.rmtree(td, ignore_errors=True)
        except Exception:
            pass


def test_preview_returns_png_base64(client: TestClient) -> None:
    r = client.post(
        "/preview",
        json={
            "member": {"name": "Test", "id_number": "123", "date": "2026-04-19", "email": "x@example.com"},
            "template_base64": _png_b64(),
            "signature_base64": None,
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert "png_base64" in data
    assert isinstance(data["png_base64"], str)
    assert len(data["png_base64"]) > 1000


def test_upload_csv_parses_and_normalizes(client: TestClient) -> None:
    csv_bytes = (
        "Name,ID Number,Date,Email\n"
        "Alice,1001,04/19/2026,alice@example.com\n"
        "Bob,1002,not-a-date,bob@example.com\n"
    ).encode("utf-8")

    r = client.post(
        "/upload-csv",
        files={"file": ("members.csv", csv_bytes, "text/csv")},
    )
    assert r.status_code == 200
    members = r.json()["members"]
    assert members[0]["id_number"] == "1001"
    assert members[0]["date"] == "2026-04-19"
    assert members[1]["id_number"] == "1002"
    assert members[1]["date"] == ""


def test_generate_batch_writes_files_and_reports_results(client: TestClient) -> None:
    out_dir = project_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    before = {p.name for p in out_dir.glob("*.png")}
    try:
        r = client.post(
            "/generate-batch",
            json={
                "members": [
                    {"name": "Skip Me", "id_number": "", "date": "2026-04-19", "email": "s@example.com"},
                    {"name": "Make Me", "id_number": "BATCH-1", "date": "2026-04-19", "email": "m@example.com"},
                ],
                "template_base64": _png_b64(),
                "signature_base64": None,
            },
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload["total"] == 2
        assert payload["ok"] == 1
        assert payload["skipped"] == 1
        assert payload["errors"] == 0
        assert "output_dir" in payload
        assert isinstance(payload["output_dir"], str)
        assert payload["output_dir"]

        after = {p.name for p in out_dir.glob("*.png")}
        created = sorted(after - before)
        assert any(name.startswith("BATCH-1") and name.endswith(".png") for name in created)
    finally:
        # Cleanup only files created by this test run.
        after = {p.name for p in out_dir.glob("*.png")}
        for name in (after - before):
            try:
                (out_dir / name).unlink(missing_ok=True)
            except Exception:
                pass


def test_generate_single_writes_file_and_returns_output_dir(client: TestClient) -> None:
    out_dir = project_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    before = {p.name for p in out_dir.glob("*.png")}
    try:
        r = client.post(
            "/generate",
            json={
                "member": {"name": "Test", "id_number": "SINGLE-1", "date": "2026-04-19", "email": "x@example.com"},
                "template_base64": _png_b64(),
                "signature_base64": None,
                "output_dir": str(out_dir),
            },
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload["filename"].endswith(".png")
        assert payload["path"]
        assert payload["output_dir"] == str(out_dir)

        after = {p.name for p in out_dir.glob("*.png")}
        created = sorted(after - before)
        assert any(name.startswith("SINGLE-1") and name.endswith(".png") for name in created)
    finally:
        after = {p.name for p in out_dir.glob("*.png")}
        for name in (after - before):
            try:
                (out_dir / name).unlink(missing_ok=True)
            except Exception:
                pass


def test_email_requires_smtp_fields(client: TestClient) -> None:
    td = Path(__file__).resolve().parents[1] / ".tmp" / f"test-email-{uuid.uuid4().hex}"
    td.mkdir(parents=True, exist_ok=True)
    try:
        os.environ["IDCARD_SETTINGS_PATH"] = str(td / "settings.json")
        r = client.post(
            "/email",
            json={
                "members": [{"name": "Test", "id_number": "1", "date": "", "email": "x@example.com"}],
                "output_dir": str(project_output_dir()),
            },
        )
        assert r.status_code == 400
        assert "active_email_account_requires_email_and_password" in str(r.json().get("detail", ""))
    finally:
        try:
            shutil.rmtree(td, ignore_errors=True)
        except Exception:
            pass
