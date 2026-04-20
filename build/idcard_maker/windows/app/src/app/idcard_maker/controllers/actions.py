# idcard_maker/controllers/actions.py
from __future__ import annotations
from types import SimpleNamespace
from pathlib import Path
from typing import Optional, List
import asyncio
import shutil
import datetime
import io
import csv
import smtplib  # <-- add this so we can report SMTP errors nicely
from ..core.csv_utils import EXPECTED_COLUMNS
import toga
from toga.style import Pack
from toga.style.pack import ROW, COLUMN
from ..constants import OFFICER_EMAILS
from PIL import Image
from toga import OpenFileDialog

from ..ui.mail_settings import build_mail_settings_window
from ..services.mailer import SMTPConfig, Mailer, build_message
from ..core.resources import resource_path
from ..services.generation import (
    attachment_path_for_id,
    project_output_dir,
    generate_single_card,
    generate_batch_cards,
)


class Actions:
    def __init__(self, app: toga.App):
        self.app = app
        self._preview_task: Optional[asyncio.Task] = None
        self._help_win: Optional[toga.Window] = None

        # Assets / data state
        self.template_path: Optional[Path] = None
        self.signature_path: Optional[Path] = None
        self.csv_rows: List[dict[str, str]] = []

        # 2-click confirmation for "Clear cards"
        self._confirm_clear = False
        self._confirm_task: Optional[asyncio.Task] = None

        # --- single source of truth for edit vs add mode
        self._edit_index: Optional[int] = None  # None => Add mode; int => Update that index

        # Mail settings state (defaults; users set real values via dialog)
        self.smtp_cfg = SMTPConfig(
            host="smtp.office365.com",
            port=587,
            use_tls=True,
            use_ssl=False,
            username="",
            password="",
            from_name="",
            from_email="",
        )
        self.subject_tpl = "Your ID card, {name}"
        self.body_tpl = (
            "Hi {name},\n\nAttached is your ID card.\n"
            "ID: {id_number}\nDate: {date}\n\nBest,\n{sender}"
        )

    # --- Edit lock: require template + signature before editing ---
    def _editing_ready(self) -> bool:
        """True only when both template and signature exist on disk."""
        return bool(
            self.template_path and self.template_path.exists()
            and self.signature_path and self.signature_path.exists()
        )

    def apply_editing_lock(self) -> None:
        """
        Enable/disable editing UI based on whether BOTH a template and a signature
        have been chosen. This now also applies to 'Load CSV'.
        """
        ui = self.app.ui
        ready = bool(
            self.template_path and self.template_path.exists()
            and self.signature_path and self.signature_path.exists()
        )

        # Inputs that allow manual editing
        inputs = [ui.name_input, ui.id_input, ui.date_input]
        if hasattr(ui, "email_input") and ui.email_input is not None:
            inputs.append(ui.email_input)

        # Buttons that modify data or render cards (CSV load now included)
        buttons = [
            getattr(ui, "add_member_btn", None),
            getattr(ui, "new_member_btn", None),
            getattr(ui, "generate_all_btn", None),
            getattr(ui, "load_csv_btn", None),     # ⬅️ NEW: gate 'Load CSV'
        ]

        # Toggle widgets
        for w in inputs:
            if w is not None:
                w.enabled = ready
        for b in buttons:
            if b is not None:
                b.enabled = ready

        # Table interaction
        if getattr(ui, "csv_table", None) is not None:
            ui.csv_table.enabled = ready

        # Gentle status hint
        try:
            if not ready:
                ui.status_label.text = "Pick a Template and a Signature to begin editing."
        except Exception:
            pass

    # ---------------- Utilities ----------------
    async def open_help(self, widget=None):
            """
            Open the bundled Help in the system web browser.
            Falls back to a status message if the file isn't present or can't be opened.
            """
            from ..core.resources import resource_path
            import webbrowser

            help_path = resource_path(self.app, "help.html")

            if help_path.exists():
                try:
                    webbrowser.open(help_path.as_uri())
                    try:
                        self.app.ui.status_label.text = "Opened Help in your default browser."
                    except Exception:
                        pass
                except Exception as e:
                    try:
                        self.app.ui.status_label.text = f"Couldn't open Help in browser: {e}"
                    except Exception:
                        pass
            else:
                try:
                    self.app.ui.status_label.text = f"Help file not found: {help_path}"
                except Exception:
                    pass

    def _row_to_dict(self, row) -> dict[str, str]:
        """Coerce a toga.Table row (list-like or object) into our dict."""
        try:
            seq = list(row)
        except TypeError:
            seq = [
                getattr(row, "name", "") or getattr(row, "Name", ""),
                getattr(row, "id_number", "") or getattr(row, "ID Number", ""),
                getattr(row, "date", "") or getattr(row, "Date", ""),
                getattr(row, "email", "") or getattr(row, "Email", ""),
            ]
        seq = (seq + ["", "", "", ""])[:4]
        return {
            "name": (seq[0] or "").strip(),
            "id_number": (seq[1] or "").strip(),
            "date": (seq[2] or "").strip(),
            "email": (seq[3] or "").strip(),
        }

    def _rows_from_table(self) -> List[dict]:
        rows = []
        tbl = self.app.ui.csv_table
        if tbl and getattr(tbl, "data", None):
            for row in tbl.data:
                rows.append(self._row_to_dict(row))
        return rows

    def _selected_row(self) -> Optional[dict]:
        tbl = self.app.ui.csv_table
        sel = getattr(tbl, "selection", None)
        if not sel:
            return None
        return self._row_to_dict(sel)

    def _selected_row_index(self) -> Optional[int]:
        """Find index of current selection in the table's data."""
        tbl = self.app.ui.csv_table
        sel = getattr(tbl, "selection", None)
        if not sel:
            return None
        # Try identity, then value equality
        try:
            for i, row in enumerate(tbl.data):
                if row is sel:
                    return i
        except Exception:
            pass
        try:
            sel_list = list(sel)
            for i, row in enumerate(tbl.data):
                try:
                    if list(row) == sel_list:
                        return i
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def _rows_as_lists(self) -> List[List[str]]:
        """Snapshot current table rows as plain lists (reliable for WinForms repaint)."""
        tbl = self.app.ui.csv_table
        snap: List[List[str]] = []
        if tbl and getattr(tbl, "data", None):
            for row in tbl.data:
                try:
                    snap.append(list(row))
                except Exception:
                    d = self._row_to_dict(row)
                    snap.append([d["name"], d["id_number"], d["date"], d["email"]])
        return snap

    # --- ADD this helper somewhere inside the Actions class (e.g., under _rows_as_lists) ---
    def _table_reassign(self, rows: list[list[str]], reselection_index: Optional[int] = None) -> None:
        """
        Force the Table to repaint immediately by clearing, reassigning data,
        and (optionally) restoring selection — while temporarily disabling on_select.
        """
        tbl = self.app.ui.csv_table
        old_handler = getattr(tbl, "on_select", None)
        try:
            # 1) detach handler to avoid recursive events during rebuild
            tbl.on_select = None

            # 2) hard reset the model (WinForms needs a *different* list to repaint)
            tbl.data = []            # empty first
            try:
                tbl.refresh()
            except Exception:
                pass

            # 3) assign a brand-new list object with brand-new row objects
            #    (breaks reference equality that can prevent redraws)
            fresh = [list(r) for r in rows]
            tbl.data = fresh

            # 4) optionally restore selection
            if reselection_index is not None and 0 <= reselection_index < len(fresh):
                try:
                    tbl.selection = tbl.data[reselection_index]
                except Exception:
                    pass

            # 5) nudge layout/paint
            try:
                tbl.refresh()
                self.app.ui.root.refresh()
            except Exception:
                pass
        finally:
            tbl.on_select = old_handler


    def _normalize_date(self, s: str) -> str:
        """Accept common formats; normalize to YYYY-MM-DD. Unparseable -> ''."""
        s = (s or "").strip()
        if not s:
            return ""
        fmts = [
            "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d",
            "%m/%d/%Y", "%m-%d-%Y",
            "%m/%d/%y",  "%m-%d-%y",
            "%d/%m/%Y", "%d-%m-%Y",
            "%d/%m/%y",  "%d-%m-%y",
        ]
        for fmt in fmts:
            try:
                return datetime.datetime.strptime(s, fmt).date().isoformat()
            except ValueError:
                pass
        return ""

    def _set_save_button_mode(self, mode: str) -> None:
        """Switch the button text between Add / Update and set edit index accordingly."""
        btn = self.app.ui.add_member_btn
        if mode == "update":
            btn.text = "Update member"
        else:
            btn.text = "Add member"

    # ---------------- New / Add / Update + live preview ----------------
    async def new_member(self, widget):
        """Clear selection & inputs; enter Add mode. This guarantees the next click adds a new row."""
        # Clear any table selection (may be ignored by some backends), but we *also* reset edit index.
        try:
            self.app.ui.csv_table.selection = None
        except Exception:
            pass

        self._edit_index = None  # <-- single source of truth (forces Add mode)

        # Clear inputs
        self.app.ui.name_input.value = ""
        self.app.ui.id_input.value = ""
        if hasattr(self.app.ui, "email_input"):
            self.app.ui.email_input.value = ""
        self.app.ui.date_input.value = ""

        self._set_save_button_mode("add")
        await self.update_preview()
        self.app.ui.status_label.text = "Ready to add a new member."

# --- REPLACE your save_member with this version ---
    async def save_member(self, widget):
        """
        If self._edit_index is None => ADD new row.
        Else => UPDATE the row at self._edit_index and force an immediate repaint.
        """
        name  = (self.app.ui.name_input.value or "").strip()
        idnum = (self.app.ui.id_input.value   or "").strip()
        date_norm = self._normalize_date(self.app.ui.date_input.value or "")
        email = (getattr(self.app.ui, "email_input", None).value or "").strip() if hasattr(self.app.ui, "email_input") else ""

        if not idnum:
            self.app.ui.status_label.text = "Enter an ID Number before saving."
            return

        row_data = [name, idnum, date_norm, email]

        if self._edit_index is None:
            # ADD — append and reassign data so the row appears immediately
            rows = self._rows_as_lists()
            rows.append(row_data)
            self._table_reassign(rows, reselection_index=None)  # stay in Add mode

            # clear inputs for rapid next entry
            self.app.ui.name_input.value = ""
            self.app.ui.id_input.value = ""
            if hasattr(self.app.ui, "email_input"):
                self.app.ui.email_input.value = ""
            self.app.ui.date_input.value = ""

            self._set_save_button_mode("add")
            self.app.ui.status_label.text = f"Added member: {idnum}"
            await asyncio.sleep(0)
            await self.update_preview()
            return

        # UPDATE — replace row at index and force repaint right now
        idx = self._edit_index
        rows = self._rows_as_lists()
        if 0 <= idx < len(rows):
            rows[idx] = row_data
            self._table_reassign(rows, reselection_index=idx)  # reselect edited row

            # extra nudge to some WinForms builds: briefly clear & restore selection
            try:
                tbl = self.app.ui.csv_table
                sel_backup = tbl.selection
                tbl.selection = None
                tbl.selection = sel_backup
            except Exception:
                pass

            self._set_save_button_mode("update")
            self.app.ui.status_label.text = f"Updated member: {idnum}"
        else:
            # if index went stale, fall back to add
            rows.append(row_data)
            self._table_reassign(rows, reselection_index=None)
            self._edit_index = None
            self._set_save_button_mode("add")
            self.app.ui.status_label.text = f"Added member: {idnum}"

        await asyncio.sleep(0)
        await self.update_preview()

# --- REPLACE your on_table_select with this version (unchanged logic + tiny polish) ---
    async def on_table_select(self, widget, *args, **kwargs):
        """
        Populate inputs and enter Update mode when a row is clicked.

        Toga backends (especially WinForms) may call on_select with extra
        positional args (row, row_index, etc). Accept *args/**kwargs to avoid
        TypeError like: "takes from 2 to 3 positional arguments but 7 were given".
        We ignore those extras and always read the current selection from the table.
        """
        # Prefer the widget passed in, but fall back to the app's table if needed
        tbl = widget if hasattr(widget, "selection") else self.app.ui.csv_table
        sel = getattr(tbl, "selection", None)

        # If multiple_select were ever enabled and selection is a sequence, pick first
        if isinstance(sel, (list, tuple)) and sel:
            sel = sel[0]

        if not sel:
            # No selection => Add mode
            self._edit_index = None
            self._set_save_button_mode("add")
            return

        # Resolve index robustly (identity first, then value equality)
        idx = None
        try:
            for i, r in enumerate(tbl.data):
                if r is sel:
                    idx = i
                    break
        except Exception:
            pass
        if idx is None:
            try:
                target = list(sel)
                for i, r in enumerate(tbl.data):
                    try:
                        if list(r) == target:
                            idx = i
                            break
                    except Exception:
                        continue
            except Exception:
                pass

        if idx is None:
            self._edit_index = None
            self._set_save_button_mode("add")
            return

        # Store the edit index and populate inputs
        self._edit_index = idx
        selected = self._row_to_dict(sel)
        self.app.ui.name_input.value = selected["name"]
        self.app.ui.id_input.value = selected["id_number"]
        if hasattr(self.app.ui, "email_input"):
            self.app.ui.email_input.value = selected["email"]
        self.app.ui.date_input.value = self._normalize_date(selected["date"])

        self._set_save_button_mode("update")
        await self.update_preview()
        
    async def update_preview(self, widget=None):
        # debounce
        if self._preview_task and not self._preview_task.done():
            self._preview_task.cancel()

        async def _do():
            # Ensure template
            if (not self.template_path) or (not self.template_path.exists()):
                ui_state = getattr(self.app.ui, "state", SimpleNamespace())
                fallback = getattr(ui_state, "template_path", None)
                if isinstance(fallback, Path) and fallback.exists():
                    self.template_path = fallback
                else:
                    self.app.ui.status_label.text = "Pick a template to preview."
                    self.app.ui.preview_imageview.image = None
                    return

            # Prefer live manual inputs
            name = (self.app.ui.name_input.value or "").strip()
            idnum = (self.app.ui.id_input.value or "").strip()
            date_norm = self._normalize_date(self.app.ui.date_input.value or "")

            # If inputs are blank, use selected row as a convenience
            if not (name and idnum):
                sel = self._selected_row()
                if sel:
                    if not name:
                        name = sel.get("name", "")
                    if not idnum:
                        idnum = sel.get("id_number", "")
                    if not date_norm:
                        date_norm = self._normalize_date(sel.get("date", ""))

            template = Image.open(self.template_path).convert("RGBA")
            signature = Image.open(self.signature_path).convert("RGBA") if self.signature_path else None
            font_path = resource_path(self.app, "courbd.ttf")
            if not font_path.exists():
                font_path = None

            canvas = generate_single_card(
                name=name, id_number=idnum, date=(date_norm or ""),
                template=template, signature=signature, font_path=font_path,
            )

            buf = io.BytesIO()
            canvas.save(buf, format="PNG")
            buf.seek(0)
            self.app.ui.preview_imageview.image = toga.Image(src=buf.getvalue())
            if (self.app.ui.date_input.value or "").strip() and not date_norm:
                self.app.ui.status_label.text = "Preview updated (unrecognized date format → left blank)."
            else:
                self.app.ui.status_label.text = "Preview updated."

        self._preview_task = asyncio.create_task(_do())

    # ---------------- Email All ----------------
    async def _ensure_smtp_credentials_via_settings(self) -> bool:
        """
        Minimal Office 365 login dialog (no full settings).
        Validates credentials immediately; returns True only if login succeeds.
        """
        # Always enforce Office 365 transport settings.
        self.smtp_cfg.host = "smtp.office365.com"
        self.smtp_cfg.port = 587
        self.smtp_cfg.use_tls = True
        self.smtp_cfg.use_ssl = False

        # If we already have credentials, do a quick connection test once.
        def _test_connect(cfg: SMTPConfig) -> Optional[str]:
            try:
                from ..services.mailer import Mailer  # local import to avoid cycles during app load
                with Mailer(cfg) as m:
                    return None  # success
            except smtplib.SMTPAuthenticationError as e:
                return "Authentication failed. Check username/password (or App Password) and try again."
            except smtplib.SMTPConnectError as e:
                return f"Unable to connect to server: {e}"
            except smtplib.SMTPException as e:
                return f"SMTP error: {e}"
            except Exception as e:
                return f"Error: {e}"

        if all([(self.smtp_cfg.username or "").strip(),
                (self.smtp_cfg.password or "").strip(),
                (self.smtp_cfg.from_email or "").strip()]):
            err = _test_connect(self.smtp_cfg)
            if err is None:
                return True
            # fall through to dialog so user can correct creds

        # Build a small login dialog
        win = toga.Window(title="Email login (Office 365)")
        self.app.windows.add(win)

        username_in   = toga.TextInput(placeholder="your_email@domain.com", style=Pack(width=280))
        from_email_in = toga.TextInput(placeholder="From email (often same as username)", style=Pack(width=280))
        from_name_in  = toga.TextInput(placeholder="From name (optional)", style=Pack(width=280))
        password_in   = toga.PasswordInput(placeholder="Password or App Password", style=Pack(width=280))
        status_lbl    = toga.Label("", style=Pack(margin_top=8, font_size=14, font_weight="bold"))

        # Prefill any known values
        username_in.value   = self.smtp_cfg.username or ""
        from_email_in.value = self.smtp_cfg.from_email or ""
        from_name_in.value  = self.smtp_cfg.from_name or ""

        # Quick sender buttons
        def apply_role(role: str):
            addr = (OFFICER_EMAILS.get(role, "") or "").strip()
            if addr:
                username_in.value = addr
                from_email_in.value = addr
                status_lbl.text = f"Applied {role} sender address."

        role_row = toga.Box(
            children=[
                toga.Label("Quick sender:", style=Pack(width=120)),
                toga.Button("President", on_press=lambda w: apply_role("President")),
                toga.Button("Vice President", on_press=lambda w: apply_role("Vice President")),
                toga.Button("Membership Officer", on_press=lambda w: apply_role("Membership Officer")),
            ],
            style=Pack(direction=ROW, margin_top=6, margin_bottom=6),
        )

        save_btn   = toga.Button("Send", style=Pack(margin_right=8))
        cancel_btn = toga.Button("Cancel")

        def on_cancel(btn):
            win.close()

        def on_save(btn):
            # Persist creds
            self.smtp_cfg.username   = (username_in.value or "").strip()
            self.smtp_cfg.password   = password_in.value or ""
            self.smtp_cfg.from_email = (from_email_in.value or "").strip()
            self.smtp_cfg.from_name  = (from_name_in.value or "").strip()

            # Validate by opening an SMTP connection now.
            err = _test_connect(self.smtp_cfg)
            if err is None:
                win.close()
            else:
                status_lbl.text = err  # keep the dialog open & show why it failed

        save_btn.on_press = on_save
        cancel_btn.on_press = on_cancel

        root = toga.Box(
            children=[
                toga.Label("Sign in to Office 365", style=Pack(font_weight="bold", margin_bottom=8)),
                role_row,
                toga.Box(children=[toga.Label("Username",   style=Pack(width=120)), username_in],   style=Pack(direction=ROW, margin_bottom=6)),
                toga.Box(children=[toga.Label("From email", style=Pack(width=120)), from_email_in], style=Pack(direction=ROW, margin_bottom=6)),
                toga.Box(children=[toga.Label("From name",  style=Pack(width=120)), from_name_in],  style=Pack(direction=ROW, margin_bottom=6)),
                toga.Box(children=[toga.Label("Password",   style=Pack(width=120)), password_in],   style=Pack(direction=ROW, margin_bottom=6)),
                status_lbl,
                toga.Box(children=[save_btn, cancel_btn], style=Pack(direction=ROW, margin_top=6)),
                
            ],
            style=Pack(direction=COLUMN, margin=12, width=520),
        )
        win.content = root
        win.show()

        # Wait until closed
        while win in self.app.windows:
            await asyncio.sleep(0.05)

        ok = all([(self.smtp_cfg.username or "").strip(),
                  (self.smtp_cfg.password or "").strip(),
                  (self.smtp_cfg.from_email or "").strip()])
        if not ok:
            try:
                self.app.ui.status_label.text = "SMTP login cancelled or incomplete."
            except Exception:
                pass
        return ok

    async def email_selected(self, widget):
        """
        Email the ID card for the currently selected row.
        - Prompts for (or reuses) Office 365 SMTP credentials.
        - If the card image doesn't exist yet, generates it (if template is set).
        """
        # 1) Get the selected row
        row = self._selected_row()
        if not row:
            self.app.ui.status_label.text = "Select a row first to email its card."
            return

        name   = (row.get("name", "") or "").strip()
        idnum  = (row.get("id_number", "") or "").strip()
        date   = (row.get("date", "") or "").strip()
        to_email = (row.get("email", "") or "").strip()

        if not idnum or not to_email:
            self.app.ui.status_label.text = "Selected row needs both an ID Number and Email."
            return

        # 2) Ensure SMTP creds
        if not await self._ensure_smtp_credentials_via_settings():
            self.app.ui.status_label.text = "SMTP not configured."
            return

        # 3) Ensure an attachment exists (generate if missing and we can)
        attach = attachment_path_for_id(idnum)
        if not attach.exists():
            if not (self.template_path and self.template_path.exists()):
                self.app.ui.status_label.text = "Card image not found. Choose a template and generate this card first."
                return
            try:
                template = Image.open(self.template_path).convert("RGBA")
                signature = Image.open(self.signature_path).convert("RGBA") if self.signature_path and self.signature_path.exists() else None
                font_path = resource_path(self.app, "courbd.ttf")
                if not font_path.exists():
                    font_path = None
                from ..services.generation import generate_single_card, project_output_dir
                # Normalize date for rendering
                date_norm = self._normalize_date(date)
                canvas = generate_single_card(
                    name=name, id_number=idnum, date=(date_norm or ""),
                    template=template, signature=signature, font_path=font_path,
                )
                out_dir = project_output_dir()
                out_dir.mkdir(parents=True, exist_ok=True)
                canvas.save(attach, format="PNG")
            except Exception as e:
                self.app.ui.status_label.text = f"Couldn't generate card for {idnum}: {e}"
                return

        # 4) Disable relevant buttons during send
        buttons = (
            getattr(self.app.ui, "email_selected_btn", None),
            getattr(self.app.ui, "email_all_btn", None),
            getattr(self.app.ui, "generate_all_btn", None),
            getattr(self.app.ui, "add_member_btn", None),
            getattr(self.app.ui, "new_member_btn", None),
            getattr(self.app.ui, "clear_cards_btn", None),
        )
        buttons = tuple(b for b in buttons if b is not None)
        for b in buttons:
            b.enabled = False

        # Simple progress UX
        self.app.ui.progress.max = 1
        self.app.ui.progress.value = 0
        self.app.ui.status_label.text = f"Emailing card to {to_email}…"

        def render_tpl(tpl: str, row: dict) -> str:
            safe = {
                "name": name,
                "id_number": idnum,
                "date": date,
                "email": to_email,
                "sender": self.smtp_cfg.from_name or self.smtp_cfg.from_email,
            }
            try:
                return tpl.format(**safe)
            except Exception:
                return tpl

        # 5) Send
        try:
            with Mailer(self.smtp_cfg) as mailer:
                msg = build_message(
                    smtp=self.smtp_cfg,
                    to_email=to_email,
                    subject=render_tpl(getattr(self, "subject_tpl", "Your ID card, {name}"), row),
                    body_text=render_tpl(getattr(self, "body_tpl", "Hi {name}…"), row),
                    attachments=[attach],
                )
                mailer.send(msg)
            self.app.ui.progress.value = 1
            self.app.ui.status_label.text = f"Emailed {idnum} to {to_email}."
        except Exception as e:
            self.app.ui.status_label.text = f"Failed to email {idnum}: {e}"
        finally:
            for b in buttons:
                b.enabled = True


    async def email_all_from_table(self, widget):
        rows = self._rows_from_table()
        if not rows:
            self.app.ui.status_label.text = "Nothing to email — add members or load a CSV first."
            return

        # Ensure credentials exist using the minimal login dialog
        if not await self._ensure_smtp_credentials_via_settings():
            self.app.ui.status_label.text = "SMTP not configured: username, password, and from_email are required."
            return

        # Disable UI while sending
        buttons = (
            getattr(self.app.ui, "pick_template_btn", None),
            getattr(self.app.ui, "pick_signature_btn", None),
            getattr(self.app.ui, "load_csv_btn", None),
            getattr(self.app.ui, "generate_all_btn", None),
            getattr(self.app.ui, "clear_cards_btn", None),
            getattr(self.app.ui, "add_member_btn", None),
            getattr(self.app.ui, "new_member_btn", None),
            getattr(self.app.ui, "email_all_btn", None),
        )
        buttons = tuple(b for b in buttons if b is not None)
        for b in buttons:
            b.enabled = False

        total = len(rows)
        sent = skipped = errors = 0
        self.app.ui.progress.max = max(total, 1)
        self.app.ui.progress.value = 0
        self.app.ui.status_label.text = f"Emailing {total} recipient(s)…"

        def render_tpl(tpl: str, row: dict) -> str:
            # Use whatever templates are currently set; date is not defaulted
            safe = {
                "name": (row.get("name", "") or "").strip(),
                "id_number": (row.get("id_number", "") or "").strip(),
                "date": (row.get("date", "") or "").strip(),
                "email": (row.get("email", "") or "").strip(),
                "sender": self.smtp_cfg.from_name or self.smtp_cfg.from_email,
            }
            try:
                return tpl.format(**safe)
            except Exception:
                return tpl

        try:
            with Mailer(self.smtp_cfg) as mailer:
                for i, row in enumerate(rows, start=1):
                    try:
                        to_email = (row.get("email", "") or "").strip()
                        idnum = (row.get("id_number", "") or "").strip()
                        if not to_email or not idnum:
                            skipped += 1
                        else:
                            attach = attachment_path_for_id(idnum)
                            if attach.exists():
                                msg = build_message(
                                    smtp=self.smtp_cfg,
                                    to_email=to_email,
                                    subject=render_tpl(getattr(self, "subject_tpl", "Your ID card, {name}"), row),
                                    body_text=render_tpl(getattr(self, "body_tpl", "Hi {name}…"), row),
                                    attachments=[attach],
                                )
                                mailer.send(msg)
                                sent += 1
                            else:
                                skipped += 1
                    except Exception:
                        errors += 1
                    finally:
                        self.app.ui.progress.value = i
                        await asyncio.sleep(0)
        finally:
            for b in buttons:
                b.enabled = True

            self.app.ui.status_label.text = f"Email merge complete: {sent} sent, {skipped} skipped, {errors} errors."

    # ---------------- Batch generate (unchanged core) ----------------
    async def generate_all_from_table(self, widget):
        if not self.template_path or not self.template_path.exists():
            self.app.ui.status_label.text = "Please choose a template image first."
            return
        if not self.signature_path or not self.signature_path.exists():
            self.app.ui.status_label.text = "Please choose a signature image first."
            return

        rows = self._rows_from_table()
        if not rows:
            self.app.ui.status_label.text = "Nothing to generate — add members or load a CSV first."
            return

        template = Image.open(self.template_path).convert("RGBA")
        signature = Image.open(self.signature_path).convert("RGBA") if self.signature_path else None
        font_path = resource_path(self.app, "courbd.ttf")
        if not font_path.exists():
            font_path = None

        out_dir = project_output_dir()
        out_dir.mkdir(parents=True, exist_ok=True)

        normalized_rows = []
        for r in rows:
            r2 = dict(r)
            r2["date"] = self._normalize_date(r.get("date", "") or "")
            normalized_rows.append(r2)

        total = len(normalized_rows)
        ok = skipped = errors = 0

        buttons = (
            self.app.ui.pick_template_btn, self.app.ui.pick_signature_btn, self.app.ui.load_csv_btn,
            self.app.ui.generate_all_btn, self.app.ui.clear_cards_btn, getattr(self.app.ui, "add_member_btn", None),
            getattr(self.app.ui, "new_member_btn", None),
        )
        buttons = tuple(b for b in buttons if b is not None)
        for b in buttons:
            b.enabled = False

        self.app.ui.progress.max = max(total, 1)
        self.app.ui.progress.value = 0
        self.app.ui.status_label.text = f"Generating {total} card(s)…"

        try:
            async for i, result in generate_batch_cards(normalized_rows, template, signature, font_path, out_dir):
                if result == "ok":
                    ok += 1
                elif result == "skip":
                    skipped += 1
                else:
                    errors += 1
                self.app.ui.progress.value = i
                await asyncio.sleep(0)
        finally:
            for b in buttons:
                b.enabled = True

        # best-effort: open folder
        try:
            import os, platform, webbrowser, subprocess
            if platform.system() == "Windows":
                os.startfile(out_dir)  # type: ignore[attr-defined]
            elif platform.system() == "Darwin":
                subprocess.run(["open", out_dir])
            else:
                webbrowser.open(out_dir.as_uri())
        except Exception:
            pass

        self.app.ui.status_label.text = (
            f"Batch complete: {ok} saved, {skipped} skipped (no ID), {errors} errors."
        )

    # ---------------- File pickers, CSV loader, clear_cards, mail settings ----------------

    async def choose_template(self, widget):
        dialog = OpenFileDialog(title="Select template image", file_types=["png", "jpg", "jpeg", "bmp"], multiple_select=False)
        paths = await self.app.main_window.dialog(dialog)
        if paths:
            self.template_path = Path(paths[0]) if isinstance(paths, list) else Path(paths)
            try:
                img = toga.Image(str(self.template_path))
                self.app.ui.preview_imageview.image = img
                self.app.ui.preview_imageview.refresh()
                if not hasattr(self.app.ui, "state"):
                    self.app.ui.state = SimpleNamespace()
                self.app.ui.state.template_path = self.template_path
                self.app.ui.state.preview_img = img
            except Exception:
                pass
            self.app.ui.status_label.text = f"Template: {self.template_path.name}"
            await self.update_preview()

            self.apply_editing_lock()

    async def choose_signature(self, widget):
        dialog = OpenFileDialog(title="Select signature image", file_types=["png", "jpg", "jpeg"], multiple_select=False)
        paths = await self.app.main_window.dialog(dialog)
        if paths:
            self.signature_path = Path(paths[0]) if isinstance(paths, list) else Path(paths)
            self.app.ui.status_label.text = f"Signature: {self.signature_path.name}"
            await self.update_preview()
            self.apply_editing_lock()

    async def load_csv(self, widget):
        # Hard guard: require template + signature before loading a CSV
        if not (self.template_path and self.template_path.exists()):
            self.app.ui.status_label.text = "Please choose a template image first."
            return
        if not (self.signature_path and self.signature_path.exists()):
            self.app.ui.status_label.text = "Please choose a signature image first."
            return

        dialog = toga.OpenFileDialog(title="Select CSV file", multiple_select=False, file_types=["csv"])
        paths = await self.app.main_window.dialog(dialog)
        if not paths:
            self.app.ui.status_label.text = "CSV load cancelled."
            return

        csv_path = Path(paths[0] if isinstance(paths, (list, tuple)) else paths)
        rows = []
        required = ["name", "id_number", "date", "email"]
        try:
            with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames:
                    self.app.ui.status_label.text = "CSV has no header row."
                    return

                header_map = {h: (h or "").strip().lower() for h in reader.fieldnames}
                rev = {}
                for orig, norm in header_map.items():
                    rev.setdefault(norm, orig)

                missing = [col for col in required if col not in rev]
                if missing:
                    self.app.ui.status_label.text = "CSV missing required columns: " + ", ".join(missing)
                    return

                for rec in reader:
                    def get(col): return (rec.get(rev[col], "") or "").strip()
                    rows.append({
                        "name": get("name"),
                        "id_number": get("id_number"),
                        "date": self._normalize_date(get("date")),
                        "email": get("email"),
                    })
        except Exception as e:
            self.app.ui.status_label.text = f"Failed to read CSV: {e}"
            return

        # Build a fresh table model and force a repaint
        table_rows = [[r["name"], r["id_number"], r["date"], r["email"]] for r in rows]
        existing = self._rows_as_lists()
        existing.extend(table_rows)
        self._table_reassign(existing, reselection_index=None)

        # Keep your in-memory mirror if you use it elsewhere
        if hasattr(self, "csv_rows"):
            try:
                self.csv_rows.extend(rows)
            except Exception:
                self.csv_rows = (self.csv_rows or []) + rows

        total_now = len(existing)
        self.app.ui.status_label.text = f"Added {len(rows)} member(s) from {csv_path.name}. Table now has {total_now} row(s)."
    async def clear_cards(self, widget):
        out_dir = project_output_dir()

        if not self._confirm_clear:
            self._confirm_clear = True
            original = self.app.ui.clear_cards_btn.text
            self.app.ui.clear_cards_btn.text = "Click again to CONFIRM delete… (6s)"
            self.app.ui.status_label.text = f"Ready to delete all cards."

            if self._confirm_task and not self._confirm_task.done():
                self._confirm_task.cancel()
            self._confirm_task = asyncio.create_task(self._reset_clear_confirm(6, original))
            return

        if self._confirm_task and not self._confirm_task.done():
            self._confirm_task.cancel()
        self._confirm_clear = False
        self.app.ui.clear_cards_btn.text = "Clear cards"

        buttons = (
            getattr(self.app.ui, "pick_template_btn", None),
            getattr(self.app.ui, "pick_signature_btn", None),
            getattr(self.app.ui, "load_csv_btn", None),
            getattr(self.app.ui, "generate_all_btn", None),
            getattr(self.app.ui, "email_all_btn", None),
            getattr(self.app.ui, "add_member_btn", None),
            getattr(self.app.ui, "new_member_btn", None),
        )
        buttons = tuple(b for b in buttons if b is not None)
        for b in buttons:
            b.enabled = False

        try:
            if out_dir.exists():
                for child in out_dir.iterdir():
                    try:
                        if child.is_file() or child.is_symlink():
                            child.unlink(missing_ok=True)
                        elif child.is_dir():
                            shutil.rmtree(child, ignore_errors=True)
                    except Exception:
                        pass
            self.csv_rows = []
            self.app.ui.csv_table.data = []

            # Clear inputs, reset button to "Add", and redraw blank preview
            self.app.ui.name_input.value = ""
            self.app.ui.id_input.value = ""
            if hasattr(self.app.ui, "email_input"):
                self.app.ui.email_input.value = ""
            self.app.ui.date_input.value = ""
            self._set_save_button_mode("add")
            try:
                self.app.ui.csv_table.selection = None
            except Exception:
                pass
            await self.update_preview()

            self.app.ui.status_label.text = f"Cleared all cards and emptied table."
        finally:
            for b in buttons:
                b.enabled = True

    async def _reset_clear_confirm(self, seconds: int, original_text: str):
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            return
        if self._confirm_clear:
            self._confirm_clear = False
            self.app.ui.clear_cards_btn.text = original_text
            self.app.ui.status_label.text = "Clear cancelled."

   # REPLACE your current save_table() with this version
    async def save_table(self, widget):
        """
        Save current table rows to a CSV with headers EXACTLY as EXPECTED_COLUMNS.
        Uses a SaveFileDialog; falls back to the output folder if needed.
        """
        rows = self._rows_as_lists()  # [[Name, ID Number, Date, Email], ...]
        if not rows:
            self.app.ui.status_label.text = "Nothing to save — the table is empty."
            return

        save_path: Path | None = None
        try:
            dialog = toga.SaveFileDialog(
                title="Save Table as CSV",
                suggested_filename="members.csv",   # <<— FIX: use suggested_filename
                file_types=["csv"],
            )
            chosen = await self.app.main_window.dialog(dialog)
            if chosen:
                # Backends differ: chosen may be str, Path, or a list/tuple
                if isinstance(chosen, (list, tuple)):
                    save_path = Path(chosen[0])
                else:
                    save_path = Path(chosen)
        except Exception:
            save_path = None

        # Fallback to project output dir
        if save_path is None:
            try:
                out_dir = project_output_dir()
            except Exception:
                out_dir = Path.cwd()
            out_dir.mkdir(parents=True, exist_ok=True)
            save_path = out_dir / "members.csv"

        # Ensure .csv extension
        if save_path.suffix.lower() != ".csv":
            save_path = save_path.with_suffix(".csv")

        try:
            with save_path.open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(EXPECTED_COLUMNS)  # ["Name", "ID Number", "Date", "Email"]
                for r in rows:
                    r = (r + ["", "", "", ""])[:4]
                    writer.writerow([(r[0] or "").strip(),
                                    (r[1] or "").strip(),
                                    (r[2] or "").strip(),
                                    (r[3] or "").strip()])
            self.app.ui.status_label.text = f"Table saved: {save_path}"
        except Exception as e:
            self.app.ui.status_label.text = f"Failed to save table: {e}"
