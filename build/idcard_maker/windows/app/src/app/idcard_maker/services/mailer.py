# idcard_maker/services/mailer.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
import mimetypes


@dataclass
class SMTPConfig:
    host: str = ""
    port: int = 587
    use_tls: bool = True       # STARTTLS on 587
    use_ssl: bool = False      # SMTPS on 465
    username: str = ""
    password: str = ""
    from_name: str = ""
    from_email: str = ""       # must be a valid mailbox on your SMTP


def _guess_mime(path: Path) -> tuple[str, str]:
    ctype, _ = mimetypes.guess_type(str(path))
    if not ctype:
        return "application", "octet-stream"
    major, minor = ctype.split("/", 1)
    return major, minor


def build_message(
    *, smtp: SMTPConfig, to_email: str, subject: str, body_text: str,
    attachments: Optional[Iterable[Path]] = None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((smtp.from_name or smtp.from_email, smtp.from_email))
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body_text)

    for p in attachments or []:
        if not p or not p.exists():
            continue
        major, minor = _guess_mime(p)
        with p.open("rb") as f:
            msg.add_attachment(f.read(), maintype=major, subtype=minor, filename=p.name)
    return msg


class Mailer:
    def __init__(self, cfg: SMTPConfig):
        self.cfg = cfg
        self._smtp: Optional[smtplib.SMTP] = None
        self._smtps: Optional[smtplib.SMTP_SSL] = None

    def __enter__(self):
        if self.cfg.use_ssl:
            context = ssl.create_default_context()
            self._smtps = smtplib.SMTP_SSL(self.cfg.host, self.cfg.port, context=context, timeout=30)
            if self.cfg.username:
                self._smtps.login(self.cfg.username, self.cfg.password)
            return self
        else:
            self._smtp = smtplib.SMTP(self.cfg.host, self.cfg.port, timeout=30)
            self._smtp.ehlo()
            if self.cfg.use_tls:
                context = ssl.create_default_context()
                self._smtp.starttls(context=context)
                self._smtp.ehlo()
            if self.cfg.username:
                self._smtp.login(self.cfg.username, self.cfg.password)
            return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if self._smtp:
                self._smtp.quit()
            if self._smtps:
                self._smtps.quit()
        except Exception:
            pass

    def send(self, message: EmailMessage):
        if self._smtps:
            self._smtps.send_message(message)
        elif self._smtp:
            self._smtp.send_message(message)
        else:
            raise RuntimeError("Mailer not connected")
