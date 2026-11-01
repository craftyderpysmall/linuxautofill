"""Run the service: sources feed a queue, and each message is checked for a code."""

import argparse
import logging
import pathlib
import queue
import subprocess
import sys
import threading

from . import config as config_module
from . import http_source, imap_source
from .deliver import Deliverer
from .detect import DEFAULT_KEYWORDS, find_code, find_link

log = logging.getLogger("linuxautofill")


def start_sources(config, messages):
    if config.http_token:
        server = http_source.make_server(
            config.http_host, config.http_port, config.http_token, messages
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        log.info("sms: listening on port %d", config.http_port)
    for address, password in config.gmail_accounts:
        threading.Thread(
            target=imap_source.run, args=(address, password, messages), daemon=True
        ).start()


def main():
    parser = argparse.ArgumentParser(prog="linuxautofill")
    parser.add_argument("--config", type=pathlib.Path, default=config_module.DEFAULT_PATH)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        config = config_module.load(args.config)
    except config_module.ConfigError as error:
        sys.exit(str(error))

    keywords = (*DEFAULT_KEYWORDS, *config.extra_keywords)
    deliverer = Deliverer(config.clear_after)
    messages = queue.Queue()
    start_sources(config, messages)

    # Only the source and outcome are logged, never a code, link or message text.
    while True:
        source, sender, text, links = messages.get()
        code = find_code(text, keywords)
        link = None if code else find_link(links, text)
        if code is None and link is None:
            log.info("%s: no code in %d character message", source, len(text))
            continue
        try:
            if code:
                delivered, kind = deliverer.deliver(code, sender), "code"
            else:
                delivered, kind = deliverer.deliver_link(link, sender), "link"
            log.info("%s: %s", source, f"{kind} delivered" if delivered else "duplicate skipped")
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            log.warning("%s: delivery failed: %s", source, type(error).__name__)


if __name__ == "__main__":
    main()
