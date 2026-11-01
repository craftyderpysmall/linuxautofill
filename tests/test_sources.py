import datetime
import json
import queue
import threading
import unittest
import urllib.error
import urllib.request
from email.message import EmailMessage

from linuxautofill import http_source, imap_source
from linuxautofill.detect import find_link

NOW = datetime.datetime(2026, 10, 31, 12, 0, tzinfo=datetime.timezone.utc)


def build_email(age_minutes=1, html=None):
    message = EmailMessage()
    message["From"] = "Acme Security <no-reply@acme.example>"
    message["Subject"] = "Your sign-in code"
    sent = NOW - datetime.timedelta(minutes=age_minutes)
    message["Date"] = sent.strftime("%a, %d %b %Y %H:%M:%S +0000")
    if html is None:
        message.set_content("Use 482913 to sign in.")
    else:
        message.set_content(html, subtype="html")
    return message.as_bytes()


class ParseMessageTest(unittest.TestCase):
    def test_plain_text(self):
        sender, text, _ = imap_source.parse_message(build_email(), now=NOW)
        self.assertEqual(sender, "Acme Security")
        self.assertIn("Your sign-in code", text)
        self.assertIn("482913", text)

    def test_html_is_stripped(self):
        markup = "<html><head><style>.a{color:#123456}</style></head><body><p>482913</p></body></html>"
        _, text, _ = imap_source.parse_message(build_email(html=markup), now=NOW)
        self.assertIn("482913", text)
        self.assertNotIn("123456", text)

    def test_button_link_is_found(self):
        markup = '<p>Please confirm</p><a href="https://t.example/x?a=1&amp;b=2"><span>Verify My Email</span></a>'
        _, _, links = imap_source.parse_message(build_email(html=markup), now=NOW)
        self.assertEqual(links[0].url, "https://t.example/x?a=1&b=2")
        self.assertEqual(links[0].label, "Verify My Email")

    def test_image_button_label_comes_from_alt_text(self):
        markup = '<a href="https://t.example/x"><img alt="Confirm email" src="b.png"></a>'
        _, _, links = imap_source.parse_message(build_email(html=markup), now=NOW)
        self.assertEqual(links[0].label, "Confirm email")

    def test_html_with_a_bare_url_and_no_anchors(self):
        # Workday sends this. Gmail's web page makes the URL clickable, but the email doesn't.
        url = "https://wd1.myworkdaysite.com/recruiting/acme/EXTERNAL/activate/token123/?redirect=%2Fjob"
        markup = (
            "<html><head><title>x</title></head><body><table><tr><td>"
            "Click this link to confirm your email address and complete setup for your candidate\r\n"
            f"      account<br>{url}<br>The link will expire after 24 hours."
            "</td></tr></table></body></html>"
        )
        _, text, links = imap_source.parse_message(build_email(html=markup), now=NOW)
        self.assertEqual(find_link(links, text), url)

    def test_line_breaks_separate_words(self):
        _, text, _ = imap_source.parse_message(
            build_email(html="<p>Your code:<br>482913<br/>Thanks</p>"), now=NOW
        )
        self.assertIn("code:\n482913\nThanks", text)

    def test_plain_email_links_are_found(self):
        message = EmailMessage()
        message.set_content("Click this link to confirm\nhttps://a.example/activate/x.\nBye")
        _, _, links = imap_source.parse_message(message.as_bytes(), now=NOW)
        self.assertEqual(links[0].url, "https://a.example/activate/x")

    def test_old_mail_is_skipped(self):
        self.assertIsNone(imap_source.parse_message(build_email(age_minutes=11), now=NOW))


class LogTimingTest(unittest.TestCase):
    def test_logs_each_leg_without_content(self):
        metadata = b'1 (UID 5 INTERNALDATE "31-Oct-2026 12:00:12 +0000" BODY[]<0> {1}'
        message = EmailMessage()
        message["Date"] = "Sat, 31 Oct 2026 12:00:00 +0000"
        message.set_content("Your code is 482913")
        with self.assertLogs(imap_source.log, "INFO") as logs:
            imap_source.log_timing(metadata, message.as_bytes())
        self.assertIn("sender to Gmail 12s", logs.output[0])
        self.assertNotIn("482913", logs.output[0])

    def test_missing_internal_date_logs_nothing(self):
        with self.assertNoLogs(imap_source.log):
            imap_source.log_timing(b"1 (UID 5", b"")


class HttpSourceTest(unittest.TestCase):
    def setUp(self):
        self.messages = queue.Queue()
        self.server = http_source.make_server("127.0.0.1", 0, "secret", self.messages)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def post(self, body, token="secret", path="/message", content_type="text/plain"):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.server.server_port}{path}",
            data=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": content_type},
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code

    def test_plain_body(self):
        self.assertEqual(self.post(b"Your code is 482913"), 204)
        self.assertEqual(self.messages.get_nowait(), ("sms", "", "Your code is 482913", []))

    def test_json_body(self):
        body = json.dumps({"text": "Your code is 482913", "sender": "Acme"}).encode()
        self.assertEqual(self.post(body, content_type="application/json"), 204)
        self.assertEqual(self.messages.get_nowait(), ("sms", "Acme", "Your code is 482913", []))

    def test_rejected_requests_queue_nothing(self):
        self.assertEqual(self.post(b"hi", token="wrong"), 401)
        self.assertEqual(self.post(b"hi", path="/other"), 404)
        self.assertEqual(self.post(b"x" * (http_source.MAX_BODY + 1)), 413)
        self.assertEqual(self.post(b"not json", content_type="application/json"), 400)
        self.assertEqual(self.post(b"[1]", content_type="application/json"), 400)
        self.assertTrue(self.messages.empty())


if __name__ == "__main__":
    unittest.main()
