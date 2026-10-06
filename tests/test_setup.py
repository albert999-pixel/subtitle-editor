import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import config
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

    def test_health_identifies_the_application(self):
        with TestClient(app.app) as client:
            self.assertEqual(client.get('/api/health').json()['application'], 'subtitle-editor')


if __name__ == '__main__':
    unittest.main()
