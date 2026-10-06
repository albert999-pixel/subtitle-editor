import unittest
from unittest.mock import MagicMock, patch
from ai_split import suggest_split, validate_boundaries, preview_response


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
            self.assertEqual(payload['word_count'], 3)
            self.assertEqual(payload['words'][-1], {'index': 3, 'text': 'Москвы'})
            client.chat.completions.create.assert_called_once()
            self.assertEqual(api.call_args.kwargs['max_retries'], 0)

    def test_truncated_response_is_visible_and_preserves_text(self):
        client = MagicMock()
        response = client.chat.completions.create.return_value
        response.choices[0].finish_reason = 'length'
        response.choices[0].message.content = '{"ends":['
        with patch('groq.Groq') as api:
            api.return_value.__enter__.return_value = client
            result = suggest_split(['полный текст'], 24, 'test-key')
            self.assertEqual(result['raw_response'], '{"ends":[')
            self.assertEqual(result['lines'], ['полный текст'])
            self.assertTrue(result['warnings'])
            client.chat.completions.create.assert_called_once()

    def test_bad_boundaries_are_visible_and_repaired_without_loss(self):
        import json
        words = ['один', 'два', 'три', 'четыре']
        for ends in ([], [1], [2, 2], [3, 2], [0, 3], [9], ['3'], [True, 3]):
            with self.subTest(ends=ends):
                raw = json.dumps({'ends': ends})
                result = preview_response(words, raw, 24, 'stop')
                self.assertEqual(result['raw_response'], raw)
                self.assertTrue(result['warnings'])
                self.assertEqual(' '.join(result['lines']), ' '.join(words))
                self.assertEqual(result['ends'], sorted(set(result['ends'])))
                self.assertEqual(result['ends'][-1], len(words))

    def test_plain_text_and_missing_field_are_shown_verbatim(self):
        for raw in ('<b>ответ модели</b>', '{"other":[]}', '{"ends":null}'):
            result = preview_response(['весь', 'текст'], raw, 24, 'stop')
            self.assertEqual(result['raw_response'], raw)
            self.assertEqual(result['lines'], ['весь текст'])
            self.assertTrue(result['warnings'])

    def test_valid_response_is_not_modified(self):
        result = preview_response(['один', 'два', 'три'], '{"ends":[1,3]}', 24, 'stop')
        self.assertEqual(result['lines'], ['один', 'два три'])
        self.assertEqual(result['warnings'], [])


if __name__ == '__main__':
    unittest.main()
