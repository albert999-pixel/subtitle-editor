import unittest
from unittest.mock import MagicMock, patch
from ai_split import suggest_split, validate_boundaries


class SplitTests(unittest.TestCase):
    def test_complete_partition_preserves_words(self):
        words = 'Нефть лошади сахар и автоспорт'.split()
        lines = validate_boundaries(words, [3, 5])
        self.assertEqual(' '.join(lines), ' '.join(words))
        self.assertTrue(all(len(line) <= 24 for line in lines))

    def test_rejects_missing_repeated_reordered_invalid_boundaries(self):
        for ends in ([], [1], [2, 2], [3, 2], [0, 3], [4], ['3'], [True, 3]):
            with self.subTest(ends=ends), self.assertRaises(ValueError):
                validate_boundaries(['а', 'б', 'в'], ends)

    def test_overlong_line_is_kept(self):
        self.assertEqual(validate_boundaries(['раз', 'два'], [2]), ['раз два'])

    def test_limits_and_overlong_word_do_not_call_groq(self):
        with patch('groq.Groq') as api:
            for texts in (['а ' * 601], []):
                with self.assertRaises(ValueError):
                    suggest_split(texts, 3, 'test-key')
            api.assert_not_called()

    def test_one_request_only_and_local_reconstruction(self):
        client = MagicMock()
        response = client.chat.completions.create.return_value
        response.choices[0].finish_reason = 'stop'
        response.choices[0].message.content = '{"ends":[2,3]}'
        with patch('groq.Groq') as api:
            api.return_value.__enter__.return_value = client
            result = suggest_split(['Иван из Москвы'], 3, 'test-key', [3])
            self.assertEqual(result['lines'], ['Иван из', 'Москвы'])
            self.assertEqual(result['overlong'], [{'index':1, 'length':7}, {'index':2, 'length':6}])
            import json
            payload = json.loads(client.chat.completions.create.call_args.kwargs['messages'][1]['content'])
            self.assertEqual(payload['max_chars'], 3)
            self.assertEqual(payload['previous_ends'], [3])
            client.chat.completions.create.assert_called_once()
            self.assertEqual(api.call_args.kwargs['max_retries'], 0)

    def test_truncated_response_is_rejected(self):
        client = MagicMock()
        client.chat.completions.create.return_value.choices[0].finish_reason = 'length'
        with patch('groq.Groq') as api:
            api.return_value.__enter__.return_value = client
            with self.assertRaisesRegex(ValueError, 'неполный'):
                suggest_split(['текст'], 24, 'test-key')


if __name__ == '__main__':
    unittest.main()
