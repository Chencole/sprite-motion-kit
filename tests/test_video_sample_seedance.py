"""Offline Seedance binding and extraction fixtures, never provider generation."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

import test_video_sample as fixtures
import batch
import mxapi
import veo_workflow
import video_sample


class SeedanceSampleTests(unittest.TestCase):
    make_video = fixtures.VideoSampleTests.make_video
    make_bound_batch = fixtures.VideoSampleTests.make_bound_batch
    export = fixtures.VideoSampleTests.export
    report = fixtures.VideoSampleTests.report
    assert_atomic_failure = fixtures.VideoSampleTests.assert_atomic_failure

    @classmethod
    def setUpClass(cls):
        cls.ffmpeg = fixtures.find_ffmpeg()
        if not cls.ffmpeg:
            raise unittest.SkipTest('Set SPRITE_TEST_FFMPEG')

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / 'sample'

    def write(self, path, value):
        path.write_text(json.dumps(value), encoding='utf-8')

    def save_packet(self, packet=None):
        packet = self.packet if packet is None else packet
        state = {**self.state, 'request_sha256': mxapi.digest(packet)}
        self.write(self.job / 'request.json', packet)
        self.write(self.job / 'job.json', state)

    def make_job(self, *, action='walk', edge_indices=None, edited_prepared=False, background='green', source_keys=()):
        self.video = self.make_video(background=background, lossy=True, edge_indices=edge_indices)
        original = Image.new('RGBA', (32, 40))
        ImageDraw.Draw(original).rectangle((4, 3, 26, 36), fill=(35, 65, 200, 255))
        for index, mode in enumerate(source_keys):
            original.putpixel((6 + index, 6), veo_workflow.KEY_BACKGROUNDS[mode])
        self.original = self.root / 'original.png'
        self.prepared = self.root / 'prepared.png'
        original.save(self.original)
        prepared = Image.new('RGBA', (864, 496), veo_workflow.KEY_BACKGROUNDS[background])
        prepared.alpha_composite(original, (400, 220))
        if edited_prepared:
            prepared.putpixel((410, 230), (255, 0, 0, 255))
        prepared.save(self.prepared)
        original_sha = hashlib.sha256(self.original.read_bytes()).hexdigest()
        prepared_sha = hashlib.sha256(self.prepared.read_bytes()).hexdigest()
        self.batch = self.make_bound_batch(self.prepared, action)
        self.binding = batch.binding(self.batch, 'mage', action)
        self.upload = self.root / 'upload-fixture'
        self.upload.mkdir()
        for name in ('source.png', 'result.png'):
            (self.upload / name).write_bytes(self.prepared.read_bytes())
        url = 'https://example.test/tmp/uploads/prepared.png'
        self.upload_packet = {'kind': 'reference_upload', 'endpoint': '/api/v2/upload/temp-image',
                              'provider_origin': 'https://example.test', 'source_file': 'source.png',
                              'source_sha256': prepared_sha}
        self.upload_state = {'kind': 'reference_upload', 'state': 'verified', 'generation_submitted': False,
                             'request_sha256': mxapi.digest(self.upload_packet), 'source_sha256': prepared_sha,
                             'remote_sha256': prepared_sha, 'result_urls': [url],
                             'local_results': [str(self.upload / 'result.png')],
                             'verification_sha256': mxapi.digest({'source_sha256': prepared_sha, 'result_urls': [url]})}
        self.write(self.upload / 'request.json', self.upload_packet)
        self.write(self.upload / 'job.json', self.upload_state)
        identity = veo_workflow.identity_source(self.batch, 'mage', self.upload)
        self.job = self.root / 'generation'
        self.job.mkdir()
        self.design = {'schema': 1, 'design_status': 'authored', 'coverage_binding': self.binding,
                       'character_id': 'mage', 'action_id': action, 'background_mode': background,
                       'action_kind': 'loop' if action == 'walk' else 'one_shot',
                       'framing': {'safe_rect': [.1, .1, .9, .9], 'minimum_clearance_ratio': .05},
                       'effects': {'allowed': [], 'allow_unlisted': False,
                                   'forbidden': ['fire', 'lightning', 'orbs', 'smoke', 'explosions', 'runes',
                                                 'sparkles', 'hitflash', 'projectiles', 'glow', 'bloom',
                                                 'spell circles', 'magic trails', 'dust', 'blood', 'debris',
                                                 'summoned objects', 'new weapons', 'extra limbs',
                                                 'floor shadows', 'scenery', 'text', 'camera moves', 'cuts']}}
        authored = self.root / 'authored-design.json'
        self.write(authored, self.design)
        self.write(self.job / 'action-design.json', self.design)
        self.inputs = {'batch': str(self.batch), 'character': 'mage', 'action': action,
                       'design': str(authored), 'expect_design': mxapi.digest(self.design),
                       'expect_scope': hashlib.sha256((self.batch / 'scope.json').read_bytes()).hexdigest(),
                       'existing_image_job': str(self.upload), 'original_image': str(self.original),
                       'prepared_image': str(self.prepared), 'source_x': 400, 'source_y': 220}
        self.write(self.job / 'prepare-inputs.json', self.inputs)
        self.provenance = {'schema': 1, 'kind': 'original_identity_pad_only',
                           'original_image': str(self.original), 'original_sha256': original_sha,
                           'prepared_image': str(self.prepared), 'prepared_sha256': prepared_sha,
                           'original_size': [32, 40], 'canvas': [864, 496], 'source_rect': [400, 220, 432, 260],
                           'original_alpha_bbox': [4, 3, 27, 37], 'prepared_body_bbox': [404, 223, 427, 257],
                           'transform': {'kind': 'pad_only', 'scale': 1, 'resample': 'none',
                                         'background_rgba': list(veo_workflow.KEY_BACKGROUNDS[background]), 'composite': 'PIL.Image.alpha_composite'},
                           'provider_image_size_validated': True, 'generated_image': False, 'visual_review_inferred': False}
        self.write(self.job / 'padding-provenance.json', self.provenance)
        options = {'resolution': '480p', 'ratio': '16:9', 'duration': 4,
                   'first_last': False, 'reference_role': 'first_frame'}
        self.packet = {'schema_version': 1, 'kind': 'video', 'model': 'seedance-2.0-fast',
                       'options': options, 'reference_count': 1,
                       'body': mxapi.build_payload('seedance-2.0-fast', 'Fixture body motion.', [url], **options),
                       'workflow': {'schema': 1, 'kind': 'project_bound_seedance_action', 'phase': 'action_video',
                                    'production_revision': 'v4_pilot_six', 'coverage_binding': self.binding,
                                    'design_sha256': mxapi.digest(self.design), 'source_mode': 'existing_image',
                                    'identity_source': identity, 'identity_character_sha256': prepared_sha,
                                    'identity_original_sha256': original_sha, 'identity_provider_origin': 'https://example.test',
                                    'padding_provenance_sha256': mxapi.digest(self.provenance),
                                    'source_risk_notes': 'Synthetic fixture; no generated still or inferred review.',
                                    'model_contract': {'route': '/api/v2/video/seedance2-fast',
                                                       'upstream_fixed_model': 'doubao-seedance-2-0-fast-260128', **options}}}
        self.state = {'schema_version': 1, 'state': 'succeeded', 'external_job_id': 'synthetic-fast-id',
                      'provider_url': 'https://example.test', 'result_urls': ['https://example.test/video.mp4'],
                      'local_results': [str(self.video)]}
        self.save_packet()
        self.options = {'action': action, 'loop': action == 'walk', 'background': background,
                        'batch': self.batch, 'batch_character': 'mage', 'generation_job': self.job}

    def validate(self):
        return video_sample.validate_generation_job(self.job, self.video, self.binding)

    def test_fast_sample_keeps_real_kind_dual_hashes_and_full_interval_gates(self):
        self.make_job()
        with patch.object(mxapi.Client, 'request', side_effect=AssertionError('No provider calls')):
            self.export(self.video, **self.options)
        report = self.report()
        evidence = report['generation_job']
        self.assertEqual(evidence['kind'], 'project_bound_seedance_action')
        self.assertEqual(evidence['model'], 'seedance-2.0-fast')
        self.assertEqual(evidence['identity_original_sha256'], self.provenance['original_sha256'])
        self.assertEqual(evidence['identity_prepared_sha256'], self.provenance['prepared_sha256'])
        self.assertNotEqual(evidence['identity_original_sha256'], evidence['identity_prepared_sha256'])
        self.assertEqual(evidence['coverage_binding'], self.binding)
        self.assertEqual(evidence['source_video_sha256'], report['source_video_sha256'])
        self.assertTrue(report['generation_interval_review']['checked_all_interval_frames'])
        self.assertTrue(report['generation_interval_review']['included_unsampled_frames'])

    def test_fast_rejects_wrong_model_route_payload_and_fabricated_still_proof(self):
        self.make_job()
        changes = [(('model',), 'seedance-2.0-mini'), (('workflow', 'kind'), 'project_bound_veo_action'),
                   (('workflow', 'model_contract', 'route'), '/api/v2/veo/generate'),
                   (('workflow', 'model_contract', 'upstream_fixed_model'), 'different-model'),
                   (('body', 'model'), 'doubao-seedance-2-0-fast-260128'), (('body', 'generate_audio'), True),
                   (('body', 'duration'), 5), (('options', 'duration'), 5),
                   (('workflow', 'source_mode'), 'reviewed_still'), (('workflow', 'action_still_review_sha256'), 'a' * 64),
                   (('workflow', 'identity_character_sha256'), self.provenance['original_sha256'])]
        for keys, value in changes:
            with self.subTest(keys=keys):
                packet = copy.deepcopy(self.packet)
                target = packet
                for key in keys[:-1]:
                    target = target[key]
                target[keys[-1]] = value
                self.save_packet(packet)
                with self.assertRaises(ValueError):
                    self.validate()
        for text, role in [('Fixture. --dur 4', 'first_frame'), ('Fixture.', 'reference_image')]:
            packet = copy.deepcopy(self.packet)
            packet['body']['content'][0]['text'] = text
            packet['body']['content'][1]['role'] = role
            self.save_packet(packet)
            with self.assertRaises(ValueError):
                self.validate()

    def test_scope_design_and_original_source_changes_are_rejected(self):
        self.make_job()
        for path in (self.batch / 'scope.json', Path(self.inputs['design']), self.original, self.prepared):
            with self.subTest(path=path.name):
                before = path.read_bytes()
                if path == Path(self.inputs['design']):
                    self.write(path, {**self.design, 'action_kind': 'one_shot'})
                else:
                    path.write_bytes(before + b' ')
                try:
                    with self.assertRaises(ValueError):
                        self.validate()
                finally:
                    path.write_bytes(before)
        changed_design = {**self.design, 'action_kind': 'one_shot'}
        self.write(self.job / 'action-design.json', changed_design)
        with self.assertRaisesRegex(ValueError, 'design changed'):
            self.validate()

    def test_padding_provenance_cannot_claim_scaling_or_inferred_review(self):
        self.make_job()
        for key, value in [('source_rect', [399, 220, 431, 260]), ('generated_image', True),
                           ('visual_review_inferred', True), ('original_sha256', self.provenance['prepared_sha256']),
                           ('transform', {**self.provenance['transform'], 'scale': 2})]:
            with self.subTest(key=key):
                proof = {**self.provenance, key: value}
                self.write(self.job / 'padding-provenance.json', proof)
                packet = copy.deepcopy(self.packet)
                packet['workflow']['padding_provenance_sha256'] = mxapi.digest(proof)
                self.save_packet(packet)
                with self.assertRaisesRegex(ValueError, 'padding provenance'):
                    self.validate()

    def test_edited_pixels_fail_even_with_consistent_scope_upload_and_file_hashes(self):
        self.make_job(edited_prepared=True)
        with self.assertRaisesRegex(ValueError, 'prepared pixels'):
            self.validate()

    def test_verified_upload_receipt_and_provider_cannot_be_substituted(self):
        self.make_job()
        for key, value in [('state', 'succeeded'), ('generation_submitted', True), ('remote_sha256', 'f' * 64),
                           ('result_urls', ['https://other.example/prepared.png'])]:
            with self.subTest(key=key):
                self.write(self.upload / 'job.json', {**self.upload_state, key: value})
                with self.assertRaises(ValueError):
                    self.validate()
        self.write(self.upload / 'job.json', self.upload_state)
        for key, value in [('state', 'submission_unknown'), ('external_job_id', ''), ('provider_url', 'https://other.example')]:
            self.write(self.job / 'job.json', {**self.state, 'request_sha256': mxapi.digest(self.packet), key: value})
            with self.assertRaises(ValueError):
                self.validate()
        self.save_packet()
        unrelated = self.root / 'unrelated.mp4'
        unrelated.write_bytes(b'not the downloaded video')
        with self.assertRaisesRegex(ValueError, 'not the downloaded result'):
            video_sample.validate_generation_job(self.job, unrelated, self.binding)

    def test_baked_effects_fail_even_with_updated_design_and_request_hashes(self):
        self.make_job()
        design = copy.deepcopy(self.design)
        design['effects']['allowed'] = ['projectiles']
        self.write(Path(self.inputs['design']), design)
        self.write(self.job / 'action-design.json', design)
        self.inputs['expect_design'] = mxapi.digest(design)
        self.write(self.job / 'prepare-inputs.json', self.inputs)
        self.packet['workflow']['design_sha256'] = mxapi.digest(design)
        self.save_packet()
        with self.assertRaises(ValueError):
            self.validate()

    def test_fast_unsampled_clipping_still_fails_atomically(self):
        self.make_job(edge_indices={1})
        self.assert_atomic_failure(self.video, 'perimeter|safe frame', **self.options)

    def test_reviewed_magenta_canvas_preserves_green_original_pixels(self):
        self.make_job(background='magenta', source_keys=('green',))
        self.assertTrue(veo_workflow._contains_key_color(self.original, 'green'))
        self.assertFalse(veo_workflow._contains_key_color(self.original, 'magenta'))
        self.export(self.video, **self.options)
        self.assertEqual(self.report()['generation_job']['background_mode'], 'magenta')
        self.assertTrue(self.report()['generation_interval_review']['checked_all_interval_frames'])

    def test_reviewed_blue_canvas_preserves_green_and_magenta_original_pixels(self):
        self.make_job(background='blue', source_keys=('green', 'magenta'))
        self.assertTrue(veo_workflow._contains_key_color(self.original, 'green'))
        self.assertTrue(veo_workflow._contains_key_color(self.original, 'magenta'))
        self.assertFalse(veo_workflow._contains_key_color(self.original, 'blue'))
        self.export(self.video, **self.options)
        report = self.report()
        self.assertEqual(report['generation_job']['background_mode'], 'blue')
        self.assertEqual(report['generation_job']['identity_original_sha256'], self.provenance['original_sha256'])
        self.assertEqual(report['generation_job']['identity_prepared_sha256'], self.provenance['prepared_sha256'])
        self.assertTrue(report['generation_interval_review']['checked_all_interval_frames'])

    def test_selected_key_color_conflicts_are_not_disabled(self):
        for mode, color in veo_workflow.KEY_BACKGROUNDS.items():
            path = self.root / f'{mode}-conflict.png'
            Image.new('RGBA', (2, 2), color).save(path)
            self.assertTrue(veo_workflow._contains_key_color(path, mode))
        self.make_job(background='blue', source_keys=('blue',))
        with self.assertRaisesRegex(ValueError, 'safe blue canvas'):
            self.validate()

    def test_design_color_cannot_disagree_with_the_verified_prepared_canvas(self):
        self.make_job()
        design = {**self.design, 'background_mode': 'magenta'}
        self.write(Path(self.inputs['design']), design)
        self.write(self.job / 'action-design.json', design)
        self.inputs['expect_design'] = mxapi.digest(design)
        self.write(self.job / 'prepare-inputs.json', self.inputs)
        self.packet['workflow']['design_sha256'] = mxapi.digest(design)
        self.save_packet()
        with self.assertRaisesRegex(ValueError, 'prepared pixels'):
            self.validate()

    def test_rehashed_padding_cannot_claim_a_different_canvas_color(self):
        self.make_job(background='magenta')
        proof = copy.deepcopy(self.provenance)
        proof['transform']['background_rgba'] = [0, 255, 0, 255]
        self.write(self.job / 'padding-provenance.json', proof)
        self.packet['workflow']['padding_provenance_sha256'] = mxapi.digest(proof)
        self.save_packet()
        with self.assertRaisesRegex(ValueError, 'padding provenance'):
            self.validate()

    def test_blue_extraction_and_source_guard_share_the_fixed_distance_boundary(self):
        for distance in (40, 41):
            color = (distance, 0, 255, 255)
            source = self.root / f'blue-distance-{distance}.png'
            Image.new('RGBA', (1, 1), color).save(source)
            self.assertEqual(veo_workflow._contains_key_color(source, 'blue'), distance <= 40)
            frame = Image.new('RGBA', (16, 16), (0, 0, 255, 255))
            frame.putpixel((8, 8), color)
            cleaned = video_sample._remove_background(frame, 'blue')
            self.assertEqual(cleaned.getpixel((8, 8))[3], 0 if distance <= 40 else 255)
        Image.new('RGBA', (1, 1), (0, 0, 255, 1)).save(source)
        self.assertTrue(veo_workflow._contains_key_color(source, 'blue'))

    def test_fast_death_is_one_shot_and_keeps_the_final_source_frame(self):
        self.make_job(action='death')
        self.assert_atomic_failure(self.video, 'loop flag', **{**self.options, 'loop': True})
        self.export(self.video, **self.options)
        clip = self.report()['clips'][0]
        self.assertFalse(clip['loop'])
        self.assertEqual(clip['source_frame_indices'][-1], 10)
        with Image.open(self.output / clip['frames'][-1]) as last:
            self.assertEqual(last.size, (96, 96))
            self.assertIsNotNone(last.getchannel('A').getbbox())


if __name__ == '__main__':
    unittest.main()
