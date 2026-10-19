from app.services.note_markup import parse_marked_note_content
from app.services.task_marker_comment_title import update_comment_in_title


def test_new_comment_goes_after_headline_without_replacing_details():
    content = "RA/OH: 9 EVENTE ASISTENT\n\nQëllimi dhe hapat\n1. Hulumto"
    assert update_comment_in_title(content, None, "TEST") == "RA/OH: 9 EVENTE ASISTENT\nCOM: TEST\n\nQëllimi dhe hapat\n1. Hulumto"


def test_unchanged_old_comments_are_not_backfilled():
    content = "Old task\nDetails"
    assert update_comment_in_title(content, "Existing comment", "Existing comment") == content
    assert update_comment_in_title(content, None, None) == content


def test_comment_updates_and_removal_preserve_other_com_notes():
    content = "Task\nCOM: Old\n\nCOM: Separate manual note\nDetails"
    updated = update_comment_in_title(content, "Old", "New")
    assert updated == "Task\nCOM: New\n\nCOM: Separate manual note\nDetails"
    assert update_comment_in_title(updated, "New", None) == "Task\n\nCOM: Separate manual note\nDetails"
    assert update_comment_in_title(updated, None, "New") == updated


def test_long_comments_remain_one_line_and_windows_line_breaks_are_preserved():
    assert update_comment_in_title("Task\r\nDetails", None, "First\nSecond") == "Task\r\nCOM: First Second\r\nDetails"


def test_replacing_a_marked_comment_does_not_break_adjacent_formatting():
    content = "Task\n[[added]]COM: Old\nDetails[[/added]]"
    updated = update_comment_in_title(content, "Old", "New")
    parsed = parse_marked_note_content(updated)
    assert "COM: Old" not in parsed.text
    assert "Task\nCOM: New" in parsed.text
    assert any(parsed.text[start:end] == "Details" for start, end in parsed.added_ranges)
    standalone = "[[added]]Task[[/added]]\n[[added]]COM: Old[[/added]]\n[[done]]Finished[[/done]]"
    updated = update_comment_in_title(standalone, "Old", "New")
    assert updated == "[[added]]Task[[/added]]\nCOM: New\n[[done]]Finished[[/done]]"
