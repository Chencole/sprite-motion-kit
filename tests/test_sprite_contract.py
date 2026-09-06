import copy,json,sys,tempfile,unittest
from pathlib import Path
from PIL import Image
S=Path(__file__).resolve().parents[1]/'plugins/sprite-motion-kit/skills/sprite-motion/scripts'
sys.path.insert(0,str(S))
import sprite_contract as contract
import motion,quality

class ContractTests(unittest.TestCase):
    def test_endpoint_strip_distinguishes_loop_seam_and_settled_hold(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);im=Image.new('RGBA',(40,20),'red');im.paste('blue',(20,0,40,20));im.save(d/'guide.png')
            for loop in [True,False]:
                s={'guide':'guide.png','count':2,'columns':2,'rows':1,'loop':loop,'phases':[0,.5 if loop else 1]}
                contract.endpoints(d,'clip',s)
                with Image.open(d/'clip-endpoints.png') as strip:
                    self.assertEqual(strip.getpixel((0,0)),(255,0,0,255));self.assertEqual(strip.getpixel((20,0)),(0,0,255,255))
                    self.assertEqual(strip.getpixel((40,0)),(255,0,0,255) if loop else (0,0,255,255))
                self.assertEqual(s['endpoints']['transition'],'last_to_first' if loop else 'hold_last')
    def test_reviewed_gutter_crop_is_shared_with_extraction(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);im=Image.new('RGBA',(100,60));im.paste('red',(15,15,25,35));im.paste('blue',(65,15,75,35));im.save(d/'source.png')
            p={'schema':1,'source_sha256':contract.digest(d/'source.png'),'image_size':[100,60],'grid':[2,1,2],'boxes':[[5,5,45,55],[55,5,95,55]],'reviewed':True,'notes':'Two 40x50 cells with 10px gutter and 5px margin'}
            motion.write(d/'crop.json',p);_,rects=contract.load_crop(d/'crop.json',d/'source.png',2,1,2)
            frames=motion.extract(im,2,1,2,rectangles=rects)
            self.assertEqual(frames[0].size,(40,50));self.assertEqual(frames[0].getpixel((10,10)),(255,0,0,255));self.assertEqual(frames[1].getpixel((10,10)),(0,0,255,255))
    def test_unreviewed_or_changed_source_crop_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);Image.new('RGBA',(100,100),'blue').save(d/'source.png')
            contract.crop_template(d/'source.png',2,2,4,d/'crop.json')
            with self.assertRaisesRegex(ValueError,'record actual'):contract.load_crop(d/'crop.json',d/'source.png',2,2,4)
            Image.new('RGBA',(100,100),'red').save(d/'source.png')
            with self.assertRaisesRegex(ValueError,'different source'):contract.load_crop(d/'crop.json',d/'source.png',2,2,4,False)
    def test_individual_body_crops_or_reordered_frames_rejected(self):
        p={'schema':1,'image_size':[100,100],'grid':[2,2,4],'boxes':[[0,0,50,50],[50,0,100,50],[0,50,50,100],[50,50,100,100]]}
        bad=copy.deepcopy(p);bad['boxes'][1]=[60,0,100,50]
        with self.assertRaisesRegex(ValueError,'same canvas'):contract.boxes(bad,(100,100),2,2,4)
        bad=copy.deepcopy(p);bad['boxes'][0],bad['boxes'][1]=bad['boxes'][1],bad['boxes'][0]
        with self.assertRaisesRegex(ValueError,'ordered'):contract.boxes(bad,(100,100),2,2,4)
    def test_automatic_separator_moves_off_body_and_preserves_pixels(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);im=Image.new('RGBA',(80,80))
            for x in [5,45]:
                im.paste('red',(x,10,x+12,42));im.paste('blue',(x,52,x+12,72))
            im.save(d/'s.png');plan=contract.automatic_plan(d/'s.png',im,2,2,4)
            self.assertGreater(plan['boxes'][0][3],42)
            frames=motion.extract(im,2,2,4,'alpha',plan['boxes'])
            self.assertEqual(len(set(f.size for f in frames)),1)
            self.assertEqual(sum(sum(f.getchannel('A').getdata()) for f in frames),sum(im.getchannel('A').getdata()))
    def test_no_safe_separator_and_discarded_weapon_are_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);im=Image.new('RGBA',(80,40));im.paste('red',(5,10,75,30));im.save(d/'s.png')
            with self.assertRaisesRegex(ValueError,'No safe'):contract.automatic_plan(d/'s.png',im,2,1,2)
            with self.assertRaisesRegex(ValueError,'discard|cut edge'):contract.validate_pixels(im,[[0,0,20,40],[60,0,80,40]])
    def test_automatic_plan_cannot_hide_pixels_in_gaps(self):
        plan={'schema':2,'method':'transparent_separators','image_size':[80,40],'grid':[2,1,2],'boxes':[[0,0,35,40],[45,0,80,40]]}
        with self.assertRaisesRegex(ValueError,'discard'):contract.boxes(plan,(80,40),2,1,2)
    def test_loop_endpoint_checks_expected_motion_not_identical_pixels(self):
        refs=[{'hip':[20,20],'hand':[30+x,30]} for x in [0,3,6,3]]
        obs=[{'frame':i,'points':copy.deepcopy(r)} for i,r in enumerate(refs)]
        self.assertEqual(quality.endpoint_check(refs,obs,[['hip','hand']],True)['max_error_pixels'],0)
        obs[-1]['points']['hand'][0]+=15
        with self.assertRaisesRegex(ValueError,'Endpoint'):quality.endpoint_check(refs,obs,[['hip','hand']],True)

if __name__=='__main__':unittest.main()
