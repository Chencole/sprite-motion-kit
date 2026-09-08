"""Package whole-sheet character art as a review sample, without model calls.

Component masks preserve detached weapons and logical grid coordinates when a
single straight cut would cross artwork in another row. Never certifies motion.
"""
import argparse
import hashlib
import json
import math
import re
import shutil
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from motion import remove_background

SKILL = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def components(clean, columns, rows, minimum):
    """Find isolated opaque bodies; assign small attached/nearby fragments.

    This is extraction, not pose detection. The source/mask overlay must still
    be inspected: a tiny fragment's anatomical owner is not known by software.
    """
    pixels = np.asarray(clean.convert('RGBA'))
    height, width = pixels.shape[:2]
    active = (pixels[:, :, 3] >= 128).ravel()
    labels = np.full(height * width, -1, dtype=np.int32)
    groups = []
    for seed in np.flatnonzero(active):
        if labels[seed] >= 0:
            continue
        label = len(groups)
        labels[seed] = label
        stack, group = [int(seed)], []
        while stack:
            p = stack.pop()
            group.append(p)
            y, x = divmod(p, width)
            for dy in (-1, 0, 1):
                ny = y + dy
                if not 0 <= ny < height:
                    continue
                for dx in (-1, 0, 1):
                    nx = x + dx
                    if not 0 <= nx < width:
                        continue
                    q = ny * width + nx
                    if active[q] and labels[q] < 0:
                        labels[q] = label
                        stack.append(q)
        yy, xx = np.divmod(np.asarray(group), width)
        groups.append({'pixels': group, 'box': [int(xx.min()), int(yy.min()), int(xx.max()) + 1, int(yy.max()) + 1]})
    bodies = [g for g in groups if len(g['pixels']) >= minimum]
    if len(bodies) != columns * rows:
        raise ValueError(f'Expected {columns * rows} isolated bodies, found {len(bodies)}. Inspect touching or fragmented poses; do not force a cut.')
    # Use opaque body centers for row/column order, before adding faint pixels.
    bodies.sort(key=lambda b: (b['box'][1] + b['box'][3]) / 2)
    ordered = []
    for row in range(rows):
        ordered.extend(sorted(bodies[row * columns:(row + 1) * columns], key=lambda b: (b['box'][0] + b['box'][2]) / 2))
    max_gap = max(4, round(min(width / columns, height / rows) * .18))

    def gap(a, b):
        dx = max(a[0] - b[2], b[0] - a[2], 0)
        dy = max(a[1] - b[3], b[1] - a[3], 0)
        return dx * dx + dy * dy

    for fragment in groups:
        if len(fragment['pixels']) >= minimum:
            continue
        distances = sorted((gap(fragment['box'], body['box']), i) for i, body in enumerate(ordered))
        if distances[0][0] > max_gap ** 2 or (len(distances) > 1 and distances[0][0] == distances[1][0]):
            raise ValueError('Ambiguous or distant detached fragment. Inspect the source before exporting.')
        ordered[distances[0][1]]['pixels'].extend(fragment['pixels'])
    for p in np.flatnonzero((pixels[:, :, 3] > 0).ravel() & (labels < 0)):
        y, x = divmod(int(p), width)
        body = min(ordered, key=lambda b: gap([x, y, x + 1, y + 1], b['box']))
        body['pixels'].append(int(p))
    exported = []
    ownership = np.full(height * width, -1, dtype=np.int32)
    for i, body in enumerate(ordered):
        yy, xx = np.divmod(np.asarray(body['pixels']), width)
        box = [int(xx.min()), int(yy.min()), int(xx.max()) + 1, int(yy.max()) + 1]
        if box[0] == 0 or box[1] == 0 or box[2] == width or box[3] == height:
            raise ValueError('Foreground touches the source boundary; complete anatomy cannot be verified.')
        frame = np.zeros((box[3] - box[1], box[2] - box[0], 4), dtype=np.uint8)
        frame[yy - box[1], xx - box[0]] = pixels[yy, xx]
        ownership[yy * width + xx] = i
        exported.append((Image.fromarray(frame), box))
    if int((ownership >= 0).sum()) != int((pixels[:, :, 3] > 0).sum()):
        raise ValueError('Foreground accounting failed')
    return exported, ownership.reshape(height, width)


def build(spec_path, out):
    spec_path, out = Path(spec_path).resolve(), Path(out).resolve()
    if out.exists():
        raise ValueError('Use a new output directory; existing samples are preserved.')
    spec = json.loads(spec_path.read_text(encoding='utf-8-sig'))
    if spec.get('schema') != 1 or spec.get('mode') != 'whole_sheet_sample':
        raise ValueError('Expected an explicitly selected whole_sheet_sample spec')
    columns, rows = spec['grid']
    if type(columns) is not int or type(rows) is not int or min(columns, rows) < 1 or columns * rows > 256:
        raise ValueError('Invalid sheet grid')
    actions = spec['actions']
    if not actions or len({a['name'] for a in actions}) != len(actions):
        raise ValueError('Action IDs must be nonempty and unique')
    expected = set(spec['required_actions'])
    if not expected or expected != {a['name'] for a in actions}:
        raise ValueError('Export must cover the complete declared action set')
    coverage = []
    for a in actions:
        if not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', a['name']):
            raise ValueError('Invalid action ID')
        if not isinstance(a.get('design'), str) or not a['design'].strip():
            raise ValueError('Each action needs a character-specific design')
        if type(a['loop']) is not bool or not isinstance(a['seconds'], (int, float)) or not math.isfinite(a['seconds']) or a['seconds'] <= 0:
            raise ValueError('Invalid playback contract')
        if not isinstance(a['rows'], list) or not a['rows'] or any(type(r) is not int or not 0 <= r < rows for r in a['rows']):
            raise ValueError('Invalid action rows')
        coverage.extend(a['rows'])
    if sorted(coverage) != list(range(rows)):
        raise ValueError('Every source row must belong to exactly one action')
    source = (spec_path.parent / spec['image']).resolve()
    with Image.open(source) as raw:
        clean = remove_background(raw, spec['background'])
    width, height = clean.size
    minimum = spec.get('minimum_body_pixels', max(8, round(width / columns * height / rows * .025)))
    if type(minimum) is not int or minimum < 4:
        raise ValueError('Invalid component threshold')
    frames, ownership = components(clean, columns, rows, minimum)
    grounds = spec['row_ground_y']
    if len(grounds) != rows or any(type(y) is not int or not 0 <= y < height for y in grounds):
        raise ValueError('Record one source ground baseline per row')
    if not spec.get('registration_notes', '').strip():
        raise ValueError('Record how grounded poses establish row baselines; never ground airborne frames')
    tw, th = spec.get('tile', [320, 320])
    ox, oy = spec.get('origin', [160, 250])
    if any(type(v) is not int for v in (tw, th, ox, oy)) or not (16 <= tw <= 2048 and 16 <= th <= 2048 and 0 <= ox < tw and 0 <= oy < th):
        raise ValueError('Invalid shared output canvas')
    # Keep source scale exactly 1.0. Only uniform row grounding and nominal
    # cell-origin translation are permitted; no pose-wise body recentering.
    rendered, records = [], []
    for i, (frame, box) in enumerate(frames):
        row, col = divmod(i, columns)
        anchor = [round((col + .5) * width / columns), grounds[row]]
        x, y = ox + box[0] - anchor[0], oy + box[1] - anchor[1]
        if min(x, y) < 0 or x + frame.width > tw or y + frame.height > th:
            raise ValueError(f'Frame {i + 1} exceeds output canvas. Enlarge common tile, do not shrink individual bodies.')
        canvas = Image.new('RGBA', (tw, th))
        canvas.alpha_composite(frame, (x, y))
        rendered.append(canvas)
        records.append({'source_frame': i, 'source_box': box, 'source_anchor': anchor, 'translation': [x, y], 'scale': 1})
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.sheet-sample-', dir=out.parent) as temporary:
        staging = Path(temporary) / 'sample'
        staging.mkdir()
        shutil.copy2(source, staging / 'source-original.png')
        clean.save(staging / 'source-transparent.png')
        overlay = clean.convert('RGB')
        draw = ImageDraw.Draw(overlay)
        for i, (_, box) in enumerate(frames):
            draw.rectangle(box, outline='#00ffff', width=1)
            draw.text((box[0], box[1]), str(i + 1), fill='#00ffff')
        overlay.save(staging / 'source-partitions.png')
        mask = np.where(ownership < 0, 0, ownership + 1).astype(np.uint16)
        Image.fromarray(mask).save(staging / 'source-frame-ids.png')
        clips = []
        for action in actions:
            name = action['name']
            folder = staging / name
            folder.mkdir()
            selected = [r * columns + c for r in action['rows'] for c in range(columns)]
            atlas = Image.new('RGBA', (tw * len(selected), th))
            contact = Image.new('RGB', (tw * min(4, len(selected)), (th + 24) * math.ceil(len(selected) / 4)), '#1d2934')
            for n, i in enumerate(selected):
                frame = rendered[i]
                frame.save(folder / f'frame-{n:03}.png')
                atlas.alpha_composite(frame, (n * tw, 0))
                contact.paste(frame, ((n % 4) * tw, (n // 4) * (th + 24)), frame)
                ImageDraw.Draw(contact).text(((n % 4) * tw + 8, (n // 4) * (th + 24) + th), str(n + 1), fill='white')
            atlas.save(folder / 'atlas.png')
            contact.save(folder / 'contact.png')
            clips.append({'name': name, 'count': len(selected), 'seconds': action['seconds'], 'loop': action['loop'],
                          'tile': [tw, th], 'origin': [ox, oy], 'design': action['design'], 'review_note': action.get('review_note', ''),
                          'frames': [f'{name}/frame-{n:03}.png' for n in range(len(selected))],
                          'registration': [records[i] for i in selected], 'accepted_by_user': False})
        report = {'character': spec['character'], 'status': 'review_sample', 'clips': clips,
                  'source_sha256': digest(source), 'source_size': [width, height], 'grid': [columns, rows],
                  'foreground_pixels_accounted_for': int((ownership >= 0).sum()), 'generation_calls_by_exporter': 0,
                  'game_assets_replaced': False, 'pose_correspondence_verified': False,
                  'registration_notes': spec['registration_notes'], 'notes': spec.get('notes', [])}
        (staging / 'sample.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        portable = dict(spec, image='source-original.png')
        (staging / 'source-spec.json').write_text(json.dumps(portable, ensure_ascii=False, indent=2), encoding='utf-8')
        shutil.copy2(SKILL / 'assets/sheet-sample-review.html', staging / 'index.html')
        staging.rename(out)
    return {'preview': str(out / 'index.html'), 'actions': [a['name'] for a in actions], 'status': 'review_sample'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.spec, args.out), ensure_ascii=False))
