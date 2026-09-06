import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'plugins/sprite-motion-kit/skills/sprite-motion/scripts'))
import sprite_contract as contract,quality,motion
class CropEvidenceTests(unittest.TestCase):
 def test_pose_checks_use_same_coordinates_as_safe_export(self):
  with tempfile.TemporaryDirectory() as t:
   d=Path(t);im=Image.new('RGBA',(80,80))
   for y in [0,40]:
    im.paste('red',(15,y+10,42 if y==0 else 25,y+30));im.paste('blue',(55,y+10,65,y+30))
   im.save(d/'source.png');Image.new('RGBA',(10,10),'red').save(d/'guide.png')
   plan=contract.automatic_plan(d/'source.png',im,2,2,4);layout=contract.cell_layout(plan,im.size)
   reference=[{'a':[15,12],'b':[15,25]} for _ in range(4)]
   obs=[]
   for i,r in enumerate(plan['boxes']):
    nx=(i%2)*40;ny=(i//2)*40
    obs.append({'frame':i,'points':{'a':[nx+15-r[0],ny+12-r[1]],'b':[nx+15-r[0],ny+25-r[1]]}})
   report={'action':'walk','source_sha256':quality.digest(d/'source.png'),'guide_sha256':quality.digest(d/'guide.png'),'frames':obs,'visual_checks':dict.fromkeys(['landmarks_match_pixels','identity_and_equipment','support_and_weight','loop_or_settling','camera'],True),'notes':'Synthetic coloured geometry tests crop coordinate transforms only'}
   data={'actions':{'walk':{'guide':'guide.png','loop':True,'columns':2,'rows':2}}}
   with patch.object(quality,'reference_points',return_value=(reference,[['a','b']])):
    with self.assertRaisesRegex(ValueError,'registration drifts'):quality.check(d,data,'walk',d/'source.png',report,None,plan['boxes'])
    result=quality.check(d,data,'walk',d/'source.png',report,None,plan['boxes'],layout['frame_translations'])
    self.assertTrue(result['passed'])
   extracted=motion.extract(im,2,2,4,'alpha',plan['boxes'],plan)
   rendered,_=contract.render_cells(im,plan)
   self.assertEqual([f.tobytes() for f in extracted],[f.tobytes() for f in rendered])
if __name__=='__main__':unittest.main()
