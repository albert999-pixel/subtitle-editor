import json
import unittest
from unittest.mock import MagicMock, patch
from ai_split import suggest_split, validate_boundaries, preview_response


class SplitTests(unittest.TestCase):
    def test_complete_partition_preserves_words(self):
        words = 'Нефть лошади сахар и автоспорт'.split()
        self.assertEqual(' '.join(validate_boundaries(words, [3, 5])), ' '.join(words))

    def test_internal_boundaries_must_be_a_complete_partition(self):
        for ends in ([], [1], [2, 2], [3, 2], [0, 3], [4], ['3'], [True, 3]):
            with self.subTest(ends=ends), self.assertRaises(ValueError):
                validate_boundaries(['а', 'б', 'в'], ends)

    def test_limits_do_not_call_groq(self):
        with patch('groq.Groq') as api:
            for texts in (['а ' * 601], []):
                with self.assertRaises(ValueError):
                    suggest_split(texts, 3, 'test-key')
            api.assert_not_called()

    def test_one_request_with_readable_text_and_previous_phrases(self):
        client = MagicMock()
        response = client.chat.completions.create.return_value
        response.choices[0].finish_reason = 'stop'
        response.choices[0].message.content = '{"groups":["Иван","из Москвы"]}'
        with patch('groq.Groq') as api:
            api.return_value.__enter__.return_value = client
            result = suggest_split(['Иван из Москвы'], 3, 'test-key', [3])
            self.assertEqual(result['lines'], ['Иван', 'из Москвы'])
            self.assertEqual(result['ends'], [1, 3])
            self.assertEqual(result['overlong'], [{'index': 1, 'length': 4}, {'index': 2, 'length': 9}])
            payload = json.loads(client.chat.completions.create.call_args.kwargs['messages'][1]['content'])
            self.assertEqual(result['max_chars'], 3)
            self.assertEqual(payload['text'], 'Иван из Москвы')
            self.assertEqual(payload['previous_groups'], ['Иван из Москвы'])
            self.assertNotIn('words', payload)
            self.assertNotIn('max_chars', payload)
            client.chat.completions.create.assert_called_once()
            self.assertEqual(api.call_args.kwargs['max_retries'], 0)

    def test_provider_json_error_shows_available_generated_answer_without_retry(self):
        import httpx
        from groq import BadRequestError
        client = MagicMock()
        raw = '{"groups":["полный текст"]}'
        response = httpx.Response(400, request=httpx.Request('POST', 'https://api.groq.com'))
        client.chat.completions.create.side_effect = BadRequestError('validation failed',
            response=response, body={'error': {'code': 'json_validate_failed', 'failed_generation': raw}})
        with patch('groq.Groq') as api:
            api.return_value.__enter__.return_value = client
            result = suggest_split(['полный текст'], 24, 'test-key')
            self.assertEqual(result['raw_response'], raw)
            self.assertEqual(result['lines'], ['полный текст'])
            self.assertTrue(result['warnings'])
            client.chat.completions.create.assert_called_once()

    def test_invalid_old_proposal_does_not_block_regeneration(self):
        client = MagicMock()
        response = client.chat.completions.create.return_value
        response.choices[0].finish_reason = 'stop'
        response.choices[0].message.content = '{"groups":["текст"]}'
        with patch('groq.Groq') as api:
            api.return_value.__enter__.return_value = client
            result = suggest_split(['текст'], 24, 'test-key', [10, 20])
            self.assertEqual(result['lines'], ['текст'])
            payload = json.loads(client.chat.completions.create.call_args.kwargs['messages'][1]['content'])
            self.assertIsNone(payload['previous_groups'])

    def test_truncated_json_is_visible_and_preserves_text(self):
        result = preview_response(['полный', 'текст'], '{"groups":[', 24, 'length')
        self.assertEqual(result['raw_response'], '{"groups":[')
        self.assertEqual(result['lines'], ['полный текст'])
        self.assertTrue(result['warnings'])

    def test_omissions_insertions_changes_and_repetitions_never_lose_text(self):
        cases = [
            (['первый', 'середина', 'последний'], ['первый', 'последний']),
            (['привет', 'мир'], ['привет лишнее', 'мир']),
            (['Иван', 'из', 'Москвы.'], ['Игорь из', 'Москвы!']),
            (['раз', 'раз', 'два', 'раз'], ['раз раз', 'два раз']),
            (['раз', 'раз', 'два', 'раз'], ['два раз', 'раз раз']),
            (['начало', 'середина', 'конец'], ['середина']),
            (['весь', 'исходный', 'текст'], ['совсем чужой ответ']),
        ]
        for words, proposed in cases:
            with self.subTest(words=words, proposed=proposed):
                raw = json.dumps({'groups': proposed}, ensure_ascii=False)
                result = preview_response(words, raw, 24, 'stop')
                self.assertEqual(result['raw_response'], raw)
                self.assertEqual(' '.join(result['lines']).split(), words)
                self.assertEqual(result['ends'], sorted(set(result['ends'])))
                self.assertEqual(result['ends'][-1], len(words))
                if ' '.join(proposed).split() != words:
                    self.assertTrue(result['warnings'])

    def test_case_and_punctuation_changes_preserve_breaks_and_original_spelling(self):
        result = preview_response(['Иван', 'Москва!'], '{"groups":["иван","москва"]}', 24, 'stop')
        self.assertEqual(result['groups'], ['Иван', 'Москва!'])
        self.assertEqual(result['lines'], ['Иван Москва!'])
        self.assertEqual(result['ends'], [2])
        self.assertTrue(result['warnings'])

    def test_unknown_empty_or_malformed_response_is_shown_verbatim(self):
        for raw in ('<b>ответ модели</b>', '{"ends":[10,20]}', '{"groups":null}',
                    '{"groups":[]}', '{"groups":[null,12,""]}'):
            result = preview_response(['весь', 'текст'], raw, 24, 'stop')
            self.assertEqual(result['raw_response'], raw)
            self.assertEqual(result['lines'], ['весь текст'])
            self.assertTrue(result['warnings'])

    def test_model_breaks_are_not_moved_by_a_preposition_heuristic(self):
        raw = '{"groups":["мы были в","магазине"]}'
        result = preview_response(['мы', 'были', 'в', 'магазине'], raw, 4, 'stop')
        self.assertEqual(result['lines'], ['мы были в', 'магазине'])
        self.assertEqual(result['raw_response'], raw)
        self.assertEqual(result['warnings'], [])
        self.assertEqual(result['quality_warnings'][0]['index'], 1)
        self.assertEqual(len(result['overlong']), 2)

    def test_semantic_groups_survive_preview_unchanged(self):
        for text, lines in [
            ('здесь тестировали автоматизацию добычи', ['здесь тестировали', 'автоматизацию добычи']),
            ('сюда ещё можно переехать жить', ['сюда ещё можно', 'переехать жить']),
            ('Нет! Мы обсуждали ремонт оборудования.', ['Нет!', 'Мы обсуждали', 'ремонт оборудования.']),
        ]:
            result = preview_response(text.split(), json.dumps({'groups': lines}), 24, 'stop')
            self.assertEqual(result['lines'], lines)
            self.assertEqual(result['warnings'], [])

    def test_good_response_is_not_modified(self):
        result = preview_response(['один', 'два', 'три'], '{"groups":["один","два три"]}', 10, 'stop')
        self.assertEqual(result['lines'], ['один', 'два три'])
        self.assertEqual(result['warnings'], [])

    def test_character_limit_packs_whole_groups_without_splitting_dependencies(self):
        words = 'здесь тестировали автоматизацию добычи'.split()
        raw = '{"groups":["здесь тестировали","автоматизацию добычи"]}'
        short = preview_response(words, raw, 24, 'stop')
        wide = preview_response(words, raw, 60, 'stop')
        self.assertEqual(short['lines'], ['здесь тестировали', 'автоматизацию добычи'])
        self.assertEqual(wide['lines'], [' '.join(words)])
        too_small = preview_response(words, raw, 10, 'stop')
        self.assertEqual(too_small['lines'], short['lines'])
        self.assertEqual(len(too_small['overlong']), 2)
        self.assertEqual(short['raw_response'], wide['raw_response'])

    def test_sentence_boundary_is_not_merged_even_when_it_fits(self):
        raw = '{"groups":["Нет!","Мы пришли."]}'
        result = preview_response('Нет! Мы пришли.'.split(), raw, 99, 'stop')
        self.assertEqual(result['lines'], ['Нет!', 'Мы пришли.'])

    def test_group_variant_keeps_breaks_and_maps_warnings_to_packed_captions(self):
        text = 'Мы были в магазине'
        raw = json.dumps({'groups': ['Мы были в', 'магазине']})
        result = preview_response(text.split(), raw, 24, 'stop')
        self.assertEqual(result['groups'], ['Мы были в', 'магазине'])
        self.assertEqual(result['group_ends'], [3, 4])
        self.assertEqual(result['lines'], [text])
        self.assertEqual(result['ends'], [4])
        self.assertEqual(result['group_quality_warnings'][0]['index'], 1)
        self.assertEqual(result['quality_warnings'][0]['index'], 1)
        self.assertEqual(result['raw_response'], raw)

    def test_long_model_chunk_is_visible_and_can_be_applied_without_losing_words(self):
        text = 'сюда ещё можно переехать жить'
        raw = json.dumps({'groups': [text]}, ensure_ascii=False)
        result = preview_response(text.split(), raw, 24, 'stop')
        self.assertEqual(result['raw_response'], raw)
        self.assertEqual(result['groups'], [text])
        self.assertEqual(result['lines'], [text])
        self.assertEqual(result['ends'], [5])
        self.assertTrue(any('длиннее трёх слов: 1' in warning for warning in result['warnings']))

    def test_six_hundred_words_still_survive_an_incomplete_proposal(self):
        words = [f'слово{i}' for i in range(600)]
        raw = json.dumps({'groups': [' '.join(words[:3]), ' '.join(words[10:20])]})
        result = preview_response(words, raw, 24, 'stop')
        self.assertEqual(' '.join(result['lines']).split(), words)
        self.assertTrue(result['warnings'])


if __name__ == '__main__':
    unittest.main()
