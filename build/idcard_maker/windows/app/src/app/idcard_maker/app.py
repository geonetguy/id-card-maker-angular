# idcard_maker/app.py
from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import toga

from .core.resources import resource_path
from .constants import APP_TITLE
from .controllers.actions import Actions
from .ui.layout import build_ui


class IDCardApp(toga.App):
    ui: SimpleNamespace  # for Pylance

    def startup(self):
        # Main window
        self.main_window: toga.MainWindow = toga.MainWindow(
            title=APP_TITLE,
            resizable=False,
        )

        # Build UI + controller
        actions = Actions(self)
        ui = build_ui(self)
        self.ui = ui

        # Help (opens system browser)
        self.commands.add(
            toga.Command(
                actions.open_help,
                text="Help",
                tooltip="View the user guide",
                group=toga.Group.HELP,
                shortcut="F1",
            )
        )

        # ---- Remove the built-in "Visit Home Page" item, if any ----
        try:
            for cmd in list(self.commands):
                text = (getattr(cmd, "text", "") or "").strip().lower()
                grp = getattr(cmd, "group", None)
                # catch variants like "Visit home page", "Home page", etc.
                if grp == toga.Group.HELP and ("visit" in text and "home" in text and "page" in text):
                    try:
                        self.commands.remove(cmd)   # preferred (supported in modern Toga)
                    except Exception:
                        cmd.enabled = False         # fallback: disable if removal not supported
        except Exception:
            pass

        # Wire buttons / actions
        ui.pick_template_btn.on_press   = actions.choose_template
        ui.pick_signature_btn.on_press  = actions.choose_signature
        ui.load_csv_btn.on_press        = actions.load_csv
        ui.add_member_btn.on_press      = actions.save_member       # unified Add/Update handler
        ui.new_member_btn.on_press      = actions.new_member        # force Add mode (clear fields)
        ui.generate_all_btn.on_press    = actions.generate_all_from_table
        ui.clear_cards_btn.on_press     = actions.clear_cards
        ui.email_selected_btn.on_press  = actions.email_selected
        ui.email_all_btn.on_press       = actions.email_all_from_table
        ui.save_table_btn.on_press      = actions.save_table

        # Table selection -> populate fields + preview; switch to Update mode
        ui.csv_table.on_select          = actions.on_table_select

        # Attach UI and show window early (so refresh calls below are valid)
        self.main_window.content = ui.container
        self.main_window.show()

        # Match stripe width to window width
        win_w, _ = self.main_window.size
        ui.stripe_view.style.width = win_w

        # ---------- Default template (packaging-safe) ----------
        default_tpl = resource_path(self, "template.png")
        if default_tpl.exists():
            if not hasattr(ui, "state"):
                ui.state = SimpleNamespace()

            actions.template_path = default_tpl
            ui.state.template_path = default_tpl

            try:
                img = toga.Image(src=str(default_tpl))
                ui.preview_imageview.image = img
                ui.preview_imageview.refresh()
            except Exception:
                pass

            ui.status_label.text = f"Template: {default_tpl.name}"
        else:
            ui.status_label.text = "Default template not found; choose a template…"

        # Optional app icon (packaging-safe)
        logo_path = resource_path(self, "logo.png")
        if logo_path.exists():
            try:
                self.icon = toga.Icon(str(logo_path))
            except Exception:
                pass

        # Enforce the “template + signature required” edit lock at startup
        actions.apply_editing_lock()

        # Live preview while typing (name/id/date/email)
        ui.name_input.on_change = actions.update_preview
        ui.id_input.on_change   = actions.update_preview
        ui.date_input.on_change = actions.update_preview
        if hasattr(ui, "email_input"):
            ui.email_input.on_change = actions.update_preview

        # Start in "Add" mode
        ui.add_member_btn.text = "Add member"


def main():
    app = IDCardApp(
        formal_name=APP_TITLE,
        app_id="ca.cupe3523.idcard_maker",  # reverse-DNS bundle id; safe for packaging
        # Do NOT pass home_page here
    )
    # Explicitly clear any home page so Toga doesn't add "Visit Home Page"
    try:
        app.home_page = None
    except Exception:
        pass
    return app


if __name__ == "__main__":
    app = main()
    app.main_loop()
