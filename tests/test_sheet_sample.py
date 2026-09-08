import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugins/sprite-motion-kit/skills/sprite-motion/scripts'))
from sheet_sample import build, components


class SheetSampleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source.png'
        im = Image.new('RGBA', (100, 100))
        draw = ImageDraw.Draw(im)
        # Two ground poses, then one grounded and one airborne jump phase.
        for box in [(15, 18, 30, 43), (65, 18, 80, 43), (15, 68, 30, 93), (65, 55, 80, 80)]:
            draw.rectangle(box, fill='#47ac73')
        im.save(self.source)
        self.spec = {'schema': 1, 'mode': 'whole_sheet_sample', 'character': 'sample', 'image': 'source.png',
                     'background': 'alpha', 'grid': [2, 2], 'tile': [80, 80], 'origin': [40, 60],
                     'row_ground_y': [44, 94], 'registration_notes': 'Ground contact in first frame of each row.',
                     'minimum_body_pixels': 100, 'required_actions': ['walk', 'jump'], 'actions': [
                         {'name': 'walk', 'rows': [0], 'seconds': 1, 'loop': True, 'design': 'Two leg phases.'},
                         {'name': 'jump', 'rows': [1], 'seconds': 1, 'loop': False, 'design': 'Launch and apex.'}]}

    def tearDown(self):
        self.temporary.cleanup()

    def run_sample(self):
        path = self.root / 'spec.json'
        path.write_text(json.dumps(self.spec), encoding='utf-8')
        return build(path, self.root / 'result')

    def test_pixel_conservation_scale_and_jump_height(self):
        self.run_sample()
        report = json.loads((self.root / 'result/sample.json').read_text())
        with Image.open(self.source) as source:
            expected = int((np.asarray(source)[:, :, 3] > 0).sum())
        self.assertEqual(report['foreground_pixels_accounted_for'], expected)
        self.assertFalse(report['pose_correspondence_verified'])
        actual = 0
        for c in report['clips']:
            for p, registration in zip(c['frames'], c['registration']):
                with Image.open(self.root / 'result' / p) as image:
                    self.assertEqual(image.mode, 'RGBA')
                    actual += int((np.asarray(image)[:, :, 3] > 0).sum())
                self.assertEqual(registration['scale'], 1)
        self.assertEqual(actual, expected)
        with Image.open(self.root / 'result/jump/frame-000.png') as start, Image.open(self.root / 'result/jump/frame-001.png') as apex:
            self.assertEqual(start.getbbox()[3] - apex.getbbox()[3], 13)
        self.assertFalse(report['clips'][1]['loop'])

    def test_no_previous_output_overwrite(self):
        self.run_sample()
        original = (self.root / 'result/sample.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'existing samples'):
            self.run_sample()
        self.assertEqual((self.root / 'result/sample.json').read_bytes(), original)

    def test_missing_action_rejected_before_write(self):
        self.spec['required_actions'].append('attack')
        with self.assertRaisesRegex(ValueError, 'complete declared'):
            self.run_sample()
        self.assertFalse((self.root / 'result').exists())

    def test_duplicate_row_rejected(self):
        self.spec['actions'][1]['rows'] = [0]
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            self.run_sample()

    def test_unsafe_action_path_rejected(self):
        self.spec['actions'][0]['name'] = '../outside'
        self.spec['required_actions'][0] = '../outside'
        with self.assertRaisesRegex(ValueError, 'Invalid action'):
            self.run_sample()

    def test_wrong_component_count_stops(self):
        with Image.open(self.source) as im:
            with self.assertRaisesRegex(ValueError, 'Expected 6'):
                components(im, 3, 2, 100)

    def test_opaque_background_stops(self):
        with Image.open(self.source) as im:
            im.convert('RGB').save(self.source)
        with self.assertRaisesRegex(ValueError, 'fully opaque'):
            self.run_sample()
        self.assertFalse((self.root / 'result').exists())

    def test_small_output_stops_without_clipping(self):
        self.spec['tile'] = [32, 32]
        self.spec['origin'] = [16, 16]
        with self.assertRaisesRegex(ValueError, 'exceeds output'):
            self.run_sample()
        self.assertFalse((self.root / 'result').exists())


if __name__ == '__main__':
    unittest.main()
