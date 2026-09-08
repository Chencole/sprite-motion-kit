import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image


SCRIPTS = Path(__file__).resolve().parents[1] / 'plugins/sprite-motion-kit/skills/sprite-motion/scripts'
sys.path.insert(0, str(SCRIPTS))

import batch
import motion
import mxapi
import veo_workflow as veo


def mapped_character(actions):
    requirements = []
    for action in actions:
        kind = 'ability' if action == 'cast_fire' else 'action'
        requirements.append({
            'id': action,
            'kind': kind,
            'game_id': ('ability.' if kind == 'ability' else 'state.') + action,
            'purpose': {
                'walk': 'Traverse the overworld outside combat with the sword stowed',
                'sword_slash': 'Draw or use the sword for one close-range slash',
                'cast_fire': 'Cast the distinct fire-bolt ability from a staff',
                'death': 'Collapse once and hold the full-size body after death',
            }[action],
            'source': 'synthetic gameplay inventory for Veo workflow tests',
            'applicable': True,
        })
    return {
        'character': 'character.png',
        'required_actions': list(actions),
        'discovery': {
            'project': 'Synthetic side-view action game',
            'inspections': [{
                'area': area,
                'status': 'inspected',
                'source': 'synthetic project fixture',
                'notes': 'Fixture records the complete gameplay inventory for workflow tests.',
            } for area in batch.DISCOVERY_AREAS],
        },
        'requirements': requirements,
        'action_map': {action: action for action in actions},
    }


class VeoWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.character = self.root / 'character.png'
        image = Image.new('RGBA', (18, 26), (0, 0, 0, 0))
        for y in range(3, 24):
            for x in range(5, 14):
                image.putpixel((x, y), (34 + x, 70 + y, 155, 255))
        image.save(self.character)
        self.scope = self.root / 'scope.json'
        motion.write(self.scope, {
            'request': 'Create all required animations for the knight',
            'characters': {'knight': mapped_character(['walk', 'sword_slash', 'cast_fire', 'death'])},
        })
        self.batch = self.root / 'batch'
        batch.create(self.scope, self.batch)

    def binding(self, action):
        return batch.binding(self.batch, 'knight', action)

    def design(self, action='walk', *, equipment='sheathed', draw=False):
        loop = action == 'walk'
        if action == 'walk':
            item = 'steel arming sword'
            states = ['sheathed', 'sheathed', 'sheathed', 'sheathed']
            phase_names = ['left contact', 'left passing', 'right contact', 'right passing']
            body = [
                'left heel contacts while the right toe pushes off',
                'right foot passes the planted left leg under the hips',
                'right heel contacts while the left toe pushes off',
                'left foot passes the planted right leg under the hips',
            ]
            equipment_motion = ['sword stays fixed in the hip scabbard'] * 4
            start_pose = 'upright left-foot contact pose with both hands empty and the sword fully sheathed'
            end_pose = 'matching left-foot contact trajectory for a continuous two-step loop'
        elif action == 'cast_fire':
            item = 'oak spell staff'
            states = ['ready', 'casting', 'casting', 'ready']
            phase_names = ['brace', 'invoke', 'release fire bolt', 'recover']
            body = [
                'feet brace and the torso settles',
                'free hand traces the fire-bolt sigil',
                'casting hand thrusts forward at the gameplay event',
                'arms and torso return to the ready stance',
            ]
            equipment_motion = [
                'staff remains planted in the rear hand',
                'staff tilts toward the cast line',
                'staff points at the fire-bolt release line',
                'staff returns to the ready angle',
            ]
            start_pose = 'side-profile ready stance with the staff held in the rear hand'
            end_pose = 'same side-profile staff-ready stance after the cast'
        elif draw:
            item = 'steel arming sword'
            states = ['ready', 'attack', 'ready', 'sheathed']
            phase_names = ['draw', 'slash impact', 'recover', 'resheathe']
            body = [
                'right hand draws while the hips turn into guard',
                'hips and shoulders drive one horizontal cut',
                'body absorbs momentum and returns to guard',
                'hand guides the blade completely into its scabbard',
            ]
            equipment_motion = [
                'blade clears the hip scabbard',
                'blade follows one readable forward arc',
                'blade decelerates back toward the hip',
                'blade enters the scabbard and leaves both hands empty',
            ]
            start_pose = 'balanced side-profile stance with the sword fully sheathed and hands empty'
            end_pose = 'balanced side-profile stance with the sword fully sheathed again'
        else:
            item = 'steel arming sword'
            states = ['ready', 'attack', 'attack', 'ready']
            phase_names = ['anticipate', 'slash impact', 'follow through', 'recover']
            body = [
                'knees load and shoulders wind back',
                'hips and shoulders drive one horizontal cut',
                'torso follows the completed sword arc',
                'weight settles back into the ready guard',
            ]
            equipment_motion = [
                'sword remains held in the right hand behind the hip',
                'sword follows one readable forward arc',
                'sword remains in the same hand through deceleration',
                'sword returns to the ready angle in the same hand',
            ]
            start_pose = 'side-profile combat guard with the drawn sword in the right hand'
            end_pose = 'same side-profile combat guard with the sword ready in the right hand'

        if action == 'cast_fire':
            kind, start_state, end_state = 'focus', 'ready', 'ready'
            attachment = 'right hand throughout the cast'
            hands_start = hands_end = 'right hand holds the staff; left hand is free'
            hands_during = 'right hand anchors the staff while the left hand casts'
            allowed = ['one compact orange fire bolt at the named release phase']
        else:
            kind = 'handheld'
            start_state = end_state = equipment
            attachment = 'left-hip leather scabbard when sheathed; right hand when ready or attacking'
            hands_start = ('both hands empty' if equipment == 'sheathed' else 'right hand holds sword; left hand is free')
            hands_end = hands_start
            hands_during = ('both hands stay empty' if action == 'walk' else 'right hand controls the sword; left hand stays free')
            allowed = []

        phases = [{
            'name': name,
            'at': at,
            'body_motion': body_motion,
            'equipment_motion': item_motion,
            'equipment_state': state,
            'game_event': ('damage resolves now' if 'impact' in name or 'release' in name else 'none'),
        } for name, at, body_motion, item_motion, state in zip(
            phase_names, [.14, .38, .62, .86], body, equipment_motion, states
        )]
        return {
            'schema': 1,
            'design_status': 'authored',
            'coverage_binding': self.binding(action),
            'character_id': 'knight',
            'action_id': action,
            'visual_identity': 'compact silver-armored pixel knight with a red cloth sash',
            'identity_constraints': [
                'retain the same silver helmet silhouette',
                'retain the red sash and short dark boots',
                'retain the same body proportions and pixel-art palette',
            ],
            'gameplay_context': self.binding(action)['requirement']['purpose'],
            'anatomy_and_weight': 'two-legged adult human with grounded weight transfer and readable shoulder and hip counter-motion',
            'design_evidence': [{
                'source': self.binding(action)['requirement']['source'],
                'observation': 'The project assigns this exact equipment state and gameplay event to this action.',
            }],
            'action_kind': 'loop' if loop else 'one_shot',
            'facing': 'right_profile',
            'root_motion': 'in_place' if loop else 'stationary',
            'background_mode': 'green',
            'start_pose': start_pose,
            'phases': phases,
            'end_pose': end_pose,
            'equipment_policy': {
                'kind': kind,
                'item': item,
                'attachment': attachment,
                'start_state': start_state,
                'end_state': end_state,
                'hands_at_start': hands_start,
                'hands_during': hands_during,
                'hands_at_end': hands_end,
                'motion': 'Follow the ordered states exactly without duplicating, dropping, or teleporting the item.',
            },
            'effects': {
                'allowed': allowed,
                'forbidden': ['camera shake', 'motion blur', 'extra weapons', 'unlisted magic'],
                'allow_unlisted': False,
            },
            'framing': {
                'character_height_ratio': .48,
                'feet_y_ratio': .82,
                'safe_rect': [.06, .06, .94, .94],
                'minimum_clearance_ratio': .04,
                'includes': ['body', 'equipment'],
                'motion_envelope': {
                    'top': 'helmet and any raised hand',
                    'front': 'the complete blade arc or spell release',
                    'back': 'the scabbard, sash, and backswing',
                    'bottom': 'both feet and any jump clearance',
                },
            },
            'complete_cycles': 2 if loop else None,
            'loop_compatibility': ({
                'equipment_state_matches': True,
                'hand_occupancy_matches': True,
                'facing_matches': True,
                'scale_matches': True,
                'velocity_matches': True,
                'notes': 'Second full step returns to the corresponding left-contact trajectory without a pause.',
            } if loop else None),
            'recovery_or_hold': '' if loop else 'return to the exact documented ready or sheathed endpoint and hold briefly',
        }

    def write_design(self, design, name='design.json'):
        path = self.root / name
        motion.write(path, design)
        return path

    def successful_image_job(self, name, local_image, *, url=None):
        job = self.root / name
        mxapi.prepare(job, 'gpt-image-2', 'Create the test identity image')
        local = job / 'result-00.png'
        with Image.open(local_image) as source:
            source.save(local)
        state = motion.read(job / 'job.json')
        state.update({
            'state': 'succeeded',
            'result_urls': [url or f'https://example.com/{name}.png'],
            'local_results': [str(local)],
        })
        mxapi.write_json(job / 'job.json', state)
        return job

    def identity_job(self, name='identity'):
        return self.successful_image_job(name, self.character)

    def completed_still(self, design_path, design, name='still'):
        job = self.root / name
        veo.prepare_still(design_path, self.batch, 'knight', design['action_id'], self.identity_job(name + '-identity'), job)
        local = job / 'result-00.png'
        Image.new('RGBA', (96, 54), (12, 220, 30, 255)).save(local)
        state = motion.read(job / 'job.json')
        state.update({
            'state': 'succeeded',
            'result_urls': [f'https://example.com/{name}.png'],
            'local_results': [str(local)],
        })
        mxapi.write_json(job / 'job.json', state)
        return job

    def review_report(self, design, still_job, name='review.json', observed=None):
        _, _, _, inputs = veo._still_inputs(still_job, design)
        report = self.root / name
        motion.write(report, {
            'schema': 1,
            'input_hashes': inputs,
            'observed_equipment_start_state': observed or design['equipment_policy']['start_state'],
            'checks': {check: True for check in veo.STILL_CHECKS},
            'notes': 'Reviewed the actual downloaded still: identity, side view, equipment state, and clearance all match.',
        })
        return report

    def reviewed_still(self, design, prefix='reviewed'):
        design_path = self.write_design(design, prefix + '-design.json')
        still = self.completed_still(design_path, design, prefix + '-still')
        report = self.review_report(design, still, prefix + '-report.json')
        veo.review_still(design_path, self.batch, 'knight', design['action_id'], still, report)
        return design_path, still

    def test_scaffold_is_bound_and_needs_ai_authoring(self):
        path = self.root / 'walk-design.json'
        result = veo.scaffold(self.batch, 'knight', 'walk', path)
        draft = motion.read(path)
        self.assertEqual(result['status'], 'needs_authoring')
        self.assertFalse(result['generation_submitted'])
        self.assertEqual(draft['coverage_binding'], self.binding('walk'))
        self.assertEqual(draft['gameplay_context'], self.binding('walk')['requirement']['purpose'])
        with self.assertRaisesRegex(ValueError, 'author'):
            veo.validate_design(draft, self.binding('walk'))

    def test_walk_prompt_keeps_sword_sheathed_and_hands_empty(self):
        design = self.design('walk')
        rendered = veo.prompts(design)
        for prompt in rendered.values():
            self.assertIn('start=sheathed, end=sheathed', prompt)
            self.assertIn('fully stowed', prompt)
            self.assertIn('never drawn or held in a hand', prompt)
            self.assertIn('both hands empty', prompt)
            self.assertIn('Strict 90-degree side profile', prompt)
        self.assertIn('Show at least 2 complete cycles', rendered['video_prompt'])
        self.assertIn('right foot passes the planted left leg', rendered['video_prompt'])

    def test_illegal_equipment_transition_and_bad_loop_seam_are_rejected(self):
        illegal = self.design('walk')
        illegal['phases'][1]['equipment_state'] = 'attack'
        with self.assertRaisesRegex(ValueError, 'Illegal equipment transition'):
            veo.validate_design(illegal)
        broken_seam = self.design('walk')
        broken_seam['loop_compatibility']['velocity_matches'] = False
        with self.assertRaisesRegex(ValueError, 'Loop seam check'):
            veo.validate_design(broken_seam)

    def test_ready_attack_and_draw_attack_chain_are_both_legal(self):
        ready = self.design('sword_slash', equipment='ready')
        draw = self.design('sword_slash', equipment='sheathed', draw=True)
        self.assertIs(veo.validate_design(ready), ready)
        self.assertIs(veo.validate_design(draw), draw)
        ready_prompt = veo.prompts(ready)['video_prompt']
        draw_prompt = veo.prompts(draw)['video_prompt']
        self.assertIn('start=ready, end=ready', ready_prompt)
        self.assertIn('1. at 0.14 — draw', draw_prompt)
        self.assertIn('4. at 0.86 — resheathe', draw_prompt)
        self.assertIn('start=sheathed, end=sheathed', draw_prompt)

    def test_identity_job_must_be_downloaded_and_match_character_pixels(self):
        missing = self.root / 'identity-missing'
        mxapi.prepare(missing, 'gpt-image-2', 'Create identity')
        state = motion.read(missing / 'job.json')
        state.update(state='succeeded', result_urls=['https://example.com/missing.png'])
        mxapi.write_json(missing / 'job.json', state)
        with self.assertRaisesRegex(ValueError, 'downloaded local result'):
            veo.identity_source(self.batch, 'knight', missing)

        mismatch = self.root / 'different.png'
        Image.new('RGBA', (18, 26), (255, 0, 0, 255)).save(mismatch)
        wrong = self.successful_image_job('identity-wrong', mismatch)
        with self.assertRaisesRegex(ValueError, 'does not match'):
            veo.identity_source(self.batch, 'knight', wrong)

        reencoded = self.root / 'reencoded.png'
        with Image.open(self.character) as source:
            source.save(reencoded, compress_level=9)
        matching = self.successful_image_job('identity-matching', reencoded)
        source = veo.identity_source(self.batch, 'knight', matching)
        self.assertEqual(source['character_pixel_sha256'], veo.image_digest(self.character))

    def test_unreviewed_still_cannot_prepare_video(self):
        design = self.design('walk')
        design_path = self.write_design(design)
        still = self.completed_still(design_path, design)
        with self.assertRaisesRegex(ValueError, 'visual review'):
            veo.prepare_video(design_path, self.batch, 'knight', 'walk', still, self.root / 'video')

    def test_review_rejects_wrong_observed_equipment_state(self):
        design = self.design('walk')
        design_path = self.write_design(design)
        still = self.completed_still(design_path, design)
        report = self.review_report(design, still, observed='ready')
        with self.assertRaisesRegex(ValueError, 'Observed equipment state'):
            veo.review_still(design_path, self.batch, 'knight', 'walk', still, report)

    def test_still_review_template_is_hash_bound_and_never_auto_passes(self):
        design = self.design('walk')
        design_path = self.write_design(design)
        still = self.completed_still(design_path, design)
        report = self.root / 'still-review-template.json'
        result = veo.still_review_template(
            design_path, self.batch, 'knight', 'walk', still, report)
        template = motion.read(report)
        self.assertEqual(result['state'], 'needs_visual_review')
        self.assertTrue(all(value is False for value in template['checks'].values()))
        self.assertEqual(template['observed_equipment_start_state'], '')
        with self.assertRaisesRegex(ValueError, 'equipment state'):
            veo.review_still(design_path, self.batch, 'knight', 'walk', still, report)

    def test_reviewed_still_prepares_veo_job_with_full_provenance(self):
        design = self.design('walk')
        design_path, still = self.reviewed_still(design)
        video = self.root / 'veo-video'
        result = veo.prepare_video(design_path, self.batch, 'knight', 'walk', still, video)
        packet, state = mxapi.read_job(video)
        still_packet, still_state = mxapi.read_job(still)
        workflow = packet['workflow']
        self.assertEqual(result['model'], 'veo-3.1-fast')
        self.assertFalse(result['generation_submitted'])
        self.assertEqual(packet['body']['images'], still_state['result_urls'])
        self.assertEqual(workflow['phase'], 'action_video')
        self.assertEqual(workflow['design_sha256'], veo.design_digest(design))
        self.assertEqual(workflow['coverage_binding'], self.binding('walk'))
        self.assertEqual(workflow['action_still_request_sha256'], still_state['request_sha256'])
        self.assertEqual(workflow['action_still_review_sha256'], veo.file_digest(still / 'still-review.json'))
        self.assertEqual(workflow['identity_character_sha256'], still_packet['workflow']['identity_source']['character_sha256'])
        self.assertEqual(state['request_sha256'], mxapi.digest(packet))

    def test_tampered_design_or_review_cannot_prepare_video(self):
        design = self.design('walk')
        design_path, still = self.reviewed_still(design, 'tamper-design')
        changed = copy.deepcopy(design)
        changed['end_pose'] = 'a materially different end pose'
        motion.write(design_path, changed)
        with self.assertRaisesRegex(ValueError, 'another, changed, or unbound design'):
            veo.prepare_video(design_path, self.batch, 'knight', 'walk', still, self.root / 'video-after-design-change')

        design2 = self.design('walk')
        design_path2, still2 = self.reviewed_still(design2, 'tamper-review')
        review = motion.read(still2 / 'still-review.json')
        review['notes'] = 'Changed after approval.'
        motion.write(still2 / 'still-review.json', review)
        with self.assertRaisesRegex(ValueError, 'current visual review'):
            veo.prepare_video(design_path2, self.batch, 'knight', 'walk', still2, self.root / 'video-after-review-change')

    def test_reviewed_still_cannot_swap_provider_url_or_local_pixels(self):
        for change in ('url', 'pixels'):
            with self.subTest(change=change):
                design = self.design('walk')
                path, still = self.reviewed_still(design, 'changed-' + change)
                if change == 'url':
                    state = motion.read(still / 'job.json')
                    state['result_urls'] = ['https://example.com/unreviewed-still.png']
                    motion.write(still / 'job.json', state)
                else:
                    Image.new('RGBA', (96, 54), 'red').save(still / 'result-00.png')
                destination = self.root / ('rejected-video-' + change)
                with self.assertRaisesRegex(ValueError, 'current inputs'):
                    veo.prepare_video(path, self.batch, 'knight', 'walk', still, destination)
                self.assertFalse(destination.exists())

    def test_identity_changes_and_key_color_conflicts_stop_before_still_creation(self):
        original = self.character.read_bytes()
        Image.new('RGBA', (18, 26), 'red').save(self.character)
        with self.assertRaisesRegex(ValueError, 'Batch character changed'):
            veo.identity_source(self.batch, 'knight', self.identity_job('changed-character'))
        self.character.write_bytes(original)
        for mode, color in [('green', (0, 255, 0, 255)), ('magenta', (255, 0, 255, 255))]:
            with self.subTest(mode=mode):
                image_path = self.root / (mode + '-costume.png')
                Image.new('RGBA', (18, 26), color).save(image_path)
                scope = motion.read(self.scope)
                scope['characters']['knight']['character'] = str(image_path)
                scope_path = self.root / (mode + '-scope.json')
                motion.write(scope_path, scope)
                batch_path = self.root / (mode + '-batch')
                batch.create(scope_path, batch_path)
                identity = self.successful_image_job(mode + '-identity', image_path)
                design = self.design('walk')
                design['coverage_binding'] = batch.binding(batch_path, 'knight', 'walk')
                design['background_mode'] = mode
                design_path = self.write_design(design, mode + '-design.json')
                output = self.root / (mode + '-still')
                with self.assertRaisesRegex(ValueError, 'selected key color'):
                    veo.prepare_still(design_path, batch_path, 'knight', 'walk', identity, output)
                self.assertFalse(output.exists())

    def test_death_design_holds_full_body_and_dropped_equipment(self):
        design = self.design('sword_slash', equipment='ready')
        design.update(action_id='death', coverage_binding=self.binding('death'),
                      gameplay_context=self.binding('death')['requirement']['purpose'],
                      start_pose='upright wounded guard with knees failing',
                      end_pose='full-size body lying on its side with dropped sword beside it',
                      recovery_or_hold='hold the full-size settled body; never stand, shrink or loop')
        design['equipment_policy'].update(end_state='dropped', hands_at_end='both hands empty',
                                          motion='release the sword on collapse and leave it beside the body')
        for phase, name, state in zip(design['phases'],
                                      ['buckle', 'fall', 'impact', 'settle'],
                                      ['ready', 'dropped', 'dropped', 'dropped']):
            phase.update(name=name, body_motion=name + ' under gravity without changing body scale',
                         equipment_state=state, equipment_motion='sword is ' + state,
                         game_event='enter dead state' if name == 'impact' else 'none')
        prompt = veo.prompts(design)['video_prompt']
        self.assertIn('One complete action only', prompt)
        self.assertIn('full-size settled body', prompt)
        self.assertIn('start=ready, end=dropped', prompt)
        self.assertNotIn('Show at least', prompt)
        path, still = self.reviewed_still(design, 'death')
        output = self.root / 'death-video'
        veo.prepare_video(path, self.batch, 'knight', 'death', still, output)
        self.assertEqual(mxapi.read_job(output)[0]['workflow']['coverage_binding'], self.binding('death'))

    def test_two_skill_designs_and_prompts_cannot_be_mixed(self):
        slash = self.design('sword_slash', equipment='ready')
        spell = self.design('cast_fire')
        slash_prompt = veo.prompts(slash)['video_prompt']
        spell_prompt = veo.prompts(spell)['video_prompt']
        self.assertIn('horizontal cut', slash_prompt)
        self.assertNotIn('fire-bolt sigil', slash_prompt)
        self.assertIn('fire-bolt sigil', spell_prompt)
        self.assertNotIn('horizontal cut', spell_prompt)

        slash_path, slash_still = self.reviewed_still(slash, 'slash')
        spell_path = self.write_design(spell, 'spell-design.json')
        with self.assertRaisesRegex(ValueError, 'another, changed, or unbound design'):
            veo.prepare_video(spell_path, self.batch, 'knight', 'cast_fire', slash_still, self.root / 'mixed-video')
        with self.assertRaisesRegex(ValueError, 'current project coverage binding'):
            veo.load_bound_design(slash_path, self.batch, 'knight', 'cast_fire')

    def test_existing_image_prepares_only_video_without_still_or_visual_review(self):
        design = self.design('walk')
        path = self.write_design(design)
        identity = self.identity_job()
        video = self.root / 'direct-veo'
        with patch.object(mxapi, 'prepare', wraps=mxapi.prepare) as prepare, \
                patch.object(veo, '_reviewed_still', side_effect=AssertionError('No still review allowed')), \
                patch.object(veo, '_contains_key_color', side_effect=AssertionError('Existing identity is reused')):
            result = veo.prepare_video(path, self.batch, 'knight', 'walk', None, video,
                                       existing_image_job=identity,
                                       source_risk_notes='Sword is already drawn in original; user authorized direct reuse.')
        self.assertEqual(prepare.call_count, 1)
        self.assertEqual(prepare.call_args.args[1], 'veo-3.1-fast')
        packet, state = mxapi.read_job(video)
        self.assertEqual(result['source_mode'], 'existing_image')
        self.assertFalse(result['generation_submitted'])
        self.assertEqual(state['state'], 'prepared')
        self.assertEqual(packet['body']['images'], ['https://example.com/identity.png'])
        self.assertNotIn('reviewed action-specific start still', packet['body']['prompt'])
        self.assertNotIn('action_still_review_sha256', packet['workflow'])
        self.assertIn('already drawn', packet['workflow']['source_risk_notes'])

    def test_existing_image_keeps_identity_and_design_gates(self):
        path = self.write_design(self.design('walk'))
        wrong_image = self.root / 'wrong.png'
        Image.new('RGBA', (18, 26), 'red').save(wrong_image)
        wrong = self.successful_image_job('wrong-identity', wrong_image)
        with self.assertRaisesRegex(ValueError, 'does not match'):
            veo.prepare_video(path, self.batch, 'knight', 'walk', None, self.root / 'bad-video',
                              existing_image_job=wrong)
        with self.assertRaisesRegex(ValueError, 'coverage binding'):
            veo.prepare_video(path, self.batch, 'knight', 'cast_fire', None, self.root / 'bad-action',
                              existing_image_job=wrong)

    def test_existing_image_cli_and_generation_evidence(self):
        import contextlib
        import io
        import video_sample
        path = self.write_design(self.design('walk'))
        identity = self.identity_job()
        video_job = self.root / 'direct-cli'
        argv = ['veo_workflow.py', 'prepare-video', '--batch', str(self.batch), '--character', 'knight',
                '--action', 'walk', '--design', str(path), '--existing-image-job', str(identity), '--job', str(video_job)]
        with patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(veo.main(), 0)
        video = video_job / 'result-00.mp4'
        video.write_bytes(b'Synthetic provenance fixture, not generated video')
        packet, state = mxapi.read_job(video_job)
        state.update(state='succeeded', local_results=[str(video)], result_urls=['https://example.com/video.mp4'])
        motion.write(video_job / 'job.json', state)
        evidence, _ = video_sample.validate_generation_job(video_job, video, self.binding('walk'))
        self.assertEqual(evidence['source_mode'], 'existing_image')
        self.assertEqual(evidence['identity_character_sha256'], veo.file_digest(self.character))
        packet['workflow']['action_still_review_sha256'] = '0' * 64
        state['request_sha256'] = mxapi.digest(packet)
        motion.write(video_job / 'request.json', packet)
        motion.write(video_job / 'job.json', state)
        with self.assertRaisesRegex(ValueError, 'fabricated still review'):
            video_sample.validate_generation_job(video_job, video, self.binding('walk'))


if __name__ == '__main__':
    unittest.main()
