"""Hand a code or link to the desktop: clipboard, notification, click action, restore later."""

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

# wl-copy can only offer one format, so the most useful one is kept.
RESTORE_TYPES = (
    "text/uri-list",
    "text/plain;charset=utf-8",
    "text/plain",
    "UTF8_STRING",
    "image/png",
)
# Set by password managers, which clear these themselves and expect them to stay gone.
SECRET_TYPE = "x-kde-passwordManagerHint"


class Deliverer:
    def __init__(self, clear_after):
        self.clear_after = clear_after
        self.recent = {}
        self.lock = threading.Lock()
        self.active = None
        self.saved = None
        self.timer = None

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

        with self.lock:
            snapshot = self._snapshot()
            # A second code replacing the first shouldn't make the first one what's restored.
            if not (snapshot and self.active and snapshot[1] == self.active.encode()):
                self.saved = snapshot
            self._copy(value.encode())
            if self.timer:
                self.timer.cancel()
            self.active = value
            self.timer = threading.Timer(self.clear_after, self._restore_if_unchanged, args=(value,))
            self.timer.start()

        threading.Thread(
            target=self._notify, args=(value, summary, body, action, on_click), daemon=True
        ).start()
        return True

    def _snapshot(self):
        """Return the clipboard as (type, data), or None if it can't or shouldn't be kept."""
        try:
            listed = subprocess.run(
                ["wl-paste", "--list-types"], capture_output=True, text=True, timeout=2
            )
            types = listed.stdout.splitlines()
            if listed.returncode != 0 or not types or SECRET_TYPE in types:
                return None
            mime = next((t for t in RESTORE_TYPES if t in types), types[0])
            data = subprocess.run(
                ["wl-paste", "--no-newline", "--type", mime], capture_output=True, timeout=2
            )
            return (mime, data.stdout) if data.returncode == 0 else None
        except (OSError, subprocess.SubprocessError) as error:
            log.warning("could not read clipboard: %s", type(error).__name__)
            return None

    def _copy(self, data, mime=None):
        # Sent over stdin so the value isn't visible in the process list. wl-copy
        # stays running in the background, so its output can't be captured here.
        subprocess.run(
            ["wl-copy", *(["--type", mime] if mime else [])],
            input=data,
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

    def _restore_if_unchanged(self, value):
        with self.lock:
            if self.active != value:
                return
            saved, self.active, self.saved = self.saved, None, None
            try:
                current = subprocess.run(
                    ["wl-paste", "--no-newline"], capture_output=True, timeout=5
                )
                if current.stdout != value.encode():
                    return
                if saved:
                    self._copy(saved[1], saved[0])
                else:
                    subprocess.run(["wl-copy", "--clear"], timeout=5)
            except (OSError, subprocess.SubprocessError) as error:
                log.warning("could not restore clipboard: %s", type(error).__name__)
