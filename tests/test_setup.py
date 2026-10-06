import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import config
from scripts import manage
from fastapi.testclient import TestClient
import app


class PackagingTests(unittest.TestCase):
    def test_environment_key_has_priority_and_is_not_persisted(self):
        old_path = config._env_path
        try:
            with tempfile.TemporaryDirectory() as directory:
                config.init(Path(directory) / '.env')
                config.save_config({'GROQ_API_KEY': 'file-secret'})
                with patch.dict(os.environ, {'GROQ_API_KEY': 'injected-secret'}):
                    self.assertEqual(config.load_config()['GROQ_API_KEY'], 'injected-secret')
                    with TestClient(app.app) as client:
                        response = client.get('/api/config')
                        self.assertTrue(response.json()['groq_key_set'])
                        self.assertNotIn('secret', response.text)
                        self.assertEqual(client.post('/api/config', json={'provider': 'groq'}).status_code, 200)
                        self.assertEqual(client.post('/api/config', json={'groq_api_key': ''}).status_code, 409)
                    self.assertNotIn('injected-secret', config._env_path.read_text())
                self.assertEqual(config.load_config()['GROQ_API_KEY'], 'file-secret')
        finally:
            config._env_path = old_path

    def test_incomplete_download_is_hidden_and_completed_download_is_available(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def fake_download(name, output_dir):
                for file in ('config.json', 'model.bin', 'tokenizer.json'):
                    (Path(output_dir) / file).write_text('{}')
            with patch.object(manage, 'ROOT', root), patch.object(manage, 'check_dependencies'), \
                 patch('faster_whisper.utils.download_model', side_effect=fake_download) as download, \
                 patch.object(app, 'MODELS_DIR', root / 'models'):
                staging = root / 'models/.downloads/tiny'
                staging.mkdir(parents=True)
                (staging / 'config.json').write_text('{}')
                self.assertEqual(app.list_local_models()['models'], [])
                manage.download('tiny')
                self.assertEqual(app.list_local_models()['models'], ['tiny'])
                manage.download('tiny')
                self.assertEqual(download.call_count, 1)

    def test_health_identifies_the_application(self):
        with TestClient(app.app) as client:
            self.assertEqual(client.get('/api/health').json()['application'], 'subtitle-editor')


if __name__ == '__main__':
    unittest.main()
