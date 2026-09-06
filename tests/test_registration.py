import sys,tempfile,unittest
from pathlib import Path
from PIL import Image
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'plugins/sprite-motion-kit/skills/sprite-motion/scripts'))
import registration,sprite_contract
class RegistrationTests(unittest.TestCase):
 def fixture(self,d):
  im=Image.new('RGBA',(80,80))
  # One contact and one airborne pose per row, with 5px row baseline drift.
  for box in [(5,20,15,35),(45,10,55,25),(5,55,15,70),(45,45,55,60)]:im.paste('red',box)
  im.save(d/'s.png');plan=sprite_contract.automatic_plan(d/'s.png',im,2,2,4)
  evidence={'source_sha256':plan['source_sha256'],'boxes':plan['boxes'],'contacts':[{'frame':0,'source_point':[10,34],'notes':'support foot'},{'frame':2,'source_point':[10,69],'notes':'support foot'}]}
  return im,plan,evidence
 def test_row_offset_preserves_airborne_height_and_pixels(self):
  with tempfile.TemporaryDirectory() as t:
   im,plan,e=self.fixture(Path(t));frames,report=registration.register(im,plan,e)
   self.assertEqual(report['row_translation_y'],[0,5])
   self.assertEqual(frames[0].getbbox()[3],frames[2].getbbox()[3])
   self.assertEqual(frames[0].getbbox()[3]-frames[1].getbbox()[3],10)
   self.assertEqual(frames[2].getbbox()[3]-frames[3].getbbox()[3],10)
   self.assertEqual(sum(int(np.asarray(f)[:,:,3].sum()) for f in frames),int(np.asarray(im)[:,:,3].sum()))
 def test_changed_crop_or_empty_ground_anchor_rejected(self):
  with tempfile.TemporaryDirectory() as t:
   im,plan,e=self.fixture(Path(t));e['source_sha256']='changed'
   with self.assertRaisesRegex(ValueError,'different source'):registration.register(im,plan,e)
   e['source_sha256']=plan['source_sha256'];e['contacts'][0]['source_point']=[0,0]
   with self.assertRaisesRegex(ValueError,'foreground'):registration.register(im,plan,e)
 def test_missing_row_evidence_rejected(self):
  with tempfile.TemporaryDirectory() as t:
   im,plan,e=self.fixture(Path(t));e['contacts'].pop()
   with self.assertRaisesRegex(ValueError,'per source row'):registration.register(im,plan,e)
if __name__=='__main__':unittest.main()
