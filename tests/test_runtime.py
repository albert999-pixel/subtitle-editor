"""Verify the real portable launcher, HTTP export and server shutdown."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request


class RuntimeTests(unittest.TestCase):
    def test_launcher_serves_editor_and_preserves_export(self):
        root = Path(__file__).resolve().parent.parent
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        with tempfile.TemporaryDirectory() as directory:
            environment = os.environ.copy()
            environment.update(SUBTITLE_CONFIG_DIR=directory, SUBTITLE_TEMP_DIR=directory,
                               SUBTITLE_MODELS_DIR=str(Path(directory) / 'models'))
            with tempfile.TemporaryFile() as log:
                process = subprocess.Popen([sys.executable, str(root / 'scripts/manage.py'),
                                            'start', '--port', str(port), '--no-browser'],
                                           env=environment, stdout=log, stderr=log)
                try:
                    base = f'http://127.0.0.1:{port}'
                    for _ in range(100):
                        try:
                            with urllib.request.urlopen(base + '/api/health', timeout=1) as response:
                                self.assertEqual(json.load(response)['application'], 'subtitle-editor')
                            break
                        except OSError:
                            if process.poll() is not None:
                                log.seek(0)
                                self.fail(log.read().decode(errors='replace'))
                            time.sleep(0.2)
                    else:
                        self.fail('Server did not start within 20 seconds')
                    with urllib.request.urlopen(base) as response:
                        self.assertEqual(response.status, 200)
                    texts = ['первый титр', 'полностью переписанный титр', 'последний титр']
                    request = urllib.request.Request(base + '/api/build-srt',
                        data=json.dumps({'lines': [{'text': t} for t in texts], 'words': []}).encode(),
                        headers={'Content-Type': 'application/json'})
                    with urllib.request.urlopen(request) as response:
                        result = json.load(response)
                    self.assertEqual(result['count'], len(texts))
                    for text in texts:
                        self.assertEqual(result['srt'].count(text), 1)
                    positions = [result['srt'].index(t) for t in texts]
                    self.assertEqual(positions, sorted(positions))
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


if __name__ == '__main__':
    unittest.main()
