# idcard_maker/ui/mail_settings.py
from types import SimpleNamespace
import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW

DEFAULT_SUBJECT = "Your ID card, {name}"
DEFAULT_BODY = (
    "Hi {name},\n\n"
    "Attached is your ID card.\n"
    "ID: {id_number}\n"
    "Date: {date}\n\n"
    "Best,\n"
    "{sender}"
)

def build_mail_settings_window(app: toga.App) -> SimpleNamespace:
    win = toga.Window(title="Mail Settings")
    app.windows.add(win)

    host = toga.TextInput(placeholder="smtp.server.com")
    port = toga.NumberInput(step=1, min=1, max=65535, value=587)
    use_tls = toga.Switch("Use STARTTLS (587)")
    use_ssl = toga.Switch("Use SSL (465)")
    username = toga.TextInput(placeholder="SMTP username (often your email)")
    password = toga.PasswordInput(placeholder="App password or SMTP password")
    from_name = toga.TextInput(placeholder="Sender name (optional)")
    from_email = toga.TextInput(placeholder="sender@example.com")

    subject_tpl = toga.TextInput(value=DEFAULT_SUBJECT)
    body_tpl = toga.MultilineTextInput(value=DEFAULT_BODY, style=Pack(height=160))

    save_btn = toga.Button("Save", style=Pack(margin_right=8))
    cancel_btn = toga.Button("Cancel")

    root = toga.Box(
        children=[
            toga.Label("SMTP server", style=Pack(font_weight="bold", margin_bottom=4)),
            toga.Box(children=[toga.Label("Host", style=Pack(width=120)), host], style=Pack(direction=ROW, margin_bottom=6)),
            toga.Box(children=[toga.Label("Port", style=Pack(width=120)), port], style=Pack(direction=ROW, margin_bottom=6)),
            use_tls, use_ssl,
            toga.Box(children=[toga.Label("Username", style=Pack(width=120)), username], style=Pack(direction=ROW, margin_top=8, margin_bottom=6)),
            toga.Box(children=[toga.Label("Password", style=Pack(width=120)), password], style=Pack(direction=ROW, margin_bottom=6)),
            toga.Box(children=[toga.Label("From name", style=Pack(width=120)), from_name], style=Pack(direction=ROW, margin_bottom=6)),
            toga.Box(children=[toga.Label("From email", style=Pack(width=120)), from_email], style=Pack(direction=ROW, margin_bottom=12)),
            toga.Label("Templates", style=Pack(font_weight="bold", margin_bottom=4)),
            toga.Box(children=[toga.Label("Subject", style=Pack(width=120)), subject_tpl], style=Pack(direction=ROW, margin_bottom=6)),
            toga.Label("Body (use {name}, {id_number}, {date}, {email}, {sender})", style=Pack(margin_bottom=6)),
            body_tpl,
            toga.Box(children=[save_btn, cancel_btn], style=Pack(direction=ROW, margin_top=12)),
        ],
        style=Pack(direction=COLUMN, margin=12, width=520),
    )
    win.content = root

    return SimpleNamespace(
        window=win,
        host=host, port=port, use_tls=use_tls, use_ssl=use_ssl,
        username=username, password=password, from_name=from_name, from_email=from_email,
        subject_tpl=subject_tpl, body_tpl=body_tpl,
        save_btn=save_btn, cancel_btn=cancel_btn,
    )
