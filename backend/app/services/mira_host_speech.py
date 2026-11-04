"""Albanian speech hints; source titles, identifiers and write arguments stay intact."""
import re

LETTERS = dict(zip("ABCÇDEËFGHIJKLMNOPQRSTUVXYZ", (
    "a", "bë", "cë", "çë", "dë", "e", "ë", "fë", "gë", "hë", "i", "jë", "kë", "lë",
    "më", "në", "o", "pë", "që", "rë", "së", "të", "u", "vë", "xë", "y", "zë")))
LETTERS["W"] = "dubël vë"
COMMON_CODES = {"FG", "GA", "KA", "BZ", "PX", "PDF", "AM", "PM", "WFE",
                "API", "UI", "UX", "HTML", "CSS", "SQL", "CSV", "JSON", "XML", "URL", "HTTP", "HTTPS"}
CODE = re.compile(r"\b[A-ZÇË]{2,6}\b")
# Addresses, paths, file names and versions are identifiers, not prose to rewrite.
IDENTIFIER = re.compile(r"https?://[^\s]+|www\.[^\s]+|[\w.+-]+@[\w.-]+\.[\w-]+|"
                        r"(?<!\w)(?:[A-Za-z]:[\\/]|\.{0,2}[\\/])[\w./\\-]+|"
                        r"\b[\w.-]+/(?:[\w.-]+/)*[\w.-]+\.[A-Za-z]{1,5}\b|"
                        r"\b[\w-]+\.(?:pdf|docx?|xlsx?|csv|json|xml|html?|js|ts|py|png|jpe?g|zip)\b|"
                        r"\bv?\d+(?:\.\d+){1,}\b(?![\d.]|\s*%)", re.IGNORECASE)
PERCENT = re.compile(r"(?<![\w.])(?P<number>\d+(?:[.,]\d+)?)\s*%")


def spell_code(code: str) -> str:
    return " ".join(LETTERS.get(letter, letter) for letter in code)


def speech_text(text: str, codes=()) -> str:
    known = COMMON_CODES | set(codes)
    def prose(value):
        value = CODE.sub(lambda match: spell_code(match[0]) if match[0] in known else match[0], value)
        return PERCENT.sub(lambda match: re.sub(r"[.,]", " presje ", match["number"]) + " për qind", value)
    parts, start = [], 0
    for match in IDENTIFIER.finditer(text):
        parts.extend((prose(text[start:match.start()]), match[0]))
        start = match.end()
    parts.append(prose(text[start:]))
    return "".join(parts)
