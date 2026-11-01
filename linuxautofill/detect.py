"""Find a verification code or link in a message. Pure text handling, no I/O."""

import re
from typing import NamedTuple
from urllib.parse import urlsplit

DEFAULT_KEYWORDS = (
    "codes?",
    "otp",
    "passcode",
    "password",
    "pin",
    "verification",
    "verify",
    "one[- ]time",
    "2fa",
    "mfa",
    "two[- ]factor",
    "two[- ]step",
    "2[- ]step",
    "authentication",
    "authenticate",
    "log[- ]?in",
    "sign[- ]?in",
    "confirm",
    "confirmation",
    "token",
)

# A candidate further than this from a keyword is unrelated to it.
MAX_GAP = 60
# Added to the gap when a sentence ends between the keyword and the candidate.
SENTENCE_PENALTY = 40
# Two candidates this close to the same distance are too close to call.
AMBIGUOUS_MARGIN = 10

VALID_CODE = re.compile(r"[A-Za-z0-9-]{4,12}")

_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"

# Text that looks like a code but isn't. Blanked out before searching.
_NOISE = re.compile(
    "|".join(
        (
            r"\bhttps?://\S+",
            r"\bwww\.\S+",
            r"\b\S+\.(?:com|net|org|io|co|me|ly)/\S*",
            r"\S+@\S+\.\S+",
            # Money.
            r"[$€£¥]\s?\d[\d,.]*",
            r"\b\d[\d,.]*\s?(?:usd|eur|gbp|dollars?|euros?|pounds?)\b",
            # Dates and times.
            r"\b\d{4}-\d{1,2}-\d{1,2}\b",
            r"\b\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\b",
            rf"\b{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b",
            rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}\s+\d{{4}}\b",
            r"\b\d{1,2}:\d{2}(?::\d{2})?\b",
            # Durations, such as "10MIN".
            r"\b\d+\s*(?:minutes?|mins?|seconds?|secs?|hours?|hrs?|days?)\b",
            # Phone numbers and short-code opt-outs.
            r"\+\d[\d ().-]{6,}\d",
            r"\(?\b\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b",
            r"\b\d{3}-\d{4}\b",
            r"\b(?:stop|help|reply|text)\s+\S+\s+to\s+\d{3,6}\b",
            # Card and account tails.
            r"\b(?:ending(?:\s+in)?|last\s+4(?:\s+digits)?(?:\s+of)?)\s+\d{4}\b",
            # Street addresses in email footers.
            r"\b\d{1,6}\s+(?:[A-Z][a-z]+\s+){1,3}"
            r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Way|Pkwy|Parkway)\b",
            # Labelled numbers.
            r"\b(?:order|invoice|tracking|account|acct|reference|ref|booking|ticket|case|"
            r"customer|member|policy|claim|transaction|txn|receipt|shipment|flight|gate|room)"
            r"\s*(?:number|no\.?|num|id|#)?(?:\s*(?:is|was))?[\s#:]*[A-Za-z0-9-]*\d[A-Za-z0-9-]*",
            # Kinds of "code" that aren't verification codes.
            r"\b(?:zip|postal|area|country|error|status|product|sort|source|qr|bar|dress)\s+codes?\b",
            r"\bpostcodes?\b",
            r"\bbarcodes?\b",
        )
    ),
    re.IGNORECASE,
)

_PROMO = re.compile(r"\d+%\s*off\b|\bpromo|\bcoupon|\bdiscount|\bvoucher|\bsale\b", re.IGNORECASE)

_CANDIDATE = re.compile(
    r"""
    (?<![\w.,/:\#$-]) (?<!\d[ -])
    (?:
        (?P<prefixed> [A-Z]{1,4}-\d{4,8} )
      | (?P<split> \d{3}[ -]\d{3} | \d{4}[ -]\d{4} )
      | (?P<digits> \d{4,8} )
      | (?P<mixed> (?=[A-Za-z0-9]*[A-Za-z])(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{4,10} )
    )
    (?![\w%-] | [.,]\d | /\d | [ ]\d)
    """,
    re.VERBOSE,
)

# "code is", "OTP:", and the like. What follows is a code, whatever it looks like.
_EXPLICIT = re.compile(
    r"\b(?i:codes?|otp|passcode|password|pin|token)\b"
    r"(?:\s+(?i:is|are)\s*:?|\s*[:=])"
    r"[\s\"'“‘*`(\[<]*"
)
_LETTERS = re.compile(r"[A-Z]{4,10}\b")
_NOT_LETTER_CODES = frozenset(
    "ABOUT BELOW CANNOT CORRECT EXPIRED INCORRECT INVALID ONLY REQUIRED SENT VALID WRONG".split()
)

_YEAR = re.compile(r"(?:19|20)\d\d")

_URL = re.compile(r"https?://[^\s<>\"'\])]+", re.IGNORECASE)
# How much text before a link counts as describing it.
LINK_CONTEXT = 120
_LINK_ACTION = re.compile(
    r"\b(?:verify|verification|confirm|confirmation|activate|activation|validate)\b", re.IGNORECASE
)
_URL_ACTION = re.compile(r"verif|confirm|activat|validat", re.IGNORECASE)
_LINK_NOISE = re.compile(
    r"unsubscribe|opt[- ]out|preferences|privacy|terms|policy|help|support|faq|contact|report|"
    r"settings|not you|wasn.t me|didn.t|cancel|deny|reject|resend|learn more|manage",
    re.IGNORECASE,
)
_GENERIC_LABEL = re.compile(r"(?:click |tap )?(?:here|this link|the link|link|open)\.?", re.IGNORECASE)


class Link(NamedTuple):
    url: str
    label: str
    context: str


def plain_links(text):
    """Return the bare URLs in text, with the text leading up to each."""
    links = []
    for match in _URL.finditer(text):
        url = match.group().rstrip(".,;:!?")
        links.append(Link(url, "", text[max(0, match.start() - LINK_CONTEXT) : match.start()]))
    return links


def _is_labelled_action(link):
    return bool(_LINK_ACTION.search(link.label)) and not _LINK_NOISE.search(link.label)


def _is_described_action(link, parts, text):
    if link.label and not _URL.match(link.label) and not _GENERIC_LABEL.fullmatch(link.label):
        return False
    location = f"{parts.hostname}{parts.path}"
    if _LINK_NOISE.search(location):
        return False
    if _URL_ACTION.search(location) and _LINK_ACTION.search(text):
        return True
    return bool(_LINK_ACTION.search(link.context)) and not _LINK_NOISE.search(link.context)


def find_link(links, text):
    """Return the link that verifies an account, or None if there isn't a clear one.

    A button labelled like "Verify My Email" wins. Otherwise the first link whose address
    or preceding words say it verifies something is used. Only web links can be returned.
    """
    described = None
    for link in links:
        try:
            parts = urlsplit(link.url)
        except ValueError:
            continue
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
            continue
        if _is_labelled_action(link):
            return link.url
        if described is None and _is_described_action(link, parts, text):
            described = link.url
    return described


def _blank(match):
    return " " * len(match.group())


def _normalise(match):
    return re.sub(r"[ -]", "", match.group()) if match["split"] else match.group()


def _explicit_code(text):
    for phrase in _EXPLICIT.finditer(text):
        if match := _CANDIDATE.match(text, phrase.end()):
            return _normalise(match)
        if match := _LETTERS.match(text, phrase.end()):
            if match.group() not in _NOT_LETTER_CODES:
                return match.group()
    return None


def _is_plausible(match):
    """Check a candidate that has no explicit phrase vouching for it."""
    if match["digits"]:
        return not _YEAR.fullmatch(match["digits"])
    if match["mixed"]:
        # Lowercase mixed words are usually names, like "sha256" or "iphone15".
        return match["mixed"] == match["mixed"].upper()
    return True


def _gap(text, match, keyword):
    if keyword.end() <= match.start():
        between = text[keyword.end() : match.start()]
    else:
        between = text[match.end() : keyword.start()]
    ends_sentence = re.search(r"[.!?](?:\s|$)", between)
    return len(between) + (SENTENCE_PENALTY if ends_sentence else 0)


def _nearest_code(text, keywords):
    scored = {}
    for match in _CANDIDATE.finditer(text):
        if _is_plausible(match):
            gap = min(_gap(text, match, keyword) for keyword in keywords)
            code = _normalise(match)
            scored[code] = min(gap, scored.get(code, gap))

    ranked = sorted(scored.items(), key=lambda item: item[1])
    if not ranked or ranked[0][1] > MAX_GAP:
        return None
    if len(ranked) > 1 and ranked[1][1] - ranked[0][1] < AMBIGUOUS_MARGIN:
        return None
    return ranked[0][0]


def find_code(text, keywords=DEFAULT_KEYWORDS):
    """Return the verification code in text, or None if there isn't a clear one.

    A false positive overwrites the clipboard, so ambiguous text returns None.
    """
    # Email layouts pad text with whitespace, which shouldn't count as distance.
    collapsed = re.sub(r"\s*\n\s*", "\n", text)
    cleaned = re.sub(r"[^\S\n]+", " ", _NOISE.sub(_blank, collapsed))
    pattern = re.compile(r"\b(?:" + "|".join(keywords) + r")\b", re.IGNORECASE)
    found = list(pattern.finditer(cleaned))
    if not found:
        return None

    code = _explicit_code(cleaned) or _nearest_code(cleaned, found)
    if code is None or not VALID_CODE.fullmatch(code):
        return None
    if _PROMO.search(text) and not code.isdigit():
        return None
    return code
