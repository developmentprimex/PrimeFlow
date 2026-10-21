"""Pilot safety: only match times to an unambiguous saved evidence quote."""
import unittest
from scripts.recording_alignment_pilot import action_times, normalized_word


def words(text):
    import re
    return [{'text': m.group(), 'char_start': m.start(), 'char_end': m.end(),
             'start': i * 0.5, 'end': i * 0.5 + 0.4, 'acoustic_score': 0.9}
            for i, m in enumerate(re.finditer(r'\S+', text))]


class AlignmentPilotTests(unittest.TestCase):
    def test_evidence_links_to_actual_word_times_preserving_albanian(self):
        text = 'Fillimi. Elsa do të përgatisë PDF.'
        action = {'evidence': 'Elsa do të përgatisë PDF', 'title': 'PDF'}
        result = action_times([action], text, words(text))[0]
        self.assertEqual((result['start'], result['end']), (0.5, 2.9))
        self.assertTrue(result['review_required'])

    def test_repeated_quote_has_no_guessed_time(self):
        text = 'Dërgo raportin. Dërgo raportin.'
        result = action_times([{'evidence': 'Dërgo raportin.'}], text, words(text))[0]
        self.assertIsNone(result['start'])

    def test_unmatched_quote_has_no_guessed_time(self):
        text = 'Dërgo raportin.'
        result = action_times([{'evidence': 'Bëj prezantimin.'}], text, words(text))[0]
        self.assertIsNone(result['start'])

    def test_unaligned_word_blocks_a_claim_of_precise_timing(self):
        text = 'Dërgo raportin.'
        timed = words(text)
        timed[1]['start'] = None
        result = action_times([{'evidence': text}], text, timed)[0]
        self.assertIsNone(result['start'])

    def test_acoustic_normalization_keeps_diacritics(self):
        self.assertEqual(normalized_word('PËRGATIT'), 'përgatit')
        self.assertEqual(normalized_word('M1'), 'mnjë')


if __name__ == '__main__':
    unittest.main()
