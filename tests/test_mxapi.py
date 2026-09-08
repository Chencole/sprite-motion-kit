import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'plugins/sprite-motion-kit/skills/sprite-motion/scripts'
sys.path.insert(0, str(SCRIPTS))
import mxapi


class FakeClient:
    credentials = SimpleNamespace(base_url='https://example.com', source='test')

    def __init__(self, response=None, failure=False):
        self.calls = []
        self.response = response or {'code': 0, 'data': {'task_id': 'task-one'}}
        self.failure = failure

    def request(self, path, **kwargs):
        self.calls.append((path, kwargs))
        if self.failure:
            raise mxapi.ProviderError('Connection failed')
        return self.response


class MxapiTest(unittest.TestCase):
    def test_https_download_works_with_desktop_fake_dns_not_private_targets(self):
        def result(address):
            return [(2, 1, 6, '', (address, 443))]
        with patch('socket.getaddrinfo', return_value=result('198.18.0.166')):
            mxapi.public_https('https://example.com/image.png')
            with self.assertRaises(mxapi.ProviderError):
                mxapi.public_https('https://198.18.0.166/image.png')
        for address in ['127.0.0.1', '192.168.1.1', '169.254.169.254']:
            with patch('socket.getaddrinfo', return_value=result(address)):
                with self.assertRaises(mxapi.ProviderError):
                    mxapi.public_https('https://example.com/image.png')

    def test_image_and_video_are_distinct(self):
        image = mxapi.build_payload('gpt-image-2', 'character', ['https://example.com/ref.png'])
        self.assertEqual(image['resolution'], '1K')
        self.assertEqual(image['reference_images'], ['https://example.com/ref.png'])
        video = mxapi.build_payload('seedance-2.0', 'walk', ['https://example.com/ref.png'], duration=4)
        self.assertEqual(video['content'][1]['role'], 'reference_image')
        self.assertEqual(video['content'][1]['image_url']['url'], 'https://example.com/ref.png')
        self.assertFalse(video['generate_audio'])
        self.assertEqual(video['resolution'], '480p')
        cheapest = mxapi.build_payload('seedance-1.0-fast', 'walk', ['https://example.com/ref.png'])
        self.assertIn('--rs 480p --dur 2', cheapest['content'][0]['text'])
        self.assertEqual(cheapest['content'][1]['role'], 'first_frame')

    def test_first_last_explicit_supported_route(self):
        refs = ['https://example.com/start.png', 'https://example.com/end.png']
        body = mxapi.build_payload('seedance-1.0-lite-i2v', 'walk', refs, first_last=True)
        self.assertEqual([x['role'] for x in body['content'][1:]], ['first_frame', 'last_frame'])
        for model, options in [('seedance-2.0', {'first_last': True}), ('seedance-1.0-lite-i2v', {})]:
            with self.assertRaises(mxapi.ProviderError):
                mxapi.build_payload(model, 'walk', refs, **options)

    def test_no_silent_reference_drop_or_parameter_clamping(self):
        for kw in [{'references': ['x', 'y']}, {'duration': 25}, {'resolution': '4K'}, {'duration': float('nan')}]:
            with self.assertRaises(mxapi.ProviderError):
                mxapi.build_payload('seedance-1.0-fast', 'walk', **kw)

    def test_numeric_and_nested_status(self):
        self.assertEqual(mxapi.status_of({'data': '{"task":{"status":3}}'}), 'succeeded')
        self.assertEqual(mxapi.status_of({'data': {'status': 4, 'video_url': 'https://example.com/preview.mp4'}}), 'failed')
        self.assertEqual(mxapi.status_of({'data': {'status': 'running'}}), 'submitted')
        self.assertEqual(mxapi.status_of({'status': 'failed', 'data': {'video_url': 'https://example.com/preview.mp4'}}), 'failed')
        self.assertEqual(mxapi.status_of({'data': {'video_url': 'https://example.com/done.mp4'}}), 'succeeded')
        self.assertEqual(mxapi.status_of({'data': {'output': [{'status': 4, 'video_url': 'https://example.com/failed.mp4'}]}}), 'failed')
        self.assertEqual(mxapi.task_id({'data': {'task_ids': ['', 'real-task']}}), 'real-task')

    def test_unverified_local_reference_transport_is_rejected_before_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp) / 'job'
            with self.assertRaises(mxapi.ProviderError):
                mxapi.prepare(job, 'seedance-2.0', 'walk', references=['local-character.png'])
            self.assertFalse(job.exists())

    def test_extract_results_not_prompt_or_reference_urls(self):
        result = mxapi.result_urls({'data': {'request': {'reference_images': ['https://example.com/input.png']},
            'content': [{'image_url': {'url': 'https://example.com/ref.png'}}],
            'result': {'videos': [{'url': 'https://example.com/output.mp4'}]}}})
        self.assertEqual(result, ['https://example.com/output.mp4'])

    def test_success_and_unknown_submission_are_never_repeated(self):
        with tempfile.TemporaryDirectory() as tmp:
            for unknown in [False, True]:
                job = Path(tmp) / str(unknown)
                mxapi.prepare(job, 'gpt-image-2', 'character')
                client = FakeClient(failure=unknown)
                if unknown:
                    with self.assertRaises(mxapi.ProviderError):
                        mxapi.submit(job, client)
                else:
                    mxapi.submit(job, client)
                with self.assertRaises(mxapi.ProviderError):
                    mxapi.submit(job, client)
                self.assertEqual(len(client.calls), 1)
                raw = (job / 'job.json').read_text()
                self.assertNotIn('Authorization', raw)

    def test_modified_preparation_never_submits(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp) / 'job'
            mxapi.prepare(job, 'seedance-2.0', 'walk')
            packet = json.loads((job / 'request.json').read_text())
            packet['body']['duration'] = 15
            (job / 'request.json').write_text(json.dumps(packet))
            client = FakeClient()
            with self.assertRaises(mxapi.ProviderError):
                mxapi.submit(job, client)
            self.assertEqual(client.calls, [])

    def test_poll_preserves_failure_with_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp) / 'job'
            mxapi.prepare(job, 'seedance-2.0', 'walk')
            mxapi.submit(job, FakeClient())
            client = FakeClient({'data': {'status': 4, 'video_url': 'https://example.com/preview.mp4', 'points_cost': 7, 'points_refunded': True}})
            self.assertEqual(mxapi.poll(job, client)['state'], 'failed')
            self.assertEqual(mxapi.read_job(job)[1]['points_cost'], 0)
            with self.assertRaises(mxapi.ProviderError):
                mxapi.download(job)

    def test_balance_uses_only_read_endpoint(self):
        client = mxapi.Client(SimpleNamespace(base_url='https://example.com', source='test'))
        with patch.object(client, 'request', return_value={'data': {'remaining_points': 123.5}}) as request:
            self.assertEqual(client.check()['remaining_points'], 123.5)
            request.assert_called_once_with('/api/v2/points/balance')

    def test_http_error_never_exposes_response_body(self):
        import io
        import urllib.error
        creds = SimpleNamespace(base_url='https://example.com', headers=lambda: {'Authorization': 'Bearer secret'})
        opener = SimpleNamespace(open=lambda *a, **kw: (_ for _ in ()).throw(urllib.error.HTTPError('https://example.com', 401, 'secret', {}, io.BytesIO(b'secret'))))
        with patch('urllib.request.build_opener', return_value=opener):
            with self.assertRaises(mxapi.ProviderError) as error:
                mxapi.Client(creds).check()
            self.assertNotIn('secret', str(error.exception))
            self.assertIn('401', str(error.exception))


if __name__ == '__main__':
    unittest.main()
