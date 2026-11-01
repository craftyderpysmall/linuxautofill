"""Watch a Gmail inbox by polling it over IMAP."""

import datetime
import email
import email.policy
import email.utils
import imaplib
import logging
import time
from html.parser import HTMLParser

from .detect import LINK_CONTEXT, Link, plain_links

log = logging.getLogger(__name__)

HOST = "imap.gmail.com"
# Measured behind Gmail's receive time: IDLE 10-23s, STATUS 6-12s, reopening the inbox 3s.
POLL_SECONDS = 0.5
SLOW_CHECK_SECONDS = 2
SOCKET_TIMEOUT = 30
MAX_AGE = datetime.timedelta(minutes=10)
# Enough for any verification email, without downloading large attachments.
FETCH = "(INTERNALDATE BODY.PEEK[]<0.262144>)"
MAX_BACKOFF = 300


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skipping = 0
        self.links = []
        self.href = None
        self.label = []
        self.context = ""

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "br":
            self.parts.append("\n")
        elif tag in ("script", "style", "head", "title"):
            self.skipping += 1
        elif tag == "a" and attributes.get("href"):
            self.href = attributes["href"].strip()
            self.label = []
            self.context = "".join(self.parts)[-LINK_CONTEXT:]
        elif tag == "img" and self.href and attributes.get("alt"):
            # Buttons are sometimes images.
            self.label.append(attributes["alt"])

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head", "title") and self.skipping:
            self.skipping -= 1
        if tag == "a" and self.href:
            self.links.append(Link(self.href, " ".join(" ".join(self.label).split()), self.context))
            self.href = None
        if tag in ("p", "div", "tr", "td", "table", "h1", "h2", "h3", "span"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skipping:
            self.parts.append(data)
            if self.href:
                self.label.append(data)


def parse_html(markup):
    """Return the visible text of an HTML email and its links."""
    extractor = _TextExtractor()
    extractor.feed(markup)
    return "".join(extractor.parts), extractor.links


def parse_message(raw, now=None):
    """Return (sender, text, links) from a raw email, or None if it's too old to matter."""
    message = email.message_from_bytes(raw, policy=email.policy.default)

    now = now or datetime.datetime.now(datetime.timezone.utc)
    try:
        sent = email.utils.parsedate_to_datetime(message["Date"])
        if sent.tzinfo and now - sent > MAX_AGE:
            return None
    except (TypeError, ValueError):
        pass

    sender = email.utils.parseaddr(str(message["From"] or ""))
    subject = str(message["Subject"] or "")
    body, links = _read_body(message)
    return sender[0] or sender[1], f"{subject}\n{body}", links


def _content(part):
    try:
        return part.get_content() if part is not None else ""
    except (LookupError, UnicodeError):
        return ""


def _read_body(message):
    """Prefer plain text for reading. Links come from HTML, since buttons only exist there,
    then from bare URLs, which some HTML emails use instead of real links."""
    plain = _content(message.get_body(preferencelist=("plain",)))
    text, links = parse_html(_content(message.get_body(preferencelist=("html",))))
    return plain or text, links + plain_links(f"{plain}\n{text}")


def log_timing(metadata, raw):
    """Log how long each leg took, to show where any delay comes from."""
    internal = imaplib.Internaldate2tuple(metadata)
    if internal is None:
        return
    received = time.mktime(internal)
    message = email.message_from_bytes(raw, policy=email.policy.default)
    try:
        sent = email.utils.parsedate_to_datetime(message["Date"]).timestamp()
    except (TypeError, ValueError):
        sent = received
    log.info(
        "mail: sender to Gmail %.0fs, Gmail to here %.0fs", received - sent, time.time() - received
    )


def _next_uid(imap):
    # Reopening gives a fresh view. STATUS and an already open mailbox both lag behind it.
    # Read-only, so nothing here can mark mail as read.
    status, _ = imap.select("INBOX", readonly=True)
    _, data = imap.response("UIDNEXT")
    if status != "OK" or not data or data[0] is None:
        raise imaplib.IMAP4.error("no UIDNEXT in EXAMINE response")
    return int(data[0])


def _fetch_new(imap, last_uid, messages):
    status, data = imap.uid("SEARCH", None, f"UID {last_uid + 1}:*")
    if status != "OK":
        raise imaplib.IMAP4.error("UID SEARCH failed")
    # "n:*" always returns the newest message, even when it's older than n.
    uids = [uid for uid in map(int, data[0].split()) if uid > last_uid]

    for uid in uids:
        status, data = imap.uid("FETCH", str(uid), FETCH)
        item = next((item for item in data if isinstance(item, tuple)), None)
        if status == "OK" and item is not None:
            log_timing(item[0], item[1])
            if parsed := parse_message(item[1]):
                messages.put(("mail", *parsed))
        last_uid = uid
    return last_uid


def _watch(address, password, messages, last_uid, on_connected):
    with imaplib.IMAP4_SSL(HOST, timeout=SOCKET_TIMEOUT) as imap:
        imap.login(address, password)
        if last_uid is None:
            last_uid = _next_uid(imap) - 1
        on_connected()

        while True:
            started = time.monotonic()
            has_new_mail = _next_uid(imap) - 1 > last_uid
            elapsed = time.monotonic() - started
            if elapsed > SLOW_CHECK_SECONDS:
                log.warning("mail %s: check took %.1fs", address, elapsed)
            if has_new_mail:
                last_uid = _fetch_new(imap, last_uid, messages)
            yield last_uid
            time.sleep(POLL_SECONDS)


def run(address, password, messages):
    """Watch forever, reconnecting with backoff. Mail missed while offline is caught up on."""
    backoff = 1
    last_uid = None

    def connected():
        nonlocal backoff
        log.info("mail %s: connected", address)
        backoff = 1

    while True:
        try:
            for last_uid in _watch(address, password, messages, last_uid, connected):
                pass
        except imaplib.IMAP4.error as error:
            log.warning("mail %s: IMAP error: %s", address, error)
        except (OSError, EOFError, imaplib.IMAP4.abort) as error:
            log.warning("mail %s: connection lost: %s", address, type(error).__name__)
        time.sleep(backoff)
        backoff = min(backoff * 2, MAX_BACKOFF)
