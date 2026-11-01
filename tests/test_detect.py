import unittest

from linuxautofill.detect import Link, find_code, find_link, plain_links

MATCHES = [
    ("Your verification code is 482913", "482913"),
    ("G-482913 is your Google verification code.", "G-482913"),
    ("482913 is your Instagram code. Don't share it.", "482913"),
    ("Your OTP: 8841", "8841"),
    ("OTP is 482913. Valid for 10 minutes.", "482913"),
    ("Use 482913 to verify your account", "482913"),
    ("Your Uber code: 4821", "4821"),
    ("Your one-time passcode is 123 456", "123456"),
    ("Your login code is 123-456", "123456"),
    ("Your PIN is 7391", "7391"),
    ("2FA token: A1B2C3", "A1B2C3"),
    ("Your sign-in code is a1b2c3", "a1b2c3"),
    ("Your confirmation code is ABCDEF", "ABCDEF"),
    ("Your code is **482913**", "482913"),
    ('Your code is "482913"', "482913"),
    ("Your verification code:\n\n    482913\n\nIt expires soon.", "482913"),
    ("Enter this code to sign in\n\n482913", "482913"),
    ("Verify your account. Use 482913", "482913"),
    ("Your code is 482913. Your order 99123 shipped.", "482913"),
    ("Your code for order 99123 is 482913", "482913"),
    ("Code 482913 expires at 10:30 on 12/25/2026", "482913"),
    ("Your Acme code is 482913. Reply STOP to 55512 to opt out.", "482913"),
    ("Your code is 4829, valid for 1000 seconds", "4829"),
    ("Your code is 2026", "2026"),
    ("Your authentication code is 482913. Visit https://acme.com/a/778899", "482913"),
    ("Your code is 482913. Save 20% off today!", "482913"),
    ("TEILEN SIE IHREN CODE NICHT: 482913", "482913"),
    (
        "Verification code\n" + (" " * 30 + "\n") * 10 + "   496660   \n" + (" " * 30 + "\n") * 10
        + "This code expires in 15 minutes.\n"
        + "Enter this code to access ADP services.\n"
        + "The email is sent from an automated system so please do not reply. "
        + "fdd6782f-8b9d-4d30-a77a-14b2e5f24933\n"
        + "ADP and the ADP logo are trademarks of ADP, Inc.' ©2026 ADP, Inc.",
        "496660",
    ),
]

NO_MATCH = [
    "",
    "Hey, are we still on for 7pm?",
    "Call me at 555-1234 about the code review",
    "The meeting is in room 4821",
    "Your order 482913 has shipped",
    "Order #482913 confirmed. Total $1234.56",
    "Your order is confirmed! Thanks for buying 1000 widgets",
    "Your package will arrive on 2026-12-25",
    "Your zip code is 90210",
    "Area code 415 and 5551",
    "Error code 5001 occurred",
    "Use code SAVE20 for 20% off",
    "Promo code WINTER26 ends tonight",
    "Your code is expired",
    "Your code is invalid",
    "Your code is VALID",
    "We changed the password in 2026",
    "Your card ending in 4242 was used to sign in",
    "Log in by Jan 12, 2026",
    "Confirm your subscription\n\nAcme Inc, 1600 Main Street",
    "Verify your email. Your balance is now over 1234 points and we think you will enjoy it.",
    "Log in to see iphone15 deals",
    "Your code is on https://acme.com/verify/482913",
    "Your code is 1234 5678 9012 3456",
    "Valid login from 1234 and 5678",
    "Verify your email.\n" + " " * 200 + "\n\nYour balance is now over 1234 points and we think you will enjoy it.",
]


class FindCodeTest(unittest.TestCase):
    def test_finds_codes(self):
        for text, expected in MATCHES:
            with self.subTest(text=text):
                self.assertEqual(find_code(text), expected)

    def test_ignores_everything_else(self):
        for text in NO_MATCH:
            with self.subTest(text=text):
                self.assertIsNone(find_code(text))

    def test_custom_keywords(self):
        self.assertEqual(find_code("Tu clave es 482913", keywords=("clave",)), "482913")
        self.assertIsNone(find_code("Tu clave es 482913"))


REDDIT_TEXT = """Your email address was added to your Reddit account.
To verify your email address and secure your account, click the button below.
This link is only valid for 3 days and it can only be used once."""

REDDIT_LINKS = [
    Link("https://click.redditmail.com/a1", "Account Settings", "Expired link? No worries, visit your "),
    Link("https://click.redditmail.com/b2", "Verify My Email", "click the button below."),
    Link("https://click.redditmail.com/c3", "Account Security FAQs", "check out our "),
    Link("https://click.redditmail.com/d4", "contact us", " or "),
    Link("https://click.redditmail.com/e5", "let us know", "isn't your Reddit account, "),
]

WORKDAY_URL = (
    "https://dicks.wd1.myworkdayjobs.com/dsg/activate/i8ya1hxv0/?redirect=%2Fen-US%2Fdsg%2Fjob"
    "%2FRetail-Golf-Club-Tech_202641847%2Fapply"
)
WORKDAY_TEXT = (
    "Verify your candidate account\n"
    "Click this link to confirm your email address and complete setup for your candidate account\n"
    f"{WORKDAY_URL}\nThe link will expire after 24 hours.\n\n"
    "This email box is not monitored. Please do not reply to this message."
)


class FindLinkTest(unittest.TestCase):
    def test_button_is_picked_over_other_links(self):
        self.assertEqual(find_link(REDDIT_LINKS, REDDIT_TEXT), "https://click.redditmail.com/b2")

    def test_button_order_does_not_matter(self):
        links = [REDDIT_LINKS[1], *REDDIT_LINKS]
        self.assertEqual(find_link(reversed(links), REDDIT_TEXT), "https://click.redditmail.com/b2")

    def test_bare_url_with_verifying_path(self):
        self.assertEqual(find_link(plain_links(WORKDAY_TEXT), WORKDAY_TEXT), WORKDAY_URL)

    def test_link_whose_label_is_its_own_url(self):
        links = [Link(WORKDAY_URL, WORKDAY_URL, "")]
        self.assertEqual(find_link(links, WORKDAY_TEXT), WORKDAY_URL)

    def test_click_here_after_verifying_words(self):
        links = [Link("https://t.example/q9", "click here", "To verify your email, please ")]
        self.assertEqual(find_link(links, "To verify your email"), "https://t.example/q9")

    def test_tracking_url_after_verifying_words(self):
        text = "Open this to confirm your email:\nhttps://t.example/q9"
        self.assertEqual(find_link(plain_links(text), text), "https://t.example/q9")

    def test_ordinary_emails_have_no_link(self):
        cases = [
            ("Your order shipped", [Link("https://shop.example/track/1", "Track package", "")]),
            ("Big sale today", [Link("https://shop.example/sale", "Shop now", "")]),
            ("News", plain_links("Read more at https://news.example/story")),
            (
                "Confirm your preferences",
                [Link("https://news.example/unsubscribe", "Unsubscribe", "")],
            ),
            ("Please verify", [Link("https://acme.example/help", "Help center", "")]),
            ("Was this you?", [Link("https://acme.example/x", "This wasn't me, cancel confirmation", "")]),
            ("Please verify", plain_links("See https://acme.example/settings/verify")),
        ]
        for text, links in cases:
            with self.subTest(text=text):
                self.assertIsNone(find_link(links, text))

    def test_only_web_links_are_returned(self):
        for url in ("javascript:alert(1)", "file:///etc/passwd", "mailto:a@b.example", "ssh://h/x"):
            with self.subTest(url=url):
                self.assertIsNone(find_link([Link(url, "Verify My Email", "")], "verify"))


if __name__ == "__main__":
    unittest.main()
