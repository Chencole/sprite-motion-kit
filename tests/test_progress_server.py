"""Loopback progress projection and media boundaries, with synthetic local evidence."""
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'plugins/sprite-motion-kit/skills/sprite-motion/scripts'
sys.path.insert(0, str(SCRIPTS))
import progress_server as progress


class ProgressServerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.evidence = progress.Evidence([self.root], [], [])

    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding='utf-8')

    def test_known_job_projection_hides_requests_urls_and_credentials(self):
        job = self.root / 'walk'
        self.write(job / 'request.json', {
            'kind': 'video', 'model': 'veo-3.1-fast',
            'body': {'prompt': 'PRIVATE_PROMPT', 'images': ['https://example.com/a?signature=PRIVATE_URL']},
            'workflow': {'phase': 'action_video', 'coverage_binding': {'character': 'knight', 'action': 'walk'}}})
        self.write(job / 'job.json', {'state': 'submitted', 'external_job_id': 'task-fixture',
                                      'Authorization': 'Bearer PRIVATE_KEY',
                                      'result_urls': ['https://example.com/a?signature=PRIVATE_URL']})
        self.evidence.scan()
        result = self.evidence.snapshot
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['stages'][3]['state'], 'waiting')
        text = json.dumps(result)
        for secret in ['PRIVATE_PROMPT', 'PRIVATE_URL', 'PRIVATE_KEY', 'https://example.com']:
            self.assertNotIn(secret, text)

    def test_missing_roots_and_partial_json_remain_visible_without_false_completion(self):
        evidence = progress.Evidence([self.root / 'missing'], [self.root / 'scope.json'], [])
        evidence.scan()
        self.assertTrue(all(not source['exists'] for source in evidence.snapshot['sources']))
        self.assertEqual(evidence.snapshot['items'], [])
        (self.root / 'scope.json').write_text('{unfinished', encoding='utf-8')
        evidence.scan()
        self.assertTrue(evidence.snapshot['warnings'])
        self.assertEqual(evidence.snapshot['items'], [])

    def test_only_registered_local_media_can_resolve(self):
        media = self.root / 'frame.png'
        media.write_bytes(b'synthetic media bytes')
        secret = self.root / 'request.json'
        secret.write_text('private fixture', encoding='utf-8')
        self.assertEqual(self.evidence.local(str(media), secret), media)
        for value in [str(secret), 'https://example.com/frame.png', '//server/share/frame.png',
                      '../outside.png', 'data:image/png;base64,AAA']:
            with self.subTest(value=value):
                self.assertIsNone(self.evidence.local(value, secret))

    def test_scan_skips_secret_and_database_directories(self):
        for folder in ['secrets', 'database', 'config', '.git']:
            self.write(self.root / folder / 'job.json', {'state': 'succeeded'})
        self.evidence.scan()
        self.assertEqual(self.evidence.snapshot['items'], [])

    def test_http_origin_raw_files_and_byte_ranges(self):
        media = self.root / 'video.mp4'
        media.write_bytes(b'0123456789')
        token = 'a' * 32
        self.evidence.files[token] = media
        server = progress.ThreadingHTTPServer(('127.0.0.1', 0), progress.Handler)
        server.daemon_threads = True
        server.evidence = self.evidence
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def close():
            server.shutdown()
            server.server_close()
            thread.join(2)
        self.addCleanup(close)
        def request(path, headers=None):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
            try:
                connection.request('GET', path, headers=headers or {})
                response = connection.getresponse()
                return response.status, dict(response.getheaders()), response.read()
            finally:
                connection.close()
        code, headers, body = request('/media/' + token, {'Range': 'bytes=2-5'})
        self.assertEqual((code, body), (206, b'2345'))
        self.assertEqual(headers['Content-Range'], 'bytes 2-5/10')
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(request('/media/' + token, {'Range': 'bytes=20-30'})[0], 416)
        self.assertEqual(request('/api/progress', {'Origin': 'https://other.example'})[0], 403)
        self.assertEqual(request('/api/progress', {'Host': 'other.example'})[0], 403)
        self.assertEqual(request('/request.json')[0], 404)
        self.assertEqual(request('/media/../../request.json')[0], 404)


if __name__ == '__main__':
    unittest.main()
