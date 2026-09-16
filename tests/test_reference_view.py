"""Reference-view compatibility; fixture-only, no provider requests."""
import copy
import unittest

import test_veo_workflow as fixtures
import motion
import veo_workflow as veo


class ReferenceViewTests(unittest.TestCase):
    setUp = fixtures.VeoWorkflowTests.setUp
    binding = fixtures.VeoWorkflowTests.binding
    design = fixtures.VeoWorkflowTests.design

    def reference_design(self):
        design = self.design()
        design['facing'] = 'reference_view'
        design['view_policy'] = {'mode': 'preserve_original_reference_view', 'user_required_side_view': False}
        return design

    def test_authored_reference_prompt_is_preserved_exactly(self):
        design = self.reference_design()
        authored = ' Preserve the supplied three-quarter viewpoint.\nWalk with the original equipment. '
        design['video_prompt'] = authored
        before = copy.deepcopy(design)
        veo.validate_design(design, self.binding('walk'))
        prompts = veo.prompts(design)
        self.assertEqual(prompts['video_prompt'], authored)
        self.assertNotIn('Strict 90-degree', prompts['still_prompt'])
        self.assertEqual(design, before)

    def test_reference_fallback_preserves_view_without_profile_template(self):
        prompts = veo.prompts(self.reference_design())
        for prompt in prompts.values():
            self.assertIn('Preserve the original viewing angle', prompt)
            self.assertNotIn('Strict 90-degree', prompt)
            self.assertNotIn('facing screen left', prompt)
            self.assertIn('fixed scale', prompt.lower())

    def test_authored_background_selection_uses_the_actual_blue_key(self):
        design = self.reference_design()
        design['background_mode'] = 'blue'
        for prompt in veo.prompts(design).values():
            self.assertIn('pure blue #0000FF', prompt)
            self.assertNotIn('bright green', prompt)
            self.assertNotIn('bright magenta', prompt)
        design['background_mode'] = 'unreviewed-custom-color'
        with self.assertRaisesRegex(ValueError, 'background_mode'):
            veo.validate_design(design)

    def test_reference_policy_is_required_and_must_not_claim_required_side_view(self):
        for policy in (None, {}, 'reference_view', {'mode': 'strict_side_profile', 'user_required_side_view': False},
                       {'mode': 'preserve_original_reference_view', 'user_required_side_view': True},
                       {'mode': 'preserve_original_reference_view', 'user_required_side_view': 0}):
            with self.subTest(policy=policy):
                design = self.reference_design()
                design['view_policy'] = policy
                with self.assertRaisesRegex(ValueError, 'reference_view requires'):
                    veo.validate_design(design)

    def test_empty_or_nontext_authored_prompt_is_not_silently_replaced(self):
        for prompt in ('', '  ', None, 12):
            design = self.reference_design()
            design['video_prompt'] = prompt
            with self.assertRaisesRegex(ValueError, 'authored reference-view video prompt'):
                veo.prompts(design)

    def test_legacy_left_and_right_profiles_keep_the_same_template(self):
        for facing, direction in [('right_profile', 'screen right'), ('left_profile', 'screen left')]:
            design = self.design()
            design['facing'] = facing
            expected = veo.prompts(design)
            design['video_prompt'] = 'Unrelated extension was not used by the old profile path.'
            self.assertEqual(veo.prompts(design), expected)
            for prompt in expected.values():
                self.assertIn(f'Strict 90-degree side profile facing {direction}; fixed camera, fixed scale, no turn toward camera. ', prompt)

    def test_reference_design_stays_bound_and_policy_and_prompt_are_hashed(self):
        design = self.reference_design()
        original = veo.design_digest(design)
        design['video_prompt'] = 'Preserve the original reference viewpoint.'
        self.assertNotEqual(original, veo.design_digest(design))
        before = veo.design_digest(design)
        design['view_policy']['author_notes'] = 'Original source is three-quarter, not side-on.'
        self.assertNotEqual(before, veo.design_digest(design))
        with self.assertRaisesRegex(ValueError, 'coverage binding'):
            veo.validate_design(design, {**self.binding('walk'), 'action': 'death'})

    def test_loading_requires_real_provider_binding_not_deferred_production_intent(self):
        design = self.reference_design()
        path = self.root / 'reference-design.json'
        motion.write(path, design)
        self.assertEqual(veo.load_bound_design(path, self.batch, 'knight', 'walk'), design)
        design['production_intent_binding'] = design.pop('coverage_binding')
        design['provider_coverage_binding'] = None
        design['provider_binding_state'] = 'deferred_until_actual_prepared_reference_is_verified'
        motion.write(path, design)
        with self.assertRaisesRegex(ValueError, 'coverage binding'):
            veo.load_bound_design(path, self.batch, 'knight', 'walk')


if __name__ == '__main__':
    unittest.main()
