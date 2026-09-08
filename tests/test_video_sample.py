import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugins/sprite-motion-kit/skills/sprite-motion/scripts'))
import video_sample


def find_ffmpeg():
    executable = os.environ.get('SPRITE_TEST_FFMPEG') or shutil.which('ffmpeg')
    if not executable:
        try:
            import imageio_ffmpeg
            executable = imageio_ffmpeg.get_ffmpeg_exe()
        except (ImportError, RuntimeError):
            pass
    return executable


class VideoSampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ffmpeg = find_ffmpeg()
        if not cls.ffmpeg:
            raise unittest.SkipTest('Set SPRITE_TEST_FFMPEG to an existing FFmpeg executable')

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.output = self.root / 'result'

    def tearDown(self):
        self.temporary.cleanup()

    def make_video(self, background='magenta', count=12, *, heights=None, lossy=False,
                   edge=False, edge_indices=None, durations=None, duplicate_endpoint=False):
        colors = {'magenta': (255, 0, 255, 255), 'green': (0, 255, 0, 255),
                  'alpha': (83, 122, 17, 0), 'opaque': (35, 35, 35, 255)}
        source = self.root / 'source'
        source.mkdir()
        self.originals = []
        for i in range(count):
            pose = 0 if duplicate_endpoint and i == count - 1 else i
            im = Image.new('RGBA', (96, 96), colors[background])
            draw = ImageDraw.Draw(im)
            x = 0 if edge or (edge_indices and i in edge_indices) else 16 + pose
            y = 48 - (heights[i] if heights else 0)
            draw.rectangle((x, y, x + 27, y + 30), fill=(25, 45, 200, 255))
            # The key color inside the costume must survive background removal.
            if background in ('magenta', 'green'):
                draw.rectangle((x + 9, y + 8, x + 16, y + 15), fill=colors[background])
            if background == 'alpha':
                draw.rectangle((x + 2, y - 1, x + 25, y - 1), fill=(70, 90, 210, 96))
            im.save(source / f'frame-{i:03d}.png')
            self.originals.append(im)
        video = self.root / ('input.mp4' if lossy else 'input.mkv')
        args = [self.ffmpeg, '-hide_banner', '-nostdin', '-loglevel', 'error']
        if durations:
            concat = source / 'frames.txt'
            concat.write_text(''.join(f"file 'frame-{i:03d}.png'\nduration {d}\n" for i, d in enumerate(durations))
                              + f"file 'frame-{len(durations)-1:03d}.png'\n", encoding='utf-8')
            args += ['-f', 'concat', '-safe', '0', '-i', str(concat), '-fps_mode', 'vfr']
        else:
            args += ['-framerate', '10', '-i', str(source / 'frame-%03d.png')]
        args += (['-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p'] if lossy
                 else ['-c:v', 'ffv1', '-pix_fmt', 'bgra'])
        subprocess.run(args + [str(video)], check=True, capture_output=True)
        return video

    def export(self, video, **changes):
        args = dict(character='Synthetic character', action='jump', start=0, duration=1,
                    count=5, loop=False, background='magenta', origin=[48, 80],
                    review_notes='Synthetic full-body interval, static camera and floor.')
        args.update(changes)
        return video_sample.export_video(video, self.ffmpeg, self.output, **args)

    def report(self):
        return json.loads((self.output / 'sample.json').read_text(encoding='utf-8'))

    def assert_atomic_failure(self, video, expression, **changes):
        with self.assertRaisesRegex(ValueError, expression):
            self.export(video, **changes)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob('.video-sample-*')), [])

    def make_bound_batch(self, character, action='walk'):
        import batch
        specification = self.root / f'{action}-scope.json'
        entry = {'character': str(character), 'discovery': {'project': 'Synthetic Veo workflow fixture',
                 'inspections': [{'area': area, 'status': 'inspected', 'source': 'Synthetic source',
                                  'notes': 'Synthetic extraction contract fixture.'}
                                 for area in batch.DISCOVERY_AREAS]},
                 'requirements': [{'id': 'required_action', 'kind': 'action',
                                   'game_id': 'state.' + action, 'purpose': action + ' animation',
                                   'source': 'Synthetic source', 'applicable': True}],
                 'action_map': {'required_action': action}}
        specification.write_text(json.dumps({'request': 'Test one project-bound Veo action',
                                              'scope_mode': 'action_study',
                                              'study_reason': 'Extraction integration test',
                                              'characters': {'mage': entry}}), encoding='utf-8')
        destination = self.root / f'{action}-batch'
        batch.create(specification, destination)
        return destination

    def make_generation_job(self, video, batch_path, action='walk', *, background='green'):
        import batch
        job = self.root / f'{action}-generation-job'
        job.mkdir()
        binding = batch.binding(batch_path, 'mage', action)
        design = {'schema': 1, 'design_status': 'authored', 'coverage_binding': binding,
                  'character_id': 'mage', 'action_id': action, 'background_mode': background,
                  'action_kind': 'loop' if action == 'walk' else 'one_shot',
                  'framing': {'safe_rect': [.1, .1, .9, .9], 'minimum_clearance_ratio': .05}}
        design_sha = hashlib.sha256(json.dumps(design, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        packet = {'schema_version': 1, 'model': 'veo-3.1-fast', 'body': {}, 'options': {},
                  'reference_count': 1, 'kind': 'video',
                  'workflow': {'schema': 1, 'kind': 'project_bound_veo_action',
                               'phase': 'action_video', 'design_sha256': design_sha,
                               'coverage_binding': binding}}
        request_sha = hashlib.sha256(json.dumps(packet, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        state = {'schema_version': 1, 'state': 'succeeded', 'request_sha256': request_sha,
                 'result_urls': ['https://example.test/action.mp4'],
                 'local_results': [str(Path(video).resolve())]}
        for name, value in [('request.json', packet), ('job.json', state), ('action-design.json', design)]:
            (job / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        return job

    def test_subframe_start_does_not_shift_later_target_times(self):
        video = self.make_video()
        self.export(video, start=.13, duration=.6, count=3)
        clip = self.report()['clips'][0]
        self.assertEqual(clip['sampling_times_seconds'], [.13, .43, .73])
        self.assertEqual(clip['source_times_seconds'], [.2, .4, .7])
        self.assertEqual(clip['source_frame_indices'], [2, 4, 7])
        for path, index in zip(clip['frames'], [2, 4, 7]):
            with Image.open(self.output / path) as frame:
                self.assertEqual(frame.getchannel('A').getbbox()[0], 16 + index)

    def test_loop_excludes_duplicate_endpoint_and_preserves_canvas(self):
        video = self.make_video(count=11, duplicate_endpoint=True)
        self.export(video, loop=True)
        clip = self.report()['clips'][0]
        self.assertEqual(clip['source_frame_indices'], [0, 2, 4, 6, 8])
        self.assertEqual(clip['tile'], [96, 96])
        self.assertEqual(clip['origin'], [48, 80])
        self.assertTrue(clip['loop'])
        for path in clip['frames']:
            with Image.open(self.output / path) as frame:
                self.assertEqual(frame.size, (96, 96))
                self.assertEqual(frame.mode, 'RGBA')
        with Image.open(self.output / clip['frames'][0]) as first, Image.open(self.output / clip['frames'][-1]) as last:
            self.assertNotEqual(first.tobytes(), last.tobytes())

    def test_source_alpha_soft_edges_and_jump_height_survive_exactly(self):
        heights = [0, 5, 15, 25, 32, 25, 15, 5, 0, 0]
        video = self.make_video(background='alpha', count=10, heights=heights)
        self.export(video, background='alpha')
        clip = self.report()['clips'][0]
        for path, index in zip(clip['frames'], clip['source_frame_indices']):
            with Image.open(self.output / path) as frame:
                original = np.array(self.originals[index])
                original[original[:, :, 3] == 0] = 0
                np.testing.assert_array_equal(np.array(frame), original)
                self.assertIn(96, np.unique(np.array(frame)[:, :, 3]))
        self.assertEqual(clip['bounds'][0][3] - clip['bounds'][2][3], 25)

    def test_green_key_removes_background_and_preserves_costume_color(self):
        video = self.make_video(background='green')
        self.export(video, background='green')
        clip = self.report()['clips'][0]
        for index, path in zip(clip['source_frame_indices'], clip['frames']):
            with Image.open(self.output / path) as frame:
                self.assertEqual(frame.getpixel((0, 0)), (0, 0, 0, 0))
                self.assertEqual(frame.getpixel((27 + index, 58)), (0, 255, 0, 255))
                self.assertEqual(int((np.array(frame)[:, :, 3] > 0).sum()), 28 * 31)

    def test_magenta_key_preserves_enclosed_costume_color(self):
        video = self.make_video()
        self.export(video)
        with Image.open(self.output / 'jump/frame-000.png') as frame:
            self.assertEqual(frame.getpixel((0, 0)), (0, 0, 0, 0))
            self.assertEqual(frame.getpixel((27, 58)), (255, 0, 255, 255))
            self.assertEqual(int((np.array(frame)[:, :, 3] > 0).sum()), 28 * 31)

    def test_explicit_all_key_scope_removes_enclosed_background_gaps(self):
        video = self.make_video(background='green')
        self.export(video, background='green', key_scope='all')
        self.assertEqual(self.report()['key_scope'], 'all')
        for path in self.report()['clips'][0]['frames']:
            with Image.open(self.output / path) as frame:
                rgba = np.array(frame)
                self.assertEqual(int((rgba[:, :, 3] > 0).sum()), 28 * 31 - 8 * 8)
                self.assertEqual(int(((rgba[:, :, 1] == 255) & (rgba[:, :, 3] > 0)).sum()), 0)

    def test_unknown_key_scope_rejected_before_export(self):
        video = self.make_video()
        self.assert_atomic_failure(video, 'Key scope', key_scope='automatic')

    def test_compressed_green_video_produces_real_alpha_without_eroding_body(self):
        video = self.make_video(background='green', lossy=True)
        self.export(video, background='green')
        for path in self.report()['clips'][0]['frames']:
            with Image.open(self.output / path) as frame:
                rgba = np.array(frame)
                self.assertEqual(rgba[0, :, 3].max(), 0)
                self.assertEqual(rgba[-1, :, 3].max(), 0)
                self.assertGreater(int((rgba[:, :, 3] > 0).sum()), 28 * 31 * .98)
                self.assertLess(int((rgba[:, :, 3] > 0).sum()), 28 * 31 * 1.3)

    def test_manifest_atlas_and_review_outputs_match_exported_frames(self):
        video = self.make_video()
        result = self.export(video)
        report = self.report()
        self.assertEqual(report['source_video_sha256'], hashlib.sha256(video.read_bytes()).hexdigest())
        self.assertEqual(report['interval'], [0, 1])
        self.assertEqual(report['background'], 'magenta')
        self.assertFalse(report['pose_correspondence_verified'])
        self.assertFalse(report['game_assets_replaced'])
        self.assertEqual(report['scope_mode'], 'action_study')
        self.assertFalse(report['full_character_complete'])
        self.assertFalse(report['clips'][0]['accepted_by_user'])
        self.assertEqual(result['preview'], str(self.output / 'index.html'))
        self.assertFalse((self.output / 'decoded').exists())
        html = (self.output / 'index.html').read_text(encoding='utf-8')
        self.assertNotIn('href="source-partitions.png"', html)
        self.assertNotIn('href="source-transparent.png"', html)
        self.assertNotIn('五动作', html)
        self.assertNotIn('五种动作', html)
        self.assertIn('单动作试样', html)
        self.assertIn('src="source-video.mkv"', html)
        self.assertEqual((self.output / report['source_video']).read_bytes(), video.read_bytes())
        self.assertFalse((self.output / 'job.json').exists())
        self.assertFalse((self.output / 'request.json').exists())
        self.assertTrue((self.output / 'jump/contact.png').is_file())
        with Image.open(self.output / 'jump/atlas.png') as atlas:
            self.assertEqual(atlas.size, (480, 96))
            for i, path in enumerate(report['clips'][0]['frames']):
                with Image.open(self.output / path) as frame:
                    np.testing.assert_array_equal(np.array(atlas.crop((i * 96, 0, (i + 1) * 96, 96))), np.array(frame))

    def test_end_past_video_is_rejected_even_when_all_sample_times_exist(self):
        video = self.make_video(count=10)
        self.assert_atomic_failure(video, 'coverage', duration=1.01, count=4)

    def test_oversampling_is_rejected_without_duplicate_padding(self):
        video = self.make_video(count=10)
        self.assert_atomic_failure(video, 'source frames', count=11)

    def test_vfr_that_would_repeat_a_nearest_frame_is_rejected(self):
        video = self.make_video(count=5, durations=[.04, .04, .32, .04, .56])
        self.assert_atomic_failure(video, 'repeat source frames', count=5)

    def test_vfr_sampling_uses_actual_timestamps(self):
        video = self.make_video(count=4, durations=[.2, .4, .2, .2])
        self.export(video, count=4)
        clip = self.report()['clips'][0]
        self.assertEqual(clip['sampling_times_seconds'], [0, 1 / 3, 2 / 3, 1])
        self.assertEqual(clip['source_times_seconds'], [0, .2, .6, 1.0])
        self.assertEqual(clip['source_frame_indices'], [0, 1, 2, 4])

    def test_exact_midpoint_ties_choose_earlier_source_frame(self):
        video = self.make_video()
        self.export(video, duration=.5, count=3)
        self.assertEqual(self.report()['clips'][0]['source_frame_indices'], [0, 2, 5])

    def test_one_shot_includes_true_endpoint_while_loop_excludes_it(self):
        video = self.make_video(count=12)
        self.export(video, action='attack', duration=1, count=5)
        one_shot = self.report()['clips'][0]
        self.assertEqual(one_shot['sampling_times_seconds'], [0, .25, .5, .75, 1])
        self.assertEqual(one_shot['source_frame_indices'][-1], 10)
        self.assertIn('[start, end]', self.report()['sampling'])

        self.output = self.root / 'loop-result'
        self.export(video, action='walk', duration=1, count=5, loop=True)
        loop = self.report()['clips'][0]
        self.assertEqual(loop['sampling_times_seconds'], [0, .2, .4, .6, .8])
        self.assertEqual(loop['source_frame_indices'][-1], 8)
        self.assertIn('[start, end)', self.report()['sampling'])

    def test_project_bound_veo_job_records_generation_and_checks_every_interval_frame(self):
        video = self.make_video(background='green', lossy=True)
        character = self.root / 'source/frame-000.png'
        batch_path = self.make_bound_batch(character)
        job = self.make_generation_job(video, batch_path)
        self.export(video, action='walk', loop=True, background='green',
                    batch=batch_path, batch_character='mage', generation_job=job)
        report = self.report()
        generation = report['generation_job']
        self.assertEqual(generation['kind'], 'project_bound_veo_action')
        self.assertEqual(generation['phase'], 'action_video')
        self.assertEqual(generation['model'], 'veo-3.1-fast')
        self.assertEqual(generation['source_video_sha256'], report['source_video_sha256'])
        inspection = report['generation_interval_review']
        self.assertTrue(inspection['checked_all_interval_frames'])
        self.assertTrue(inspection['included_unsampled_frames'])
        self.assertGreater(inspection['source_frame_count'], report['clips'][0]['count'])
        self.assertTrue(inspection['all_foreground_inside_contract'])

    def test_project_bound_veo_checks_unsampled_frames_for_clipping(self):
        video = self.make_video(background='green', lossy=True, edge_indices={1})
        character = self.root / 'source/frame-000.png'
        batch_path = self.make_bound_batch(character)
        job = self.make_generation_job(video, batch_path)
        self.assert_atomic_failure(
            video, 'perimeter|safe frame', action='walk', loop=True, background='green',
            batch=batch_path, batch_character='mage', generation_job=job)

    def test_bound_death_preserves_final_body_and_rejects_loop_export(self):
        import batch
        video = self.make_video(background='green', lossy=True,
                                heights=[4, 4, 4, 4, 4, 3, 2, 1, 0, 0, 0, 0])
        character = self.root / 'source/frame-000.png'
        batch_path = self.make_bound_batch(character, 'death')
        job = self.make_generation_job(video, batch_path, 'death')
        options = dict(action='death', background='green', batch=batch_path,
                       batch_character='mage', generation_job=job)
        self.assert_atomic_failure(video, 'loop flag', loop=True, **options)
        self.export(video, loop=False, **options)
        clip = self.report()['clips'][0]
        self.assertEqual(clip['source_frame_indices'][-1], 10)
        self.assertFalse(clip['loop'])
        with Image.open(self.output / clip['frames'][-1]) as final_frame:
            bounds = final_frame.getchannel('A').getbbox()
            self.assertEqual(final_frame.size, (96, 96))
            self.assertGreaterEqual(bounds[2] - bounds[0], 28)
            self.assertGreaterEqual(bounds[3] - bounds[1], 31)
        attached = batch.attach_video(batch_path, 'mage', 'death', self.output)
        item = attached['actions'][0]
        review = self.root / 'death-review.json'
        review.write_text(json.dumps({
            'artifact_hashes': item['artifact_hashes'], 'coverage_binding': item['coverage_binding'],
            'action_design_sha256': self.report()['generation_job']['design_sha256'],
            'checks': {key: True for key in batch.VISUAL_CHECKS + batch.WORKFLOW_VIDEO_CHECKS
                       + ['source_video', 'ability_or_weapon_match']},
            'notes': 'Synthetic endpoint and batch integration fixture, not natural death motion.'}), encoding='utf-8')
        batch.review(batch_path, 'mage', 'death', review)
        self.assertTrue(batch.finish(batch_path)['scope_complete'])

    def test_bound_walk_rejects_one_shot_export(self):
        video = self.make_video(background='green', lossy=True)
        batch_path = self.make_bound_batch(self.root / 'source/frame-000.png')
        job = self.make_generation_job(video, batch_path)
        self.assert_atomic_failure(video, 'loop flag', action='walk', loop=False, background='green',
                                   batch=batch_path, batch_character='mage', generation_job=job)

    def test_existing_image_video_retains_framing_and_batch_binding(self):
        import batch
        video = self.make_video(background='green', lossy=True)
        character = self.root / 'source/frame-000.png'
        batch_path = self.make_bound_batch(character)
        job = self.make_generation_job(video, batch_path)
        packet = json.loads((job / 'request.json').read_text(encoding='utf-8'))
        state = json.loads((job / 'job.json').read_text(encoding='utf-8'))
        character_sha = hashlib.sha256(character.read_bytes()).hexdigest()
        source = {'url': 'https://example.test/original.png', 'request_sha256': '1' * 64,
                  'local_sha256': character_sha, 'character_sha256': character_sha,
                  'character_pixel_sha256': '2' * 64}
        packet['body']['images'] = [source['url']]
        packet['workflow'].update(source_mode='existing_image', identity_source=source,
                                  identity_character_sha256=character_sha,
                                  source_risk_notes='Synthetic direct image reuse; no still review.')
        state['request_sha256'] = video_sample._json_digest(packet)
        (job / 'request.json').write_text(json.dumps(packet), encoding='utf-8')
        (job / 'job.json').write_text(json.dumps(state), encoding='utf-8')
        self.export(video, action='walk', loop=True, background='green',
                    batch=batch_path, batch_character='mage', generation_job=job)
        self.assertEqual(self.report()['generation_job']['source_mode'], 'existing_image')
        self.assertTrue(self.report()['generation_interval_review']['checked_all_interval_frames'])
        result = batch.attach_video(batch_path, 'mage', 'walk', self.output)
        self.assertFalse(result['scope_complete'])

    def test_generation_binding_rejects_wrong_video_and_coverage(self):
        import batch
        video = self.make_video(background='green', lossy=True)
        batch_path = self.make_bound_batch(self.root / 'source/frame-000.png')
        job = self.make_generation_job(video, batch_path)
        binding = batch.binding(batch_path, 'mage', 'walk')
        changed = {**binding, 'action': 'death'}
        with self.assertRaisesRegex(ValueError, 'coverage binding'):
            video_sample.validate_generation_job(job, video, changed)
        other_video = self.root / 'unrelated.mp4'
        other_video.write_bytes(b'Synthetic unrelated video bytes')
        with self.assertRaisesRegex(ValueError, 'not the downloaded result'):
            video_sample.validate_generation_job(job, other_video, binding)

    def test_full_interval_inspection_rejects_missing_decoded_frames(self):
        with self.assertRaisesRegex(ValueError, 'every source frame'):
            video_sample._check_workflow_interval(
                [], [{'index': 0}], (96, 96), background='green', key_scope='edge-connected',
                black_sidebars=None, safe_rect=[.1, .1, .9, .9], clearance=.05, sampled_indices=[0])

    def test_generation_job_must_match_source_model_design_binding_and_background(self):
        video = self.make_video(background='green', lossy=True)
        character = self.root / 'source/frame-000.png'
        batch_path = self.make_bound_batch(character)
        job = self.make_generation_job(video, batch_path)
        self.assert_atomic_failure(
            video, 'Background extraction', action='walk', loop=True, background='magenta',
            batch=batch_path, batch_character='mage', generation_job=job)

        packet = json.loads((job / 'request.json').read_text(encoding='utf-8'))
        state = json.loads((job / 'job.json').read_text(encoding='utf-8'))
        original_packet, original_state = dict(packet), dict(state)
        packet['model'] = 'seedance-2.0-fast'
        state['request_sha256'] = hashlib.sha256(
            json.dumps(packet, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        (job / 'request.json').write_text(json.dumps(packet), encoding='utf-8')
        (job / 'job.json').write_text(json.dumps(state), encoding='utf-8')
        self.assert_atomic_failure(
            video, 'project-bound Veo', action='walk', loop=True, background='green',
            batch=batch_path, batch_character='mage', generation_job=job)
        (job / 'request.json').write_text(json.dumps(original_packet), encoding='utf-8')
        (job / 'job.json').write_text(json.dumps(original_state), encoding='utf-8')

        design = json.loads((job / 'action-design.json').read_text(encoding='utf-8'))
        design['framing']['safe_rect'][0] = .2
        (job / 'action-design.json').write_text(json.dumps(design), encoding='utf-8')
        self.assert_atomic_failure(
            video, 'design changed', action='walk', loop=True, background='green',
            batch=batch_path, batch_character='mage', generation_job=job)

    def test_opaque_input_fails_and_cleans_staging_directory(self):
        video = self.make_video(background='opaque')
        self.assert_atomic_failure(video, 'fully opaque', background='alpha')

    def test_clipped_character_fails_and_cleans_staging_directory(self):
        video = self.make_video(edge=True)
        self.assert_atomic_failure(video, 'perimeter|canvas edge')

    def test_decode_failure_is_atomic(self):
        video = self.root / 'corrupt.mp4'
        video.write_bytes(b'not a video')
        self.assert_atomic_failure(video, 'decoding failed')

    def test_late_write_failure_leaves_no_output(self):
        video = self.make_video()
        with patch.object(video_sample, 'SKILL', self.root / 'missing-template'):
            with self.assertRaises(FileNotFoundError):
                self.export(video)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob('.video-sample-*')), [])

    def test_existing_output_is_preserved(self):
        video = self.make_video()
        self.export(video)
        before = {p.relative_to(self.output): p.read_bytes() for p in self.output.rglob('*') if p.is_file()}
        with self.assertRaisesRegex(ValueError, 'existing samples'):
            self.export(video)
        after = {p.relative_to(self.output): p.read_bytes() for p in self.output.rglob('*') if p.is_file()}
        self.assertEqual(after, before)

    def test_invalid_origin_fails_atomically(self):
        video = self.make_video()
        self.assert_atomic_failure(video, 'outside', origin=[96, 80])

    def test_bound_video_export_connects_to_batch_review_without_becoming_full_character(self):
        import batch
        video = self.make_video()
        reference = self.root / 'source/frame-000.png'
        specification = self.root / 'scope.json'
        entry = {'character': str(reference), 'discovery': {'project': 'Synthetic movement study', 'inspections': [
            {'area': area, 'status': 'inspected', 'source': 'Synthetic test scope', 'notes': 'Walk-only study fixture.'}
            for area in batch.DISCOVERY_AREAS]},
            'requirements': [{'id': 'move', 'kind': 'action', 'game_id': 'controller.walk',
                              'purpose': 'Walk input', 'source': 'Synthetic controller', 'applicable': True}],
            'action_map': {'move': 'walk'}}
        specification.write_text(json.dumps({'request': 'Inspect one walk sample', 'scope_mode': 'action_study',
                                             'study_reason': 'Only this diagnostic was requested', 'characters': {'mage': entry}}), encoding='utf-8')
        destination = self.root / 'batch'
        batch.create(specification, destination)
        self.export(video, action='walk', batch=destination, batch_character='mage')
        report = self.report()
        self.assertEqual(report['coverage_binding'], batch.binding(destination, 'mage', 'walk'))
        self.assertEqual((self.output / report['character_reference']).read_bytes(), reference.read_bytes())
        state = batch.attach_video(destination, 'mage', 'walk', self.output)
        self.assertFalse(state['scope_complete'])
        item = state['actions'][0]
        approval = self.root / 'review.json'
        approval.write_text(json.dumps({'artifact_hashes': item['artifact_hashes'], 'coverage_binding': item['coverage_binding'],
                                        'checks': {k: True for k in batch.VISUAL_CHECKS + ['source_video', 'ability_or_weapon_match']},
                                        'notes': 'Synthetic export integration test; not an art-quality claim.'}), encoding='utf-8')
        batch.review(destination, 'mage', 'walk', approval)
        result = batch.finish(destination)
        self.assertTrue(result['scope_complete'])
        self.assertFalse(result['complete'])
        self.assertFalse(result['full_character_complete'])

    def test_invalid_character_reference_is_rejected_before_export(self):
        video = self.make_video()
        reference = self.root / 'not-image.png'
        reference.write_bytes(b'not an image')
        self.assert_atomic_failure(video, 'readable image', character_image=reference)


if __name__ == '__main__':
    unittest.main()
