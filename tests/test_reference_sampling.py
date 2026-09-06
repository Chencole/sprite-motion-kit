import copy
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from PIL import Image

S=Path(__file__).resolve().parents[1]/'plugins/sprite-motion-kit/skills/sprite-motion/scripts'
sys.path.insert(0,str(S))
import reference_bundle


def walking_points(crouched=False,repeated_leg=False):
    frames=[]
    for i in range(8):
        stride=20*math.cos(i*math.tau/8);frame={}
        for side,hipx,step in [('near',50,stride),('far',52,stride+10 if repeated_leg else -stride)]:
            frame[side+'_hip']=[hipx,35]
            frame[side+'_ankle']=[hipx+step,85]
            frame[side+'_knee']=[hipx+step/2+(25 if crouched else 0),60]
        frames.append(frame)
    return frames


class ReferenceSamplingTests(unittest.TestCase):
    def test_full_loop_omits_duplicate_endpoint_and_half_cycle_is_rejected(self):
        result=reference_bundle.assess_phase_coverage([i/8 for i in range(8)],True)
        self.assertTrue(result['passed']);self.assertEqual(result['wrap_gap'],.125)
        self.assertFalse(reference_bundle.assess_phase_coverage([i/16 for i in range(8)],True)['passed'])
        self.assertFalse(reference_bundle.assess_phase_coverage([0,.25,.5],True)['passed'])
        with self.assertRaisesRegex(ValueError,'ordered phases'):
            reference_bundle.assess_phase_coverage([i/7 for i in range(8)],True)

    def test_one_shot_requires_final_phase_and_uneven_loop_keys_remain_allowed(self):
        self.assertTrue(reference_bundle.assess_phase_coverage([i/7 for i in range(8)],False)['passed'])
        self.assertFalse(reference_bundle.assess_phase_coverage([i/8 for i in range(8)],False)['passed'])
        self.assertTrue(reference_bundle.assess_phase_coverage([0,.1,.2,.3,.4,.55,.7,.9],True)['passed'])

    def test_good_walk_measures_two_hip_crossings_and_leg_exchange(self):
        result=reference_bundle.assess_sampled_humanoid_walk(walking_points())
        self.assertTrue(result['passed']);self.assertTrue(result['ankle_order_exchanges'])
        for leg in result['legs'].values():
            self.assertTrue(leg['crosses_hip']);self.assertAlmostEqual(leg['max_knee_extension_degrees'],180)

    def test_repeated_leg_motion_is_rejected_even_when_each_ankle_crosses_hip(self):
        result=reference_bundle.assess_sampled_humanoid_walk(walking_points(repeated_leg=True))
        self.assertTrue(all(leg['crosses_hip'] for leg in result['legs'].values()))
        self.assertFalse(result['passed']);self.assertFalse(result['ankle_order_exchanges'])

    def test_trailing_ankle_is_rejected_and_small_jitter_does_not_count_as_crossing(self):
        frames=walking_points()
        for i,frame in enumerate(frames):
            frame['near_ankle'][0]=frame['near_hip'][0]+.1*math.cos(i*math.tau/8)
        result=reference_bundle.assess_sampled_humanoid_walk(frames)
        self.assertFalse(result['passed']);self.assertFalse(result['legs']['near']['crosses_hip'])

    def test_crouched_extension_requires_explicit_reason_and_keeps_exchange_check(self):
        frames=walking_points(crouched=True)
        normal=reference_bundle.assess_sampled_humanoid_walk(frames)
        self.assertFalse(normal['passed']);self.assertLess(normal['legs']['near']['max_knee_extension_degrees'],150)
        with self.assertRaisesRegex(ValueError,'gait_reason'):
            reference_bundle.assess_sampled_humanoid_walk(frames,'crouched')
        intentional=reference_bundle.assess_sampled_humanoid_walk(frames,'crouched',{'gait_reason':'Deliberately crouches below the low tunnel ceiling'})
        self.assertTrue(intentional['passed']);self.assertIsNone(intentional['extension_requirement_degrees'])
        self.assertFalse(reference_bundle.assess_sampled_humanoid_walk(walking_points(True,True),'digitigrade',{'gait_reason':'Digitigrade creature with deliberately bent knees'})['passed'])

    def test_unknown_anatomy_is_explicitly_unassessed(self):
        result=reference_bundle.assess_sampled_humanoid_walk([{'body':[20,20],'tail':[30,20]}]*8)
        self.assertEqual(result['status'],'not_assessed');self.assertIsNone(result['passed'])
        self.assertIn('near_ankle',result['missing_joints'])

    def fixture(self,root):
        Image.new('RGB',(512,256),'blue').save(root/'guide.png')
        Image.new('RGB',(512,256),'blue').save(root/'reference.png')
        points={'frames':walking_points(),'edges':[[side+'_'+a,side+'_'+b] for side in ('near','far') for a,b in [('hip','knee'),('knee','ankle')]]}
        (root/'points.json').write_text(json.dumps(points),encoding='utf-8')
        action={'guide':'guide.png','reference':'reference.png','landmarks':'points.json','columns':4,'rows':2,'count':8,'tile':[128,128],
                'origin':[64,90],'floor_y':90,'loop':True,'seconds':1.3,'phases':[i/8 for i in range(8)],
                'reference_layout':{'tile':[128,128],'columns':4,'count':8},'design':dict.fromkeys(['intent','support_and_contact','phases','end_state'],'Synthetic side-view walking test')}
        return {'schema':1,'source_description':'Synthetic test reference','reuse_reason':'Exercise reference sampling validation','source_asset_sha256':'a'*64,
                'character_analysis':dict.fromkeys(['anatomy','mass_and_balance','equipment'],'Synthetic humanoid'),'actions':{'walk':action}}

    def test_import_rejects_half_cycle_and_bad_legs_before_writing_job(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);data=self.fixture(root)
            result=reference_bundle.validate(data,root)
            self.assertTrue(result['walk']['sampled_humanoid_walk']['passed'])
            half=copy.deepcopy(data);half['actions']['walk']['phases']=[i/16 for i in range(8)]
            with self.assertRaisesRegex(ValueError,'phase coverage'):reference_bundle.validate(half,root)
            points=json.loads((root/'points.json').read_text(encoding='utf-8'));points['frames']=walking_points(repeated_leg=True)
            (root/'points.json').write_text(json.dumps(points),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'ankle ordering'):reference_bundle.validate(data,root)

    def test_prepare_records_measured_reference_assessment(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);data=self.fixture(root)
            (root/'bundle.json').write_text(json.dumps(data),encoding='utf-8')
            Image.new('RGB',(16,16),'brown').save(root/'character.png')
            reference_bundle.prepare(root/'character.png',root/'job',root/'bundle.json','Fixture','magenta')
            job=json.loads((root/'job/job.json').read_text(encoding='utf-8'))
            report=job['actions']['walk']['reference_assessment']
            self.assertTrue(report['phase_coverage']['passed']);self.assertTrue(report['sampled_humanoid_walk']['passed'])


if __name__=='__main__':unittest.main()
