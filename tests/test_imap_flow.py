"""Runs the real imaplib client against a small fake server, since Gmail needs credentials."""

import imaplib
import queue
import re
import socketserver
import threading
import unittest
from email.message import EmailMessage
from email.utils import formatdate
from unittest import mock

from linuxautofill import imap_source


def build_email():
    message = EmailMessage()
    message["From"] = "Acme <no-reply@acme.example>"
    message["Subject"] = "Your code"
    message["Date"] = formatdate()
    message.set_content("Your code is 482913")
    return message.as_bytes()


class FakeImap(socketserver.StreamRequestHandler):
    def send(self, line):
        self.wfile.write(line + b"\r\n")

    def handle(self):
        server = self.server
        self.send(b"* OK [CAPABILITY IMAP4rev1] ready")
        while line := self.rfile.readline():
            tag, command = line.strip().split(b" ", 1)
            upper = command.upper()
            if upper.startswith(b"CAPABILITY"):
                self.send(b"* CAPABILITY IMAP4rev1")
            elif upper.startswith(b"SELECT") or upper.startswith(b"EXAMINE"):
                server.commands.append(upper.split()[0])
                server.opens += 1
                # New mail shows up on the third check: login position, poll, poll.
                if server.opens == 3:
                    server.uids.append(6)
                self.send(b"* 1 EXISTS")
                self.send(b"* OK [UIDNEXT %d] next" % (server.uids[-1] + 1))
            elif upper.startswith(b"UID SEARCH"):
                first = int(re.search(rb"UID (\d+):", command)[1])
                uids = b" ".join(str(u).encode() for u in server.uids if u >= first)
                # Like a real server, "n:*" always includes the newest message.
                self.send(b"* SEARCH " + (uids or str(server.uids[-1]).encode()))
            elif upper.startswith(b"UID FETCH"):
                server.commands.append(command)
                body = build_email()
                self.send(b"* 1 FETCH (UID %d BODY[]<0> {%d}" % (server.uids[-1], len(body)))
                self.wfile.write(body + b")\r\n")
            elif upper.startswith(b"LOGOUT"):
                self.send(b"* BYE")
                self.send(tag + b" OK done")
                return
            self.send(tag + b" OK done")


class ImapFlowTest(unittest.TestCase):
    def setUp(self):
        socketserver.ThreadingTCPServer.allow_reuse_address = True
        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), FakeImap)
        self.server.daemon_threads = True
        self.server.uids = [5]
        self.server.opens = 0
        self.server.commands = []
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def test_new_mail_is_fetched_without_marking_it_read(self):
        port = self.server.server_address[1]
        connect = lambda host, timeout: imaplib.IMAP4("127.0.0.1", port, timeout=5)
        messages = queue.Queue()
        with (
            mock.patch.object(imap_source.imaplib, "IMAP4_SSL", connect),
            mock.patch.object(imap_source, "POLL_SECONDS", 0),
        ):
            watch = imap_source._watch("me", "pw", messages, None, lambda: None)
            self.assertEqual(next(watch), 5)
            self.assertTrue(messages.empty())
            self.assertEqual(next(watch), 6)
            self.assertEqual(next(watch), 6)
            watch.close()

        self.assertEqual(messages.get_nowait()[0:2], ("mail", "Acme"))
        self.assertTrue(messages.empty())
        self.assertNotIn(b"SELECT", self.server.commands)
        self.assertIn(b"EXAMINE", self.server.commands)
        self.assertTrue(any(b"BODY.PEEK[]" in c for c in self.server.commands))


if __name__ == "__main__":
    unittest.main()
