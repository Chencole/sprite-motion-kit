"""Shared body-action coverage retains every gameplay skill and runtime event."""
import copy
import json
from pathlib import Path
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'plugins/sprite-motion-kit/skills/sprite-motion/scripts'
sys.path.insert(0, str(SCRIPTS))
import batch
import motion
import veo_workflow
import video_sample
import test_video_batch as video_fixtures
import test_veo_workflow as veo_fixtures


class BodyRuntimeCoverageTests(unittest.TestCase):
    def setUp(self):
        self.fixture = video_fixtures.VideoBatchTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.scope = copy.deepcopy(self.fixture.spec)
        self.scope['motion_strategy'] = batch.BODY_RUNTIME_STRATEGY
        entry = self.scope['characters']['mage']
        original = entry['requirements']
        old_map = entry['action_map']
        entry['gameplay_inventory'] = copy.deepcopy(original)
        entry['requirements'], entry['action_map'], entry['runtime_mappings'] = [], {}, []
        groups = {}
        for item in original:
            body = 'cast_common' if item['kind'] == 'ability' else old_map[item['id']]
            groups.setdefault(body, []).append(item['game_id'])
            entry['runtime_mappings'].append({
                'game_id': item['game_id'], 'body_action': body,
                'game_event': 'existing_dispatcher:' + item['game_id'],
                'runtime_vfx': ['runtime.' + item['game_id']] if item['kind'] == 'ability' else [],
            })
        for body, game_ids in groups.items():
            kind = 'cast' if body == 'cast_common' else 'attack' if body == 'attack' else 'death' if body == 'death' else 'locomotion'
            entry['requirements'].append({
                'id': body, 'game_id': 'body.' + body, 'kind': 'action',
                'source': 'Synthetic body mapping, preserving original game inventory',
                'purpose': 'One reusable ' + body + ' body animation', 'applicable': True,
                'body_action_kind': kind, 'covered_game_ids': game_ids,
            })
            entry['action_map'][body] = body
        entry['effects'] = {'allowed': [], 'forbidden': list(batch.RUNTIME_VFX_FORBIDDEN), 'allow_unlisted': False}

    def test_two_spells_share_one_body_binding_and_one_review(self):
        root = self.fixture.create_batch(self.scope)
        state = batch.status(root)
        self.assertEqual(state['motion_strategy'], batch.BODY_RUNTIME_STRATEGY)
        self.assertEqual(state['required'], 6)
        binding = batch.binding(root, 'mage', 'cast_common')
        self.assertEqual(len(binding['covered_game_ids']), 2)
        self.assertEqual(len(binding['runtime_mappings']), 2)
        self.assertEqual({item['body_action'] for item in binding['runtime_mappings']}, {'cast_common'})
        for action in self.fixture.actions(root):
            sample = self.fixture.sample(root, action)
            batch.attach_video(root, 'mage', action, sample)
            report = self.fixture.review_report(root, action)
            report['checks'].update({key: True for key in batch.BODY_RUNTIME_CHECKS})
            self.fixture.approve(root, action, report)
        completed = batch.finish(root)
        self.assertTrue(completed['full_character_complete'])
        self.assertEqual(completed['reviewed'], 6)
        self.assertNotIn('cast_fire', self.fixture.actions(root))

    def test_missing_skill_coverage_or_runtime_mapping_is_rejected(self):
        for missing in ('covered', 'mapping'):
            with self.subTest(missing=missing):
                scope = copy.deepcopy(self.scope)
                entry = scope['characters']['mage']
                if missing == 'covered':
                    entry['requirements'][-1]['covered_game_ids'].pop()
                else:
                    entry['runtime_mappings'].pop()
                with self.assertRaisesRegex(ValueError, 'omit'):
                    batch.validate_scope(scope)

    def test_runtime_mapping_rejects_duplicate_unknown_wrong_body_and_missing_events(self):
        for change in ('duplicate', 'unknown', 'body', 'event', 'vfx'):
            with self.subTest(change=change):
                scope = copy.deepcopy(self.scope)
                mappings = scope['characters']['mage']['runtime_mappings']
                if change == 'duplicate':
                    mappings.append(copy.deepcopy(mappings[0]))
                elif change == 'unknown':
                    mappings[0]['game_id'] = 'ability.not_in_inventory'
                elif change == 'body':
                    mappings[0]['body_action'] = 'other_body'
                elif change == 'event':
                    del mappings[0]['game_event']
                else:
                    mappings[0]['runtime_vfx'] = 'baked_fire'
                with self.assertRaises(ValueError):
                    batch.validate_scope(scope)

    def test_more_than_three_combat_bodies_or_disguised_cast_is_rejected(self):
        scope = copy.deepcopy(self.scope)
        entry = scope['characters']['mage']
        for number in range(2):
            action = 'extra_cast_' + str(number)
            game_id = 'ability.' + action
            entry['gameplay_inventory'].append({'game_id': game_id, 'kind': 'ability',
                                                'source': 'Synthetic extra ability', 'purpose': 'Existing skill', 'applicable': True})
            entry['requirements'].append({'id': action, 'kind': 'action', 'game_id': 'body.' + action,
                                           'source': 'Synthetic mapping', 'purpose': 'Cast body', 'applicable': True,
                                           'body_action_kind': 'cast', 'covered_game_ids': [game_id]})
            entry['action_map'][action] = action
            entry['runtime_mappings'].append({'game_id': game_id, 'body_action': action,
                                              'game_event': 'existing.skill.dispatch', 'runtime_vfx': []})
        with self.assertRaisesRegex(ValueError, '1 to 3'):
            batch.validate_scope(scope)
        scope = copy.deepcopy(self.scope)
        scope['characters']['mage']['requirements'][-1]['body_action_kind'] = 'locomotion'
        with self.assertRaisesRegex(ValueError, 'counted attack or cast'):
            batch.validate_scope(scope)

    def test_body_effects_allow_nothing_and_require_all_forbidden_categories(self):
        effects = self.scope['characters']['mage']['effects']
        with self.assertRaisesRegex(ValueError, 'allowed='):
            batch.validate_body_effects({**effects, 'allowed': ['fire']})
        for category in batch.RUNTIME_VFX_FORBIDDEN:
            with self.subTest(category=category):
                changed = copy.deepcopy(effects)
                changed['forbidden'].remove(category)
                with self.assertRaisesRegex(ValueError, 'every runtime VFX'):
                    batch.validate_body_effects(changed)

    def test_shared_body_review_must_cover_runtime_separation_and_mapping(self):
        root = self.fixture.create_batch(self.scope)
        sample = self.fixture.sample(root, 'cast_common')
        batch.attach_video(root, 'mage', 'cast_common', sample)
        report = self.fixture.review_report(root, 'cast_common')
        with self.assertRaisesRegex(ValueError, 'body_motion_only'):
            self.fixture.approve(root, 'cast_common', report)

    def test_unknown_strategy_and_duplicate_inventory_are_rejected(self):
        scope = copy.deepcopy(self.scope)
        scope['motion_strategy'] = 'body_actions_typo'
        with self.assertRaisesRegex(ValueError, 'motion_strategy'):
            batch.validate_scope(scope)
        scope = copy.deepcopy(self.scope)
        inventory = scope['characters']['mage']['gameplay_inventory']
        inventory.append(copy.deepcopy(inventory[0]))
        with self.assertRaisesRegex(ValueError, 'unique'):
            batch.validate_scope(scope)

    def test_veo_design_enforces_body_only_effects_and_prompt(self):
        root = self.fixture.create_batch(self.scope)
        fixture = veo_fixtures.VeoWorkflowTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        design = fixture.design('cast_fire')
        design.update(character_id='mage', action_id='cast_common',
                      coverage_binding=batch.binding(root, 'mage', 'cast_common'))
        with self.assertRaisesRegex(ValueError, 'allowed='):
            veo_workflow.validate_design(design)
        design['effects'] = copy.deepcopy(self.scope['characters']['mage']['effects'])
        prompt = veo_workflow.prompts(design)['video_prompt']
        self.assertIn('Body motion only', prompt)
        self.assertIn('Multiple gameplay skills reuse this single animation', prompt)
        self.assertIn('Allowed effects: none', prompt)

    def test_scaffold_carries_complete_body_effects_policy(self):
        root = self.fixture.create_batch(self.scope)
        path = self.fixture.root / 'cast-design.json'
        veo_workflow.scaffold(root, 'mage', 'cast_common', path)
        design = motion.read(path)
        self.assertEqual(design['design_status'], 'needs_authoring')
        self.assertEqual(design['effects'], self.scope['characters']['mage']['effects'])
        self.assertEqual(len(design['coverage_binding']['runtime_mappings']), 2)

    def test_extraction_rejects_baked_vfx_even_with_updated_snapshot_hashes(self):
        root = self.fixture.create_batch(self.scope)
        binding = batch.binding(root, 'mage', 'cast_common')
        job = self.fixture.root / 'cast-video-job'
        job.mkdir()
        video = job / 'result.mp4'
        video.write_bytes(b'Synthetic generation provenance, not a real video')
        design = {'character_id': 'mage', 'action_id': 'cast_common', 'action_kind': 'one_shot',
                  'coverage_binding': binding, 'effects': copy.deepcopy(binding['effects_policy']),
                  'background_mode': 'green', 'framing': {'safe_rect': [.1, .1, .9, .9], 'minimum_clearance_ratio': .05}}
        packet = {'kind': 'video', 'model': 'veo-3.1-fast',
                  'workflow': {'kind': 'project_bound_veo_action', 'phase': 'action_video',
                               'coverage_binding': binding, 'design_sha256': video_sample._json_digest(design)}}
        state = {'state': 'succeeded', 'local_results': [str(video)],
                 'result_urls': ['https://example.test/video.mp4'], 'request_sha256': video_sample._json_digest(packet)}
        def write():
            motion.write(job / 'action-design.json', design)
            motion.write(job / 'request.json', packet)
            motion.write(job / 'job.json', state)
        write()
        evidence, _ = video_sample.validate_generation_job(job, video, binding)
        self.assertEqual(evidence['coverage_binding']['motion_strategy'], batch.BODY_RUNTIME_STRATEGY)
        design['effects']['allowed'] = ['baked lightning']
        packet['workflow']['design_sha256'] = video_sample._json_digest(design)
        state['request_sha256'] = video_sample._json_digest(packet)
        write()
        with self.assertRaisesRegex(ValueError, 'allowed='):
            video_sample.validate_generation_job(job, video, binding)


if __name__ == '__main__':
    unittest.main()
