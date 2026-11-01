import subprocess
import unittest
from unittest import mock

from linuxautofill.deliver import Deliverer


class DeliverLinkTest(unittest.TestCase):
    def setUp(self):
        self.deliverer = Deliverer(clear_after=60)

    def notify(self, url, sender, stdout=""):
        """Run the notification step and return the notify-send and Popen mocks."""
        result = subprocess.CompletedProcess([], 0, stdout=stdout)
        with (
            mock.patch("subprocess.run", return_value=result) as run,
            mock.patch("subprocess.Popen") as popen,
        ):
            self.deliverer._notify(url, "Verification link", f"From {sender}. Opens x.", "Open", self.deliverer._open)
        return run, popen

    def test_click_opens_the_link(self):
        _, popen = self.notify("https://a.example/v", "Acme", stdout="default\n")
        self.assertEqual(popen.call_args[0][0], ["xdg-open", "https://a.example/v"])

    def test_nothing_opens_without_a_click(self):
        _, popen = self.notify("https://a.example/v", "Acme", stdout="")
        popen.assert_not_called()

    def test_sender_markup_is_escaped(self):
        run, _ = self.notify("https://a.example/v", "<b>Evil</b>")
        self.assertIn("&lt;b&gt;Evil&lt;/b&gt;", run.call_args[0][0][-1])

    def test_only_web_links_are_accepted(self):
        with self.assertRaises(ValueError):
            self.deliverer.deliver_link("file:///etc/passwd", "Acme")

    def test_notification_names_the_domain(self):
        with mock.patch.object(self.deliverer, "_send", return_value=True) as send:
            self.deliverer.deliver_link("https://evil.example/verify?x=1", "Acme")
        self.assertIn("Opens evil.example.", send.call_args[0][2])

    def test_same_link_is_delivered_once(self):
        with (
            mock.patch.object(self.deliverer, "_copy"),
            mock.patch("threading.Thread"),
            mock.patch("threading.Timer"),
        ):
            self.assertTrue(self.deliverer.deliver_link("https://a.example/v", ""))
            self.assertFalse(self.deliverer.deliver_link("https://a.example/v", ""))


if __name__ == "__main__":
    unittest.main()
