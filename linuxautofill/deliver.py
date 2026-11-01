"""Hand a code or link to the desktop: clipboard, notification, click action, clear later."""

import html
import logging
import shutil
import subprocess
import threading
import time
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

# The same code can arrive twice, for example by SMS and email.
DEDUPE_SECONDS = 120


class Deliverer:
    def __init__(self, clear_after):
        self.clear_after = clear_after
        self.recent = {}

    def deliver(self, code, sender):
        """Deliver a code and return True, or return False for a recent duplicate."""
        can_paste = shutil.which("wtype") is not None
        hint = "Click to paste." if can_paste else "Copied to clipboard."
        action = "Paste" if can_paste else None
        return self._send(code, code, self._body(sender, hint), action, self._paste)

    def deliver_link(self, url, sender):
        """Deliver a link and return True, or return False for a recent duplicate."""
        if urlsplit(url).scheme.lower() not in ("http", "https"):
            raise ValueError("not a web link")
        # The domain is shown so that a lookalike can be spotted before clicking.
        hint = f"Opens {urlsplit(url).hostname}. Click to open."
        return self._send(url, "Verification link", self._body(sender, hint), "Open", self._open)

    def _body(self, sender, hint):
        return f"From {sender}. {hint}" if sender else hint

    def _send(self, value, summary, body, action, on_click):
        now = time.monotonic()
        self.recent = {v: t for v, t in self.recent.items() if now - t < DEDUPE_SECONDS}
        if value in self.recent:
            return False
        self.recent[value] = now

        self._copy(value)
        threading.Thread(
            target=self._notify, args=(value, summary, body, action, on_click), daemon=True
        ).start()
        threading.Timer(self.clear_after, self._clear_if_unchanged, args=(value,)).start()
        return True

    def _copy(self, value):
        # Sent over stdin so the value isn't visible in the process list. wl-copy
        # stays running in the background, so its output can't be captured here.
        subprocess.run(
            ["wl-copy"],
            input=value.encode(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=5,
        )

    def _notify(self, value, summary, body, action, on_click):
        command = [
            "notify-send",
            "--app-name=LinuxAutofill",
            f"--expire-time={self.clear_after * 1000}",
        ]
        if action:
            command.append(f"--action=default={action}")
        # mako renders markup in notifications, and the sender is untrusted.
        command += [html.escape(summary), html.escape(body)]

        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=self.clear_after + 5
            )
        except subprocess.TimeoutExpired:
            return
        if result.returncode != 0:
            log.warning("notification failed with exit code %d", result.returncode)
        elif result.stdout.strip() == "default":
            # Only ever acted on after a click, so a message can't do anything by itself.
            on_click(value)

    def _paste(self, code):
        subprocess.run(["wtype", code], timeout=5)

    def _open(self, url):
        # Not waited on, because xdg-open can stay running as long as the browser does.
        subprocess.Popen(
            ["xdg-open", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def _clear_if_unchanged(self, value):
        try:
            current = subprocess.run(
                ["wl-paste", "--no-newline"], capture_output=True, timeout=5
            )
            if current.stdout == value.encode():
                subprocess.run(["wl-copy", "--clear"], timeout=5)
        except (OSError, subprocess.SubprocessError) as error:
            log.warning("could not clear clipboard: %s", type(error).__name__)
