"""Rich note runs shared by reporting-point email and native exports."""
from __future__ import annotations

import html
from app.services.note_markup import parse_marked_note_content


def marked_note_runs(content: str | None) -> list[dict]:
    parsed = parse_marked_note_content(content)
    boundaries = sorted({0, len(parsed.text), *(pos for pair in (*parsed.done_ranges, *parsed.added_ranges) for pos in pair)})
    runs = []
    for start, end in zip(boundaries, boundaries[1:]):
        done = any(a <= start and end <= b for a, b in parsed.done_ranges)
        added = any(a <= start and end <= b for a, b in parsed.added_ranges)
        style = {"strike": True, "fill": "#DBEAFE", "color": "#064E3B"} if done and added else (
            {"fill": "#BFDBFE", "color": "#172554"} if added else
            {"strike": True, "fill": "#D1FAE5", "color": "#065F46"} if done else {})
        runs.append({"text": parsed.text[start:end], **style})
    return runs


def runs_html(runs: list[dict]) -> str:
    parts = []
    for run in runs:
        text = html.escape(run["text"]).replace("\n", "<br>")
        style = ";".join(value for value in (
            f"background:{run['fill']}" if run.get("fill") else "",
            f"color:{run['color']}" if run.get("color") else "",
            "text-decoration:line-through;text-decoration-thickness:2px" if run.get("strike") else "",
        ) if value)
        parts.append(f'<span style="{style}">{text}</span>' if style else text)
    return "".join(parts)


def wrapped_runs(runs: list[dict], lines: tuple[str, ...]) -> list[list[dict]]:
    """Apply marks to the existing measured wrapping, including skipped spaces."""
    expanded, column = [], 0
    for run in runs:
        chars = []
        for char in run["text"]:
            if char == "\t":
                spaces = 4 - column % 4
                chars.append(" " * spaces)
                column += spaces
            else:
                chars.append(char)
                column = 0 if char in "\r\n" else column + 1
        expanded.append({**run, "text": "".join(chars)})
    text = "".join(run["text"] for run in expanded)
    ranges, offset = [], 0
    for run in expanded:
        ranges.append((offset, offset + len(run["text"]), run))
        offset += len(run["text"])
    cursor, result = 0, []
    for line in lines:
        start = text.find(line, cursor) if line else cursor
        if start < 0:
            raise ValueError("Rich report text does not match wrapped lines")
        end = start + len(line)
        result.append([{**run, "text": text[max(start, a):min(end, b)]}
                       for a, b, run in ranges if b > start and a < end])
        cursor = end + (1 if not line and text[cursor:cursor + 1] == "\n" else 0)
    return result
