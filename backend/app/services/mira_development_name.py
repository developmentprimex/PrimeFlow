"""Display name and compatibility with historical Mira Zhvillim records."""

import re

NAME = "Mira Zhvillim"
MEETING_NAME = "Zhvillim"
COMMAND = "mira-zhvillim"
MEETING_NAME_PREFIX = re.compile(
    r"^(?:(?:(?:Mira[ \t]+)?AI[ \t_-]*Agent|Mira[ \t]+Zhvillim)\b|Zhvillim(?=\s+(?:\d|·)|$))",
    re.IGNORECASE,
)
DATE_LINE = re.compile(r"^E \w+, \d{1,2} \w+ \d{4}$", re.IGNORECASE)


def meeting_title(title: str) -> str:
    return MEETING_NAME_PREFIX.sub(MEETING_NAME, title, count=1)


def meeting_note_heading(content: str | None) -> str | None:
    if not content:
        return content
    heading, separator, body = content.partition("\n\n")
    first_line, newline, second_line = heading.partition("\n")
    if newline and DATE_LINE.fullmatch(first_line):
        heading = first_line + newline + meeting_title(second_line)
    else:
        heading = meeting_title(heading)
    return heading + separator + body
