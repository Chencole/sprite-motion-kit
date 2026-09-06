"""Regressions for lost motion that stays inside per-frame angle tolerance."""
import copy
import math
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

SCRIPTS=Path(__file__).resolve().parents[1]/'plugins/sprite-motion-kit/skills/sprite-motion/scripts'
sys.path.insert(0,str(SCRIPTS))
import motion
import quality


class SegmentMotionTests(unittest.TestCase):
    edges=[['head','shoulder'],['shoulder','hip'],['shoulder','elbow'],['elbow','hand']]

    def poses(self,angles,forearm=40):
        frames=[]
        for degrees in angles:
            a=math.radians(degrees)
            frames.append({'head':[50,10],'shoulder':[50,30],'hip':[50,70],
                           'elbow':[70,40],'hand':[70+forearm*math.cos(a),40+forearm*math.sin(a)]})
        return frames

    def observe(self,frames):
        return [{'frame':i,'points':copy.deepcopy(f)} for i,f in enumerate(frames)]

    def test_repeating_first_pose_cannot_pass_material_arm_swing(self):
        ref=self.poses([0,30,0,-30,0]);observed=self.observe([ref[0]]*5)
        # Both endpoints are identical and every per-frame error is at most
        # 30 degrees, so neither the endpoint nor old 32-degree gate caught it.
        self.assertEqual(quality.endpoint_check(ref,observed,self.edges,False)['max_error_pixels'],0)
        with self.assertRaisesRegex(ValueError,'loses material movement'):
            quality.compare(ref,observed,self.edges)

    def test_token_arm_movement_cannot_replace_reference_swing(self):
        ref=self.poses([0,30,0,-30,0]);observed=self.observe(self.poses([0,5,0,-5,0]))
        with self.assertRaisesRegex(ValueError,'loses material movement'):
            quality.compare(ref,observed,self.edges)

    def test_same_amplitude_in_opposite_phases_is_rejected(self):
        ref=self.poses([0,15,0,-15,0]);observed=self.observe(self.poses([0,-15,0,15,0]))
        # Amplitudes match and each angle error is below the existing limit.
        with self.assertRaisesRegex(ValueError,'reference phases'):
            quality.compare(ref,observed,self.edges)

    def test_correct_motion_preserves_different_proportions_scale_and_offset(self):
        ref=self.poses([0,30,0,-30,0]);observed=self.observe(self.poses([0,30,0,-30,0],forearm=58))
        for f in observed:
            # A longer forearm and shorter torso are legitimate character
            # proportions, while the exact directed action remains intact.
            f['points']['hip']=[50,60]
            f['points']={n:(np.array(p)*.55+[120,80]).tolist() for n,p in f['points'].items()}
        result=quality.compare(ref,observed,self.edges)
        self.assertTrue(result['passed']);self.assertEqual(len(result['segment_motion']),1)
        self.assertAlmostEqual(result['segment_motion'][0]['phase_correlation'],1)

    def test_small_annotation_or_incidental_motion_does_not_require_swing(self):
        ref=self.poses([0,3,0,-3,0]);observed=self.observe([ref[0]]*5)
        result=quality.compare(ref,observed,self.edges)
        self.assertTrue(result['passed']);self.assertEqual(result['segment_motion'],[])

    def test_direction_motion_across_angle_wrap_is_not_a_false_mismatch(self):
        ref=self.poses([175,205,175,145,175]);observed=self.observe(ref)
        self.assertTrue(quality.compare(ref,observed,self.edges)['passed'])

    def test_subpixel_travel_on_tiny_segment_is_not_material_motion(self):
        ref=self.poses([0,30,0,-30,0],forearm=1);observed=self.observe([ref[0]]*5)
        result=quality.compare(ref,observed,self.edges)
        self.assertTrue(result['passed']);self.assertEqual(result['segment_motion'],[])


class PlaybackFingerprintTests(unittest.TestCase):
    def test_custom_playback_change_invalidates_its_input_hash(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            for name in ['plan.json','character.png','guide.png','playback.png']:
                (root/name).write_bytes(name.encode())
            data={'schema':2,'motion_plan':'plan.json','character':'character.png',
                  'actions':{'swing':{'guide':'guide.png','reference':'playback.png'}}}
            before=motion.fingerprints(root,data)
            (root/'playback.png').write_bytes(b'different playback')
            after=motion.fingerprints(root,data)
            self.assertNotEqual(before['reference:swing'],after['reference:swing'])
            self.assertEqual({k:v for k,v in before.items() if k!='reference:swing'},
                             {k:v for k,v in after.items() if k!='reference:swing'})


if __name__=='__main__':unittest.main()
