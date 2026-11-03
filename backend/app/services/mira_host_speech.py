"""Albanian speech hints; source titles, identifiers and write arguments stay intact."""
import re

LETTERS = dict(zip("ABCÇDEËFGHIJKLMNOPQRSTUVXYZ", (
    "a", "bë", "cë", "çë", "dë", "e", "ë", "fë", "gë", "hë", "i", "jë", "kë", "lë",
    "më", "në", "o", "pë", "që", "rë", "së", "të", "u", "vë", "xë", "y", "zë")))
LETTERS["W"] = "dubël vë"
COMMON_CODES = {"FG", "GA", "KA", "BZ", "PX", "PDF", "AM", "PM", "WFE"}
CODE = re.compile(r"\b[A-ZÇË]{2,6}\b")


def spell_code(code: str) -> str:
    return " ".join(LETTERS.get(letter, letter) for letter in code)


def speech_text(text: str, codes=()) -> str:
    known = COMMON_CODES | set(codes)
    return CODE.sub(lambda match: spell_code(match[0]) if match[0] in known else match[0], text)
