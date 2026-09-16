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
    def test_fast_fixed_route_first_frame_payload_submit_then_poll(self):
        ref = 'https://example.com/character.png'
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp) / 'fast'
            mxapi.prepare(job, 'seedance-2.0-fast', ' Walk in place. ', [ref])
            packet, _ = mxapi.read_job(job)
            body = packet['body']
            self.assertEqual(body, {
                'content': [{'type': 'text', 'text': 'Walk in place.'},
                            {'type': 'image_url', 'image_url': {'url': ref}, 'role': 'first_frame'}],
                'resolution': '480p', 'ratio': '1:1', 'duration': 4, 'generate_audio': False,
            })
            self.assertEqual(packet['model'], 'seedance-2.0-fast')
            client = FakeClient()
            mxapi.submit(job, client)
            self.assertEqual(client.calls, [('/api/v2/video/seedance2-fast', {'body': body})])
            polling = FakeClient({'data': {'status': 'succeeded', 'video_url': 'https://example.com/fast.mp4'}})
            self.assertEqual(mxapi.poll(job, polling)['state'], 'succeeded')
            self.assertEqual(polling.calls, [('/api/v2/video/task', {'query': {'task_id': 'task-one'}})])
            with self.assertRaises(mxapi.ProviderError):
                mxapi.submit(job, client)
            self.assertEqual(len(client.calls), 1)

    def test_fast_reference_mode_is_explicit_and_preserves_every_image(self):
        refs = [f'https://example.com/reference-{index}.png' for index in range(9)]
        first = mxapi.build_payload('seedance-2.0-fast', 'Walk.', refs[:1], reference_role='first_frame')
        self.assertEqual(first['content'][1]['role'], 'first_frame')
        for count in (1, 2, 9):
            with self.subTest(count=count):
                body = mxapi.build_payload('seedance-2.0-fast', 'Walk.', refs[:count], reference_role='reference_image')
                self.assertEqual([image['role'] for image in body['content'][1:]], ['reference_image'] * count)
                self.assertEqual([image['image_url']['url'] for image in body['content'][1:]], refs[:count])
        self.assertEqual(mxapi.build_payload('seedance-2.0-fast', 'Walk.')['content'], [{'type': 'text', 'text': 'Walk.'}])

    def test_fast_supported_controls_remain_top_level(self):
        for resolution in ('480p', '720p'):
            for duration in (4, 15):
                with self.subTest(resolution=resolution, duration=duration):
                    body = mxapi.build_payload('seedance-2.0-fast', 'Walk.', resolution=resolution,
                                               duration=duration, ratio='16:9')
                    self.assertEqual((body['resolution'], body['duration'], body['ratio']), (resolution, duration, '16:9'))
                    self.assertEqual(body['content'][0]['text'], 'Walk.')
                    self.assertFalse(body['generate_audio'])
                    self.assertNotIn('model', body)

    def test_fast_invalid_controls_roles_and_inline_flags_stop_before_preparation(self):
        refs = ['https://example.com/character.png']
        cases = [(refs, 'Walk.', {'resolution': value}) for value in ('1080p', '4K')]
        cases += [(refs, 'Walk.', {'duration': value}) for value in (0, 3, 16, 4.5, True)]
        cases += [(refs, 'Walk.', {'ratio': value}) for value in ('3:2', '2:3', 'bad')]
        cases += [(refs, text, {}) for text in ('Walk. --dur 4', '--rs 480p walk', 'Walk. --ratio=16:9',
                                               'Walk.\n--dur=4', 'Walk.\t--rs=720p', 'Walk. --ratio')]
        cases += [(refs * 2, 'Walk.', {}), (refs * 2, 'Walk.', {'reference_role': 'first_frame'}),
                  (refs * 2, 'Walk.', {'first_last': True}),
                  (refs, 'Walk.', {'first_last': True, 'reference_role': 'reference_image'}),
                  (refs, 'Walk.', {'reference_role': 'last_frame'}),
                  ([], 'Walk.', {'reference_role': 'first_frame'}),
                  ([], 'Walk.', {'reference_role': 'reference_image'}),
                  (refs * 10, 'Walk.', {'reference_role': 'reference_image'}),
                  (['local-character.png'], 'Walk.', {})]
        with tempfile.TemporaryDirectory() as tmp, patch.object(mxapi, 'Client') as client:
            for index, (references, prompt, options) in enumerate(cases):
                with self.subTest(index=index):
                    job = Path(tmp) / str(index)
                    with self.assertRaises(mxapi.ProviderError):
                        mxapi.prepare(job, 'seedance-2.0-fast', prompt, references, **options)
                    self.assertFalse(job.exists())
            client.assert_not_called()

    def test_fast_cli_preparation_needs_no_credentials_or_network(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as tmp:
            prompt = Path(tmp) / 'prompt.txt'
            prompt.write_text('Walk in place.', encoding='utf-8')
            for role in (None, 'first_frame', 'reference_image'):
                job = Path(tmp) / str(role)
                argv = ['mxapi.py', 'prepare', '--model', 'seedance-2.0-fast', '--prompt-file', str(prompt),
                        '--reference', 'https://example.com/character.png', '--resolution', '720p',
                        '--ratio', '16:9', '--duration', '4', '--job', str(job)]
                if role is not None:
                    argv += ['--reference-role', role]
                with patch.object(sys, 'argv', argv), patch.object(mxapi, 'Client') as client, \
                        patch.object(mxapi, 'load_mxapi_credentials') as credentials, contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(mxapi.main(), 0)
                    client.assert_not_called()
                    credentials.assert_not_called()
                packet, state = mxapi.read_job(job)
                body = packet['body']
                self.assertEqual(body['content'][1]['role'], role or 'first_frame')
                self.assertEqual((body['resolution'], body['ratio'], body['duration']), ('720p', '16:9', 4))
                self.assertEqual(state['state'], 'prepared')

    def test_fast_unknown_submission_remains_locked_without_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp) / 'fast-unknown'
            mxapi.prepare(job, 'seedance-2.0-fast', 'Walk.', ['https://example.com/character.png'])
            client = FakeClient(failure=True)
            with self.assertRaises(mxapi.ProviderError):
                mxapi.submit(job, client)
            self.assertEqual(mxapi.read_job(job)[1]['state'], 'submission_unknown')
            with self.assertRaises(mxapi.ProviderError):
                mxapi.submit(job, client)
            self.assertEqual(len(client.calls), 1)

    def test_mini_fixed_route_and_smallest_defaults_submit_then_poll(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp) / 'mini'
            mxapi.prepare(job, 'seedance-2.0-mini', 'Walk in place.',
                          ['https://example.com/character.png'])
            packet, _ = mxapi.read_job(job)
            body = packet['body']
            self.assertEqual(body['resolution'], '480p')
            self.assertEqual(body['duration'], 4)
            self.assertEqual(body['content'][0], {'type': 'text', 'text': 'Walk in place.'})
            self.assertEqual(body['content'][1], {'type': 'image_url',
                             'image_url': {'url': 'https://example.com/character.png'}, 'role': 'first_frame'})
            self.assertNotIn('model', body)
            self.assertNotIn('watermark', body)  # Not a documented Mini field.
            self.assertEqual(set(body), {'content', 'ratio', 'resolution', 'duration', 'generate_audio'})
            self.assertFalse(body['generate_audio'])
            client = FakeClient()
            mxapi.submit(job, client)
            self.assertEqual(client.calls, [('/api/v2/video/seedance2-mini', {'body': body})])
            polling = FakeClient({'data': {'status': 'succeeded', 'video_url': 'https://example.com/video.mp4'}})
            self.assertEqual(mxapi.poll(job, polling)['state'], 'succeeded')
            self.assertEqual(polling.calls, [('/api/v2/video/task', {'query': {'task_id': 'task-one'}})])

    def test_mini_text_first_last_and_explicit_reference_roles(self):
        text_only = mxapi.build_payload('seedance-2.0-mini', 'Walk.')
        self.assertEqual(text_only['content'], [{'type': 'text', 'text': 'Walk.'}])
        refs = ['https://example.com/first.png', 'https://example.com/last.png']
        endpoints = mxapi.build_payload('seedance-2.0-mini', 'Walk.', refs, first_last=True,
                                       resolution='720p', duration=15, ratio='adaptive')
        self.assertEqual([x['role'] for x in endpoints['content'][1:]], ['first_frame', 'last_frame'])
        self.assertEqual([x['image_url']['url'] for x in endpoints['content'][1:]], refs)
        self.assertEqual((endpoints['resolution'], endpoints['duration'], endpoints['ratio']), ('720p', 15, 'adaptive'))
        for count in (1, 2):
            reference = mxapi.build_payload('seedance-2.0-mini', 'Walk.', refs[:count], reference_role='reference_image')
            self.assertEqual([x['role'] for x in reference['content'][1:]], ['reference_image'] * count)

    def test_mini_unsupported_sizes_durations_and_legacy_text_stop_before_job(self):
        invalid_options = ([{'resolution': size} for size in ('1080p', '4K', 'mini')]
                           + [{'duration': duration} for duration in (0, 3, 16, -1, 4.5, True)]
                           + [{'ratio': ratio} for ratio in ('3:2', '2:3')])
        with tempfile.TemporaryDirectory() as tmp:
            for index, options in enumerate(invalid_options):
                with self.subTest(options=options):
                    job = Path(tmp) / str(index)
                    with self.assertRaises(mxapi.ProviderError):
                        mxapi.prepare(job, 'seedance-2.0-mini', 'Walk.', **options)
                    self.assertFalse(job.exists())
        for text in ('Walk. --dur 4', '--rs 480p walk', 'Walk. --ratio=1:1'):
            with self.assertRaises(mxapi.ProviderError):
                mxapi.build_payload('seedance-2.0-mini', text)

    def test_mini_endpoint_roles_require_explicit_consistent_mode(self):
        refs = ['https://example.com/first.png', 'https://example.com/last.png']
        cases = [(refs, {}), (refs[:1], {'first_last': True}), ([], {'first_last': True}),
                 (refs, {'reference_role': 'first_frame'}), ([], {'reference_role': 'reference_image'}),
                 (refs, {'first_last': True, 'reference_role': 'reference_image'}),
                 (refs + refs[:1], {'reference_role': 'reference_image'})]
        for references, options in cases:
            with self.subTest(options=options, count=len(references)), self.assertRaises(mxapi.ProviderError):
                mxapi.build_payload('seedance-2.0-mini', 'Walk.', references, **options)
        # Explicit roles must not change the untouched standard adapter.
        with self.assertRaises(mxapi.ProviderError):
            mxapi.build_payload('seedance-2.0', 'Walk.', refs[:1], reference_role='first_frame')

    def test_mini_cli_preparation_preserves_model_and_role_selection(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as tmp:
            prompt, job = Path(tmp) / 'prompt.txt', Path(tmp) / 'job'
            prompt.write_text('Walk in place.', encoding='utf-8')
            argv = ['mxapi.py', 'prepare', '--model', 'seedance-2.0-mini', '--prompt-file', str(prompt),
                    '--reference', 'https://example.com/image.png', '--reference-role', 'reference_image', '--job', str(job)]
            with patch('sys.argv', argv), patch('mxapi.Client.request', side_effect=AssertionError('Prepare is local')):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(mxapi.main(), 0)
            packet, state = mxapi.read_job(job)
            self.assertEqual(packet['model'], 'seedance-2.0-mini')
            self.assertEqual(packet['body']['content'][1]['role'], 'reference_image')
            self.assertEqual((packet['body']['resolution'], packet['body']['duration']), ('480p', 4))
            self.assertEqual(state['state'], 'prepared')

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
