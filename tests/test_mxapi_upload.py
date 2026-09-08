"""Same-account original-art publication fixtures; no network or paid generation."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

SCRIPTS = Path(__file__).resolve().parents[1] / 'plugins/sprite-motion-kit/skills/sprite-motion/scripts'
sys.path.insert(0, str(SCRIPTS))
import mxapi
import motion
import veo_workflow
import test_veo_workflow as workflow_fixture


class UploadReferenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.image = self.root / 'original.png'
        Image.new('RGBA', (24, 32), (30, 60, 180, 255)).save(self.image)
        self.raw = self.image.read_bytes()
        self.job = self.root / 'upload'
        self.credentials = SimpleNamespace(base_url='https://example.com', source='fixture',
                                           headers=lambda: {'Authorization': 'Bearer fixture-secret',
                                                            'Content-Type': 'application/json'})
        self.client = mxapi.Client(self.credentials)

    def response(self, **changes):
        data = {'url': '/tmp/uploads/original.png', 'filename': 'original.png',
                'size': len(self.raw), 'type': 'image/png'}
        data.update(changes)
        return {'code': 200, 'message': 'success', 'data': data}

    def upload(self):
        with patch.object(self.client, 'request', return_value=self.response()) as request, \
                patch.object(mxapi, '_download_reference', return_value=self.raw) as download:
            result = mxapi.upload_reference(self.image, self.job, self.client)
        return result, request, download

    def test_upload_posts_exact_multipart_and_hashes_original_bytes(self):
        calls = []
        class Response(io.BytesIO):
            def geturl(self):
                return 'https://example.com/tmp/uploads/original.png'
        def open_request(request, **kwargs):
            calls.append(request)
            return Response(json.dumps(self.response()).encode() if len(calls) == 1 else self.raw)
        with patch.object(mxapi.urllib.request, 'build_opener', return_value=SimpleNamespace(open=open_request)), \
                patch.object(mxapi, 'public_https'):
            result = mxapi.upload_reference(self.image, self.job, self.client)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].full_url, 'https://example.com/api/v2/upload/temp-image')
        self.assertEqual(calls[0].method, 'POST')
        self.assertEqual(calls[0].get_header('Authorization'), 'Bearer fixture-secret')
        self.assertIn('multipart/form-data; boundary=', calls[0].get_header('Content-type'))
        self.assertIn(b'name="image"; filename="reference.png"', calls[0].data)
        self.assertIn(self.raw, calls[0].data)
        self.assertIsNone(calls[1].get_header('Authorization'))
        self.assertEqual(result['state'], 'verified')
        self.assertFalse(result['generation_submitted'])
        self.assertEqual(result['source_sha256'], hashlib.sha256(self.raw).hexdigest())
        packet, state, local = mxapi.read_uploaded_reference(self.job)
        self.assertEqual(packet['kind'], 'reference_upload')
        self.assertEqual(local.read_bytes(), self.raw)
        self.assertEqual(self.image.read_bytes(), self.raw)
        self.assertNotIn('fixture-secret', (self.job / 'job.json').read_text())
        with self.assertRaises(mxapi.ProviderError):
            mxapi.submit(self.job, self.client)

    def test_cross_origin_and_unsafe_results_are_rejected(self):
        for value in ['https://other.example/image.png', '//other.example/image.png',
                      'http://example.com/image.png', 'https://user:pass@example.com/x',
                      'https://example.com:444/x', '/x#fragment', '/x\nHeader', '/\\other.example/x']:
            with self.subTest(value=value), self.assertRaises(mxapi.ProviderError):
                mxapi.same_origin_reference('https://example.com', value)
        self.assertEqual(mxapi.same_origin_reference('https://example.com', '/tmp/uploads/x.png'),
                         'https://example.com/tmp/uploads/x.png')

    def test_redirect_cannot_move_uploaded_reference_to_another_origin(self):
        handler = mxapi.ReferenceRedirect('https://example.com')
        with self.assertRaises(mxapi.ProviderError):
            handler.redirect_request(None, None, 302, '', {}, 'https://other.example/image.png')

    def test_download_mismatch_never_creates_verified_receipt(self):
        with patch.object(self.client, 'request', return_value=self.response()), \
                patch.object(mxapi, '_download_reference', return_value=b'changed bytes'):
            with self.assertRaisesRegex(mxapi.ProviderError, 'source SHA256'):
                mxapi.upload_reference(self.image, self.job, self.client)
        with self.assertRaises(mxapi.ProviderError):
            mxapi.read_uploaded_reference(self.job)

    def test_bad_provider_metadata_is_rejected_before_download(self):
        for field, value in [('size', 1), ('type', 'text/html'), ('url', 'https://other.example/x')]:
            with self.subTest(field=field), \
                    patch.object(self.client, 'request', return_value=self.response(**{field: value})), \
                    patch.object(mxapi, '_download_reference') as download:
                with self.assertRaises(mxapi.ProviderError):
                    mxapi.upload_reference(self.image, self.root / field, self.client)
                download.assert_not_called()

    def test_invalid_and_oversize_sources_never_upload(self):
        invalid = self.root / 'invalid.png'
        invalid.write_bytes(b'not an image')
        large = self.root / 'large.png'
        with large.open('wb') as stream:
            stream.truncate(mxapi.REFERENCE_MAX_BYTES + 1)
        with patch.object(self.client, 'request') as request:
            for source in [invalid, large]:
                with self.assertRaises(mxapi.ProviderError):
                    mxapi.upload_reference(source, self.job, self.client)
            request.assert_not_called()
        self.assertFalse(self.job.exists())

    def test_receipt_url_and_local_pixels_cannot_change(self):
        self.upload()
        state = motion.read(self.job / 'job.json')
        changed = dict(state, result_urls=['https://example.com/other.png'])
        motion.write(self.job / 'job.json', changed)
        with self.assertRaisesRegex(mxapi.ProviderError, 'SHA256 changed'):
            mxapi.read_uploaded_reference(self.job)
        motion.write(self.job / 'job.json', state)
        Path(state['local_results'][0]).write_bytes(b'changed original')
        with self.assertRaisesRegex(mxapi.ProviderError, 'SHA256 changed'):
            mxapi.read_uploaded_reference(self.job)

    def test_existing_upload_job_never_posts_again(self):
        self.upload()
        with patch.object(self.client, 'request') as request:
            with self.assertRaises(FileExistsError):
                mxapi.upload_reference(self.image, self.job, self.client)
            request.assert_not_called()

    def test_workflow_cannot_submit_to_a_different_provider(self):
        mxapi.prepare(self.job, 'gpt-image-2', 'Prepare an action-specific still',
                      ['https://example.com/tmp/uploads/original.png'])
        packet, state = mxapi.read_job(self.job)
        for workflow in [{'identity_source': {'provider_origin': 'https://original.example'}},
                         {'identity_provider_origin': 'https://original.example'}]:
            packet['workflow'] = workflow
            state['request_sha256'] = mxapi.digest(packet)
            motion.write(self.job / 'request.json', packet)
            motion.write(self.job / 'job.json', state)
            with patch.object(self.client, 'request') as request:
                with self.assertRaisesRegex(mxapi.ProviderError, 'provider origin'):
                    mxapi.submit(self.job, self.client)
                request.assert_not_called()
            self.assertFalse((self.job / 'submit.lock').exists())

    def test_cli_upload_dispatches_without_generation(self):
        argv = ['mxapi.py', '--mypixelflow-root', 'fixture-project', '--node', 'fixture-node',
                'upload-reference', '--image', str(self.image), '--job', str(self.job)]
        with patch.object(sys, 'argv', argv), \
                patch.object(mxapi, 'load_mxapi_credentials', return_value=self.credentials), \
                patch.object(mxapi.Client, 'request', return_value=self.response()) as request, \
                patch.object(mxapi, '_download_reference', return_value=self.raw), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(mxapi.main(), 0)
        self.assertEqual(request.call_args.args[0], '/api/v2/upload/temp-image')

    def test_original_game_image_upload_can_prepare_still_without_generated_identity(self):
        fixture = workflow_fixture.VeoWorkflowTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        original = fixture.character.read_bytes()
        response = self.response(size=len(original))
        with patch.object(self.client, 'request', return_value=response), \
                patch.object(mxapi, '_download_reference', return_value=original):
            mxapi.upload_reference(fixture.character, self.job, self.client)
        design = fixture.design('walk')
        path = fixture.write_design(design)
        still = self.root / 'still'
        result = veo_workflow.prepare_still(path, fixture.batch, 'knight', 'walk', self.job, still)
        self.assertFalse(result['generation_submitted'])
        packet, _ = mxapi.read_job(still)
        self.assertEqual(packet['body']['reference_images'], ['https://example.com/tmp/uploads/original.png'])
        self.assertEqual(packet['workflow']['identity_source']['kind'], 'reference_upload')
        self.assertEqual(packet['workflow']['identity_source']['character_sha256'], hashlib.sha256(original).hexdigest())
        self.assertEqual(fixture.character.read_bytes(), original)
        direct_video = self.root / 'existing-image-video'
        with patch.object(mxapi, 'prepare', wraps=mxapi.prepare) as prepare:
            direct = veo_workflow.prepare_video(path, fixture.batch, 'knight', 'walk', None, direct_video,
                                               existing_image_job=self.job)
        self.assertEqual(prepare.call_count, 1)
        self.assertEqual(prepare.call_args.args[1], 'veo-3.1-fast')
        self.assertEqual(direct['source_mode'], 'existing_image')
        self.assertFalse(direct['generation_submitted'])
        self.assertEqual(mxapi.read_job(direct_video)[0]['workflow']['identity_source']['kind'], 'reference_upload')


if __name__ == '__main__':
    unittest.main()
