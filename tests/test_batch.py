import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image, ImageDraw

SCRIPTS = Path(__file__).resolve().parents[1] / 'plugins/sprite-motion-kit/skills/sprite-motion/scripts'
sys.path.insert(0, str(SCRIPTS))
import batch
import motion


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        # Bookkeeping fixtures use synthetic observations; pose accuracy is tested in test_pose_quality.
        q=motion.quality_module()
        q.reference_points=lambda *args: ([{'a':[0,0],'b':[1,0]} for _ in range(8)],[['a','b']])
        patcher=patch.object(motion,'quality_module',return_value=q);patcher.start();self.addCleanup(patcher.stop)
        self.root = Path(self.temp.name)
        self.character = self.root / 'character.png'
        Image.new('RGBA', (24,40), 'blue').save(self.character)
        self.spec = self.root / 'scope.json'
        motion.write(self.spec, {'request':'Walk, run, two attacks and death for the knight', 'characters':{
            'knight': {'character':'character.png','required_actions':['walk','run','thrust','overhead_cut','death']}}})
        self.batch = self.root / 'batch'; batch.create(self.spec, self.batch)

    def job(self, actions):
        # Use the explicitly approved legacy fixture only to isolate coverage/export bookkeeping.
        job = self.root / ('job-' + '-'.join(actions))
        motion.prepare(self.character, job, legacy_reference_reason='Test fixture approved for export bookkeeping')
        jd = motion.read(job / 'job.json')
        jd['actions'] = {a:dict(jd['actions']['walk']) for a in actions}
        motion.write(job / 'job.json', jd)
        raw = self.root / 'frames.png'
        im = Image.new('RGBA', (400,200)); d=ImageDraw.Draw(im)
        for i in range(8):
            x=i%4*100; y=i//4*100; d.rectangle((x+30,y+15,x+65,y+85), fill='blue')
        im.save(raw)
        for a in actions:
            jd=motion.read(job/'job.json')
            report=motion.quality_module().observations_template(job,jd,a,raw,motion.mannequin_module())
            report['frames']=[{'frame':i,'points':{'a':[30,15],'b':[65,15]}} for i in range(8)]
            report['visual_checks']={k:True for k in report['visual_checks']};report['notes']='Synthetic export bookkeeping fixture only.'
            report_path=self.root/'observations.json';motion.write(report_path,report)
            motion.pack(job,a,raw,observations=report_path)
        batch.attach(self.batch, 'knight', job)
        return job

    def approve(self, action):
        item = next(e for e in batch.status(self.batch)['actions'] if e['action']==action)
        report = self.root / 'report.json'
        motion.write(report, {'artifact_hashes':item['artifact_hashes'], 'checks':{
            k:True for k in ['appearance','whole_body_motion','timing_and_transition','transparency_and_crop','requested_action']},
            'notes':'Synthetic fixture reviewed for this test; not a real art-quality claim.'})
        batch.review(self.batch, 'knight', action, report)

    def test_death_only_cannot_finish(self):
        self.job(['death']); self.approve('death')
        state=batch.status(self.batch)
        self.assertEqual(state['reviewed'],1); self.assertEqual(state['required'],5)
        with self.assertRaisesRegex(ValueError,'run: missing_job'): batch.finish(self.batch)

    def test_draft_cannot_be_accepted_as_completed_art(self):
        job=self.job(['walk'])
        clip=motion.read(job/'walk/clip.json');clip['draft']=True;motion.write(job/'walk/clip.json',clip)
        item=next(e for e in batch.status(self.batch)['actions'] if e['action']=='walk')
        self.assertEqual(item['state'],'incomplete')
        report=self.root/'invalid-approval.json';motion.write(report,{'artifact_hashes':{}})
        with self.assertRaisesRegex(ValueError,'Draft'):batch.review(self.batch,'knight','walk',report)

    def test_all_packed_still_requires_visual_review(self):
        self.job(['walk','run','thrust','overhead_cut','death'])
        with self.assertRaisesRegex(ValueError,'awaiting_visual_review'): batch.finish(self.batch)

    def test_all_reviewed_then_modified_atlas_invalidates(self):
        actions=['walk','run','thrust','overhead_cut','death']; job=self.job(actions)
        for action in actions:self.approve(action)
        self.assertTrue(batch.finish(self.batch)['complete'])
        Image.new('RGBA',(20,20),'red').save(job/'run/atlas.png')
        self.assertFalse(batch.status(self.batch)['complete'])
        with self.assertRaisesRegex(ValueError,'run: awaiting_visual_review'):batch.finish(self.batch)

    def test_scope_cannot_silently_shrink(self):
        scope=motion.read(self.batch/'scope.json');scope['characters']['knight']['required_actions']=['death']
        motion.write(self.batch/'scope.json',scope)
        with self.assertRaisesRegex(ValueError,'Scope changed'):batch.status(self.batch)

    def test_character_mismatch_rejected(self):
        job=self.job(['death'])
        Image.new('RGBA',(24,40),'red').save(job/'character.png')
        with self.assertRaisesRegex(ValueError,'different character'):batch.attach(self.batch,'knight',job)

    def test_repack_and_missing_frame_invalidate(self):
        job=self.job(['death']);self.approve('death')
        (job/'death/frame-003.png').unlink()
        item=next(e for e in batch.status(self.batch)['actions'] if e['action']=='death')
        self.assertEqual(item['state'],'incomplete')

    def test_partial_jobs_combine_without_dropping_actions(self):
        self.job(['walk','run']); self.job(['thrust','overhead_cut','death'])
        for a in ['walk','run','thrust','overhead_cut','death']:self.approve(a)
        self.assertTrue(batch.finish(self.batch)['complete'])


if __name__=='__main__':unittest.main()
