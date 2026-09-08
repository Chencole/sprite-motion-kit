import copy
import sys
import tempfile
import unittest
from pathlib import Path
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'plugins/sprite-motion-kit/skills/sprite-motion/scripts'))
import conditioning
import motion


class ConditioningTests(unittest.TestCase):
    def fixture(self):
        mapping={}
        points={}
        for side,source,x in [('right','near',50),('left','far',60)]:
            for joint,original,y in [('shoulder','shoulder',20),('elbow','elbow',30),('wrist','hand',40),('hip','hip',45),('knee','knee',65),('ankle','ankle',85)]:
                mapping[side+'_'+joint]=source+'_'+original;points[source+'_'+original]=[x,y]
        return mapping,points

    def test_identity_is_fixed_when_feet_cross_not_sorted_by_x(self):
        mapping,points=self.fixture()
        points['near_ankle'][0]=85;points['far_ankle'][0]=20
        first=conditioning.mapped_points(points,mapping,(128,128))
        points['near_ankle'][0]=20;points['far_ankle'][0]=85
        second=conditioning.mapped_points(points,mapping,(128,128))
        self.assertEqual(first['right_ankle'],[85,85]);self.assertEqual(second['right_ankle'],[20,85])
        self.assertEqual(second['left_ankle'],[85,85])

    def test_ground_and_joint_positions_are_not_recentered(self):
        mapping,points=self.fixture();points['near_ankle'][1]=62
        result=conditioning.mapped_points(points,mapping,(128,128))
        self.assertEqual(result['right_ankle'][1],62);self.assertEqual(result['left_ankle'][1],85)
        self.assertNotIn('nose',result);self.assertEqual(result['neck'],[55,20])

    def test_missing_duplicate_and_outside_joints_fail(self):
        mapping,points=self.fixture();bad=copy.deepcopy(mapping);bad['left_ankle']='near_ankle'
        with self.assertRaisesRegex(ValueError,'distinct'):conditioning.mapped_points(points,bad,(128,128))
        del points['near_ankle']
        with self.assertRaisesRegex(ValueError,'Missing'):conditioning.mapped_points(points,mapping,(128,128))
        points['near_ankle']=[129,3]
        with self.assertRaisesRegex(ValueError,'outside'):conditioning.mapped_points(points,mapping,(128,128))

    def test_control_images_have_actual_channels_fixed_size_and_no_backdrop(self):
        mapping,points=self.fixture();image=conditioning.draw_openpose(conditioning.mapped_points(points,mapping,(128,128)),(128,128))
        self.assertEqual(image.size,(128,128));self.assertEqual(image.mode,'RGB')
        self.assertEqual(image.getpixel((0,0)),(0,0,0))
        self.assertEqual(image.getpixel((50,85)),conditioning.COLORS[10])
        self.assertEqual(image.getpixel((60,85)),conditioning.COLORS[13])

    def test_openpose_limb_and_joint_colors_match_rgb_channel_semantics(self):
        # Literal expected RGB values catch a palette/channel swap rather than
        # comparing the implementation's palette to itself.
        # Isolate segments so another limb's intentional paint order cannot
        # overwrite the midpoint being checked.
        image=conditioning.draw_openpose({'right_elbow':[50,20],'right_wrist':[80,20]},(128,128))
        self.assertEqual(image.getpixel((65,20)),(153,153,0))
        self.assertEqual(image.getpixel((80,20)),(170,255,0))
        image=conditioning.draw_openpose({'left_elbow':[100,50],'left_wrist':[100,80]},(128,128))
        self.assertEqual(image.getpixel((100,65)),(51,153,0))
        self.assertEqual(image.getpixel((100,80)),(0,255,85))
        image=conditioning.draw_openpose({'right_knee':[20,90],'right_ankle':[20,120]},(128,128))
        self.assertEqual(image.getpixel((20,105)),(0,153,102))
        image=conditioning.draw_openpose({'left_knee':[90,90],'left_ankle':[90,120]},(128,128))
        self.assertEqual(image.getpixel((90,105)),(0,51,153))

    def test_prepared_package_preserves_original_sequence_canvas_and_source_hashes(self):
        # Run the real imported-job/conditioning path on temporary engineering
        # fixtures. No inference dependency or model is loaded.
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);mapping,points=self.fixture();frames=[]
            for i,lift in enumerate([0,5,12,18,18,12,5,0]):
                frame={name:[xy[0],xy[1]-lift] for name,xy in points.items()}
                frame['near_ankle'][0]=80-i*6;frame['far_ankle'][0]=30+i*6
                frames.append(frame)
            edges=[[side+'_'+a,side+'_'+b] for side in ['near','far']
                   for a,b in [('shoulder','elbow'),('elbow','hand'),('hip','knee'),('knee','ankle')]]
            motion.write(root/'points.json',{'frames':frames,'edges':edges})
            Image.new('RGBA',(24,40),'blue').save(root/'character.png')
            Image.new('RGB',(512,256),'black').save(root/'guide.png')
            Image.new('RGB',(1024,128),'black').save(root/'playback.png')
            phases=[0,.08,.22,.38,.57,.76,.91,1]
            action={'guide':'guide.png','reference':'playback.png','landmarks':'points.json',
                    'columns':4,'rows':2,'count':8,'tile':[128,128],'origin':[54.25,96.5],
                    'floor_y':96.5,'seconds':1.75,'loop':False,'phases':phases,
                    'reference_layout':{'tile':[128,128],'columns':8,'count':8},
                    'design':dict.fromkeys(['intent','support_and_contact','phases','end_state'],'Synthetic jump fixture')}
            bundle={'schema':1,'source_description':'Measured engineering fixture','reuse_reason':'Input packaging regression',
                    'source_asset_sha256':'a'*64,'character_analysis':dict.fromkeys(['anatomy','mass_and_balance','equipment'],'Synthetic humanoid fixture'),
                    'actions':{'jump':action}}
            motion.write(root/'bundle.json',bundle)
            job=root/'job';motion.prepare(root/'character.png',job,reference_bundle=root/'bundle.json')
            data=motion.read(job/'job.json')
            report={'input_hashes':data['input_hashes'],'actions':{'jump':{
                **dict.fromkeys(['anatomy','support_and_contact','timing','camera','end_state'],True),
                'notes':'Engineering fixture for packaging only, not reviewed character art.'}}}
            motion.write(root/'review.json',report);motion.review_reference(job,root/'review.json')
            map_data={'body':'humanoid','anatomical_mapping_reason':'Near/right and far/left are fixed source fixture names.','joints':mapping}
            motion.write(root/'mapping.json',map_data)
            before={str(p.relative_to(job)):p.read_bytes() for p in job.rglob('*') if p.is_file()}
            target=root/'controls';conditioning.prepare(job,'jump',root/'mapping.json',target)
            result=motion.read(target/'conditioning.json')
            self.assertEqual(result['input_hashes'],data['input_hashes'])
            for name in ['seconds','loop','phases','origin','floor_y','columns']:
                self.assertEqual(result[name],action[name])
            self.assertEqual([result['width'],result['height']],action['tile'])
            self.assertEqual(result['mapped_points'],[conditioning.mapped_points(f,mapping,(128,128)) for f in frames])
            self.assertEqual(result['anatomical_mapping'],map_data)
            self.assertEqual((target/'character.png').read_bytes(),(job/'character.png').read_bytes())
            self.assertEqual(result['character']['sha256'],conditioning.fingerprint(target/'character.png'))
            for entry in result['controls'][0]['frames']:
                self.assertEqual(entry['sha256'],conditioning.fingerprint(target/entry['path']))
                with Image.open(target/entry['path']) as image:self.assertEqual(image.size,(128,128))
            self.assertEqual(before,{str(p.relative_to(job)):p.read_bytes() for p in job.rglob('*') if p.is_file()})
            self.assertFalse(result['generation_executed']);self.assertEqual(result['approval'],'diagnostic_only')
            # A revised source must not be silently converted under old hashes.
            changed=copy.deepcopy(frames);changed[3]['near_hand'][0]+=2
            motion.write(job/data['actions']['jump']['landmarks'],{'frames':changed,'edges':edges})
            with self.assertRaisesRegex(ValueError,'changed'):conditioning.prepare(job,'jump',root/'mapping.json',root/'stale-controls')
            self.assertFalse((root/'stale-controls').exists())


if __name__=='__main__':unittest.main()
