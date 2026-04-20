# idcard_maker/app.py
from __future__ import annotations

import os
import socket
import threading
import time
import tempfile
import webbrowser
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from functools import partial

import toga

from .api_app import app as api_app
from .constants import APP_TITLE
from .core.resources import resource_path


class IDCardApp(toga.App):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._static_httpd: ThreadingHTTPServer | None = None
        self._static_thread: threading.Thread | None = None
        self._static_port: int | None = None

    def _is_port_open(self, host: str, port: int, timeout_s: float = 0.15) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout_s):
                return True
        except Exception:
            return False

    def _find_running_dev_server_url(self) -> str | None:
        """
        Try to detect an Angular dev server URL.

        `npm start` (ng serve) typically binds to port 4200, but will prompt to
        use the next port if 4200 is already in use. It may also bind IPv6 only
        (`::1`) on some systems. We probe a small port range on common hosts.
        """
        hosts = ["127.0.0.1", "localhost", "::1"]
        for port in range(4200, 4211):
            for host in hosts:
                if self._is_port_open(host, port):
                    if host == "127.0.0.1":
                        return f"http://127.0.0.1:{port}/"
                    if host == "localhost":
                        return f"http://localhost:{port}/"
                    # IPv6-only bind (common when localhost resolves to ::1)
                    return f"http://[::1]:{port}/"
        return None

    def _find_built_dist_index(self) -> Path | None:
        """
        Find the built Angular `index.html` regardless of current working dir.

        In Briefcase dev/run, the CWD may be inside `.briefcase/...`, so we
        search upward from this file and from CWD for a `frontend/dist/...` tree.
        """
        candidates: list[Path] = []
        try:
            candidates.append(Path.cwd())
        except Exception:
            pass
        try:
            candidates.append(Path(__file__).resolve())
        except Exception:
            pass

        seen: set[Path] = set()
        for base in candidates:
            for parent in [base, *base.parents]:
                if parent in seen:
                    continue
                seen.add(parent)
                dist_index = (
                    parent / "frontend" / "dist" / "frontend" / "browser" / "index.html"
                )
                if dist_index.exists():
                    return dist_index
        return None

    def _start_api_server(self, host: str = "127.0.0.1", port: int = 8000) -> None:
        """
        Start the FastAPI server (uvicorn) in a background thread.
        Keeps Python authoritative for rendering/generation/email.
        """
        if self._is_port_open(host, port):
            return

        def _run() -> None:
            try:
                import uvicorn

                config = uvicorn.Config(
                    api_app,
                    host=host,
                    port=port,
                    log_level="warning",
                    access_log=False,
                )
                uvicorn.Server(config).run()
            except Exception:
                return

        threading.Thread(target=_run, name="idcard-api", daemon=True).start()

        # Best-effort: wait briefly so the Angular UI can call the API immediately.
        for _ in range(20):
            if self._is_port_open(host, port):
                break
            time.sleep(0.05)

    def _find_free_port(self, host: str = "127.0.0.1") -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, 0))
            return int(s.getsockname()[1])

    def _start_static_server(self, directory: Path, host: str = "127.0.0.1") -> str:
        """
        Toga's WinForms WebView only accepts http/https URLs. Serve built Angular
        files from a local HTTP server when the dev server isn't running.
        """
        if self._static_port is not None and self._static_httpd is not None:
            return f"http://{host}:{self._static_port}/"

        if not directory.exists():
            return "about:blank"

        port = self._find_free_port(host)
        handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
        httpd = ThreadingHTTPServer((host, port), handler)

        def _run() -> None:
            try:
                httpd.serve_forever()
            except Exception:
                pass

        t = threading.Thread(target=_run, name="idcard-web-static", daemon=True)
        t.start()

        self._static_httpd = httpd
        self._static_thread = t
        self._static_port = port
        return f"http://{host}:{port}/"

    def _start_placeholder_ui(self, host: str = "127.0.0.1") -> str:
        """
        Start a tiny static server hosting a placeholder page.
        This is used when neither the Angular dev server nor a built dist is available.
        """
        tmp_dir = Path(tempfile.mkdtemp(prefix="idcard-maker-ui-"))
        index = tmp_dir / "index.html"
        index.write_text(
            """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>ID Card Maker</title>
    <style>
      body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 0; padding: 24px; }
      code { background: #f3f4f6; padding: 2px 6px; border-radius: 6px; }
      .card { max-width: 900px; margin: 0 auto; border: 1px solid #e5e7eb; border-radius: 12px; padding: 18px; }
      h1 { margin: 0 0 10px; font-size: 18px; }
      p { margin: 8px 0; color: #111827; }
      .muted { color: #6b7280; font-size: 13px; }
    </style>
  </head>
  <body>
    <div class="card">
      <h1>ID Card Maker UI not found</h1>
      <p>Start the Angular dev server:</p>
      <p><code>cd frontend</code></p>
      <p><code>npm start</code></p>
      <p class="muted">Then restart this app (or set <code>IDCARD_WEB_URL</code>).</p>
    </div>
  </body>
</html>
""",
            encoding="utf-8",
        )
        return self._start_static_server(tmp_dir, host=host)

    def _resolve_web_url(self) -> str:
        override = (os.environ.get("IDCARD_WEB_URL") or "").strip()
        if override:
            return override

        # Prefer Angular dev server if running (npm start).
        dev_url = self._find_running_dev_server_url()
        if dev_url:
            return dev_url

        # Fall back to local build output if present.
        dist_index = self._find_built_dist_index()
        if dist_index is not None:
            return self._start_static_server(dist_index.parent)

        # Last resort: serve a placeholder page over HTTP (WebView requires http/https).
        return self._start_placeholder_ui()

    async def open_help(self, widget=None):
        help_path = resource_path(self, "help.html")
        if help_path.exists():
            try:
                webbrowser.open(help_path.as_uri())
            except Exception:
                pass

    def startup(self):
        self.main_window: toga.MainWindow = toga.MainWindow(
            title=APP_TITLE,
            resizable=True,
        )

        # Start backend API in-process (no business logic duplication in Angular).
        self._start_api_server()

        # Help (opens system browser)
        self.commands.add(
            toga.Command(
                self.open_help,
                text="Help",
                tooltip="View the user guide",
                group=toga.Group.HELP,
                shortcut="F1",
            )
        )

        # Remove built-in "Visit Home Page" item, if any.
        try:
            for cmd in list(self.commands):
                text = (getattr(cmd, "text", "") or "").strip().lower()
                grp = getattr(cmd, "group", None)
                if grp == toga.Group.HELP and ("visit" in text and "home" in text and "page" in text):
                    try:
                        self.commands.remove(cmd)
                    except Exception:
                        cmd.enabled = False
        except Exception:
            pass

        web_url = self._resolve_web_url()
        webview = toga.WebView(url=web_url, style=toga.style.Pack(flex=1))

        self.main_window.content = webview
        self.main_window.show()

        # Optional app icon (packaging-safe)
        logo_path = resource_path(self, "logo.png")
        if logo_path.exists():
            try:
                self.icon = toga.Icon(str(logo_path))
            except Exception:
                pass


def main():
    app = IDCardApp(
        formal_name=APP_TITLE,
        app_id="ca.cupe3523.idcard_maker",
    )
    # Explicitly clear any home page so Toga doesn't add "Visit Home Page"
    try:
        app.home_page = None
    except Exception:
        pass
    return app


if __name__ == "__main__":
    main().main_loop()
