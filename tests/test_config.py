import pathlib
import tempfile
import unittest

from linuxautofill import config


class LoadTest(unittest.TestCase):
    def load(self, text, mode=0o600):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "config.toml"
            path.write_text(text)
            path.chmod(mode)
            return config.load(path)

    def test_single_account_table(self):
        loaded = self.load('[gmail]\naddress = "a@gmail.com"\napp_password = "ab cd"\n')
        self.assertEqual(loaded.gmail_accounts, [("a@gmail.com", "abcd")])

    def test_multiple_accounts(self):
        loaded = self.load(
            '[[gmail]]\naddress = "a@gmail.com"\napp_password = "one"\n'
            '[[gmail]]\naddress = "b@gmail.com"\napp_password = "two"\n'
        )
        self.assertEqual(
            loaded.gmail_accounts, [("a@gmail.com", "one"), ("b@gmail.com", "two")]
        )

    def test_blank_address_is_ignored(self):
        loaded = self.load('[http]\ntoken = "t"\n[[gmail]]\naddress = ""\napp_password = ""\n')
        self.assertEqual(loaded.gmail_accounts, [])

    def test_missing_password_is_rejected(self):
        with self.assertRaisesRegex(config.ConfigError, "b@gmail.com"):
            self.load(
                '[[gmail]]\naddress = "a@gmail.com"\napp_password = "one"\n'
                '[[gmail]]\naddress = "b@gmail.com"\n'
            )

    def test_no_sources_is_rejected(self):
        with self.assertRaises(config.ConfigError):
            self.load("clear_after = 30\n")

    def test_readable_file_is_rejected(self):
        with self.assertRaisesRegex(config.ConfigError, "chmod 600"):
            self.load('[http]\ntoken = "t"\n', mode=0o644)


if __name__ == "__main__":
    unittest.main()
