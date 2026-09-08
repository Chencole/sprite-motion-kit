"""Coverage and review bookkeeping tests; synthetic sources are not decoded video."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw


SCRIPTS = Path(__file__).resolve().parents[1] / 'plugins/sprite-motion-kit/skills/sprite-motion/scripts'
sys.path.insert(0, str(SCRIPTS))
import batch


DISCOVERY_AREAS = [
    'state_machine', 'control_inputs', 'abilities', 'weapons',
    'damage_death_revival', 'interactions',
]
REVIEW_CHECKS = [
    'appearance', 'whole_body_motion', 'timing_and_transition',
    'transparency_and_crop', 'requested_action', 'source_video',
    'ability_or_weapon_match',
]


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class VideoBatchTests(unittest.TestCase):
    """These fixtures verify bookkeeping, never natural motion or video decoding."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.character = self.root / 'character.png'
        image = Image.new('RGBA', (24, 32))
        ImageDraw.Draw(image).rectangle((7, 3, 17, 28), fill=(35, 80, 180, 255))
        image.save(self.character)
        self.serial = 0
        requirements = []
        action_map = {}
        for requirement_id, kind, game_id, action in [
            ('movement_walk', 'action', 'state.walk', 'walk'),
            ('movement_run', 'action', 'state.run', 'run'),
            ('primary_sword', 'weapon', 'weapon.sword.slash', 'attack'),
            ('body_death', 'action', 'state.dead', 'death'),
            ('movement_jump', 'action', 'input.jump', 'jump'),
            ('fire_magic', 'ability', 'ability.fire_bolt', 'cast_fire'),
            ('ice_magic', 'ability', 'ability.ice_nova', 'cast_ice'),
        ]:
            requirements.append({
                'id': requirement_id, 'kind': kind, 'game_id': game_id,
                'purpose': 'Synthetic inventory requirement for ' + game_id,
                'source': 'synthetic-game/player.json#' + game_id,
                'applicable': True,
            })
            action_map[requirement_id] = action
        self.spec = {
            'request': 'Complete the synthetic character, including its two distinct magic abilities.',
            'characters': {
                'mage': {
                    'character': 'character.png',
                    'discovery': {
                        'project': 'Synthetic game fixture; no real gameplay inspected',
                        'inspections': [
                            {'area': area, 'status': 'inspected',
                             'source': 'synthetic-game/player.json#' + area,
                             'notes': 'Synthetic complete inventory fixture for ' + area}
                            for area in DISCOVERY_AREAS
                        ],
                    },
                    'requirements': requirements,
                    'action_map': action_map,
                },
            },
        }

    def create_batch(self, spec=None):
        self.serial += 1
        spec_path = self.root / f'scope-{self.serial}.json'
        output = self.root / f'batch-{self.serial}'
        write_json(spec_path, copy.deepcopy(self.spec if spec is None else spec))
        batch.create(spec_path, output)
        return output

    def actions(self, batch_path):
        return [item['action'] for item in batch.status(batch_path)['actions']]

    def item(self, batch_path, action):
        return next(item for item in batch.status(batch_path)['actions'] if item['action'] == action)

    def sample(self, batch_path, action, *, source_bytes=None, indices=(0, 1)):
        self.serial += 1
        sample = self.root / f'sample-{self.serial}-{action}'
        folder = sample / action
        folder.mkdir(parents=True)
        shutil.copyfile(self.character, sample / 'character-reference.png')
        source = sample / 'source-video.mp4'
        source.write_bytes(source_bytes if source_bytes is not None else
                           b'SYNTHETIC BOOKKEEPING FIXTURE, NOT DECODED VIDEO: ' + action.encode('ascii'))
        color = hashlib.sha256(action.encode('ascii')).digest()
        frames = []
        for index in range(2):
            frame = Image.new('RGBA', (24, 32))
            ImageDraw.Draw(frame).rectangle((6 + index, 3, 16 + index, 28),
                                            fill=(color[0], color[1], color[2], 255))
            frame.save(folder / f'frame-{index:03d}.png')
            frames.append(frame)
        atlas = Image.new('RGBA', (48, 32))
        for index, frame in enumerate(frames):
            atlas.alpha_composite(frame, (24 * index, 0))
        atlas.save(folder / 'atlas.png')
        contact = Image.new('RGB', atlas.size, '#1d2934')
        contact.paste(atlas, mask=atlas.getchannel('A'))
        contact.save(folder / 'contact.png')
        clip = {
            'name': action, 'count': 2, 'seconds': 1.0,
            'loop': action in ('walk', 'run'), 'tile': [24, 32], 'origin': [12, 29],
            'frames': [f'{action}/frame-{index:03d}.png' for index in range(2)],
            'sampling_times_seconds': [0.0, 0.5],
            'source_frame_indices': list(indices), 'source_times_seconds': [0.0, 0.5],
            'bounds': [list(frame.getchannel('A').getbbox()) for frame in frames],
            'accepted_by_user': False,
        }
        write_json(sample / 'sample.json', {
            'schema': 2, 'character': 'mage', 'status': 'video_review_sample',
            'scope_mode': 'action_study', 'clips': [clip],
            'character_reference': 'character-reference.png',
            'character_sha256': sha256(sample / 'character-reference.png'),
            'coverage_binding': batch.binding(batch_path, 'mage', action),
            'source_video': source.name, 'source_video_name': source.name,
            'source_video_sha256': sha256(source), 'interval': [0.0, 1.0],
            'sampling': 'Synthetic two-frame bookkeeping fixture; no video decoding claimed.',
            'background': 'alpha', 'key_scope': None,
            'background_removal': 'preserved source alpha',
            'pose_correspondence_verified': False, 'game_assets_replaced': False,
            'notes': ['Synthetic pixels exercise artifact identity, not animation quality.'],
        })
        (sample / 'index.html').write_text('<p>Synthetic bookkeeping fixture only.</p>', encoding='utf-8')
        return sample

    def attach_all(self, batch_path):
        samples = {}
        for action in self.actions(batch_path):
            samples[action] = self.sample(batch_path, action)
            batch.attach_video(batch_path, 'mage', action, samples[action])
        return samples

    def review_report(self, batch_path, action):
        return {
            'artifact_hashes': self.item(batch_path, action)['artifact_hashes'],
            'coverage_binding': batch.binding(batch_path, 'mage', action),
            'checks': {check: True for check in REVIEW_CHECKS},
            'notes': 'Synthetic fixture review for bookkeeping only; no real visual-quality claim.',
        }

    def approve(self, batch_path, action, report=None):
        report_path = self.root / 'review.json'
        write_json(report_path, self.review_report(batch_path, action) if report is None else report)
        return batch.review(batch_path, 'mage', action, report_path)

    def test_schema_two_derives_actions_from_complete_inventory(self):
        batch_path = self.create_batch()
        state = batch.status(batch_path)
        self.assertEqual(read_json(batch_path / 'batch.json')['schema'], 2)
        self.assertEqual(set(self.actions(batch_path)),
                         set(self.spec['characters']['mage']['action_map'].values()))
        self.assertEqual(state['required'], 7)
        self.assertFalse(state['scope_complete'])
        self.assertFalse(state['full_character_complete'])
        self.assertFalse(state['complete'])
        requirement = self.spec['characters']['mage']['requirements'][-1]
        binding = batch.binding(batch_path, 'mage', 'cast_ice')
        self.assertEqual(binding, {
            'scope_sha256': sha256(batch_path / 'scope.json'), 'character': 'mage',
            'action': 'cast_ice', 'requirement': requirement,
        })
        self.assertEqual(self.item(batch_path, 'cast_ice')['requirement'], requirement)

    def test_missing_mapping_for_any_applicable_requirement_rejects_create(self):
        for requirement_id in ('movement_walk', 'primary_sword', 'fire_magic', 'ice_magic'):
            with self.subTest(requirement=requirement_id):
                spec = copy.deepcopy(self.spec)
                del spec['characters']['mage']['action_map'][requirement_id]
                with self.assertRaises(ValueError):
                    self.create_batch(spec)

    def test_two_spells_cannot_share_generic_attack_action(self):
        spec = copy.deepcopy(self.spec)
        mapping = spec['characters']['mage']['action_map']
        mapping['fire_magic'] = mapping['ice_magic'] = 'generic_attack'
        with self.assertRaises(ValueError):
            self.create_batch(spec)

    def test_explicit_required_actions_must_exactly_match_mapping(self):
        for actions in (['walk'], list(self.spec['characters']['mage']['action_map'].values()) + ['unmapped_cast']):
            with self.subTest(actions=actions):
                spec = copy.deepcopy(self.spec)
                spec['characters']['mage']['required_actions'] = actions
                with self.assertRaises(ValueError):
                    self.create_batch(spec)

    def test_discovery_must_cover_every_area_once(self):
        for change in ('missing', 'duplicate'):
            with self.subTest(change=change):
                spec = copy.deepcopy(self.spec)
                inspections = spec['characters']['mage']['discovery']['inspections']
                if change == 'missing':
                    inspections.pop()
                else:
                    inspections.append(copy.deepcopy(inspections[0]))
                with self.assertRaises(ValueError):
                    self.create_batch(spec)

    def test_nonapplicable_requirement_needs_reason_and_no_action_mapping(self):
        spec = copy.deepcopy(self.spec)
        requirement = {'id': 'revival', 'kind': 'action', 'game_id': 'state.revive',
                       'purpose': 'No revival state in this synthetic character.',
                       'source': 'synthetic-game/player.json#states', 'applicable': False}
        spec['characters']['mage']['requirements'].append(requirement)
        with self.assertRaises(ValueError):
            self.create_batch(spec)
        requirement['exclusion_reason'] = 'Synthetic inventory has permanent death and no revival transition.'
        batch_path = self.create_batch(spec)
        self.assertEqual(batch.status(batch_path)['required'], 7)
        spec['characters']['mage']['action_map']['revival'] = 'revive'
        with self.assertRaises(ValueError):
            self.create_batch(spec)

    def test_missing_second_spell_review_blocks_finish_even_when_all_attached(self):
        batch_path = self.create_batch()
        self.attach_all(batch_path)
        for action in self.actions(batch_path):
            if action != 'cast_ice':
                self.approve(batch_path, action)
        state = batch.status(batch_path)
        self.assertEqual(state['reviewed'], 6)
        self.assertNotEqual(self.item(batch_path, 'cast_ice')['state'], 'reviewed')
        self.assertFalse(state['scope_complete'])
        self.assertFalse(state['full_character_complete'])
        self.assertFalse(state['complete'])
        with self.assertRaises(ValueError):
            batch.finish(batch_path)

    def test_complete_inventory_and_all_current_reviews_can_finish(self):
        batch_path = self.create_batch()
        self.attach_all(batch_path)
        for action in self.actions(batch_path):
            self.approve(batch_path, action)
        state = batch.finish(batch_path)
        self.assertTrue(state['scope_complete'])
        self.assertTrue(state['full_character_complete'])
        self.assertTrue(state['complete'])
        self.assertEqual(state['reviewed'], state['required'])
        self.assertTrue(read_json(batch_path / 'completion.json')['full_character_complete'])

    def test_different_character_pixels_cannot_be_attached_even_with_updated_sample_hash(self):
        batch_path = self.create_batch()
        sample = self.sample(batch_path, 'cast_fire')
        Image.new('RGBA', (24, 32), 'red').save(sample / 'character-reference.png')
        manifest = read_json(sample / 'sample.json')
        manifest['character_sha256'] = sha256(sample / 'character-reference.png')
        write_json(sample / 'sample.json', manifest)
        with self.assertRaises(ValueError):
            batch.attach_video(batch_path, 'mage', 'cast_fire', sample)

    def test_wrong_declared_character_hash_is_rejected(self):
        batch_path = self.create_batch()
        sample = self.sample(batch_path, 'walk')
        manifest = read_json(sample / 'sample.json')
        manifest['character_sha256'] = '0' * 64
        write_json(sample / 'sample.json', manifest)
        with self.assertRaises(ValueError):
            batch.attach_video(batch_path, 'mage', 'walk', sample)

    def test_wrong_scope_action_or_requirement_binding_is_rejected(self):
        for field in ('scope_sha256', 'character', 'action', 'requirement'):
            with self.subTest(field=field):
                batch_path = self.create_batch()
                sample = self.sample(batch_path, 'cast_fire')
                manifest = read_json(sample / 'sample.json')
                if field == 'requirement':
                    manifest['coverage_binding'][field]['game_id'] = 'ability.ice_nova'
                else:
                    manifest['coverage_binding'][field] = 'wrong-binding'
                write_json(sample / 'sample.json', manifest)
                with self.assertRaises(ValueError):
                    batch.attach_video(batch_path, 'mage', 'cast_fire', sample)

    def test_same_source_frames_cannot_fill_two_action_aliases(self):
        batch_path = self.create_batch()
        source = b'SAME SYNTHETIC SOURCE UNDER DIFFERENT ACTION NAMES'
        fire = self.sample(batch_path, 'cast_fire', source_bytes=source)
        ice = self.sample(batch_path, 'cast_ice', source_bytes=source)
        batch.attach_video(batch_path, 'mage', 'cast_fire', fire)
        with self.assertRaises(ValueError):
            batch.attach_video(batch_path, 'mage', 'cast_ice', ice)
        self.assertNotEqual(self.item(batch_path, 'cast_ice')['state'], 'reviewed')

    def test_identical_output_frames_cannot_fill_two_actions_with_different_sources(self):
        batch_path = self.create_batch()
        fire = self.sample(batch_path, 'cast_fire')
        ice = self.sample(batch_path, 'cast_ice')
        for filename in ('frame-000.png', 'frame-001.png', 'atlas.png', 'contact.png'):
            shutil.copyfile(fire / 'cast_fire' / filename, ice / 'cast_ice' / filename)
        batch.attach_video(batch_path, 'mage', 'cast_fire', fire)
        with self.assertRaises(ValueError):
            batch.attach_video(batch_path, 'mage', 'cast_ice', ice)

    def test_artifact_changes_invalidate_review(self):
        for artifact in ('frame', 'atlas', 'source', 'manifest'):
            with self.subTest(artifact=artifact):
                batch_path = self.create_batch()
                sample = self.sample(batch_path, 'walk')
                batch.attach_video(batch_path, 'mage', 'walk', sample)
                self.approve(batch_path, 'walk')
                self.assertEqual(self.item(batch_path, 'walk')['state'], 'reviewed')
                if artifact in ('frame', 'atlas'):
                    path = sample / 'walk' / ('frame-000.png' if artifact == 'frame' else 'atlas.png')
                    with Image.open(path) as image:
                        changed = image.convert('RGBA')
                    changed.putpixel((10, 10), (250, 20, 50, 255))
                    changed.save(path)
                elif artifact == 'source':
                    (sample / 'source-video.mp4').write_bytes(b'REPLACED SYNTHETIC SOURCE')
                else:
                    manifest = read_json(sample / 'sample.json')
                    manifest['clips'][0]['origin'] = [13, 29]
                    write_json(sample / 'sample.json', manifest)
                self.assertNotEqual(self.item(batch_path, 'walk')['state'], 'reviewed')
                self.assertFalse(batch.status(batch_path)['full_character_complete'])

    def test_stored_review_checks_are_revalidated_by_status(self):
        for check in REVIEW_CHECKS:
            with self.subTest(check=check):
                batch_path = self.create_batch()
                sample = self.sample(batch_path, 'cast_fire')
                batch.attach_video(batch_path, 'mage', 'cast_fire', sample)
                self.approve(batch_path, 'cast_fire')
                state = read_json(batch_path / 'batch.json')
                state['reviews']['mage']['cast_fire']['checks'][check] = False
                write_json(batch_path / 'batch.json', state)
                self.assertNotEqual(self.item(batch_path, 'cast_fire')['state'], 'reviewed')

    def test_stored_review_binding_is_revalidated_by_status(self):
        batch_path = self.create_batch()
        sample = self.sample(batch_path, 'cast_fire')
        batch.attach_video(batch_path, 'mage', 'cast_fire', sample)
        self.approve(batch_path, 'cast_fire')
        state = read_json(batch_path / 'batch.json')
        state['reviews']['mage']['cast_fire']['coverage_binding']['action'] = 'cast_ice'
        write_json(batch_path / 'batch.json', state)
        self.assertNotEqual(self.item(batch_path, 'cast_fire')['state'], 'reviewed')

    def test_stored_review_still_requires_observation_notes(self):
        batch_path = self.create_batch()
        sample = self.sample(batch_path, 'cast_fire')
        batch.attach_video(batch_path, 'mage', 'cast_fire', sample)
        self.approve(batch_path, 'cast_fire')
        state = read_json(batch_path / 'batch.json')
        state['reviews']['mage']['cast_fire']['notes'] = ' '
        write_json(batch_path / 'batch.json', state)
        self.assertNotEqual(self.item(batch_path, 'cast_fire')['state'], 'reviewed')

    def test_video_review_requires_both_extra_checks_and_exact_binding(self):
        batch_path = self.create_batch()
        sample = self.sample(batch_path, 'cast_fire')
        batch.attach_video(batch_path, 'mage', 'cast_fire', sample)
        for missing_check in ('source_video', 'ability_or_weapon_match'):
            with self.subTest(check=missing_check):
                report = self.review_report(batch_path, 'cast_fire')
                del report['checks'][missing_check]
                with self.assertRaises(ValueError):
                    self.approve(batch_path, 'cast_fire', report)
        report = self.review_report(batch_path, 'cast_fire')
        report['coverage_binding'] = batch.binding(batch_path, 'mage', 'cast_ice')
        with self.assertRaises(ValueError):
            self.approve(batch_path, 'cast_fire', report)

    def test_walk_study_can_finish_its_scope_but_never_full_character(self):
        spec = copy.deepcopy(self.spec)
        spec.update(scope_mode='action_study', study_reason='User requested only a walk timing study.')
        entry = spec['characters']['mage']
        entry['requirements'] = [entry['requirements'][0]]
        entry['action_map'] = {'movement_walk': 'walk'}
        batch_path = self.create_batch(spec)
        sample = self.sample(batch_path, 'walk')
        batch.attach_video(batch_path, 'mage', 'walk', sample)
        self.approve(batch_path, 'walk')
        state = batch.finish(batch_path)
        self.assertEqual(state['required'], 1)
        self.assertTrue(state['scope_complete'])
        self.assertFalse(state['full_character_complete'])
        self.assertFalse(state['complete'])
        self.assertEqual(state['delivery_kind'], 'action_study')
        completion = read_json(batch_path / 'completion.json')
        self.assertFalse(completion['complete'])
        self.assertFalse(completion['full_character_complete'])
        self.assertEqual(completion['delivery_kind'], 'action_study')

    def test_study_without_explicit_reason_is_rejected(self):
        spec = copy.deepcopy(self.spec)
        spec['scope_mode'] = 'action_study'
        with self.assertRaises(ValueError):
            self.create_batch(spec)

    def test_malformed_scope_containers_raise_validation_errors(self):
        for case in ('root', 'character', 'discovery', 'inspection', 'requirement', 'declared_action'):
            with self.subTest(case=case):
                spec = copy.deepcopy(self.spec)
                entry = spec['characters']['mage']
                if case == 'root':
                    spec = []
                elif case == 'character':
                    spec['characters']['mage'] = None
                elif case == 'discovery':
                    entry['discovery'] = None
                elif case == 'inspection':
                    entry['discovery']['inspections'][0] = None
                elif case == 'requirement':
                    entry['requirements'][0] = None
                else:
                    entry['required_actions'] = [[] for _ in entry['action_map']]
                with self.assertRaises(ValueError):
                    self.create_batch(spec)

    def test_malformed_video_containers_raise_validation_errors(self):
        for case in ('root', 'clip', 'tile', 'origin', 'source_frame_indices',
                     'source_times_seconds', 'frames', 'unhashable_frames'):
            with self.subTest(case=case):
                batch_path = self.create_batch()
                sample = self.sample(batch_path, 'walk')
                manifest = read_json(sample / 'sample.json')
                if case == 'root':
                    manifest = []
                elif case == 'clip':
                    manifest['clips'] = [None]
                elif case == 'unhashable_frames':
                    manifest['clips'][0]['frames'] = [[], []]
                else:
                    manifest['clips'][0][case] = None
                write_json(sample / 'sample.json', manifest)
                with self.assertRaises(ValueError):
                    batch.attach_video(batch_path, 'mage', 'walk', sample)

    def test_corrupt_attached_sample_is_incomplete_instead_of_crashing_status(self):
        for field in ('tile', 'source_frame_indices', 'frames'):
            with self.subTest(field=field):
                batch_path = self.create_batch()
                sample = self.sample(batch_path, 'walk')
                batch.attach_video(batch_path, 'mage', 'walk', sample)
                self.approve(batch_path, 'walk')
                manifest = read_json(sample / 'sample.json')
                manifest['clips'][0][field] = None
                write_json(sample / 'sample.json', manifest)
                self.assertNotEqual(self.item(batch_path, 'walk')['state'], 'reviewed')
                self.assertFalse(batch.status(batch_path)['complete'])

    def test_malformed_review_containers_raise_validation_errors(self):
        batch_path = self.create_batch()
        sample = self.sample(batch_path, 'walk')
        batch.attach_video(batch_path, 'mage', 'walk', sample)
        for case in ('root', 'checks'):
            with self.subTest(case=case):
                report = self.review_report(batch_path, 'walk')
                if case == 'root':
                    report = []
                else:
                    report['checks'] = None
                with self.assertRaises(ValueError):
                    self.approve(batch_path, 'walk', report)

    def test_corrupt_stored_review_is_incomplete_instead_of_crashing_status(self):
        batch_path = self.create_batch()
        sample = self.sample(batch_path, 'walk')
        batch.attach_video(batch_path, 'mage', 'walk', sample)
        self.approve(batch_path, 'walk')
        state = read_json(batch_path / 'batch.json')
        state['reviews']['mage']['walk']['checks'] = None
        write_json(batch_path / 'batch.json', state)
        self.assertNotEqual(self.item(batch_path, 'walk')['state'], 'reviewed')

    def test_nonimage_character_reference_cannot_create_batch(self):
        self.character.write_bytes(b'This file is not a character image despite its PNG extension.')
        with self.assertRaises(ValueError):
            self.create_batch()

    def test_non_png_frame_or_atlas_cannot_be_mislabeled_as_png(self):
        for filename in ('frame-000.png', 'atlas.png'):
            with self.subTest(filename=filename):
                batch_path = self.create_batch()
                sample = self.sample(batch_path, 'walk')
                path = sample / 'walk' / filename
                with Image.open(path) as image:
                    wrong_format = image.copy()
                wrong_format.save(path, format='TIFF')
                with self.assertRaises(ValueError):
                    batch.attach_video(batch_path, 'mage', 'walk', sample)

    def test_one_transparent_pixel_does_not_make_an_opaque_scene_acceptable(self):
        batch_path = self.create_batch()
        sample = self.sample(batch_path, 'walk')
        atlas = Image.new('RGBA', (48, 32))
        for index in range(2):
            frame = Image.new('RGBA', (24, 32), (35, 80, 180, 255))
            frame.putpixel((0, 0), (0, 0, 0, 0))
            frame.save(sample / 'walk' / f'frame-{index:03d}.png')
            atlas.alpha_composite(frame, (24 * index, 0))
        atlas.save(sample / 'walk' / 'atlas.png')
        manifest = read_json(sample / 'sample.json')
        manifest['clips'][0]['bounds'] = [[0, 0, 24, 32], [0, 0, 24, 32]]
        write_json(sample / 'sample.json', manifest)
        with self.assertRaises(ValueError):
            batch.attach_video(batch_path, 'mage', 'walk', sample)

    def test_video_artifacts_cannot_escape_sample_directory(self):
        for field in ('character_reference', 'source_video'):
            with self.subTest(field=field):
                batch_path = self.create_batch()
                sample = self.sample(batch_path, 'walk')
                manifest = read_json(sample / 'sample.json')
                original = sample / manifest[field]
                outside = self.root / ('outside-' + original.name)
                shutil.copyfile(original, outside)
                manifest[field] = '../' + outside.name
                write_json(sample / 'sample.json', manifest)
                with self.assertRaises(ValueError):
                    batch.attach_video(batch_path, 'mage', 'walk', sample)

    def test_completion_snapshot_becomes_stale_after_artifact_or_review_changes(self):
        batch_path = self.create_batch()
        samples = self.attach_all(batch_path)
        for action in self.actions(batch_path):
            self.approve(batch_path, action)
        self.assertFalse(batch.status(batch_path)['completion_current'])
        self.assertTrue(batch.finish(batch_path)['completion_current'])
        manifest = read_json(samples['walk'] / 'sample.json')
        manifest['notes'].append('Updated inspection observation after completion.')
        write_json(samples['walk'] / 'sample.json', manifest)
        self.assertFalse(batch.status(batch_path)['completion_current'])
        self.approve(batch_path, 'walk')
        self.assertTrue(batch.status(batch_path)['complete'])
        self.assertFalse(batch.status(batch_path)['completion_current'])
        self.assertTrue(batch.finish(batch_path)['completion_current'])
        state = read_json(batch_path / 'batch.json')
        state['reviews']['mage']['walk']['checks']['source_video'] = False
        write_json(batch_path / 'batch.json', state)
        self.assertFalse(batch.status(batch_path)['completion_current'])

    def test_malformed_completion_snapshot_does_not_hide_current_action_status(self):
        batch_path = self.create_batch()
        self.attach_all(batch_path)
        for action in self.actions(batch_path):
            self.approve(batch_path, action)
        batch.finish(batch_path)
        write_json(batch_path / 'completion.json', [])
        state = batch.status(batch_path)
        self.assertTrue(state['scope_complete'])
        self.assertFalse(state['completion_current'])

    def test_duplicate_detector_compares_frames_across_video_and_packed_job(self):
        batch_path = self.create_batch()
        sample = self.sample(batch_path, 'cast_ice')
        job = self.root / 'synthetic-packed-job'
        action_folder = job / 'cast_fire'
        action_folder.mkdir(parents=True)
        for index in range(2):
            shutil.copyfile(sample / 'cast_ice' / f'frame-{index:03d}.png',
                            action_folder / f'frame-{index:03d}.png')
        write_json(action_folder / 'clip.json', {'count': 2})
        data = read_json(batch_path / 'batch.json')
        data['jobs'] = {'mage': {'cast_fire': str(job)}}
        data['videos'] = {'mage': {'cast_ice': str(sample)}}
        # This unit test isolates the route-independent pixel comparison; the
        # synthetic packed folder is not a valid or approved 3D generation job.
        duplicates = batch.duplicate_actions(data, read_json(batch_path / 'scope.json'))
        self.assertIn(('mage', 'cast_ice'), duplicates)

    def test_fully_reviewed_legacy_scope_still_cannot_claim_full_completion(self):
        legacy = self.root / 'legacy-batch'
        legacy.mkdir()
        write_json(legacy / 'scope.json', {
            'request': 'Old scope has no recorded gameplay discovery.',
            'scope_mode': 'full_character',
            'characters': {'mage': {'character': str(self.character),
                                    'character_sha256': sha256(self.character),
                                    'required_actions': ['walk']}},
        })
        hashes = {'fixture': 'isolated legacy status evidence'}
        write_json(legacy / 'batch.json', {
            'schema': 1, 'scope_sha256': sha256(legacy / 'scope.json'),
            'jobs': {'mage': {'walk': str(self.root / 'legacy-job')}},
            'reviews': {'mage': {'walk': {
                'artifact_hashes': hashes,
                'checks': {check: True for check in REVIEW_CHECKS},
                'notes': 'Synthetic legacy bookkeeping evidence only.',
            }}},
        })
        with patch.object(batch, 'action_evidence', return_value=hashes):
            state = batch.status(legacy)
            self.assertTrue(state['scope_complete'])
            self.assertFalse(state['full_character_complete'])
            self.assertFalse(state['complete'])
            with self.assertRaises(ValueError):
                batch.finish(legacy)


if __name__ == '__main__':
    unittest.main()
