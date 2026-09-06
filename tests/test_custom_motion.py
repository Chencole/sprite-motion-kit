import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
SCRIPTS=ROOT/'plugins/sprite-motion-kit/skills/sprite-motion/scripts'
def module(name):
    spec=importlib.util.spec_from_file_location(name,SCRIPTS/(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
m=module('mannequin');motion=module('motion')

def custom_plan():
    p=m.scaffold('humanoid',['overhead_cut','lunge','hop'])
    p['name']='Authored sword attacks and hop';p['design_status']='authored'
    p['joints'].append({'id':'blade_tip','parent':'near_hand','offset':[0,-.6,0],'radius':.026,'color':'extra'})
    def key(t,shoulder=0,elbow=0,root=None,chest=0,knee=0):
        return {'time':t,'root':root or [0,.055,0], 'rotations':{'near_shoulder':[0,0,shoulder],
            'near_elbow':[0,0,elbow],'chest':[0,0,chest],
            'near_hip':[0,0,-knee*.5],'near_knee':[0,0,knee],
            'far_hip':[0,0,-knee*.5],'far_knee':[0,0,knee]}}
    p['actions']['overhead_cut'].update(seconds=1.3,frame_count=12,description='Lift sword overhead, cut down and recover',keys=[
        key(0,15,-15),key(.35,165,-35,chest=8),key(.5,150,-20,chest=4),
        key(.68,60,10,chest=-12),key(.85,25,5,chest=-8),key(1.3,15,-15)])
    p['actions']['lunge'].update(seconds=1.1,frame_count=10,description='Draw arm back, extend weapon with a forward lunge, recover',keys=[
        key(0,45,-40),key(.25,20,-70,chest=5),key(.48,85,0,[.3,.055,0],-8),
        key(.68,85,0,[.3,.055,0],-8),key(1.1,45,-40)])
    p['actions']['hop'].update(seconds=1.2,frame_count=12,description='Crouch, jump vertically, land and recover',keys=[
        key(0),key(.22,20,-20,[0,-.08,0],knee=-50),key(.4,60,-20,[0,.32,0],knee=-20),
        key(.60,80,-20,[0,.8,0],knee=-30),key(.83,40,-15,[0,.32,0],knee=-20),
        key(1.0,20,-20,[0,-.08,0],knee=-50),key(1.2)])
    p['character_analysis']={'anatomy':'Two legs, two arms, sword attached to near hand','mass_and_balance':'Human mass with planted feet before attacks','equipment':'One sword changes reach and arm swing'}
    for name,a in p['actions'].items():a['design']={'intent':a['description'],'support_and_contact':'Feet support body; hop has an airborne phase','phases':'Anticipation, active action, then recovery','end_state':'Stable upright pose after recovery'}
    return p

# These tests isolate packing mechanics; final acceptance is tested separately.
def draft_pack(*args,**kwargs):return motion.pack(*args,**kwargs,draft=True)

class CustomMotionTests(unittest.TestCase):
    def test_arbitrary_actions_are_not_preset_dispatch(self):
        p=custom_plan();self.assertEqual(m.validate(p)['actions'],['overhead_cut','lunge','hop'])
        p['actions']['strange_new_spell']=p['actions'].pop('lunge')
        self.assertIn('strange_new_spell',m.validate(p)['actions'])
    def test_scaffold_is_neutral_until_ai_authors_it(self):
        p=m.scaffold('humanoid',['walk','another_attack'])
        self.assertEqual(p['design_status'],'needs_motion_design')
        for action in p['actions'].values():
            first=m.positions(p['joints'],action['keys'][0]);last=m.positions(p['joints'],action['keys'][-1])
            self.assertTrue(all(np.allclose(first[j],last[j]) for j in first))
    def test_art_preparation_rejects_unauthored_plan(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'plan.json';m.write(p,m.scaffold('humanoid',['slash']))
            with self.assertRaisesRegex(ValueError,'design this motion plan'):motion.prepare('unused.png',Path(d)/'job',motion_plan=p)
    def test_custom_extra_arms_keep_segment_lengths_and_weapon_attachment(self):
        p=custom_plan();p['body']='six-arm'
        for name in ['middle_near','middle_far','lower_near','lower_far']:
            parent='chest' if name.startswith('middle') else 'spine'
            for joint,offset in [('shoulder',[0,0,.3 if name.endswith('near') else -.3]),('elbow',[0,-.3,0]),('hand',[0,-.25,0]),('weapon',[0,-.4,0])]:
                j=name+'_'+joint;p['joints'].append({'id':j,'parent':parent,'offset':offset,'radius':.04,'color':'extra'});parent=j
        p['actions']['overhead_cut']['keys'][2]['rotations']['lower_near_shoulder']=[30,20,85]
        m.validate(p)
        for t in np.linspace(0,1.3,17):
            points=m.positions(p['joints'],m.sample(p['actions']['overhead_cut'],float(t)))
            for n in p['joints']:
                if n['parent'] is not None:self.assertAlmostEqual(np.linalg.norm(points[n['id']]-points[n['parent']]),np.linalg.norm(n['offset']),places=8)
    def test_different_actions_have_distinct_weapon_trajectories(self):
        p=custom_plan();paths=[]
        for name in ['overhead_cut','lunge']:
            a=p['actions'][name];paths.append(np.array([m.positions(p['joints'],m.sample(a,float(t)))['blade_tip'] for t in np.linspace(0,a['seconds'],12)]))
        self.assertGreater(np.linalg.norm(paths[0]-paths[1]),1)
    def test_quadruped_topology_and_roll_are_not_a_human_fall(self):
        p=m.scaffold('quadruped',['death'],examples=True);m.validate(p)
        self.assertEqual(len([j for j in p['joints'] if j['id'].endswith('_toe')]),4)
        self.assertEqual(p['actions']['death']['keys'][-1]['root_rotation'],[90,0,0])
    def test_invalid_topology_timing_and_nonfinite_rejected(self):
        p=custom_plan()
        changes=[lambda q:q['joints'][1].update(parent='missing'),lambda q:q['joints'][1].update(id='pelvis'),
                 lambda q:q['camera'].update(azimuth=float('nan')),
                 lambda q:q['actions']['hop']['keys'][1].update(time=0),
                 lambda q:q['actions']['hop']['keys'][1].update(rotations={'missing':[0,0,0]}),
                 lambda q:q['actions'].update({'../escape':q['actions']['hop']})]
        for change in changes:
            q=copy.deepcopy(p);change(q)
            with self.assertRaises(ValueError):m.validate(q)
    def test_loop_seam_is_checked(self):
        p=m.scaffold('humanoid',['walk'],examples=True);m.validate(p)
        p['actions']['walk']['keys'][-1]['root'][0]+=.2
        with self.assertRaisesRegex(ValueError,'loop endpoints'):m.validate(p)
    def test_fixed_canvas_preserves_airborne_height(self):
        frames=[]
        for y in [65,20,65]:
            im=Image.new('RGBA',(100,100));im.paste((80,140,210,255),(40,y,60,y+20));frames.append(im)
        result,meta=motion.align_registered(frames,(200,200),[100,100],[50,90])
        self.assertGreater(result[0].getbbox()[1]-result[1].getbbox()[1],80)
        self.assertEqual(meta[0]['origin'],meta[1]['origin'])
        self.assertEqual(meta[0]['scale'],meta[1]['scale'])
    def test_dark_purple_is_not_chroma_key(self):
        im=Image.new('RGB',(100,100),'magenta');im.paste((90,20,140),(20,20,80,80))
        keyed=motion.remove_background(im,'magenta')
        self.assertEqual(keyed.getpixel((0,0))[3],0);self.assertEqual(keyed.getpixel((40,40))[3],255)
    def test_default_prepare_cannot_silently_use_legacy(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'custom motion plan is required'):
                motion.prepare('unused.png',Path(d)/'job')
            self.assertFalse((Path(d)/'job').exists())
    def test_missing_character_analysis_and_action_design_fail(self):
        p=custom_plan()
        for section,field in [('character_analysis','mass_and_balance'),('action','support_and_contact')]:
            q=copy.deepcopy(p)
            del (q['character_analysis'] if section=='character_analysis' else q['actions']['hop']['design'])[field]
            with self.assertRaises(ValueError):motion.validate_design(q)
    def test_authored_label_cannot_approve_neutral_scaffold(self):
        p=custom_plan();a=p['actions']['lunge'];a['keys']=[copy.deepcopy(a['keys'][0]) for _ in range(3)]
        for k,t in zip(a['keys'],[0,.5,1.1]):k['time']=t
        with self.assertRaisesRegex(ValueError,'neutral scaffold'):motion.validate_design(p)
    def test_review_gate_and_changed_inputs(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);character=d/'character.png';Image.new('RGBA',(20,30),'blue').save(character)
            p=custom_plan();p['actions']={'hop':p['actions']['hop']};p['frame_size']=[64,64]
            plan=d/'plan.json';m.write(plan,p);job=d/'job'
            result=motion.prepare(character,job,motion_plan=plan)
            self.assertEqual(result['requests'],[]);self.assertFalse((job/'hop-request.txt').exists())
            with self.assertRaisesRegex(ValueError,'not been reviewed'):draft_pack(job,'hop',job/'reference/hop-guide.png')
            data=m.read(job/'job.json');report={'input_hashes':data['input_hashes'],'actions':{'hop':{k:True for k in ['anatomy','support_and_contact','timing','camera','end_state']}}}
            report['actions']['hop']['notes']='Engineering fixture: body rises above floor and returns upright.'
            rp=d/'review.json';m.write(rp,report);motion.review_reference(job,rp)
            self.assertTrue((job/'hop-request.txt').is_file())
            self.assertIn('Human mass',(job/'hop-request.txt').read_text())
            for target in ['character.png','reference/motion-plan.json','reference/hop-guide.png']:
                file=job/target;original=file.read_bytes();file.write_bytes(original+b' ')
                with self.assertRaises(ValueError):draft_pack(job,'hop',job/'reference/hop-guide.png')
                file.write_bytes(original)

    def test_custom_render_and_pack_roundtrip(self):
        # Renderer output is engineering input for this test, not AI character art.
        with tempfile.TemporaryDirectory() as d:
            p=custom_plan();p['actions']={'hop':p['actions']['hop']};p['frame_size']=[160,160]
            job=Path(d)/'job';job.mkdir();m.render(p,job/'reference',preview_count=4)
            guide=m.read(job/'reference/guide.json');a=guide['actions']['hop'];a.update(status='awaiting_generation',guide='reference/hop-guide.png',reference='reference/hop-reference.png')
            Image.new('RGBA',(20,30),'blue').save(job/'character.png')
            data={'schema':2,'character':'character.png','motion_plan':'reference/motion-plan.json','actions':{'hop':a},'plan_sha256':guide['plan_sha256'],'reference_review':{'engineering_fixture':True}}
            data['input_hashes']=motion.fingerprints(job,data);m.write(job/'job.json',data)
            draft_pack(job,'hop',job/'reference/hop-guide.png')
            clip=m.read(job/'hop/clip.json');self.assertEqual(clip['alignment'],'reference_canvas');self.assertFalse(clip['loop'])
            self.assertEqual(clip['plan_sha256'],guide['plan_sha256'])
            self.assertGreater(clip['frames'][0]['bounds'][1]-clip['frames'][5]['bounds'][1],15)
            self.assertIn('reference_layout',(job/'review.html').read_text(encoding='utf-8'))
            self.assertFalse(clip['visual_review_passed'])

if __name__=='__main__':unittest.main()
