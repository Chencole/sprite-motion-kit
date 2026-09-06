import copy,json,sys,tempfile,unittest
from pathlib import Path
from PIL import Image
S=Path(__file__).resolve().parents[1]/'plugins/sprite-motion-kit/skills/sprite-motion/scripts'
sys.path.insert(0,str(S))
import motion,quality,reference_bundle

class BundleTests(unittest.TestCase):
    def fixture(self,d):
        Image.new('RGBA',(16,16),'brown').save(d/'character.png')
        Image.new('RGB',(128,64),'blue').save(d/'guide.png')
        Image.new('RGB',(128,64),'blue').save(d/'reference.png')
        motion.write(d/'points.json',{'edges':[['hip','foot']], 'frames':[{'hip':[32,20+i],'foot':[30+i,52]} for i in range(8)]})
        action={'guide':'guide.png','reference':'reference.png','landmarks':'points.json','columns':4,'rows':2,'count':8,'tile':[32,32], 'origin':[16,28],'floor_y':28,'loop':False,'seconds':1,'phases':[i/7 for i in range(8)],'reference_layout':{'tile':[32,32],'columns':4,'count':8},'design':dict.fromkeys(['intent','support_and_contact','phases','end_state'],'Synthetic motion fixture')}
        # Keep projected points in the declared cell.
        motion.write(d/'points.json',{'edges':[['hip','foot']], 'frames':[{'hip':[16,10+i/3],'foot':[15+i/3,28]} for i in range(8)]})
        data={'schema':1,'source_description':'Synthetic 3D render fixture','reuse_reason':'Tests imported reference invariants','source_asset_sha256':'a'*64,'character_analysis':dict.fromkeys(['anatomy','mass_and_balance','equipment'],'Fixture'), 'actions':{a:copy.deepcopy(action) for a in ['walk','run','attack','death','jump']}}
        motion.write(d/'bundle.json',data);return data
    def ready(self,d):
        self.fixture(d);motion.prepare(d/'character.png',d/'job',reference_bundle=d/'bundle.json')
        data=motion.read(d/'job/job.json');r={'input_hashes':data['input_hashes'],'actions':{a:{**dict.fromkeys(['anatomy','support_and_contact','timing','camera','end_state'],True),'notes':'Synthetic fixture accepted only for testing'} for a in data['actions']}}
        motion.write(d/'report.json',r);motion.review_reference(d/'job',d/'report.json');return motion.read(d/'job/job.json')
    def test_all_five_imported_without_replacing_rig_and_requests_locked_until_review(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);self.fixture(d);motion.prepare(d/'character.png',d/'job',reference_bundle=d/'bundle.json')
            data=motion.read(d/'job/job.json');self.assertEqual(set(data['actions']),{'walk','run','attack','death','jump'})
            self.assertFalse(list((d/'job').glob('*-request.txt')))
            self.assertIn('ground y=28',data['actions']['walk']['request_draft'])
            self.assertIn('#FF00FF',data['actions']['walk']['request_draft'])
            self.assertEqual((d/'guide.png').read_bytes(),(d/'job/reference/walk-guide.png').read_bytes())
    def test_changed_preview_cannot_reuse_review(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);data=self.ready(d)
            (d/'job/reference/run-reference.png').write_bytes((d/'character.png').read_bytes())
            with self.assertRaises(ValueError):motion.verify_job_contract(d/'job',data)
    def test_prompt_only_provider_is_blocked_before_requests_are_written(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);self.ready(d);before=(d/'job/job.json').read_bytes()
            motion.write(d/'adapter.json',{'name':'prompt only','evidence':'Test tool schema','parameters':['prompt','referenced_image_paths']})
            with self.assertRaisesRegex(ValueError,'no structured'):motion.generation_check(d/'job',d/'adapter.json')
            self.assertEqual(before,(d/'job/job.json').read_bytes())
            self.assertFalse(list((d/'job').glob('*-request.txt')))
    def test_provider_controls_are_real_arguments_for_all_five(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);self.ready(d)
            motion.write(d/'adapter.json',{'name':'fixture','evidence':'Synthetic schema','parameters':['prompt','size'],'canvas_binding':{'kind':'size_string','parameter':'size'},'supported_sizes':[[128,64]]})
            result=motion.generation_check(d/'job',d/'adapter.json');self.assertEqual(len(result['packets']),5)
            for p in result['packets']:
                r=motion.read(p);self.assertEqual(r['tool_arguments'],{'size':'128x64'});self.assertFalse(r['automatic_retry'])
                self.assertEqual(r['grid'],[4,2]);self.assertEqual(r['cell_ground_y'],28)
    def test_prompt_cannot_masquerade_as_canvas_parameter(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);self.ready(d)
            motion.write(d/'adapter.json',{'name':'fixture','evidence':'Synthetic schema','parameters':['prompt'],'canvas_binding':{'kind':'size_string','parameter':'prompt'},'supported_sizes':[[128,64]]})
            with self.assertRaisesRegex(ValueError,'dedicated'):motion.generation_check(d/'job',d/'adapter.json')
    def test_unsupported_size_rejects_entire_set_without_partial_requests(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);self.ready(d)
            motion.write(d/'adapter.json',{'name':'fixture','evidence':'Synthetic schema','parameters':['width','height'],'canvas_binding':{'kind':'width_height','width':'width','height':'height'},'supported_sizes':[[64,64]]})
            with self.assertRaisesRegex(ValueError,'no confirmed'):motion.generation_check(d/'job',d/'adapter.json')
            self.assertFalse(list((d/'job').glob('*-request.txt')))
    def test_keyed_export_has_real_alpha_and_holds_nonloop_endpoint(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);self.ready(d);im=Image.new('RGB',(128,64),'#ff00ff')
            for i in range(8):
                x=i%4*32;y=i//4*32;im.paste('#704522',(x+12,y+12,x+20,y+25))
            im.save(d/'sheet.png');motion.pack(d/'job','jump',d/'sheet.png',draft=True)
            out=Image.open(d/'job/jump/atlas.png');self.assertEqual(out.mode,'RGBA');self.assertEqual(out.getpixel((0,0))[3],0)
            clip=motion.read(d/'job/jump/clip.json');self.assertEqual(clip['phases'][-1],1);self.assertFalse(clip['loop'])
            self.assertEqual(len({tuple(f['translation']) for f in clip['frames']}),1)
    def test_checkerboard_or_single_alpha_pixel_not_transparent(self):
        im=Image.new('RGBA',(40,40),'white');im.putpixel((1,1),(0,0,0,0))
        with self.assertRaisesRegex(ValueError,'perimeter'):motion.remove_background(im,'auto')
    def test_magenta_character_does_not_get_erased(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);self.fixture(d);Image.new('RGBA',(16,16),'magenta').save(d/'character.png')
            with self.assertRaisesRegex(ValueError,'contains'):motion.prepare(d/'character.png',d/'job',reference_bundle=d/'bundle.json')
            self.assertFalse((d/'job').exists())
    def test_malformed_baseline_and_path_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);data=self.fixture(d)
            for field,value in [('floor_y',70),('guide','../escape.png'),('tile',[30,32])]:
                bad=copy.deepcopy(data);bad['actions']['walk'][field]=value
                with self.assertRaises(ValueError):reference_bundle.validate(bad,d)

class RegistrationTests(unittest.TestCase):
    def test_whole_row_shift_rejected_despite_correct_limb_angles(self):
        ref=quality.read(S.parent/'assets/walk-landmarks.json');obs=[]
        for i,p in enumerate(ref['frames']):obs.append({'frame':i,'points':{n:[v[0],v[1]+(8 if i>=4 else 0)] for n,v in p.items()}})
        with self.assertRaisesRegex(ValueError,'registration'):quality.compare(ref['frames'],obs,ref['edges'])
    def test_reference_jump_height_is_preserved_not_grounded(self):
        refs=[{'hip':[15,20-y],'foot':[15,30-y]} for y in [0,6,12,6,0]]
        obs=[{'frame':i,'points':copy.deepcopy(r)} for i,r in enumerate(refs)]
        self.assertTrue(quality.compare(refs,obs,[['hip','foot']])['passed'])
        for f in obs:f['points']={'hip':[15,20],'foot':[15,30]}
        with self.assertRaisesRegex(ValueError,'registration'):quality.compare(refs,obs,[['hip','foot']])

if __name__=='__main__':unittest.main()
