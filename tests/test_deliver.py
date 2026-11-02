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
            mock.patch.object(self.deliverer, "_snapshot", return_value=None),
            mock.patch("threading.Thread"),
            mock.patch("threading.Timer"),
        ):
            self.assertTrue(self.deliverer.deliver_link("https://a.example/v", ""))
            self.assertFalse(self.deliverer.deliver_link("https://a.example/v", ""))


class FakeClipboard:
    """Stands in for subprocess.run, answering wl-copy and wl-paste."""

    def __init__(self, data=None, types=("text/plain",)):
        self.data = data
        self.types = list(types) if data is not None else []
        self.copied_type = None

    def __call__(self, command, input=None, **kwargs):
        if command[0] == "wl-copy":
            if "--clear" in command:
                self.data, self.types = None, []
            else:
                self.data = input
                self.copied_type = command[2] if "--type" in command else None
                self.types = [self.copied_type or "text/plain"]
            return subprocess.CompletedProcess(command, 0)
        if self.data is None:
            return subprocess.CompletedProcess(command, 1, stdout=b"")
        if "--list-types" in command:
            return subprocess.CompletedProcess(command, 0, stdout="\n".join(self.types))
        return subprocess.CompletedProcess(command, 0, stdout=self.data)


class RestoreClipboardTest(unittest.TestCase):
    def setUp(self):
        self.deliverer = Deliverer(clear_after=60)

    def run_with(self, clipboard, *steps):
        with (
            mock.patch("subprocess.run", clipboard),
            mock.patch("threading.Thread"),
            mock.patch("threading.Timer") as timer,
        ):
            for step in steps:
                step(timer)

    def code(self, value):
        return lambda timer: self.deliverer.deliver(value, "")

    def expire(self, value):
        return lambda timer: self.deliverer._restore_if_unchanged(value)

    def test_previous_clipboard_comes_back(self):
        clipboard = FakeClipboard(b"mine\n")
        self.run_with(clipboard, self.code("482913"), self.expire("482913"))
        self.assertEqual(clipboard.data, b"mine\n")

    def test_empty_clipboard_is_cleared(self):
        clipboard = FakeClipboard()
        self.run_with(clipboard, self.code("482913"), self.expire("482913"))
        self.assertIsNone(clipboard.data)

    def test_newer_copy_is_left_alone(self):
        clipboard = FakeClipboard(b"mine")

        def user_copies(timer):
            clipboard.data = b"newer"

        self.run_with(clipboard, self.code("482913"), user_copies, self.expire("482913"))
        self.assertEqual(clipboard.data, b"newer")

    def test_two_codes_restore_the_original(self):
        clipboard = FakeClipboard(b"mine")
        self.run_with(
            clipboard,
            self.code("482913"),
            self.code("771204"),
            self.expire("482913"),
            self.expire("771204"),
        )
        self.assertEqual(clipboard.data, b"mine")

    def test_second_code_cancels_the_first_timer(self):
        clipboard = FakeClipboard(b"mine")
        self.run_with(
            clipboard,
            self.code("482913"),
            self.code("771204"),
            lambda timer: timer.return_value.cancel.assert_called_once(),
        )

    def test_copy_between_codes_is_the_one_restored(self):
        clipboard = FakeClipboard(b"mine")

        def user_copies(timer):
            clipboard.data = b"newer"

        self.run_with(
            clipboard,
            self.code("482913"),
            user_copies,
            self.code("771204"),
            self.expire("771204"),
        )
        self.assertEqual(clipboard.data, b"newer")

    def test_images_keep_their_type(self):
        clipboard = FakeClipboard(b"\x89PNG", types=("text/html", "image/png"))
        self.run_with(clipboard, self.code("482913"), self.expire("482913"))
        self.assertEqual((clipboard.data, clipboard.copied_type), (b"\x89PNG", "image/png"))

    def test_password_manager_entries_are_not_restored(self):
        clipboard = FakeClipboard(b"hunter2", types=("text/plain", "x-kde-passwordManagerHint"))
        self.run_with(clipboard, self.code("482913"), self.expire("482913"))
        self.assertIsNone(clipboard.data)

    def test_delivery_survives_an_unreadable_clipboard(self):
        def broken(command, input=None, **kwargs):
            if command[0] == "wl-paste":
                raise subprocess.TimeoutExpired(command, 2)
            return subprocess.CompletedProcess(command, 0)

        with (
            mock.patch("subprocess.run", broken),
            mock.patch("threading.Thread"),
            mock.patch("threading.Timer"),
            self.assertLogs("linuxautofill.deliver", "WARNING"),
        ):
            self.assertTrue(self.deliverer.deliver("482913", ""))


if __name__ == "__main__":
    unittest.main()
