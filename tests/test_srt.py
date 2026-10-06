import random
import re
import unittest
from html import unescape

from srt import build_srt_content


def source(text):
    return [{"word": word, "start": i, "end": i + .8}
            for i, word in enumerate(text.split())]


def milliseconds(value):
    h, m, s, ms = map(int, re.split(r"[:,]", value))
    if m >= 60 or s >= 60 or ms >= 1000:
        raise AssertionError("Invalid SRT timestamp")
    return ((h * 60 + m) * 60 + s) * 1000 + ms


class ExportTests(unittest.TestCase):
    def export(self, texts, words):
        content, count = build_srt_content(
            [{"text": text} for text in texts], words)
        expected = [" ".join(text.splitlines()).strip() for text in texts if text.strip()]
        blocks = content.split("\n\n") if content else []
        self.assertEqual(count, len(expected))
        self.assertEqual(len(blocks), len(expected))
        previous_end = 0
        intervals = []
        for number, (block, text) in enumerate(zip(blocks, expected), 1):
            index, timing, rendered = block.split("\n")
            self.assertEqual(index, str(number))
            self.assertEqual(unescape(re.sub(r"<[^>]*>", "", rendered)), text)
            start, end = map(milliseconds, timing.split(" --> "))
            self.assertGreaterEqual(start, previous_end)
            self.assertGreaterEqual(end - start, 500)
            previous_end = end
            intervals.append((start, end))
        return intervals

    def test_deleted_repeated_word_uses_context(self):
        intervals = self.export(["первый", "да второй"], source("да первый да второй"))
        self.assertEqual(intervals, [(1000, 1800), (2000, 3800)])

    def test_fully_rewritten_word_and_caption_are_preserved(self):
        self.assertEqual(self.export(["Нурлан"], source("Нурлат")), [(0, 800)])
        self.export(["совсем другая", "новая фраза"], source("исходный текст"))

    def test_insertions_at_start_middle_end(self):
        self.export(["новое", "привет вставка", "мир", "добавлено"], source("привет мир"))

    def test_split_merge_and_punctuation(self):
        self.assertEqual(self.export(["привет", "мир привет!"], source("привет, мир. привет!")),
                         [(0, 800), (1000, 2800)])

    def test_reordered_and_duplicated_rows_stay_in_editor_order(self):
        self.export(["третий", "первый", "первый", "второй"], source("первый второй третий"))

    def test_zero_duration_overlapping_and_backwards_source(self):
        self.export(["а", "б", "в"], [
            {"word": "а", "start": 1, "end": 1},
            {"word": "б", "start": .5, "end": 2},
            {"word": "в", "start": 1, "end": .9},
        ])

    def test_rounding_carries_to_next_minute_and_hour(self):
        for seconds, expected in ((59.9996, "00:01:00,000"), (3599.9996, "01:00:00,000")):
            content, _ = build_srt_content([{"text": "текст"}], [{"word":"текст", "start":seconds, "end":seconds+1}])
            self.assertIn(expected + " -->", content)

    def test_no_usable_timings_still_preserves_text(self):
        self.export(["первый", "второй"], [])
        self.export(["текст"], [{"word": "текст", "start": float("nan"), "end": 1}])

    def test_blank_rows_and_literal_markup(self):
        self.export(["", "  ", "a <b> &  b", "?"], source("a b"))

    def test_export_has_no_color_markup(self):
        text, count = build_srt_content([{"text": "раз два"}], source("раз два"))
        self.assertEqual(count, 1)
        self.assertNotIn("<font", text)

    def test_recognizer_entry_with_multiple_words(self):
        self.export(["два", "слова"], [{"word": "два слова", "start": 1, "end": 2}])

    def test_many_edits_never_lose_or_repeat_captions(self):
        rng = random.Random(42)
        original = "да один да два три да четыре".split()
        for _ in range(100):
            edited = original.copy()
            for _ in range(5):
                action = rng.choice(("delete", "insert", "replace"))
                i = rng.randrange(len(edited) + 1)
                if action == "insert":
                    edited.insert(i, rng.choice(("да", "новое", "?")))
                elif i < len(edited):
                    if action == "delete":
                        edited.pop(i)
                    else:
                        edited[i] = "исправлено"
            self.export(edited, source(" ".join(original)))


if __name__ == "__main__":
    unittest.main()
