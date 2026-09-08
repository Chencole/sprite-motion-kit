import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugins/sprite-motion-kit/skills/sprite-motion/scripts'))
import batch
import video_sample


def fixture(clipped=False):
    im = Image.new('RGBA', (160, 96), (0, 0, 0, 255))
    d = ImageDraw.Draw(im)
    d.rectangle((20, 0, 139, 95), fill=(0, 255, 0, 255))
    d.rectangle((65, 30, 89, 80), fill=(30, 40, 180, 255))
    d.rectangle((70, 40, 75, 65), fill=(0, 0, 0, 255))
    d.rectangle((85, 42, 150, 46), fill=(230, 230, 230, 255))
    d.rectangle((142, 43, 148, 45), fill=(0, 0, 0, 255))
    if clipped:
        d.rectangle((84, 0, 86, 30), fill=(240, 240, 240, 255))
    return im


class SidebarPixelsTests(unittest.TestCase):
    def test_fixed_sidebar_key_preserves_canvas_weapon_and_enclosed_dark_detail(self):
        im = fixture()
        with self.assertRaisesRegex(ValueError, 'perimeter'):
            video_sample._remove_background(im, 'green', 'all')
        clean = video_sample._remove_background(im, 'green', 'all', [20, 20])
        self.assertEqual(clean.size, im.size)
        self.assertEqual(clean.getpixel((0, 50)), (0, 0, 0, 0))
        self.assertEqual(clean.getpixel((159, 50)), (0, 0, 0, 0))
        self.assertEqual(clean.getpixel((150, 44)), im.getpixel((150, 44)))
        self.assertEqual(clean.getpixel((145, 44)), im.getpixel((145, 44)))
        self.assertEqual(clean.getpixel((72, 50)), im.getpixel((72, 50)))
        self.assertEqual(clean.getchannel('A').getbbox(), (65, 30, 151, 81))

    def test_invalid_widths_cannot_consume_center_or_apply_to_source_alpha(self):
        for widths in ([80, 80], [-1, 20], [0, 0], [20.5, 20], [True, 20]):
            with self.subTest(widths=widths), self.assertRaises(ValueError):
                video_sample._remove_background(fixture(), 'green', 'all', widths)
        with self.assertRaises(ValueError):
            video_sample._remove_background(fixture(), 'alpha', 'all', [20, 20])

    def test_diagnostic_export_is_never_batch_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'sample.json').write_text(json.dumps({'status': 'video_draft_sample', 'scope_mode': 'action_study'}))
            with self.assertRaisesRegex(ValueError, 'bound single-action'):
                batch.video_evidence(root, 'unused', 'attack', {})
            for extra in ({'draft': True}, {'source_edge_frames': [25]}):
                (root / 'sample.json').write_text(json.dumps({'status': 'video_review_sample', 'scope_mode': 'action_study', **extra}))
                with self.assertRaisesRegex(ValueError, 'Diagnostic or source-clipped'):
                    batch.video_evidence(root, 'unused', 'attack', {})


class SidebarVideoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ffmpeg = os.environ.get('SPRITE_TEST_FFMPEG') or shutil.which('ffmpeg')
        if not cls.ffmpeg:
            raise unittest.SkipTest('Set SPRITE_TEST_FFMPEG for actual video tests')

    def test_source_clipping_only_exports_as_explicit_draft_with_original_frame_indices(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(10):
                fixture(clipped=i < 3).save(root / f'input-{i:03}.png')
            video = root / 'input.mkv'
            subprocess.run([self.ffmpeg, '-hide_banner', '-nostdin', '-loglevel', 'error',
                '-framerate', '10', '-i', str(root / 'input-%03d.png'), '-c:v', 'ffv1', '-pix_fmt', 'bgra', str(video)],
                check=True, capture_output=True)
            options = dict(character='Synthetic sword carrier', action='attack', start=0, duration=1,
                count=5, loop=False, background='green', origin=[80, 81], key_scope='all',
                black_sidebars=[20, 20], review_notes='Source sword touches top edge; diagnostic only.')
            with self.assertRaisesRegex(ValueError, 'touches the canvas edge'):
                video_sample.export_video(video, self.ffmpeg, root / 'strict', **options)
            self.assertFalse((root / 'strict').exists())
            result = video_sample.export_video(video, self.ffmpeg, root / 'draft', draft=True, **options)
            self.assertEqual(result['status'], 'video_draft_sample')
            report = json.loads((root / 'draft/sample.json').read_text())
            self.assertTrue(report['draft'])
            self.assertEqual(report['black_sidebars'], [20, 20])
            self.assertEqual(report['source_edge_frames'], [0, 2])
            self.assertEqual(report['clips'][0]['source_frame_indices'], [0, 2, 4, 6, 8])
            self.assertFalse(report['full_character_complete'])
            with Image.open(root / 'draft/attack/frame-000.png') as im:
                self.assertEqual(im.size, (160, 96))
                self.assertEqual(im.getpixel((150, 44)), (230, 230, 230, 255))
                self.assertEqual(im.getpixel((85, 0)), (240, 240, 240, 255))
            self.assertIn('诊断草稿', (root / 'draft/index.html').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
