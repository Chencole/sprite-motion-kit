import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('motion',ROOT/'plugins/sprite-motion-kit/skills/sprite-motion/scripts/motion.py')
motion=importlib.util.module_from_spec(spec);spec.loader.exec_module(motion)

def sheet(cols,rows,death=False,magenta=False):
    im=Image.new('RGBA',(cols*100+1,rows*100+1),(255,0,255,255) if magenta else (0,0,0,0))
    d=ImageDraw.Draw(im)
    for n in range(cols*rows):
        x=round((n%cols)*im.width/cols);y=round((n//cols)*im.height/rows)
        box=(x+15,y+68,x+85,y+85) if death and n>2 else (x+35,y+15,x+60,y+85)
        d.rectangle(box,fill=(80+n*3,140,210,255))
    return im

# These tests isolate packing mechanics; final acceptance is tested separately.
def draft_pack(*args,**kwargs):return motion.pack(*args,**kwargs,draft=True)

class MotionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.character=self.root/'character.png'
        Image.new('RGBA',(20,30),'blue').save(self.character)
        self.job=self.root/'job';motion.prepare(self.character,self.job,legacy_reference_reason='Approved side humanoid walk and fall match this test fixture')
    def test_prepare_preserves_existing_job(self):
        before=(self.job/'job.json').read_bytes()
        with self.assertRaises(ValueError):motion.prepare(self.character,self.job,legacy_reference_reason='Approved side humanoid walk and fall match this test fixture')
        self.assertEqual(before,(self.job/'job.json').read_bytes())
    def test_alpha_and_nondivisible_grid(self):
        frames=motion.extract(sheet(4,2),4,2,8)
        self.assertEqual(len(frames),8)
        self.assertGreater(frames[0].getbbox()[0],0)
    def test_magenta_removal(self):
        f=motion.extract(sheet(4,2,magenta=True),4,2,8)[0]
        self.assertEqual(f.getpixel((0,0))[3],0)
        self.assertEqual(f.getpixel((40,40))[3],255)
    def test_opaque_background_rejected(self):
        with self.assertRaises(ValueError):motion.extract(Image.new('RGB',(200,200),'white'),2,2,4)
    def test_empty_and_clipped_rejected(self):
        for f in [Image.new('RGBA',(100,100)),Image.new('RGBA',(100,100),(0,0,0,0))]:
            with self.assertRaises(ValueError):motion.extract(f,1,1,1)
        f=Image.new('RGBA',(100,100));ImageDraw.Draw(f).rectangle((0,10,30,60),fill='blue')
        with self.assertRaises(ValueError):motion.extract(f,1,1,1)
    def test_death_keeps_one_scale(self):
        frames,meta=motion.align(motion.extract(sheet(4,3,death=True),4,3,12),'death')
        self.assertEqual(len(set(m['scale'] for m in meta)),1)
        self.assertGreater(frames[-1].getbbox()[2]-frames[-1].getbbox()[0],frames[0].getbbox()[2]-frames[0].getbbox()[0])
    def test_overflow_rejected(self):
        with self.assertRaises(ValueError):motion.align(motion.extract(sheet(4,2),4,2,8),'walk',tile=(16,448))
    def test_full_job_and_settled_corpse(self):
        for action,rows in [('walk',2),('death',3)]:
            source=self.root/f'{action}.png';sheet(4,rows,death=action=='death').save(source)
            draft_pack(self.job,action,source,hold_from=8 if action=='death' else None)
        clip=motion.read(self.job/'death/clip.json')
        self.assertFalse(clip['loop']);self.assertFalse(clip['visual_review_passed'])
        self.assertEqual((self.job/'death/frame-008.png').read_bytes(),(self.job/'death/frame-011.png').read_bytes())
        self.assertEqual(clip['frames'][8],clip['frames'][11])
        html=(self.job/'review.html').read_text(encoding='utf-8')
        self.assertIn('data:image/png;base64,',html);self.assertNotIn('__CLIPS__',html)
        self.assertEqual(motion.read(self.job/'job.json')['status'],'awaiting_visual_review')
    def test_invalid_grid_timing_and_hold(self):
        path=self.root/'walk.png';sheet(4,2).save(path)
        for kwargs in [{'count':0},{'columns':0},{'seconds':0},{'seconds':float('nan')},{'phases':[0]*8},{'hold_from':1}]:
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):draft_pack(self.job,'walk',path,**kwargs)
    def test_final_hold_cannot_replace_checked_sequence(self):
        path=self.root/'death.png';sheet(4,3,death=True).save(path)
        before=(self.job/'job.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'replace reviewed motion'):motion.pack(self.job,'death',path,hold_from=0)
        self.assertFalse((self.job/'death').exists());self.assertEqual(before,(self.job/'job.json').read_bytes())
    def test_loop_custom_phases_and_source_repack(self):
        path=self.root/'walk.png';sheet(4,2).save(path)
        phases=[0,.125,.25,.375,.5,.625,.75,.95]
        draft_pack(self.job,'walk',path,phases=phases)
        clip=motion.read(self.job/'walk/clip.json');self.assertEqual(clip['phases'],phases)
        draft_pack(self.job,'walk',self.job/'walk/generated-source.png')

if __name__=='__main__':unittest.main()
