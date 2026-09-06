import copy,sys,tempfile,unittest
from pathlib import Path
import numpy as np
from PIL import Image
SCRIPTS=Path(__file__).resolve().parents[1]/'plugins/sprite-motion-kit/skills/sprite-motion/scripts'
sys.path.insert(0,str(SCRIPTS))
import quality,motion,mannequin

class PoseQualityTests(unittest.TestCase):
    def setUp(self):
        self.ref=quality.read(SCRIPTS.parent/'assets/walk-landmarks.json')
        self.obs=[{'frame':i,'points':copy.deepcopy(f)} for i,f in enumerate(self.ref['frames'])]
    def test_correct_phase_angles_allow_scale_and_translation(self):
        for f in self.obs:f['points']={k:(np.array(v)*.55+[100,45]).tolist() for k,v in f['points'].items()}
        self.assertTrue(quality.compare(self.ref['frames'],self.obs,self.ref['edges'])['passed'])
    def test_first_four_repeated_poses_rejected(self):
        for i in range(4):self.obs[i]['points']=copy.deepcopy(self.ref['frames'][0])
        with self.assertRaisesRegex(ValueError,'reference phases'):quality.compare(self.ref['frames'],self.obs,self.ref['edges'])
    def test_moving_only_boot_does_not_fake_thigh_passing(self):
        self.obs[2]['points']['near_knee']=self.ref['frames'][0]['near_knee']
        with self.assertRaises(ValueError):quality.compare(self.ref['frames'],self.obs,self.ref['edges'])
    def test_missing_and_reordered_frames_rejected(self):
        for obs in [self.obs[:4],self.obs[::-1]]:
            with self.assertRaises(ValueError):quality.compare(self.ref['frames'],obs,self.ref['edges'])
    def test_nonfinite_and_unobserved_landmarks_rejected(self):
        for p in [None,[float('nan'),0]]:
            obs=copy.deepcopy(self.obs);obs[3]['points']['near_knee']=p
            with self.assertRaises(ValueError):quality.compare(self.ref['frames'],obs,self.ref['edges'])
    def test_folded_normal_walk_reference_rejected(self):
        p=mannequin.scaffold('humanoid',['walk'],examples=True)
        for k in p['actions']['walk']['keys']:
            for side in ['near','far']:k['rotations'][side+'_knee']=[0,0,-85]
        self.assertEqual(len(quality.reference_issues(p,mannequin)),2)
    def test_crouch_action_is_not_forced_into_normal_walk(self):
        p=mannequin.scaffold('humanoid',['crouch'],examples=True)
        self.assertEqual(quality.reference_issues(p,mannequin),[])
    def test_missing_evidence_cannot_export(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);im=Image.new('RGBA',(20,20),'blue');im.save(d/'char.png')
            motion.prepare(d/'char.png',d/'job',actions=['walk'],legacy_reference_reason='Fixture for evidence gate')
            atlas=Image.new('RGBA',(400,200))
            for i in range(8):atlas.paste(im,(i%4*100+40,i//4*100+40))
            atlas.save(d/'sheet.png')
            with self.assertRaisesRegex(ValueError,'observations required'):motion.pack(d/'job','walk',d/'sheet.png')
            motion.pack(d/'job','walk',d/'sheet.png',draft=True)
            self.assertTrue(motion.read(d/'job/walk/clip.json')['draft'])
    def test_changed_source_invalidates_review(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);Image.new('RGBA',(20,20),'blue').save(d/'char.png')
            motion.prepare(d/'char.png',d/'job',actions=['walk'],legacy_reference_reason='Approved human reference fixture')
            Image.new('RGB',(1536,1104),'blue').save(d/'source.png');data=motion.read(d/'job/job.json')
            report=quality.observations_template(d/'job',data,'walk',d/'source.png',mannequin)
            report.update(frames=self.obs,notes='Synthetic landmarks test geometry, not real pixel recognition.')
            report['visual_checks']={k:True for k in report['visual_checks']}
            self.assertTrue(quality.check(d/'job',data,'walk',d/'source.png',report,mannequin)['passed'])
            Image.new('RGB',(100,100),'red').save(d/'source.png')
            with self.assertRaisesRegex(ValueError,'exact action'):quality.check(d/'job',data,'walk',d/'source.png',report,mannequin)
    def test_export_does_not_introduce_per_frame_anchor_changes(self):
        frames=[]
        for x,y in [(30,60),(34,40),(38,60)]:
            im=Image.new('RGBA',(100,100));im.paste('blue',(x,y,x+20,y+20));frames.append(im)
        result,meta=motion.align_canvas(frames,(200,200),100)
        self.assertEqual(len({tuple(m['translation']) for m in meta}),1)
        self.assertLess(result[1].getbbox()[1],result[0].getbbox()[1])
        self.assertGreater(result[2].getbbox()[0],result[0].getbbox()[0])
    def test_four_frame_trial_preserves_opposite_contacts(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);Image.new('RGBA',(20,20),'blue').save(d/'char.png')
            motion.prepare(d/'char.png',d/'job',actions=['walk'],frame_indices=[0,2,4,6],legacy_reference_reason='Approved source reduced to two contacts and two passing poses')
            data=motion.read(d/'job/job.json');ref,edges=quality.reference_points(d/'job',data,'walk',mannequin)
            self.assertEqual(data['actions']['walk']['count'],4)
            self.assertEqual(data['actions']['walk']['phases'],[0,.25,.5,.75])
            self.assertEqual(ref[2],self.ref['frames'][4])
            motion.phase_inputs(d/'job','walk',d/'phase-inputs')
            split=motion.read(d/'phase-inputs/phases.json')
            self.assertEqual([f['frame'] for f in split['frames']],[0,1,2,3])
            self.assertEqual([f['phase'] for f in split['frames']],[0,.25,.5,.75])

if __name__=='__main__':unittest.main()
