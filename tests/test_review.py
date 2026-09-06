import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SKILL=ROOT/'plugins/sprite-motion-kit/skills/sprite-motion'
sys.path.insert(0,str(SKILL/'scripts'))
import source_preview


class ReviewTests(unittest.TestCase):
    def test_metadata_preserves_declared_scale_and_inspected_ground(self):
        spec={'tile':[512,512],'columns':4,'rows':2,'origin':[256,395.130432128906],'floor_y':395.130432128906}
        report={'common_ground_y':409,'layout':{'origin':[2,3]}}
        meta=source_preview.comparison_metadata(spec,(1774,887),report)
        self.assertEqual(meta['reference_scale'],1774/2048)
        self.assertEqual(meta['origin'],[223.75,409])
        self.assertEqual(meta['floor_y'],409)
        self.assertEqual(meta['reference_floor_y'],spec['floor_y'])
        self.assertEqual(meta['ground_basis'],'inspected_row_contacts')
        declared=source_preview.comparison_metadata(spec,(1774,887),layout={'origin':[2,3]})
        self.assertAlmostEqual(declared['floor_y'],3+spec['floor_y']*1774/2048)

    @unittest.skipUnless(shutil.which('node'),'Node is needed for browser math checks')
    def test_browser_coordinates_timing_and_legacy_fallback(self):
        template=(SKILL/'assets/review.html').read_text(encoding='utf-8')
        math=template.split('// REVIEW_MATH_START:',1)[1].split('\n',1)[1].split('// REVIEW_MATH_END',1)[0]
        script=math+r'''
const assert=require('node:assert/strict');
const c={tile:[444,489],origin:[221.75,409],floor_y:409,reference_origin:[256,395.130432128906],reference_floor_y:395.130432128906,reference_scale:1774/2048,reference_layout:{tile:[512,512]}};
const g=comparisonGeometry(c);
assert.equal(g.art[1]+c.floor_y,g.reference[1]+c.reference_floor_y*g.scale);
assert.equal(g.art[0]+c.origin[0],g.reference[0]+c.reference_origin[0]*g.scale);
assert.ok(g.art[0]>=0&&g.art[1]>=0);
assert.ok(g.reference[0]>=0&&g.reference[1]>=0);
assert.ok(g.art[1]+489<=g.height);
assert.ok(g.reference[1]+512*g.scale<=g.height);
assert.equal(g.scale,1774/2048); // Canvas/declared scale, never measured body fitting.
const legacy=comparisonGeometry({tile:[444,489],reference_layout:{tile:[512,512]}});
assert.deepEqual(legacy.art,[0,0]);assert.deepEqual(legacy.reference,[0,22.5]);assert.equal(legacy.ground,null);
const loop={count:8,seconds:4/3,phases:Array.from({length:8},(_,i)=>i/8),loop:true};
assert.equal(poseIndex(loop,.1),0);assert.equal(referenceIndex(loop,.1,48,true),0);assert.equal(referenceIndex(loop,.1,48,false),3);
for(let i=0;i<8;i++)assert.equal(referenceIndex(loop,loop.phases[i]*loop.seconds,48,true),i*6);
const once={count:8,seconds:2,phases:Array.from({length:8},(_,i)=>i/7),loop:false};
assert.equal(referenceIndex(once,1.98,48,false),46); // Last source sample occurs at the endpoint, not early.
assert.equal(referenceIndex(once,2,48,false),47);
assert.equal(poseIndex(once,2),7);
console.log('review geometry and timing passed');
'''
        result=subprocess.run([shutil.which('node'),'-e',script],text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
