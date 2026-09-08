"""Veo public API contract fixtures; no provider requests or credit consumption."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'plugins/sprite-motion-kit/skills/sprite-motion/scripts'
sys.path.insert(0, str(SCRIPTS))
import mxapi


class FakeVeoClient:
    credentials = SimpleNamespace(base_url='https://example.com', source='fixture')

    def __init__(self, response):
        self.response = response
        self.calls = []

    def request(self, path, **kwargs):
        self.calls.append((path, kwargs))
        return self.response


class VeoTest(unittest.TestCase):
    def test_first_image_payload_uses_exact_model_fields_and_no_paid_expansion(self):
        body = mxapi.build_payload('veo-3.1-fast', ' Walk in place. ', ['https://example.com/character.png'])
        self.assertEqual(body, {
            'model': 'veo31-fast', 'prompt': 'Walk in place.', 'aspectRatio': '16:9',
            'images': ['https://example.com/character.png'],
            'enableExtendImg': False, 'enableTranslation': False,
        })
        self.assertEqual(mxapi.build_payload('seedance-2.0-mini', 'Walk.')['ratio'], '1:1')

    def test_documented_text_and_explicit_endpoint_modes(self):
        self.assertEqual(mxapi.build_payload('veo-3.1-fast', 'Walk.')['images'], [])
        refs = ['https://example.com/first.png', 'https://example.com/last.png']
        body = mxapi.build_payload('veo-3.1-fast', 'Walk.', refs, first_last=True, ratio='9:16')
        self.assertEqual(body['images'], refs)
        self.assertEqual(body['aspectRatio'], '9:16')

    def test_unsupported_controls_stop_before_job_creation(self):
        ref = 'https://example.com/character.png'
        cases = [([], {'duration': d}) for d in (0, 4, 8, None, True) if d is not None]
        cases += [([], {'resolution': r}) for r in ('480p', '720p', '1080p', '4K', '')]
        cases += [([], {'ratio': r}) for r in ('1:1', 'adaptive', '4:3')]
        cases += [([ref, ref], {}), ([ref] * 3, {'first_last': True}),
                  ([ref], {'first_last': True}), ([], {'first_last': True}),
                  ([ref], {'reference_role': 'reference_image'})]
        with tempfile.TemporaryDirectory() as tmp:
            for index, (refs, options) in enumerate(cases):
                with self.subTest(refs=len(refs), options=options):
                    job = Path(tmp) / str(index)
                    with self.assertRaises(mxapi.ProviderError):
                        mxapi.prepare(job, 'veo-3.1-fast', 'Walk.', refs, **options)
                    self.assertFalse(job.exists())

    def test_cli_preparation_uses_veo_default_ratio_without_credentials_or_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            prompt = Path(tmp) / 'prompt.txt'
            prompt.write_text('Walk in place.', encoding='utf-8')
            job = Path(tmp) / 'veo'
            args = ['mxapi.py', 'prepare', '--model', 'veo-3.1-fast', '--prompt-file', str(prompt),
                    '--reference', 'https://example.com/character.png', '--job', str(job)]
            with patch.object(sys, 'argv', args), patch.object(mxapi, 'Client') as client, \
                    patch.object(mxapi, 'load_mxapi_credentials') as credentials, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(mxapi.main(), 0)
                client.assert_not_called()
                credentials.assert_not_called()
            body = json.loads((job / 'request.json').read_text(encoding='utf-8'))['body']
            self.assertEqual(body['aspectRatio'], '16:9')
            self.assertNotIn('duration', body)
            self.assertNotIn('resolution', body)

    def test_documented_submit_poll_result_cost_and_no_second_submit(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp) / 'veo'
            mxapi.prepare(job, 'veo-3.1-fast', 'Walk.', ['https://example.com/character.png'])
            packet, _ = mxapi.read_job(job)
            submit = FakeVeoClient({'code': 200, 'data': {'task_id': 'veo-task'}})
            self.assertEqual(mxapi.submit(job, submit)['state'], 'submitted')
            self.assertEqual(submit.calls, [('/api/v2/veo/generate', {'body': packet['body']})])
            with self.assertRaises(mxapi.ProviderError):
                mxapi.submit(job, submit)
            self.assertEqual(len(submit.calls), 1)
            poll = FakeVeoClient({'code': 200, 'data': {'task_id': 'veo-task', 'status': 'processing',
                                 'video_url': None, 'points_cost': 40, 'points_refunded': False}})
            self.assertEqual(mxapi.poll(job, poll)['state'], 'submitted')
            poll.response['data'].update(status='completed', video_url='https://example.com/video.mp4')
            result = mxapi.poll(job, poll)
            self.assertEqual((result['state'], result['result_count'], result['points_cost']), ('succeeded', 1, 40))
            self.assertEqual(poll.calls, [('/api/v2/veo/task', {'query': {'task_id': 'veo-task'}})] * 2)
            self.assertEqual(mxapi.read_job(job)[1]['result_urls'], ['https://example.com/video.mp4'])
            poll.response['data'].update(status='failed', points_refunded=True)
            result = mxapi.poll(job, poll)
            self.assertEqual((result['state'], result['points_cost']), ('failed', 0))


if __name__ == '__main__':
    unittest.main()
