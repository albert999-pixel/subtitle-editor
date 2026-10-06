import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
import app as application
import config
from transcription import transcribe_with_groq


class ImmediateThread:
    def __init__(self, target, **kwargs):
        self.target = target
    def start(self):
        self.target()


class GroqTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.old_config_path = config._env_path
        config.init(self.root / '.env')
        self.old_status = application.transcription_status
        application.transcription_status = {'status': 'idle'}
        self.patches = [patch.object(application, 'TEMP_DIR', self.root),
                        patch.object(application, 'Thread', ImmediateThread)]
        for p in self.patches:
            p.start()
        self.client = TestClient(application.app)

    def tearDown(self):
        self.client.close()
        for p in self.patches:
            p.stop()
        config._env_path = self.old_config_path
        application.transcription_status = self.old_status
        self.directory.cleanup()

    def test_key_is_not_returned_and_unrelated_updates_preserve_it(self):
        r = self.client.post('/api/config', json={'groq_api_key': 'test-secret', 'provider': 'groq'})
        self.assertEqual(r.status_code, 200)
        r = self.client.get('/api/config')
        self.assertTrue(r.json()['groq_key_set'])
        self.assertNotIn('test-secret', r.text)
        self.client.post('/api/config', json={'groq_model': 'whisper-large-v3'})
        self.assertEqual(config.load_config()['GROQ_API_KEY'], 'test-secret')
        self.client.post('/api/config', json={'groq_api_key': ''})
        self.assertFalse(self.client.get('/api/config').json()['groq_key_set'])

    def test_missing_key_and_invalid_provider_fail_before_processing(self):
        for data in ({'provider':'groq'}, {'provider':'other'}):
            r = self.client.post('/api/transcribe', files={'file':('test.wav', b'audio')}, data=data)
            self.assertEqual(r.status_code, 400)
            self.assertEqual(application.transcription_status['status'], 'idle')

    def test_cloud_dispatch_returns_words_and_playable_audio(self):
        self.client.post('/api/config', json={'groq_api_key':'test-secret'})
        words = [{'word':'привет', 'start':0, 'end':1}]
        with patch.object(application, 'transcribe_with_groq', return_value=words) as cloud, \
             patch.object(application, 'transcribe_with_local_model') as local:
            r = self.client.post('/api/transcribe', files={'file':('test.wav', b'audio')},
                                 data={'provider':'groq', 'groq_model':'whisper-large-v3'})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(cloud.call_args.args[1:], ('test-secret', 'whisper-large-v3'))
            local.assert_not_called()
        self.assertEqual(self.client.get('/api/status').json()['words'], words)
        self.assertEqual(self.client.get('/api/audio').content, b'audio')

    def test_local_mode_does_not_call_cloud(self):
        with patch.object(application, 'transcribe_with_local_model', return_value=[]) as local, \
             patch.object(application, 'transcribe_with_groq') as cloud:
            self.client.post('/api/transcribe', files={'file':('test.wav', b'audio')})
            local.assert_called_once()
            cloud.assert_not_called()

    def test_validation_does_not_overwrite_settings(self):
        for payload in ({'provider':'invalid'}, {'groq_model':'invalid'}, {'groq_api_key':'a\nb'}):
            self.assertEqual(self.client.post('/api/config', json=payload).status_code, 400)
        self.assertEqual(config.load_config(), config.DEFAULTS)

    def test_sdk_request_uses_word_timestamps(self):
        audio = self.root / 'sample.wav'
        audio.write_bytes(b'test')
        client = MagicMock()
        client.audio.transcriptions.create.return_value.model_dump.return_value = {
            'words':[{'word':' привет ', 'start':0, 'end':1}]}
        with patch('groq.Groq') as constructor:
            constructor.return_value.__enter__.return_value = client
            self.assertEqual(transcribe_with_groq(audio, 'test-secret', 'whisper-large-v3-turbo'),
                             [{'word':'привет', 'start':0., 'end':1.}])
            kwargs = client.audio.transcriptions.create.call_args.kwargs
            self.assertEqual(kwargs['timestamp_granularities'], ['word'])
            self.assertEqual(kwargs['response_format'], 'verbose_json')

    def test_rate_limit_message_does_not_echo_provider_response(self):
        import httpx
        from groq import RateLimitError
        audio = self.root / 'sample.wav'
        audio.write_bytes(b'test')
        response = httpx.Response(429, request=httpx.Request('POST', 'https://api.groq.com'))
        client = MagicMock()
        client.audio.transcriptions.create.side_effect = RateLimitError('test-secret', response=response, body=None)
        with patch('groq.Groq') as constructor:
            constructor.return_value.__enter__.return_value = client
            with self.assertRaisesRegex(RuntimeError, 'лимит запросов') as error:
                transcribe_with_groq(audio, 'test-secret', 'whisper-large-v3')
            self.assertNotIn('test-secret', str(error.exception))


if __name__ == '__main__':
    unittest.main()
